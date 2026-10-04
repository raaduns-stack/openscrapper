from src.models.criteria import SearchCriteria
from src.search.template_engine import SearchTemplateEngine
from src.search.domain_resolver import ExternalDomainResolver


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return self.rows


class FakeConn:
    def execute(self, sql, params=()):
        sql = ' '.join(sql.split())
        if sql.startswith('SELECT expanded_role FROM role_expansions'):
            return FakeCursor([])
        if sql.startswith('SELECT t.id,t.category_id'):
            return FakeCursor([('1','c1','google','{industry} {geography-1} {domain}','people','People')])
        raise AssertionError(sql)


class FakeDomainResolver:
    def __init__(self):
        self.calls = []
    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return ['example.com', 'www.example.com']


class Adapter:
    def build_url(self, query):
        return 'https://example.test/?q=' + query.replace(' ', '+')


def test_domain_is_derived_and_deduplicated():
    resolver = FakeDomainResolver()
    engine = SearchTemplateEngine(FakeConn(), {'google': Adapter()}, resolver)
    criteria = SearchCriteria(industry='real estate', geography='United Kingdom')
    params = engine.generate(criteria)
    assert [p.query for p in params] == [
        'real estate United Kingdom example.com',
        'real estate United Kingdom www.example.com',
    ]
    assert resolver.calls == [{
        'industry': 'real estate',
        'geography': 'United Kingdom',
        'role': '',
        'keyword': '',
    }]


def test_domain_cleaning_returns_hostname_only():
    clean = ExternalDomainResolver._clean_domain
    assert clean('http://www.Example.com/path') == 'example.com'
    assert clean('https://example.com/') == 'example.com'
    assert clean('example.com') == 'example.com'
