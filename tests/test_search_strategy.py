from src.models.criteria import SearchCriteria
from src.search.strategy import SearchStrategyEngine


def test_google_and_bing_parameters_are_provider_specific():
    c=SearchCriteria(industry='gold', geography='India', target_type='people', roles=['buyer'], max_leads=100)
    params=SearchStrategyEngine().generate(c, max_queries=20)
    assert params
    google=[p for p in params if p.provider=='google']
    bing=[p for p in params if p.provider=='bing']
    assert google and bing
    assert any('email' in p.query.lower() for p in google) or any('contact' in p.query.lower() for p in google)
    assert any('-intitle:"profiles"' in p.query and 'site:linkedin.com/in/' in p.query for p in bing)
    assert all(p.url.startswith(('https://www.google.com/search?q=','https://www.bing.com/search?q=')) for p in params)


def test_strategy_expands_role_synonyms_and_contact_families():
    c=SearchCriteria(industry='gold', geography='Germany', target_type='people', roles=['buyer'])
    params=SearchStrategyEngine().generate(c, max_queries=20)
    queries=[p.query.lower() for p in params]
    assert any('purchasing' in q for q in queries)
    assert any('procurement' in q for q in queries)
    assert any('"@"' in q for q in queries)
    assert any('contact' in q for q in queries)
    assert any('phone' in q for q in queries)


def test_strategy_does_not_hardcode_india_linkedin_domain():
    c=SearchCriteria(industry='gold', geography='Germany', target_type='people', roles=['buyer'])
    params=SearchStrategyEngine().generate(c, max_queries=20)
    assert not any('in.linkedin.com' in p.query for p in params)
    assert not any('in.linkedin.com' in p.url for p in params)


def test_strategy_respects_query_limit():
    c=SearchCriteria(industry='gold', geography='Germany', target_type='people', roles=['buyer'])
    for limit in (1, 5, 20, 50):
        assert len(SearchStrategyEngine().generate(c, max_queries=limit)) <= limit


def test_search_strategy_matrix_covers_target_types_and_multiple_roles():
    for target_type in ('people', 'companies', 'both'):
        c=SearchCriteria(industry='metals', product='gold', geography='Germany', target_type=target_type, roles=['buyer','supplier'], keywords=['refinery'])
        params=SearchStrategyEngine().generate(c, max_queries=20)
        queries=' '.join(p.query.lower() for p in params)
        assert 'gold buyer' in queries
        assert 'gold supplier' in queries
        assert 'refinery' in queries


def test_search_strategy_preserves_geography_and_never_hardcodes_country_linkedin_domain():
    for geography in ('Germany','India','United Kingdom','South Africa'):
        c=SearchCriteria(industry='gold', geography=geography, target_type='people', roles=['buyer'])
        params=SearchStrategyEngine().generate(c, max_queries=20)
        assert params
        assert any(geography.casefold() in p.query.casefold() for p in params)
        assert all('in.linkedin.com' not in p.query for p in params)


def test_search_strategy_has_broad_and_contact_families():
    c=SearchCriteria(industry='gold', geography='Germany', target_type='people', roles=['buyer'])
    families={p.family for p in SearchStrategyEngine().generate(c, max_queries=20)}
    assert {'linkedin-google','contact-google','linkedin-bing','contact-bing','broad'} <= families
