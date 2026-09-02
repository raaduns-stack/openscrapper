import asyncio

from src.agent.discovery import DiscoveryAgent
from src.agent.discovery_controller import DiscoveryController
from src.agent.query_expansion import QueryExpander
from src.agent.relevance import RelevanceScorer
from src.models.criteria import SearchCriteria
from src.search.models import SearchResult, SearchResults


def criteria(**overrides):
    data = {
        "industry": "gold",
        "product": "gold",
        "geography": "Nigeria",
        "target_type": "companies",
        "roles": [],
        "keywords": [],
        "max_leads": 20,
    }
    data.update(overrides)
    return SearchCriteria(**data)


def test_query_expansion_is_bounded_and_unique():
    queries = QueryExpander().expand(criteria(), max_queries=10)
    assert 1 <= len(queries) <= 10
    assert len(queries) == len({q.casefold() for q in queries})
    assert all("gold" in q.lower() for q in queries)


def test_company_query_contains_commercial_intent():
    queries = QueryExpander().expand(criteria(), max_queries=10)
    joined = " ".join(queries).lower()
    assert any(term in joined for term in ("company", "business", "supplier", "dealer", "trader"))


def test_controller_respects_budget():
    plan = DiscoveryController().plan(criteria(max_leads=20))
    assert plan.budget == 10
    assert len(plan.queries) <= plan.budget


def test_relevance_prefers_business_source():
    scorer = RelevanceScorer()
    good = SearchResult(
        title="Gold Mining Companies Nigeria",
        url="https://example.com/gold-mining-companies-nigeria",
        snippet="Directory of gold mining companies and suppliers in Nigeria",
        provider="test",
    )
    bad = SearchResult(
        title="Gold Price Forecast",
        url="https://example.com/gold-price-forecast",
        snippet="Latest gold rates and investment forecast",
        provider="test",
    )
    assert scorer.score(good, criteria()) > scorer.score(bad, criteria())
    assert scorer.is_relevant(good, criteria())


class FakeSearch:
    async def search(self, query, limit_per_provider=10):
        return SearchResults(
            query=query,
            results=[
                SearchResult(
                    title="Gold Mining Company Nigeria",
                    url="https://company.example",
                    snippet="Gold mining company and supplier in Nigeria",
                    provider="fake",
                ),
                SearchResult(
                    title="Gold Price Forecast",
                    url="https://noise.example",
                    snippet="Gold price forecast and rates",
                    provider="fake",
                ),
            ],
        )


def test_discovery_filters_and_deduplicates_sources():
    agent = DiscoveryAgent(search=FakeSearch())
    results = asyncio.run(agent.discover(criteria(max_leads=5)))

    urls = [item.url for item in results]

    assert "https://company.example" in urls
    assert urls.count("https://company.example") == 1
    assert len(results) <= 5
    assert results == sorted(results, key=lambda item: item.score, reverse=True)
