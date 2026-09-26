from src.enrichment.firecrawl import FirecrawlEnricher
import src.models.lead as lead_model
from src.models.lead import Lead
from src.models.lead import strip_protected_lead_fields
from src.pipeline import _merge_enrichment, _same_enrichment_person


def lead(**overrides):
    data = {
        "first_name": "Jane", "last_name": "Doe", "company_name": "Acme",
        "position": "Director", "source_url": "https://example.com/source",
        "country": "US",
    }
    data.update(overrides)
    return Lead.model_validate(data)


def test_firecrawl_relevance_accepts_targeted_search_result():
    seed = lead(email="jane@example.com")
    item = {"query": '"Jane Doe" "Acme"', "title": "Team", "snippet": "Leadership", "url": "https://example.com/team"}
    assert FirecrawlEnricher.relevant(item, seed)


def test_firecrawl_relevance_accepts_company_match_in_result():
    seed = lead()
    item = {"query": '"Jane Doe" "Acme"', "title": "Acme Leadership", "snippet": "Executive team", "url": "https://example.com/team"}
    assert FirecrawlEnricher.relevant(item, seed)


def test_enrichment_fills_missing_fields():
    merged = _merge_enrichment(lead(), lead(phone="+15551234567", city="Austin"))
    assert merged.phone == "+15551234567"
    assert merged.city == "Austin"


def test_enrichment_replaces_obvious_artifact():
    existing = lead(position="Email List", company_name="Acme")
    incoming = lead(position="Sales Director", company_name="Acme")
    merged = _merge_enrichment(existing, incoming)
    assert merged.position == "Sales Director"


def test_enrichment_does_not_overwrite_valid_existing_value():
    existing = lead(position="Sales Director")
    incoming = lead(position="Manager")
    merged = _merge_enrichment(existing, incoming)
    assert merged.position == "Sales Director"


def test_enrichment_matches_same_person_across_different_source_urls():
    existing = lead(company_name=None, state="California", country="United States", source_url="https://www.linkedin.com/in/justin-gold")
    incoming = lead(company_name="Oldman, Cooley, Sallus, Birnberg, Coleman & Gold LLP", position="Partner", state="California", country="United States", source_url="https://legaltalknetwork.com/guests/justin-gold/")
    assert _same_enrichment_person(existing, incoming)


def test_enrichment_does_not_require_source_url_identity():
    existing = lead(source_url="https://site-a.example/jane-doe", state="California", country="United States")
    incoming = lead(source_url="https://site-b.example/jane-doe", state="California", country="United States")
    assert _same_enrichment_person(existing, incoming)


