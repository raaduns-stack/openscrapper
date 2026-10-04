import uuid
from fastapi.testclient import TestClient
from src.api import app as api
from src.db import db
from datetime import timedelta


def auth_client():
    client=TestClient(api.app)
    email=f"v131-{uuid.uuid4().hex}@example.test"
    r=client.post('/auth/register',json={'email':email,'password':'StrongTestPassword123!'})
    assert r.status_code==200
    user_id=r.json()['user_id']
    token=r.json().get('token')
    if not token:
        token=client.post('/auth/login',json={'email':email,'password':'StrongTestPassword123!'}).json()['token']
    return client,{'Authorization':f'Bearer {token}'},user_id


def fund(user_id, cents=10000):
    with db() as conn:
        conn.execute('UPDATE wallets SET balance_cents=%s WHERE user_id=%s',(cents,uuid.UUID(user_id)))
        conn.commit()


def create_scrap(client,headers,name='Lifecycle'):
    r=client.post('/scraps',headers=headers,json={'name':name,'criteria':{'industry':'gold'}})
    assert r.status_code==200
    return r.json()


def test_current_scrap_survives_auth_reload():
    client,headers,user_id=auth_client(); fund(user_id)
    scrap=create_scrap(client,headers)
    current=client.get('/scraps/current',headers=headers)
    assert current.status_code==200 and current.json()['id']==str(uuid.UUID(scrap['id']))
    assert client.get('/scraps/current',headers=headers).json()['id']==str(uuid.UUID(scrap['id']))


def test_session_uses_20_minute_sliding_idle_timeout():
    client,headers,user_id=auth_client()
    with db() as conn:
        token_hash=conn.execute("SELECT token_hash FROM sessions WHERE user_id=%s ORDER BY created_at DESC LIMIT 1",(uuid.UUID(user_id),)).fetchone()[0]
        conn.execute("UPDATE sessions SET expires_at=now()+interval '1 minute' WHERE token_hash=%s",(token_hash,)); conn.commit()
    assert client.get('/auth/me',headers=headers).status_code==200
    with db() as conn:
        remaining=conn.execute("SELECT expires_at-now() FROM sessions WHERE token_hash=%s",(token_hash,)).fetchone()[0]
    assert timedelta(minutes=19) < remaining < timedelta(minutes=21)


def test_serp_state_survives_in_memory_restart():
    client,headers,user_id=auth_client(); fund(user_id)
    scrap=create_scrap(client,headers)
    token=client.post('/serp/sessions',headers=headers,json={'scrap_id':scrap['id'],'ttl_seconds':86400}).json()['token']
    imported=client.post('/serp/import',headers=headers,json={'token':token,'urls':['https://example.com/a','https://example.com/a']})
    assert imported.status_code==200
    api.SERP_SESSIONS.clear()
    restored=client.get(f'/serp/sessions/{token}',headers=headers)
    assert restored.status_code==200 and restored.json()['urls']==['https://example.com/a','https://example.com/a']


def test_scrap_creation_charges_configured_price():
    client,headers,user_id=auth_client(); fund(user_id,1000)
    before=client.get('/billing',headers=headers).json()['balance_cents']
    created=create_scrap(client,headers)
    billing=client.get('/billing',headers=headers).json()
    price=billing['scrap_creation_price_cents']
    assert created['charged_cents']==price
    assert billing['balance_cents']==before-price
    with db() as conn:
        count=conn.execute("SELECT count(*) FROM wallet_transactions WHERE user_id=%s AND transaction_type='scrap_creation' AND reference_id=%s",(uuid.UUID(user_id),created['id'])).fetchone()[0]
    assert count==1


def test_insufficient_balance_does_not_create_scrap_or_charge():
    client,headers,user_id=auth_client(); fund(user_id,199)
    response=client.post('/scraps',headers=headers,json={'name':'No funds','criteria':{'industry':'gold'}})
    assert response.status_code==402
    assert client.get('/scraps/current',headers=headers).json() is None
    with db() as conn:
        count=conn.execute("SELECT count(*) FROM wallet_transactions WHERE user_id=%s AND transaction_type='scrap_creation'",(uuid.UUID(user_id),)).fetchone()[0]
    assert count==0


