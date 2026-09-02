import asyncio
from pathlib import Path

from src.extract.adaptive import AdaptiveLeadExtractor
from src.models.lead import Lead


def test_metadata_and_deterministic_business_extraction():
    html = Path("tests/fixtures/business.html").read_text()
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    leads = asyncio.run(extractor.extract(html, "https://example.com/business"))

    assert leads
    assert any(lead.business_name for lead in leads)
    assert all(str(lead.source_url) == "https://example.com/business" for lead in leads)


def test_contact_extraction():
    html = Path("tests/fixtures/contacts.html").read_text()
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    leads = asyncio.run(extractor.extract(html, "https://example.com/contacts"))

    assert leads
    contacts = [contact for lead in leads for contact in lead.contacts]
    assert contacts
    assert any(contact.person_name for contact in contacts)
import pytest

def test_jsonld_business_extraction():
    html = """<html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Organization",
     "name":"JSONLD Mining Ltd","address":{"@type":"PostalAddress",
     "addressLocality":"Accra","addressRegion":"Greater Accra"},
     "telephone":"+233 20 123 4567","url":"https://jsonldmining.example"}
    </script></head><body></body></html>"""
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")
    leads = asyncio.run(extractor.extract(html, "https://example.com/jsonld"))
    assert len(leads) == 1
    assert leads[0].business_name == "JSONLD Mining Ltd"
    assert leads[0].city == "Accra"
    assert leads[0].state == "Greater Accra"
    assert leads[0].phone == "+233201234567"


def test_llm_fallback_is_used_only_when_deterministic_extraction_fails(monkeypatch):
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    async def fake_llm(html, source_url):
        return []

    monkeypatch.setattr(extractor, "_llm_extract", fake_llm)

    leads = asyncio.run(
        extractor.extract("<html><body><p>plain content</p></body></html>",
                          "https://example.com/plain")
    )
    assert leads == []

def test_llm_output_is_pydantic_validated(monkeypatch):
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    async def fake_llm(html, source_url):
        return [
            Lead(
                business_name="Valid Mining Ltd",
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
    assert leads[0].business_name == "Valid Mining Ltd"
    assert str(leads[0].source_url) == "https://example.com/source"


def test_llm_fallback_does_not_return_invalid_leads(monkeypatch):
    extractor = AdaptiveLeadExtractor(model="openai/gpt-oss-20b")

    async def fake_llm(html, source_url):
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

    async def fail_llm(html, source_url):
        raise AssertionError("LLM must not run when deterministic extraction succeeds")

    monkeypatch.setattr(extractor, "_llm_extract", fail_llm)

    html = Path("tests/fixtures/business.html").read_text()

    leads = asyncio.run(
        extractor.extract(html, "https://example.com/business")
    )

    assert leads