def test_firecrawl_query_plan_is_field_aware(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test")
    enricher = FirecrawlEnricher()
    with_email = enricher.query_plan(lead(email="jane@example.com"))
    without_email = enricher.query_plan(lead(email=None))
    assert [step["intent"] for step in with_email] == ["email_identity", "identity_confirmation", "professional_company"]
    assert [step["intent"] for step in without_email] == ["identity_confirmation", "professional_company", "contact_source_discovery"]
    assert with_email[-1]["allow_linkedin"] is True
    assert without_email[-1]["allow_linkedin"] is False


def test_firecrawl_collect_prioritizes_independent_sources(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test")
    enricher = FirecrawlEnricher(search_limit=5, max_queries=1, max_pages=2)
    seed = lead(source_url="https://linkedin.com/in/jane-doe")
    enricher.search = lambda _lead: [
        {"url": "https://linkedin.com/in/jane-doe", "title": "Jane Doe", "snippet": "Acme", "query": "Jane Doe"},
        {"url": "https://example.org/team/jane-doe", "title": "Jane Doe", "snippet": "Acme", "query": "Jane Doe"},
    ]
    enricher.scrape = lambda url: {"url": url, "title": "Jane Doe", "markdown": "Jane Doe Acme", "status": 200}
    items, pages = enricher.collect(seed)
    assert [item["url"] for item in items] == ["https://example.org/team/jane-doe"]
    assert [page["url"] for page in pages] == ["https://example.org/team/jane-doe"]


def test_missing_email_prioritizes_non_linkedin_pages(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test")
    enricher = FirecrawlEnricher(search_limit=5, max_queries=3, max_pages=2)
    seed = lead(email=None, source_url="https://directory.example/jane-doe")
    enricher.search = lambda _lead: [
        {"url": "https://linkedin.com/in/jane-doe", "title": "Jane Doe", "snippet": "Acme", "query": "Jane Doe", "intent": "identity_confirmation", "allow_linkedin": True},
        {"url": "https://example.org/team/jane-doe", "title": "Jane Doe", "snippet": "Acme contact", "query": "Jane Doe Acme", "intent": "contact_source_discovery", "allow_linkedin": False},
    ]
    enricher.scrape = lambda url: {"url": url, "title": "Jane Doe", "markdown": "Jane Doe Acme", "status": 200}
    _, pages = enricher.collect(seed)
    assert pages[0]["url"] == "https://example.org/team/jane-doe"
    assert pages[0]["linkedin_source"] is False


def test_firecrawl_search_credits_are_counted_per_request(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test")
    enricher = FirecrawlEnricher(max_queries=3)
    class Response:
        def __init__(self, items): self.items = items
        def raise_for_status(self): pass
        def json(self): return {"data": {"web": self.items}}
    responses = [
        Response([{"url": f"https://example.org/a{i}"} for i in range(4)]),
        Response([{"url": f"https://example.org/b{i}"} for i in range(4)]),
        Response([{"url": f"https://example.org/a{i}"} for i in range(4)]),
    ]
    enricher.session.post = lambda *args, **kwargs: responses.pop(0)
    enricher.query_plan = lambda _lead: [
        {"intent": "a", "query": "a", "allow_linkedin": True},
        {"intent": "b", "query": "b", "allow_linkedin": True},
        {"intent": "c", "query": "c", "allow_linkedin": True},
    ]
    enricher.search(lead())
    assert enricher.usage["search_results_returned"] == 12
    assert enricher.usage["search_results"] == 8
    assert enricher.usage["estimated_search_credits"] == 6


def test_firecrawl_search_credits_round_up_each_response(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test")
    enricher = FirecrawlEnricher(max_queries=1)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"data": {"web": [{"url": f"https://example.org/{i}"} for i in range(11)]}}
    enricher.session.post = lambda *args, **kwargs: Response()
    enricher.search(lead())
    assert enricher.usage["estimated_search_credits"] == 4


def test_firecrawl_search_with_zero_results_costs_zero(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test")
    enricher = FirecrawlEnricher(max_queries=1)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"data": {"web": []}}
    enricher.session.post = lambda *args, **kwargs: Response()
    enricher.search(lead())
    assert enricher.usage["estimated_search_credits"] == 0


def test_default_protected_fields_are_email_and_phone():
    assert lead_model.PROTECTED_LEAD_FIELDS == frozenset({"email", "phone"})


def test_protected_field_is_stripped_from_automation_payload(monkeypatch):
    monkeypatch.setattr(lead_model, "PROTECTED_LEAD_FIELDS", frozenset({"phone"}))
    payload = {"first_name": "Jane", "phone": "+15551234567", "city": "Austin"}
    assert strip_protected_lead_fields(payload) == {"first_name": "Jane", "city": "Austin"}


def test_enrichment_does_not_fill_protected_field(monkeypatch):
    monkeypatch.setattr(lead_model, "PROTECTED_LEAD_FIELDS", frozenset({"phone"}))
    existing = lead(phone=None)
    incoming = lead(phone="+15551234567", city="Austin")
    merged = _merge_enrichment(existing, incoming, evidence_pages=[
        {"url": "https://independent.example/jane", "status": 200, "markdown": "Jane Doe Acme +15551234567 Austin"}
    ])
    assert merged.phone is None
    assert merged.city == "Austin"


def test_unprotected_field_still_enriches_when_protection_is_enabled(monkeypatch):
    monkeypatch.setattr(lead_model, "PROTECTED_LEAD_FIELDS", frozenset({"phone"}))
    existing = lead(phone=None)
    incoming = lead(phone="+15551234567", city="Austin")
    merged = _merge_enrichment(existing, incoming, evidence_pages=[
        {"url": "https://independent.example/jane", "status": 200, "markdown": "Jane Doe Acme +15551234567 Austin"}
    ])
    assert merged.city == "Austin"