def test_retry_create_while_current_scrap_does_not_double_charge():
    client,headers,user_id=auth_client(); fund(user_id,1000)
    first=create_scrap(client,headers)
    price=first['charged_cents']
    retry=client.post('/scraps',headers=headers,json={'name':'Retry','criteria':{'industry':'gold'}})
    assert retry.status_code==409
    assert client.get('/billing',headers=headers).json()['balance_cents']==1000-price
    assert client.get('/scraps/current',headers=headers).json()['id']==str(uuid.UUID(first['id']))


def test_submission_completion_releases_current_scrap_and_allows_next():
    client,headers,user_id=auth_client(); fund(user_id,1000)
    first=create_scrap(client,headers)
    completed=client.post(f"/scraps/{first['id']}/complete-submission",headers=headers)
    assert completed.status_code==200 and completed.json()['status']=='submitted'
    assert client.get('/scraps/current',headers=headers).json() is None
    second=create_scrap(client,headers,'Second')
    assert second['id']!=first['id']
    assert client.get('/billing',headers=headers).json()['balance_cents']==1000-first['charged_cents']-second['charged_cents']


def test_research_completion_does_not_close_current_scrap():
    client,headers,user_id=auth_client(); fund(user_id,1000)
    scrap=create_scrap(client,headers,'Research stays open')
    with db() as conn:
        job_id=uuid.uuid4()
        conn.execute("INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,'completed','Export','{}','{}')",(job_id,uuid.UUID(scrap['id'])))
        conn.commit()
    current=client.get('/scraps/current',headers=headers)
    assert current.status_code==200 and current.json()['id']==str(uuid.UUID(scrap['id']))
    assert current.json()['status']=='active'


def test_current_scrap_isolated_between_users():
    client,ha,ua=auth_client(); _,hb,ub=auth_client(); fund(ua); fund(ub)
    scrap=create_scrap(client,ha,'User A')
    assert client.get('/scraps/current',headers=hb).json() is None
    assert client.get('/scraps/current',headers=ha).json()['id']==str(uuid.UUID(scrap['id']))


def test_serp_limit_rejects_over_capacity_without_partial_import():
    client,headers,user_id=auth_client(); fund(user_id)
    scrap=create_scrap(client,headers,'SERP limit')
    token=client.post('/serp/sessions',headers=headers,json={'scrap_id':scrap['id'],'ttl_seconds':86400}).json()['token']
    with db() as conn:
        conn.execute("UPDATE app_settings SET value='2'::jsonb WHERE key='serp_result_limit'"); conn.commit()
    try:
        ok=client.post('/serp/import',headers=headers,json={'token':token,'results':[{'url':'https://example.com/1'},{'url':'https://example.com/2'}]})
        assert ok.status_code==200
        rejected=client.post('/serp/import',headers=headers,json={'token':token,'results':[{'url':'https://example.com/3'}]})
        assert rejected.status_code==409
        current=client.get(f'/scraps/{scrap["id"]}',headers=headers).json()
        assert current['counts']['serp_results']==2 and current['serp_limit']==2
    finally:
        with db() as conn:
            conn.execute("UPDATE app_settings SET value='1000'::jsonb WHERE key='serp_result_limit'"); conn.commit()


def test_serp_limit_applies_to_sync_endpoint():
    client,headers,user_id=auth_client(); fund(user_id)
    scrap=create_scrap(client,headers,'SERP sync limit')
    with db() as conn:
        conn.execute("UPDATE app_settings SET value='1'::jsonb WHERE key='serp_result_limit'"); conn.commit()
    try:
        ok=client.post('/serp/sync',headers={**headers,'X-Scrap-Id':scrap['id']},json={'token':'a'*32,'results':[{'url':'https://example.com/1'}]})
        assert ok.status_code==200
        rejected=client.post('/serp/sync',headers={**headers,'X-Scrap-Id':scrap['id']},json={'token':'a'*32,'results':[{'url':'https://example.com/2'}]})
        assert rejected.status_code==409
    finally:
        with db() as conn:
            conn.execute("UPDATE app_settings SET value='1000'::jsonb WHERE key='serp_result_limit'"); conn.commit()



