import json, os, re
from groq import Groq
from urllib.parse import quote_plus
from src.models.lead import Lead
from src.search.premium import HttpPremiumSerpProvider


def _json_object(text: str) -> dict:
    text = (text or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('GPT-OSS-20B did not return a JSON object')
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError('GPT-OSS-20B returned a non-object result')
    return value


def llm_candidates(lead: Lead, page_text: str, search_items: list[dict]) -> tuple[list[Lead], dict]:
    key = os.getenv('GROQ_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GROQ_API_KEY is not configured')
    evidence = {
        'existing_lead': lead.model_dump(mode='json'),
        'page_text': (page_text or '')[:18000],
        'search_results': search_items[:8],
    }
    prompt = '''You are a lead-data enrichment engine. Return ONLY one JSON object with a leads array. Each array item must use exactly these fields: first_name,last_name,position,company_name,phone,city,state,country,website,email,source_url. Compare the supplied evidence against the existing lead and return evidence-backed corrections as well as missing fields. For the existing person, you MAY replace an existing field when the supplied evidence directly and clearly supports the new value; do not preserve an incorrect existing value merely because it is non-empty. Never invent values or guess. If the existing lead has no email, do not use LinkedIn-only evidence for an email value. Do not use page titles, URL fragments, email-list labels, CAPTCHA text, masked contact fragments, or generic mailbox names as person-specific fields. Keep reliable existing identity values when the evidence does not clearly contradict them. If the evidence clearly identifies a different person, you may return that person as a separate lead. If evidence does not support a field, return null.\n\nEvidence:\n''' + json.dumps(evidence, ensure_ascii=False)
    client = Groq(api_key=key)
    response_schema = {
        'type': 'json_schema',
        'json_schema': {
            'name': 'lead_enrichment',
            'strict': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'leads': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {field: {'type': ['string', 'null']} for field in ('first_name','last_name','position','company_name','phone','city','state','country','website','email','source_url')},
                            'required': ['first_name','last_name','position','company_name','phone','city','state','country','website','email','source_url'],
                            'additionalProperties': False,
                        },
                    },
                },
                'required': ['leads'],
                'additionalProperties': False,
            },
        },
    }
    try:
        response = client.chat.completions.create(
            model=os.getenv('LLM_ENRICHMENT_MODEL', 'openai/gpt-oss-20b'),
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0,
            max_completion_tokens=4096,
            include_reasoning=False,
            response_format=response_schema,
        )
    except Exception as exc:
        raise RuntimeError(f'Groq GPT-OSS-20B request failed: {exc}') from exc
    text = ((response.choices or [None])[0].message.content if response.choices else '') or ''
    data = _json_object(text)
    allowed = {'first_name','last_name','position','company_name','phone','city','state','country','website','email','source_url'}
    rows = data.get('leads') or []
    if not isinstance(rows, list):
        raise ValueError('GPT-OSS-20B leads output is not an array')
    result = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        clean = {field: row.get(field) for field in allowed}
        if not clean.get('source_url'):
            continue
        try:
            result.append(Lead.model_validate(clean))
        except Exception:
            continue
    usage = response.usage
    input_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
    output_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
    details = getattr(usage, 'completion_tokens_details', None)
    reasoning_tokens = int(getattr(details, 'reasoning_tokens', 0) or 0)
    estimated_cost_usd = (input_tokens * 0.075 + output_tokens * 0.30) / 1_000_000
    telemetry = {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'reasoning_tokens': reasoning_tokens,
        'cost_usd': estimated_cost_usd,
        'model': response.model or os.getenv('LLM_ENRICHMENT_MODEL', 'openai/gpt-oss-20b'),
        'calls': 1,
    }
    return result, telemetry
