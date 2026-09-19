import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.collector.scrapy_runner import CollectedPage
from src.models.criteria import CrawlerConfig, SearchCriteria
from src.models.lead import Lead
from src.pipeline import LeadDiscoveryPipeline
from src.search.serp_extractor import extract_destination_urls
from src.search.strategy import SearchStrategyEngine


class FakeCollector:
    def __init__(self, pages):
        self.pages = pages
        self.received = []

    async def collect(self, urls):
        self.received = list(urls)
        return self.pages


def page(url, html, status=200):
    return CollectedPage(url=url, html=html, text=" ".join(__import__('bs4').BeautifulSoup(html, 'html.parser').stripped_strings), status=status)


def test_v13_e2e_import_to_validated_qualified_deduped_lead_and_occurrences():
    html = '''<article class="contact"><h2>Gold Buyer</h2><span class="name">John Doe</span><span class="role">buyer</span><span class="company">Acme Gold</span><span class="city">Lagos</span><span class="country">Nigeria</span><a href="mailto:john.doe@acmegold.example">john.doe@acmegold.example</a></article>'''
    collector = FakeCollector([page("https://example.test/john", html), page("https://example.test/john", html)])
    pipeline = LeadDiscoveryPipeline(crawler_config=CrawlerConfig(max_crawl_pages=10, max_crawl_urls=10))
    pipeline.collector = collector
    criteria = SearchCriteria(industry="gold", product="gold", geography="Nigeria", roles=["buyer"], max_leads=10)
    leads = asyncio.run(pipeline.run_urls(criteria, ["https://example.test/john", "https://example.test/john"]))
    assert collector.received == ["https://example.test/john", "https://example.test/john"]
    assert len(leads) == 1
    assert str(leads[0].email) == "john.doe@acmegold.example"


def test_v13_email_acceptance_and_generic_mailbox_rejection():
    assert Lead(email="john@provider.example", source_url="https://x.example").email
    assert Lead(email="john@company.example", source_url="https://x.example").email
    with pytest.raises(ValidationError):
        Lead(email="info@company.example", source_url="https://x.example")


def test_v13_serp_import_preserves_duplicate_url_occurrences():
    html = '''<div><a href="https://acme.example/a"><h3>A</h3></a><a href="https://acme.example/a"><h3>A again</h3></a><a href="https://www.google.com/search?q=x"><h3>search</h3></a></div>'''
    assert extract_destination_urls(html, "https://www.google.com/search?q=gold") == ["https://acme.example/a", "https://acme.example/a"]


def test_v13_serp_challenge_stops_import():
    assert extract_destination_urls("<html>captcha verify you are human</html>", "https://www.google.com/sorry/index") == []


def test_v13_search_strategy_generates_google_and_bing_parameters():
    criteria = SearchCriteria(industry="gold", product="gold", geography="India", roles=["buyer"], max_leads=20)
    params = SearchStrategyEngine().generate(criteria, max_queries=20)
    assert params and {p.provider for p in params} == {"google", "bing"}
    assert any("email" in p.query.lower() for p in params)
    assert any("linkedin.com/in" in p.query.lower() for p in params)


def test_v13_url_import_api_rejects_google_sheets_without_target():
    from src.api.app import UrlImportRequest
    with pytest.raises(ValidationError):
        UrlImportRequest(criteria={"industry": "gold"}, urls=["https://example.test"], export_format="google_sheets")
