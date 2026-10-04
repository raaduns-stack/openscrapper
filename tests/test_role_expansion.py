from src.models.criteria import SearchCriteria
from src.search.template_engine import SearchTemplateEngine


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
    def fetchall(self):
        return self.rows


class FakeConn:
    def execute(self, sql, params=()):
        sql = ' '.join(sql.split())
        if sql.startswith('SELECT expanded_role FROM role_expansions'):
            anchor = str(params[0]).casefold()
            rows = {
                'ceo': [('Chief Executive Officer',), ('Managing Director',), ('President',)],
            }.get(anchor, [])
            return FakeCursor(rows)
        if sql.startswith('SELECT t.id,t.category_id'):
            return FakeCursor([('1','c1','google','"{role}" "{geography-1}" email','people','People')])
        raise AssertionError(sql)


class Adapter:
    def build_url(self, query):
        return 'https://example.test/?q=' + query.replace(' ', '+')


def test_role_expansion_generates_one_parameter_per_role():
    engine = SearchTemplateEngine(FakeConn(), {'google': Adapter()})
    criteria = SearchCriteria(industry='software', geography='United States', roles=['CEO'])
    params = engine.generate(criteria)
    queries = [p.query for p in params]
    assert queries == [
        '"CEO" "United States" email',
        '"Chief Executive Officer" "United States" email',
        '"Managing Director" "United States" email',
        '"President" "United States" email',
    ]
    assert all(' OR ' not in q for q in queries)


def test_unknown_role_falls_back_to_exact_user_role():
    engine = SearchTemplateEngine(FakeConn(), {'google': Adapter()})
    criteria = SearchCriteria(industry='software', geography='United States', roles=['Unmapped Executive'])
    params = engine.generate(criteria)
    assert [p.query for p in params] == ['"Unmapped Executive" "United States" email']
