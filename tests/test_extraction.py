import asyncio
from pathlib import Path

from src.extract.adaptive import AdaptiveLeadExtractor
from src.models.lead import Lead


def test_metadata_and_deterministic_business_extraction():
    html = Path("tests/fixtures/business.html").read_text()
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    leads = asyncio.run(extractor.extract(html, "https://example.com/business"))

    assert leads == []


def test_contact_extraction():
    html = Path("tests/fixtures/contacts.html").read_text()
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    leads = asyncio.run(extractor.extract(html, "https://example.com/contacts"))

    assert leads
    assert any(lead.first_name == "John" and lead.last_name == "Doe" for lead in leads)
    assert any(str(lead.email) == "john.doe@examplegold.com" for lead in leads)
import pytest

def test_jsonld_business_extraction():
    html = """<html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Person",
     "name":"Jane Doe","email":"jane@example.com","jobTitle":"Director",
     "worksFor":{"@type":"Organization","name":"JSONLD Mining Ltd"},
     "address":{"@type":"PostalAddress","addressLocality":"Accra",
     "addressRegion":"Greater Accra"},"telephone":"+233 20 123 4567",
     "url":"https://jsonldmining.example"}
    </script></head><body></body></html>"""
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")
    leads = asyncio.run(extractor.extract(html, "https://example.com/jsonld"))
    assert len(leads) == 1
    assert leads[0].first_name == "Jane"
    assert leads[0].last_name == "Doe"
    assert leads[0].company_name == "JSONLD Mining Ltd"
    assert leads[0].city == "Accra"
    assert leads[0].state == "Greater Accra"
    assert leads[0].phone == "+233201234567"


def test_llm_fallback_is_used_only_when_deterministic_extraction_fails(monkeypatch):
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    async def fake_llm(html, source_url, evidence=None):
        return []

    monkeypatch.setattr(extractor, "_llm_extract", fake_llm)

    leads = asyncio.run(
        extractor.extract("<html><body><p>plain content</p></body></html>",
                          "https://example.com/plain")
    )
    assert leads == []

def test_llm_output_is_pydantic_validated(monkeypatch):
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    async def fake_llm(html, source_url, evidence=None):
        return [
            Lead(
                first_name="Valid",
                last_name="Contact",
                email="valid@example.com",
                company_name="Valid Mining Ltd",
                source_url=source_url,
            )
        ]

    monkeypatch.setattr(extractor, "_llm_extract", fake_llm)

    leads = asyncio.run(
        extractor.extract(
            "<html><body><p>unstructured business content</p></body></html>",
            "https://example.com/source",
        )
    )

    assert len(leads) == 1
    assert leads[0].company_name == "Valid Mining Ltd"
    assert leads[0].email == "valid@example.com"
    assert str(leads[0].source_url) == "https://example.com/source"


def test_llm_fallback_does_not_return_invalid_leads(monkeypatch):
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    async def fake_llm(html, source_url, evidence=None):
        return []

    monkeypatch.setattr(extractor, "_llm_extract", fake_llm)

    leads = asyncio.run(
        extractor.extract(
            "<html><body><p>unstructured content</p></body></html>",
            "https://example.com/source",
        )
    )

    assert leads == []


def test_deterministic_extraction_prevents_llm_call(monkeypatch):
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    async def fail_llm(html, source_url, evidence=None):
        raise AssertionError("LLM must not run when deterministic extraction succeeds")

    monkeypatch.setattr(extractor, "_llm_extract", fail_llm)

    html = Path("tests/fixtures/contacts.html").read_text()

    leads = asyncio.run(
        extractor.extract(html, "https://example.com/contacts")
    )

    assert leads
    assert all(lead.email for lead in leads)
    assert all(lead.first_name or lead.last_name for lead in leads)

def test_evidence_builds_candidate_when_business_container_is_missing():
    from src.extract.candidates import CandidateBuilder
    from src.extract.evidence import EvidenceBuilder

    evidence = EvidenceBuilder().build(
        url="https://example.com/contact",
        html="""
        <html><body>
          <h1>Contact us</h1>
          <p>ABC Mining Ltd</p>
          <p>Email: sales@abcmining.com</p>
        </body></html>
        """,
    )

    candidate = CandidateBuilder().build(evidence)

    assert candidate.company_name is None
    assert candidate.email is None
    assert evidence.fields
    assert evidence.fields[0].value == "sales@abcmining.com"


def test_structured_html_accepts_itemprop_email_text_and_rejects_email_only():
    html = """<html><body>
    <article class="business"><h2>Structured Mining</h2>
      <div class="contact" itemscope itemtype="https://schema.org/Person">
        <span itemprop="name">Alice Smith</span>
        <span itemprop="email">alice@structured.example</span>
      </div>
      <div class="contact"><span itemprop="email">orphan@structured.example</span></div>
    </article></body></html>"""
    extractor = AdaptiveLeadExtractor()
    leads = asyncio.run(extractor.extract(html, "https://example.com/structured"))
    assert len(leads) == 1
    assert leads[0].first_name == "Alice"
    assert leads[0].last_name == "Smith"
    assert str(leads[0].email) == "alice@structured.example"


def test_deterministic_extraction_handles_standalone_and_company_contacts_without_llm(monkeypatch):
    extractor = AdaptiveLeadExtractor()

    async def fail_llm(*args, **kwargs):
        raise AssertionError("LLM must not run for deterministic contacts")

    monkeypatch.setattr(extractor, "_llm_extract", fail_llm)
    html = """<html><body>
      <div class="contact"><h3>Standalone Person</h3>
        <a href="mailto:standalone@example.com">standalone@example.com</a></div>
      <article class="business"><h2>Mining Co</h2>
        <div class="contact"><h3>Company Person</h3>
          <a href="mailto:company@example.com">company@example.com</a></div>
      </article>
    </body></html>"""
    leads = asyncio.run(extractor.extract(html, "https://example.com/mixed"))
    assert {str(lead.email) for lead in leads} == {"standalone@example.com", "company@example.com"}


def test_llm_self_correction_retries_once(monkeypatch):
    extractor = AdaptiveLeadExtractor()

    class Result:
        def __init__(self):
            self.output = type("Output", (), {"leads": [Lead(first_name="Jane", email="jane@example.com", source_url="https://example.com/page")]})()

    class Agent:
        def __init__(self):
            self.calls = []

        async def run(self, prompt):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                raise ValueError("invalid structured output")
            return Result()

    agent = Agent()
    extractor.agent = agent
    leads = asyncio.run(extractor._llm_extract("<html>empty</html>", "https://example.com/page"))
    assert len(agent.calls) == 2
    assert "CORRECTION REQUIRED" in agent.calls[1]
    assert str(leads[0].email) == "jane@example.com"


def test_llm_self_correction_is_hard_bounded():
    extractor = AdaptiveLeadExtractor()

    class Agent:
        def __init__(self):
            self.calls = 0

        async def run(self, prompt):
            self.calls += 1
            raise ValueError("invalid structured output")

    agent = Agent()
    extractor.agent = agent
    leads = asyncio.run(extractor._llm_extract("<html>empty</html>", "https://example.com/page"))
    assert leads == []
    assert agent.calls == extractor.LLM_MAX_ATTEMPTS