def test_dataforseo_provider_normalizes_google_organic_results(monkeypatch):
    from src.search.premium import DataForSeoPremiumSerpProvider
    import src.search.premium as premium
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"status_code":20000,"tasks":[{"status_code":20000,"status_message":"Ok","result":[{"items":[
                {"type":"organic","url":"https://example.com/a","title":"A","description":"Desc A"},
                {"type":"paid","url":"https://ads.example.com"},
                {"type":"organic","url":"https://example.com/b","title":"B","description":"Desc B"}
            ]}]}]}
    calls=[]
    def fake_post(url, **kwargs):
        calls.append((url,kwargs)); return Response()
    monkeypatch.setattr(premium.requests, 'post', fake_post)
    monkeypatch.setenv('DATAFORSEO_LOGIN','login')
    monkeypatch.setenv('DATAFORSEO_PASSWORD','password')
    monkeypatch.setenv('DATAFORSEO_LOCATION_CODE','2840')
    monkeypatch.setenv('DATAFORSEO_LANGUAGE_CODE','en')
    items=DataForSeoPremiumSerpProvider({'login':'login','password':'password'},{'location_code':2840,'language_code':'en'}).search('https://www.google.com/search?q=buyers+india',limit=10)
    assert [x.url for x in items]==['https://example.com/a','https://example.com/b']
    assert items[0].snippet=='Desc A'
    assert calls[0][0].endswith('/v3/serp/google/organic/live/advanced')
    assert calls[0][1]['json'][0]['keyword']=='buyers india'


def test_premium_serp_extraction_charges_once_and_persists_results(monkeypatch):
    client,headers,user_id=auth_client(); fund(user_id,1000)
    scrap=create_scrap(client,headers,'Premium')
    class FakeProvider:
        def search_all(self, search_url, *, limit):
            from src.search.premium import PremiumSerpItem
            return [PremiumSerpItem('https://example.com/person','Person','Buyer contact',search_url)]
    monkeypatch.setattr(api, 'HttpPremiumSerpProvider', FakeProvider)
    key=uuid.uuid4().hex
    r=client.post('/serp/premium',headers=headers,json={'scrap_id':scrap['id'],'search_url':'https://www.google.com/search?q=buyers+india','idempotency_key':key})
    assert r.status_code==200 and r.json()['results']==1 and r.json()['charged_cents']==100
    premium_price=r.json()['charged_cents']
    expected_balance=1000-scrap['charged_cents']-premium_price
    assert client.get('/billing',headers=headers).json()['balance_cents']==expected_balance
    retry=client.post('/serp/premium',headers=headers,json={'scrap_id':scrap['id'],'search_url':'https://www.google.com/search?q=buyers+india','idempotency_key':key})
    assert retry.status_code==200 and retry.json()['extraction_id']==r.json()['extraction_id']
    expected_balance=1000-scrap['charged_cents']-premium_price
    assert client.get('/billing',headers=headers).json()['balance_cents']==expected_balance
    with db() as conn:
        assert conn.execute("SELECT count(*) FROM serp_results WHERE scrap_id=%s",(uuid.UUID(scrap['id']),)).fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM wallet_transactions WHERE user_id=%s AND transaction_type='premium_serp_extraction'",(uuid.UUID(user_id),)).fetchone()[0]==1


def test_premium_serp_failure_refunds_charge(monkeypatch):
    client,headers,user_id=auth_client(); fund(user_id,1000)
    scrap=create_scrap(client,headers,'Premium failure')
    class FailingProvider:
        def search_all(self, search_url, *, limit): raise RuntimeError('provider unavailable')
    monkeypatch.setattr(api, 'HttpPremiumSerpProvider', FailingProvider)
    before=client.get('/billing',headers=headers).json()['balance_cents']
    r=client.post('/serp/premium',headers=headers,json={'scrap_id':scrap['id'],'search_url':'https://www.bing.com/search?q=buyers+india','idempotency_key':uuid.uuid4().hex})
    assert r.status_code==502
    assert client.get('/billing',headers=headers).json()['balance_cents']==before


