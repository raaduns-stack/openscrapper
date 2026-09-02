from pathlib import Path
from src.extract.leads import LeadExtractor
from src.models.lead import Lead

FIXTURE = Path("tests/fixtures/business.html")

def test_html_extraction():
    leads = LeadExtractor().extract(FIXTURE.read_text(), "https://source.example/search")
    assert len(leads) == 1
    lead = leads[0]
    assert lead.business_name == "Acme Plumbing"
    assert lead.city == "New York"
    assert lead.state == "NY"
    assert lead.phone == "(212) 555-0100"
    assert str(lead.website) == "https://acmeplumbing.example/"

def test_json_extraction():
    html = """<html><body>[{"company":{"name":"Test Plumbing"},"address":{"city":"Boston"},"phone":"555-1234","website":"test.example"}]</body></html>"""
    leads = LeadExtractor().extract(html, "https://source.example/api")
    assert len(leads) == 1
    assert leads[0].business_name == "Test Plumbing"
    assert leads[0].city == "Boston"
    assert leads[0].phone == "555-1234"
    assert str(leads[0].website) == "https://test.example/"

def test_cloudflare_block():
    html = "<html><head><title>Attention Required! | Cloudflare</title></head><body>You have been blocked</body></html>"
    try:
        LeadExtractor().extract(html, "https://blocked.example")
        assert False
    except RuntimeError as e:
        assert "blocked" in str(e).lower()

def test_dedupe():
    from src.dedupe.leads import dedupe
    a = Lead(business_name="Acme Plumbing", city="New York", state="NY", source_url="https://a.example")
    b = Lead(business_name="ACME PLUMBING", city="New York", state="NY", source_url="https://a.example")
    c = Lead(business_name="Acme Plumbing", city="Boston", state="MA", source_url="https://a.example")
    result = dedupe([a, b, c])
    assert len(result) == 2

def test_exports(tmp_path):
    from src.exports.csv_export import export_csv
    from src.exports.xlsx_export import export_xlsx
    import pandas as pd

    lead = Lead(
        business_name="Acme Plumbing",
        city="New York",
        state="NY",
        phone="555-0100",
        source_url="https://source.example",
    )

    csv_path = export_csv([lead], str(tmp_path / "leads.csv"))
    xlsx_path = export_xlsx([lead], str(tmp_path / "leads.xlsx"))

    assert csv_path.exists()
    assert xlsx_path.exists()
    assert len(pd.read_csv(csv_path)) == 1
    assert len(pd.read_excel(xlsx_path)) == 1
def test_security_verification_block():
    html = """<html><body><h1>Performing security verification</h1><p>This website uses a security service to protect against malicious bots.</p><p>Cloudflare</p></body></html>"""
    try:
        LeadExtractor().extract(html, "https://blocked.example")
        assert False
    except RuntimeError as e:
        assert "blocked" in str(e).lower()

def test_contact_extraction():
    from src.extract.adaptive import AdaptiveLeadExtractor
    html = Path("tests/fixtures/contacts.html").read_text()
    leads = AdaptiveLeadExtractor()._extract_candidates(html, "https://source.example/contact")
    assert len(leads) == 1
    assert len(leads[0].contacts) == 1
    contact = leads[0].contacts[0]
    assert contact.person_name == "John Doe"
    assert contact.job_title == "Managing Director"
    assert contact.email == "john.doe@examplegold.com"
    assert contact.phone == "+2348098765432"

def test_lead_qualification_matches_criteria():
    from src.agent.qualification import LeadQualifier
    from src.models.criteria import SearchCriteria

    lead = Lead(
        business_name="Nigeria Gold Mining Company",
        city="Lagos",
        state="Lagos",
        source_url="https://source.example",
    )
    criteria = SearchCriteria(
        industry="gold",
        product="gold",
        geography="Nigeria",
        target_type="companies",
    )

    result = LeadQualifier().qualify(lead, criteria)
    assert result.relevant
    assert result.score >= 2.0


def test_lead_qualification_rejects_unrelated_lead():
    from src.agent.qualification import LeadQualifier
    from src.models.criteria import SearchCriteria

    lead = Lead(
        business_name="Nigeria Real Estate Company",
        city="Lagos",
        state="Lagos",
        source_url="https://source.example",
    )
    criteria = SearchCriteria(
        industry="gold",
        product="gold",
        geography="Nigeria",
        target_type="companies",
    )

    result = LeadQualifier().qualify(lead, criteria)
    assert not result.relevant
