from pydantic import ValidationError
import pytest

from src.models.lead import Lead
from src.pipeline import LeadDiscoveryPipeline


def test_serp_snippet_extracts_patrick_ryan_without_email():
    payload = LeadDiscoveryPipeline._serp_payload(
        {
            "url": "https://rocketreach.co/patrick-ryan-email_53214203",
            "title": "Patrick Ryan Email & Phone Number",
            "snippet": "Get Patrick Ryan's email address ... Patrick Ryan, based in New York, NY, US, is currently a RN, Clinical nurse specialist adult acute and ...",
        },
        "https://rocketreach.co/patrick-ryan-email_53214203",
    )
    assert payload is not None
    assert payload["first_name"] == "Patrick"
    assert payload["last_name"] == "Ryan"
    assert payload["position"] == "RN"
    assert payload["city"] == "New York"
    assert payload["state"] == "NY"
    assert payload["country"] == "United States"
    lead = Lead.model_validate(payload, context={"generic_prefixes": set()})
    assert lead.email is None


def test_email_database_page_is_not_a_person_lead():
    with pytest.raises(ValidationError):
        Lead.model_validate(
            {
                "first_name": "Nurses",
                "last_name": "Email List",
                "position": "1.2M+ Verified Nurse Email Database",
                "source_url": "https://example.com/nurses",
            },
            context={"generic_prefixes": set()},
        )


def test_email_cannot_be_misclassified_as_position():
    with pytest.raises(ValidationError):
        Lead.model_validate(
            {
                "first_name": "Kelly",
                "last_name": "Coba",
                "position": "kelly.coba@gmail.com",
                "source_url": "https://example.com/kelly",
            },
            context={"generic_prefixes": set()},
        )

@pytest.mark.parametrize(
    "title,url",
    [
        ("Alumni Job Board | Columbia School of Nursing", "https://www.nursing.columbia.edu/alumni-job-board"),
        ("Progamme Faculty | ICN - International Council of Nurses", "https://icn.ch/progamme-faculty"),
        ("Learning a new fishin' hole | Columns", "https://www.countrymessenger.com/opinion/columns/learning-a-new-fishin-hole/article_x.html"),
        ("Registered Nurse Salary | New Graduate Nurse", "https://www.youtube.com/watch?v=5VNYfQQR55c"),
    ],
)
def test_generic_serp_pages_are_not_people(title, url):
    payload = LeadDiscoveryPipeline._serp_payload({"title": title, "snippet": title}, url)
    assert payload is None


def test_rocketreach_person_is_found_from_raw_serp_evidence():
    payload = LeadDiscoveryPipeline._serp_payload(
        {
            "title": "Patrick Ryan Email & Phone Number",
            "snippet": "Patrick Ryan Email & Phone Number\nRocketReach",
            "raw_text": "Get Patrick Ryan's email address (p******@gmail ... Patrick Ryan, based in New York, NY, US, is currently a RN, Clinical nurse specialist adult acute and ...",
        },
        "https://rocketreach.co/patrick-ryan-email_53214203",
    )
    assert payload["first_name"] == "Patrick"
    assert payload["last_name"] == "Ryan"
    assert payload["position"] == "RN"
    assert payload["city"] == "New York"
    Lead.model_validate(payload, context={"generic_prefixes": set()})