def test_premium_search_url_validation_is_strict():
    client,headers,user_id=auth_client(); fund(user_id,1000)
    scrap=create_scrap(client,headers,'Premium validation')
    for url in ('http://www.google.com/search?q=x','https://example.com/search?q=x','https://www.google.com/','https://www.google.com/search'):
        r=client.post('/serp/premium',headers=headers,json={'scrap_id':scrap['id'],'search_url':url,'idempotency_key':uuid.uuid4().hex})
        assert r.status_code==422


def test_premium_provider_registry_has_four_providers():
    from src.search.premium import SUPPORTED_PROVIDERS, provider_statuses
    assert set(SUPPORTED_PROVIDERS)=={'serper','dataforseo','serpapi','brightdata'}
    rows=provider_statuses()
    assert {r['provider'] for r in rows}==set(SUPPORTED_PROVIDERS)
    assert sum(r['is_default'] for r in rows)==1
    assert next(r for r in rows if r['is_default'])['provider']=='serper'


def test_serper_provider_normalizes_results(monkeypatch):
    from src.search.premium import SerperPremiumSerpProvider
    import src.search.premium as premium
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'organic':[{'link':'https://example.com/a','title':'A','snippet':'Desc'}]}
    calls=[]
    monkeypatch.setattr(premium.requests,'post',lambda url,**kwargs:(calls.append((url,kwargs)) or Response()))
    items=SerperPremiumSerpProvider({'api_key':'key'},{'endpoint':'https://google.serper.dev/search'}).search('https://www.google.com/search?q=buyers+india',limit=10)
    assert items[0].url=='https://example.com/a'
    assert calls[0][1]['headers']['X-API-KEY']=='key'
    assert calls[0][1]['json']['q']=='buyers india'


def test_serpapi_provider_normalizes_results(monkeypatch):
    from src.search.premium import SerpApiPremiumSerpProvider
    import src.search.premium as premium
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'organic_results':[{'link':'https://example.com/a','title':'A','snippet':'Desc'}]}
    calls=[]
    monkeypatch.setattr(premium.requests,'get',lambda url,**kwargs:(calls.append((url,kwargs)) or Response()))
    items=SerpApiPremiumSerpProvider({'api_key':'key'},{'endpoint':'https://serpapi.com/search.json'}).search('https://www.google.com/search?q=buyers+india',limit=10)
    assert items[0].url=='https://example.com/a'
    assert calls[0][1]['params']['engine']=='google'
    assert calls[0][1]['params']['api_key']=='key'


def test_brightdata_provider_normalizes_results(monkeypatch):
    from src.search.premium import BrightDataPremiumSerpProvider
    import src.search.premium as premium
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'organic':[{'link':'https://example.com/b','title':'B','description':'Desc B'}]}
    calls=[]
    monkeypatch.setattr(premium.requests,'post',lambda url,**kwargs:(calls.append((url,kwargs)) or Response()))
    items=BrightDataPremiumSerpProvider({'api_key':'key'},{'endpoint':'https://api.brightdata.com/request','zone':'serp_api1'}).search('https://www.bing.com/search?q=buyers+india',limit=10)
    assert items[0].url=='https://example.com/b'
    assert calls[0][1]['json']['zone']=='serp_api1'


def test_admin_can_configure_default_premium_provider(monkeypatch):
    client,headers,user_id=auth_client()
    admin_email=f"admin-{uuid.uuid4().hex}@example.test"
    with db() as conn:
        conn.execute("UPDATE users SET email=%s WHERE id=%s",(admin_email,uuid.UUID(user_id))); conn.commit()
    with db() as conn:
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,credentials,settings) VALUES('serpapi',true,false,NULL,'{}') ON CONFLICT(provider) DO NOTHING"); conn.commit()
    import os
    monkeypatch.setenv('ADMIN_EMAILS',admin_email)
    with db() as conn:
        conn.execute("UPDATE premium_provider_configs SET credentials=NULL WHERE provider='serpapi'"); conn.commit()
    r=client.post('/admin/premium-providers/serpapi',headers=headers,json={'credentials':{'api_key':'test-key'},'settings':{'endpoint':'https://serpapi.com/search.json'},'enabled':True,'make_default':True})
    assert r.status_code==200 and r.json()['is_default'] is True and r.json()['configured'] is True
    rows=client.get('/admin/premium-providers',headers=headers).json()
    assert sum(x['is_default'] for x in rows)==1
    with db() as conn:
        conn.execute("UPDATE premium_provider_configs SET is_default=false"); conn.execute("UPDATE premium_provider_configs SET is_default=true,enabled=true WHERE provider='serper'"); conn.commit()


