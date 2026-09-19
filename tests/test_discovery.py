import asyncio

from src.agent.discovery import DiscoveryAgent
from src.agent.discovery_controller import DiscoveryController
from src.agent.query_expansion import QueryExpander
from src.models.criteria import SearchCriteria


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


def test_query_expansion_includes_contact_intent_early():
    queries = QueryExpander().expand(
        criteria(target_type="people", roles=["buyer"]), max_queries=10
    )
    contact_queries = [q.lower() for q in queries if any(
        term in q.lower() for term in ("contact", "email", "phone", "staff", "team", "sales")
    )]
    assert contact_queries
    assert any("buyer" in q and "contact" in q for q in contact_queries)
    assert next(i for i, q in enumerate(queries) if q.lower() == contact_queries[0]) <= 3


    plan = DiscoveryController().plan(criteria(max_leads=20))
    assert plan.query_budget == 10
    assert plan.budget == plan.query_budget
    assert len(plan.queries) <= plan.query_budget
