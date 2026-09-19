from src.agent.qualification import LeadQualifier
from src.models.criteria import SearchCriteria
from src.models.lead import Lead


def lead(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane@example.com",
        "company_name": "Acme Mining",
        "source_url": "https://example.com/contact",
    }
    data.update(overrides)
    return Lead(**data)


def test_industry_match_qualifies():
    result = LeadQualifier().qualify(lead(), SearchCriteria(industry="mining"))
    assert result.relevant
    assert result.score >= 2
    assert "matched:mining" in result.reasons


def test_role_match_qualifies():
    result = LeadQualifier().qualify(
        lead(position="Procurement Manager"),
        SearchCriteria(industry="manufacturing", roles=["procurement manager"]),
    )
    assert result.relevant
    assert "role:procurement manager" in result.reasons


def test_geography_alone_does_not_qualify():
    result = LeadQualifier().qualify(
        lead(company_name="Acme Services", country="Nigeria"),
        SearchCriteria(industry="mining", geography="Nigeria"),
    )
    assert not result.relevant
    assert "geography:Nigeria" in result.reasons


def test_keyword_match_qualifies_without_exact_industry():
    result = LeadQualifier().qualify(
        lead(company_name="Acme Services", position="Buyer"),
        SearchCriteria(industry="manufacturing", keywords=["buyer"]),
    )
    assert result.relevant
    assert "matched:buyer" in result.reasons


def test_unrelated_lead_is_rejected():
    result = LeadQualifier().qualify(
        lead(company_name="Acme Real Estate", position="Accountant"),
        SearchCriteria(industry="mining", product="gold", roles=["buyer"]),
    )
    assert not result.relevant
    assert result.score == 0