def test_admin_settings_and_user_deletion_are_persistent():
    client,headers,user_id=auth_client()
    admin_email=f"admin-{uuid.uuid4().hex}@example.test"
    target_email=f"delete-me-{uuid.uuid4().hex}@example.test"
    with db() as conn:
        conn.execute("UPDATE users SET email=%s WHERE id=%s",(admin_email,uuid.UUID(user_id)))
        conn.execute("INSERT INTO users(id,email,password_hash) VALUES(%s,%s,'x')",(uuid.uuid4(),target_email))
        conn.commit()
    import os
    os.environ['ADMIN_EMAILS']=admin_email
    r=client.post('/admin/scrap-price?amount_cents=375',headers=headers); assert r.status_code==200
    r=client.post('/admin/premium-serp-price',headers=headers,json={'amount_cents':225}); assert r.status_code==200
    r=client.post('/admin/serp-limit',headers=headers,json={'limit':2500}); assert r.status_code==200
    settings=client.get('/admin/settings',headers=headers); assert settings.status_code==200 and settings.json()['scrap_creation_price_cents']==375 and settings.json()['premium_serp_price_cents']==225 and settings.json()['serp_result_limit']==2500
    users=client.get('/admin/users',headers=headers); assert users.status_code==200 and any(u['email']==target_email for u in users.json())
    target=next(u for u in users.json() if u['email']==target_email)
    r=client.delete(f"/admin/users/{target['id']}",headers=headers); assert r.status_code==200
    assert not any(u['email']==target_email for u in client.get('/admin/users',headers=headers).json())
    assert client.delete(f'/admin/users/{user_id}',headers=headers).status_code==409


def test_admin_user_pagination_and_bulk_delete_limit():
    client,headers,user_id=auth_client()
    admin_email=f"admin-{uuid.uuid4().hex}@example.test"
    target_ids=[]
    with db() as conn:
        conn.execute("UPDATE users SET email=%s WHERE id=%s",(admin_email,uuid.UUID(user_id)))
        for i in range(205):
            uid=uuid.uuid4(); target_ids.append(str(uid))
            conn.execute("INSERT INTO users(id,email,password_hash) VALUES(%s,%s,'x')",(uid,f"bulk-{i}-{uuid.uuid4().hex}@example.test"))
        conn.commit()
    import os
    os.environ['ADMIN_EMAILS']=admin_email
    r=client.get('/admin/users/paged',headers=headers,params={'page':1,'page_size':200})
    assert r.status_code==200 and r.json()['page_size']==200 and r.json()['total'] >= 206 and len(r.json()['users'])==200
    r=client.get('/admin/users/paged',headers=headers,params={'page':2,'page_size':200})
    assert r.status_code==200 and len(r.json()['users']) >= 6
    r=client.post('/admin/users/bulk-delete',headers=headers,json={'user_ids':target_ids[:201]})
    assert r.status_code==422
    r=client.post('/admin/users/bulk-delete',headers=headers,json={'user_ids':target_ids[:200]})
    assert r.status_code==200 and r.json()['deleted']==200
    r=client.post('/admin/users/bulk-delete',headers=headers,json={'user_ids':[user_id]})
    assert r.status_code==409
    r=client.post('/admin/users/bulk-delete',headers=headers,json={'user_ids':target_ids[200:]})
    assert r.status_code==200 and r.json()['deleted']==5


async def _fake_page_extract(self, html, source_url, evidence=None):
    from src.models.lead import Lead
    return [Lead(first_name="Jane",last_name="Doe",email="jane@example.com",source_url=source_url)]

