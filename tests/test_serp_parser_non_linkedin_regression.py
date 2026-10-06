from src.models.lead import Lead
from src.pipeline import LeadDiscoveryPipeline


def test_non_linkedin_possessive_contact_title_extracts_person():
    url = "https://www.signalhire.com/profiles/jane-doe-email/1"
    payload = LeadDiscoveryPipeline._serp_payload(
        {"url": url, "title": "Jane Doe's email & phone number - Chief Executive Officer"},
        url,
    )
    assert payload is not None
    assert payload["first_name"] == "Jane"
    assert payload["last_name"] == "Doe"
    Lead.model_validate(payload, context={"generic_prefixes": set()})


def test_linkedin_person_parser_remains_supported():
    url = "https://www.linkedin.com/in/jane-doe"
    payload = LeadDiscoveryPipeline._serp_payload(
        {"url": url, "title": "Jane Doe - Chief Executive Officer @ Example Corp"},
        url,
    )
    assert payload is not None
    assert payload["first_name"] == "Jane"
    assert payload["last_name"] == "Doe"
    assert payload["position"] == "Chief Executive Officer"
    assert payload["company_name"] == "Example Corp"


def test_generic_non_person_page_stays_rejected():
    url = "https://example.com/email-database"
    payload = LeadDiscoveryPipeline._serp_payload(
        {"url": url, "title": "Verified Executive Email Database", "snippet": "Contact database"},
        url,
    )
    assert payload is None
