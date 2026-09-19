import re
from urllib.parse import urlparse
from src.models.lead import Lead

def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())

def _normalize_email(value: str | None) -> str:
    return (value or "").strip().casefold()

def _normalize_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")

def _normalize_website(value: str | None) -> str:
    if not value: return ""
    parsed = urlparse(str(value).strip().casefold())
    return (parsed.netloc or parsed.path).removeprefix("www.").rstrip("/")

def dedupe(leads: list[Lead]) -> list[Lead]:
    seen: set[tuple[str, ...]] = set()
    result: list[Lead] = []
    for lead in leads:
        email = _normalize_email(str(lead.email) if lead.email else None)
        phone = _normalize_phone(lead.phone)
        first = _normalize(lead.first_name)
        last = _normalize(lead.last_name)
        company = _normalize(lead.company_name)
        city = _normalize(lead.city)
        state = _normalize(lead.state)
        website = _normalize_website(str(lead.website) if lead.website else None)
        keys = {
            ("email", email) if email else None,
            ("phone", phone) if phone else None,
            ("website", website) if website else None,
            ("source_person", _normalize_website(str(lead.source_url)), first, last) if lead.source_url and (first or last) else None,
            ("person", first, last, company) if (first or last) and company else None,
            ("company_location", company, city, state) if company and city and state else None,
        }
        keys.discard(None)
        match_index = next((i for i, existing in enumerate(result) if keys & {
            ("email", _normalize_email(str(existing.email) if existing.email else None)) if existing.email else None,
            ("phone", _normalize_phone(existing.phone)) if existing.phone else None,
            ("website", _normalize_website(str(existing.website) if existing.website else None)) if existing.website else None,
            ("source_person", _normalize_website(str(existing.source_url)), _normalize(existing.first_name), _normalize(existing.last_name)) if existing.source_url and (existing.first_name or existing.last_name) else None,
            ("person", _normalize(existing.first_name), _normalize(existing.last_name), _normalize(existing.company_name)) if (existing.first_name or existing.last_name) and existing.company_name else None,
        } - {None}), None)
        if match_index is not None:
            existing=result[match_index]
            merged=existing.model_copy(update={
                field: getattr(lead, field) if getattr(lead, field) is not None else getattr(existing, field)
                for field in ("first_name","last_name","position","company_name","country","city","state","email","phone","website","source_url")
            })
            if existing.capture_stage != lead.capture_stage:
                merged=merged.model_copy(update={"capture_stage":"serp+scrapy"})
            result[match_index]=merged
            seen.update(keys)
            continue
        if any(key in seen for key in keys):
            continue
        result.append(lead)
        seen.update(keys)
    return result