def test_page_indexer_charges_once_and_dedupes(monkeypatch):
    client,headers,user_id=auth_client(); fund(user_id,1000)
    scrap=create_scrap(client,headers,'Page Indexer')
    monkeypatch.setattr(api.AdaptiveLeadExtractor,'extract',_fake_page_extract)
    payload={'url':'https://example.com/contact','title':'Contact Jane','html':'<html><body><div class="contact"><span>Jane Doe</span><a href="mailto:jane@example.com">jane@example.com</a></div></body></html>','auto':False}
    first=client.post('/page-indexer/process',headers=headers,json=payload)
    assert first.status_code==200
    assert first.json()['charged_cents']==1 and first.json()['leads']==1
    second=client.post('/page-indexer/process',headers=headers,json=payload)
    assert second.status_code==200 and second.json()['duplicate'] is True and second.json()['charged_cents']==0
    assert client.get('/billing',headers=headers).json()['balance_cents']==799
    with db() as conn:
        assert conn.execute("SELECT count(*) FROM leads WHERE scrap_id=%s",(uuid.UUID(scrap['id']),)).fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM wallet_transactions WHERE user_id=%s AND transaction_type='page_indexer'",(uuid.UUID(user_id),)).fetchone()[0]==1

def test_page_indexer_discards_ineligible_without_charge():
    client,headers,user_id=auth_client(); fund(user_id,1000); create_scrap(client,headers,'Page Indexer Gate')
    response=client.post('/page-indexer/process',headers=headers,json={'url':'https://example.com/about','title':'About','html':'<html><body><p>Company overview only.</p></body></html>'})
    assert response.status_code==200 and response.json()['eligible'] is False
    assert client.get('/billing',headers=headers).json()['balance_cents']==800


def test_admin_scrap_reset_refunds_and_preserves_completed_leads(monkeypatch):
    client,headers,user_id=auth_client(); fund(user_id,1000)
    monkeypatch.setattr(api, '_send_wallet_adjustment_email', lambda *args: None)
    admin_email=f"admin-{uuid.uuid4().hex}@example.test"
    with db() as conn:
        conn.execute("UPDATE users SET email=%s,role='admin' WHERE id=%s",(admin_email,uuid.UUID(user_id)))
        scrap=create_scrap(client,headers,'Reset me')
        sid=uuid.UUID(scrap['id'])
        completed_id=uuid.uuid4(); working_id=uuid.uuid4()
        conn.execute("INSERT INTO leads(id,scrap_id,data,status) VALUES(%s,%s,%s,'completed')",(completed_id,sid,{'first_name':'Keep','last_name':'Lead'}))
        conn.execute("INSERT INTO leads(id,scrap_id,data,status) VALUES(%s,%s,%s,'working')",(working_id,sid,{'first_name':'Delete','last_name':'Lead'}))
        conn.commit()
    monkeypatch.setenv('ADMIN_EMAILS',admin_email)
    before=client.get('/billing',headers=headers).json()['balance_cents']
    response=client.post(f'/admin/scraps/{scrap["id"]}/reset',headers=headers)
    assert response.status_code==200 and response.json()['refunded_cents']==scrap['charged_cents']
    assert client.get('/billing',headers=headers).json()['balance_cents']==before+scrap['charged_cents']
    with db() as conn:
        assert conn.execute("SELECT count(*) FROM scraps WHERE id=%s",(sid,)).fetchone()[0]==0
        assert conn.execute("SELECT scrap_id,user_id,status FROM leads WHERE id=%s",(completed_id,)).fetchone()==(None,uuid.UUID(user_id),'completed')
        assert conn.execute("SELECT count(*) FROM leads WHERE id=%s",(working_id,)).fetchone()[0]==0
        assert conn.execute("SELECT count(*) FROM wallet_transactions WHERE user_id=%s AND transaction_type='scrap_reset_refund' AND reference_id=%s",(uuid.UUID(user_id),str(sid))).fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM admin_audit_events WHERE action='scrap_reset' AND metadata->>'scrap_id'=%s",(str(sid),)).fetchone()[0]==1


def test_admin_scrap_reset_is_admin_only(monkeypatch):
    client,headers,user_id=auth_client(); fund(user_id,1000); scrap=create_scrap(client,headers,'Protected reset')
    monkeypatch.setenv('ADMIN_EMAILS','different-admin@example.test')
    response=client.post(f'/admin/scraps/{scrap["id"]}/reset',headers=headers)
    assert response.status_code==403
    assert client.get('/scraps/current',headers=headers).json()['id']==str(uuid.UUID(scrap['id']))
