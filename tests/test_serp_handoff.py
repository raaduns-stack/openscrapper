from src.db import db
from fastapi.testclient import TestClient

from src.api import app as api


def test_serp_import_session_preserves_duplicate_url_occurrences():
    client=TestClient(api.app)
    created=client.post('/serp/sessions',json={'ttl_seconds':600})
    assert created.status_code==200
    token=created.json()['token']
    urls=['https://example.com/a','https://example.com/a','https://example.com/b']
    imported=client.post('/serp/import',json={'token':token,'urls':urls,'page_url':'https://www.google.com/search?q=test'})
    assert imported.status_code==200
    assert imported.json()['count']==3
    current=client.get(f'/serp/sessions/{token}')
    assert current.status_code==200
    assert current.json()['urls']==urls


def test_serp_import_rejects_unknown_token():
    response=TestClient(api.app).post('/serp/import',json={'token':'x'*32,'urls':['https://example.com']})
    assert response.status_code==404


def test_serp_source_accepts_google_search_url_and_extracts_query():
    client=TestClient(api.app)
    token=client.post('/serp/sessions',json={'ttl_seconds':600}).json()['token']
    response=client.post('/serp/sources',json={'token':token,'url':'https://www.google.com/search?q=%2B%22Gold+buyer%22+%2B%22France%22+%2B%22contact%22'})
    assert response.status_code==200
    assert response.json()['provider']=='google'
    assert response.json()['query']=='+"Gold buyer" +"France" +"contact"'


def test_serp_source_rejects_non_search_urls():
    client=TestClient(api.app)
    token=client.post('/serp/sessions',json={'ttl_seconds':600}).json()['token']
    response=client.post('/serp/sources',json={'token':token,'url':'https://www.google.com/maps'})
    assert response.status_code==422


def test_serp_source_is_preserved_in_session():
    client=TestClient(api.app)
    token=client.post('/serp/sessions',json={'ttl_seconds':600}).json()['token']
    client.post('/serp/sources',json={'token':token,'url':'https://www.bing.com/search?q=gold+buyer+france'})
    current=client.get(f'/serp/sessions/{token}')
    assert current.json()['sources'][0]['provider']=='bing'
    assert current.json()['sources'][0]['query']=='gold buyer france'


def test_serp_session_requires_scrap_ownership():
    import uuid
    client=TestClient(api.app)
    a=client.post('/auth/register',json={'email':f'serp-a-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}).json()
    b=client.post('/auth/register',json={'email':f'serp-b-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}).json()
    ha={'Authorization':f"Bearer {a['token']}"}; hb={'Authorization':f"Bearer {b['token']}"}
    with db() as conn:
        conn.execute("UPDATE wallets SET balance_cents=10000 WHERE user_id=%s",(__import__('uuid').UUID(a['user_id']),)); conn.commit()
    scrap=client.post('/scraps',headers=ha,json={'name':'SERP A'}).json()['id']
    denied=client.post('/serp/sessions',headers=hb,json={'scrap_id':scrap})
    assert denied.status_code==404
    created=client.post('/serp/sessions',headers=ha,json={'scrap_id':scrap})
    assert created.status_code==200
    token=created.json()['token']
    assert client.get(f'/serp/sessions/{token}',headers=hb).status_code==403
    assert client.get(f'/serp/sessions/{token}',headers=ha).status_code==200


def test_serp_import_persists_results_and_duplicate_occurrences():
    import uuid
    client=TestClient(api.app)
    auth=client.post('/auth/register',json={'email':f'serp-persist-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}).json()
    headers={'Authorization':f"Bearer {auth['token']}"}
    with db() as conn:
        conn.execute("UPDATE wallets SET balance_cents=10000 WHERE user_id=%s",(__import__('uuid').UUID(auth['user_id']),)); conn.commit()
    scrap=client.post('/scraps',headers=headers,json={'name':'SERP persist'}).json()['id']
    token=client.post('/serp/sessions',headers=headers,json={'scrap_id':scrap}).json()['token']
    item={'url':'https://example.com/contact','title':'Contact','snippet':'Email person@example.com','provider':'google','page_url':'https://www.google.com/search?q=contact'}
    response=client.post('/serp/import',headers=headers,json={'token':token,'results':[item,item]})
    assert response.status_code==200 and response.json()['results']==2
    live=client.get(f'/scraps/{scrap}',headers=headers).json()
    assert live['counts']['serp_results']==2 and live['counts']['url_occurrences']==2


def test_serp_session_cannot_be_imported_without_owner_auth():
    import uuid
    client=TestClient(api.app)
    auth=client.post('/auth/register',json={'email':f'serp-auth-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}).json()
    headers={'Authorization':f"Bearer {auth['token']}"}
    with db() as conn:
        conn.execute("UPDATE wallets SET balance_cents=10000 WHERE user_id=%s",(__import__('uuid').UUID(auth['user_id']),)); conn.commit()
    scrap=client.post('/scraps',headers=headers,json={'name':'SERP auth'}).json()['id']
    token=client.post('/serp/sessions',headers=headers,json={'scrap_id':scrap}).json()['token']
    response=client.post('/serp/import',json={'token':token,'urls':['https://example.com']})
    assert response.status_code==401
