from pathlib import Path

from src.models.lead import Lead


def make_lead(**overrides):
    data = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "company_name": "Acme Plumbing",
        "source_url": "https://source.example",
    }
    data.update(overrides)
    return Lead(**data)

def test_html_extraction():
    html = """<article><h2>Acme Plumbing</h2><div class="contact"><span class="name">John Doe</span><a href="mailto:john@acme.example">john@acme.example</a><span class="city">New York</span><span class="state">NY</span><span class="phone">(212) 555-0100</span><a href="https://acmeplumbing.example">Website</a></div></article>"""
    from src.extract.adaptive import AdaptiveLeadExtractor
    import asyncio
    leads = asyncio.run(AdaptiveLeadExtractor().extract(html, "https://source.example/search"))
    assert len(leads) == 1
    lead = leads[0]
    assert lead.company_name == "Acme Plumbing"
    assert lead.first_name == "John"
    assert lead.last_name == "Doe"
    assert lead.city == "New York"
    assert lead.state == "NY"
    assert lead.phone == "+12125550100"
    assert str(lead.email) == "john@acme.example"

def test_json_extraction():
    from src.extract.adaptive import AdaptiveLeadExtractor
    import asyncio
    html = """<html><head><script type=\"application/ld+json\">{\"@type\":\"Person\",\"name\":\"Jane Doe\",\"email\":\"jane@example.com\",\"worksFor\":{\"name\":\"Test Plumbing\"},\"address\":{\"addressLocality\":\"Boston\"}}</script></head><body></body></html>"""
    leads = asyncio.run(AdaptiveLeadExtractor().extract(html, "https://source.example/api"))
    assert len(leads) == 1
    assert leads[0].company_name == "Test Plumbing"
    assert leads[0].city == "Boston"

def test_cloudflare_block():
    html = "<html><head><title>Attention Required! | Cloudflare</title></head><body>You have been blocked</body></html>"
    try:
        from src.extract.leads import LeadExtractor
        LeadExtractor().extract(html, "https://blocked.example")
        assert False
    except RuntimeError as e:
        assert "blocked" in str(e).lower()

def test_dedupe():
    from src.dedupe.leads import dedupe
    a = make_lead(company_name="Acme Plumbing", city="New York", state="NY")
    b = make_lead(first_name="John", last_name="Doe", company_name="ACME PLUMBING", city="New York", state="NY")
    c = make_lead(first_name="Jane", last_name="Doe", email="jane@example.com", company_name="Acme Plumbing", city="Boston", state="MA")
    result = dedupe([a, b, c])
    assert len(result) == 2

def test_exports(tmp_path):
    from src.exports.csv_export import export_csv
    from src.exports.xlsx_export import export_xlsx
    import pandas as pd

    lead = make_lead(city="New York", state="NY", phone="555-0100")

    csv_path = export_csv([lead], str(tmp_path / "leads.csv"))
    xlsx_path = export_xlsx([lead], str(tmp_path / "leads.xlsx"))

    assert csv_path.exists()
    assert xlsx_path.exists()
    assert len(pd.read_csv(csv_path)) == 1
    assert len(pd.read_excel(xlsx_path)) == 1
def test_security_verification_block():
    html = """<html><body><h1>Performing security verification</h1><p>This website uses a security service to protect against malicious bots.</p><p>Cloudflare</p></body></html>"""
    try:
        from src.extract.leads import LeadExtractor
        LeadExtractor().extract(html, "https://blocked.example")
        assert False
    except RuntimeError as e:
        assert "blocked" in str(e).lower()

def test_contact_extraction():
    from src.extract.adaptive import AdaptiveLeadExtractor
    html = Path("tests/fixtures/contacts.html").read_text()
    leads = AdaptiveLeadExtractor()._extract_candidates(html, "https://source.example/contact")
    assert len(leads) == 1
    lead = leads[0]
    assert lead.first_name == "John"
    assert lead.last_name == "Doe"
    assert lead.position == "Managing Director"
    assert lead.email == "john.doe@examplegold.com"
    assert lead.phone == "+2348098765432"

def test_lead_qualification_matches_criteria():
    from src.agent.qualification import LeadQualifier
    from src.models.criteria import SearchCriteria

    lead = make_lead(
        company_name="Nigeria Gold Mining Company",
        city="Lagos",
        state="Lagos",
        country="Nigeria",
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

    lead = make_lead(
        company_name="Nigeria Real Estate Company",
        city="Lagos",
        state="Lagos",
        country="Nigeria",
    )
    criteria = SearchCriteria(
        industry="gold",
        product="gold",
        geography="Nigeria",
        target_type="companies",
    )

    result = LeadQualifier().qualify(lead, criteria)
    assert not result.relevant


def test_harvested_collection_failure_propagates():
    import asyncio
    from src.models.criteria import SearchCriteria
    from src.pipeline import LeadDiscoveryPipeline

    class FailingCollector:
        async def collect(self, urls, progress_callback=None, scrap_id=None):
            raise RuntimeError("scrapy worker failed")

    pipeline = LeadDiscoveryPipeline()
    pipeline.collector = FailingCollector()
    try:
        asyncio.run(pipeline.run_harvested(
            SearchCriteria(industry="gold", max_leads=10),
            [{"url": "https://example.com"}],
        ))
        assert False, "collection failure must propagate"
    except RuntimeError as exc:
        assert "scrapy worker failed" in str(exc)
