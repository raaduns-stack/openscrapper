from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api import app as api
from src.api.app import JobRequest
from src.db import db
from psycopg.types.json import Jsonb
from psycopg.types.json import Jsonb


CRITERIA = {
    "industry": "gold",
    "geography": "Nigeria",
    "target_type": "people",
    "max_leads": 10,
}


def test_google_sheets_requires_spreadsheet_id():
    try:
        JobRequest(criteria=CRITERIA, export_format="google_sheets")
        assert False
    except ValidationError as exc:
        assert "google_spreadsheet_id" in str(exc)


def _insert_job(scrap_id, job_id, status="completed", export_format="csv", output=None):
    import uuid
    from psycopg.types.json import Jsonb
    with db() as conn:
        conn.execute("INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,%s,%s,%s,%s)",(uuid.UUID(job_id),uuid.UUID(scrap_id),status,"Export",Jsonb({"export_format":export_format}),Jsonb({"lead_count":1,"output":output}))); conn.commit()

def _test_scrap_auth():
    import uuid
    client=TestClient(api.app)
    email=f"job-{uuid.uuid4().hex}@example.test"
    r=client.post("/auth/register",json={"email":email,"password":"StrongTestPassword123!"}); assert r.status_code==200
    token=r.json()["token"]
    user_id=r.json()["user_id"]
    with db() as conn:
        conn.execute("UPDATE wallets SET balance_cents=10000 WHERE user_id=%s",(__import__('uuid').UUID(user_id),)); conn.commit()
    scrap=client.post("/scraps",headers={"Authorization":f"Bearer {token}"},json={"name":"Job test","criteria":{"industry":"gold"}}); assert scrap.status_code==200
    return scrap.json()["id"], token

def test_google_sheets_download_is_not_a_file():
    scrap_id,token=_test_scrap_auth(); job_id=__import__('uuid').uuid4().hex
    _insert_job(scrap_id,job_id,output="sheet-id",export_format="google_sheets")
    response=TestClient(api.app).get(f"/jobs/{job_id}/download",headers={"Authorization":f"Bearer {token}"})
    assert response.status_code==409

def test_file_job_download_missing_file():
    scrap_id,token=_test_scrap_auth(); job_id=__import__('uuid').uuid4().hex
    _insert_job(scrap_id,job_id,output="output/does-not-exist.csv")
    response=TestClient(api.app).get(f"/jobs/{job_id}/download",headers={"Authorization":f"Bearer {token}"})
    assert response.status_code==404

def test_unknown_job_returns_404():
    _,token=_test_scrap_auth()
    response=TestClient(api.app).get("/jobs/not-real",headers={"Authorization":f"Bearer {token}"})
    assert response.status_code==404

def test_job_read_survives_in_memory_state_loss():
    scrap_id,token=_test_scrap_auth(); job_id=__import__('uuid').uuid4().hex
    _insert_job(scrap_id,job_id,output="output/restart.csv")
    api.JOBS.clear(); response=TestClient(api.app).get(f"/jobs/{job_id}",headers={"Authorization":f"Bearer {token}"})
    assert response.status_code==200; assert response.json()["job_id"].replace("-","")==job_id; assert response.json()["status"]=="completed"

def test_startup_reconciles_interrupted_jobs():
    scrap_id,token=_test_scrap_auth(); job_id=__import__('uuid').uuid4().hex
    _insert_job(scrap_id,job_id,status="running",output="output/restart.csv")
    api._reconcile_jobs_on_startup(); response=TestClient(api.app).get(f"/jobs/{job_id}",headers={"Authorization":f"Bearer {token}"})
    assert response.status_code==200; assert response.json()["status"]=="failed"; assert response.json()["error"]=="Job did not survive process restart"

def test_job_isolation_between_users():
    scrap_id,token=_test_scrap_auth(); job_id=__import__('uuid').uuid4().hex; _insert_job(scrap_id,job_id)
    other=TestClient(api.app).post("/auth/register",json={"email":f"other-{__import__('uuid').uuid4().hex}@example.test","password":"StrongTestPassword123!"}).json()["token"]
    response=TestClient(api.app).get(f"/jobs/{job_id}",headers={"Authorization":f"Bearer {other}"})
    assert response.status_code==404

def test_job_request_accepts_independent_crawl_url_limit():
    from src.api.app import JobRequest

    request = JobRequest(
        criteria={"industry": "gold"},
        crawler={"max_crawl_pages": 25, "max_crawl_urls": 250},
    )
    assert request.crawler.max_crawl_pages == 25
    assert request.crawler.max_crawl_urls == 250

def test_search_parameters_are_persisted_and_owned():
    import uuid
    client=TestClient(api.app)
    email=f"search-param-{uuid.uuid4().hex}@example.test"
    auth=client.post('/auth/register',json={'email':email,'password':'StrongTestPassword123!'}); assert auth.status_code==200
    headers={'Authorization':f"Bearer {auth.json()['token']}"}
    with db() as conn:
        conn.execute("UPDATE wallets SET balance_cents=10000 WHERE user_id=%s",(__import__('uuid').UUID(auth.json()['user_id']),)); conn.commit()
    scrap=client.post('/scraps',headers=headers,json={'name':'Persistent Search','criteria':{'industry':'gold','geography':'Germany','roles':['buyer']}}); assert scrap.status_code==200
    scrap_id=scrap.json()['id']
    criteria={'industry':'gold','geography':'Germany','target_type':'people','roles':['buyer'],'max_leads':10}
    generated=client.post('/search/parameters',headers=headers,json={'scrap_id':scrap_id,'criteria':criteria,'max_queries':6}); assert generated.status_code==200
    expected=generated.json()['parameters']; assert len(expected)==6
    stored=client.get(f'/scraps/{scrap_id}/search-parameters',headers=headers); assert stored.status_code==200
    assert stored.json()==expected
    other=client.post('/auth/register',json={'email':f"other-{uuid.uuid4().hex}@example.test",'password':'StrongTestPassword123!'}); assert other.status_code==200
    other_headers={'Authorization':f"Bearer {other.json()['token']}"}
    denied=client.get(f'/scraps/{scrap_id}/search-parameters',headers=other_headers); assert denied.status_code==200
    assert denied.json()==[]



def test_job_cancel_is_owner_scoped_and_persistent():
    import uuid
    scrap_id,token=_test_scrap_auth(); job_id=uuid.uuid4().hex
    _insert_job(scrap_id,job_id,status="queued")
    client=TestClient(api.app)
    other=client.post("/auth/register",json={"email":f"cancel-other-{uuid.uuid4().hex}@example.test","password":"StrongTestPassword123!"}).json()["token"]
    denied=client.post(f"/jobs/{job_id}/cancel",headers={"Authorization":f"Bearer {other}"}); assert denied.status_code==404
    canceled=client.post(f"/jobs/{job_id}/cancel",headers={"Authorization":f"Bearer {token}"}); assert canceled.status_code==200
    assert canceled.json()["status"]=="canceled"
    loaded=client.get(f"/jobs/{job_id}",headers={"Authorization":f"Bearer {token}"}); assert loaded.status_code==200
    assert loaded.json()["status"]=="canceled"

def test_cancel_completed_job_is_idempotent():
    import uuid
    scrap_id,token=_test_scrap_auth(); job_id=uuid.uuid4().hex
    _insert_job(scrap_id,job_id,status="completed")
    response=TestClient(api.app).post(f"/jobs/{job_id}/cancel",headers={"Authorization":f"Bearer {token}"})
    assert response.status_code==200; assert response.json()["status"]=="completed"

def test_client_mailbox_prefix_add_remove_is_isolated():
    import uuid
    client=TestClient(api.app)
    a=client.post('/auth/register',json={'email':f'policy-a-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}); assert a.status_code==200
    b=client.post('/auth/register',json={'email':f'policy-b-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}); assert b.status_code==200
    ah={'Authorization':f"Bearer {a.json()['token']}"}; bh={'Authorization':f"Bearer {b.json()['token']}"}
    added=client.post('/settings/generic-mailbox-prefixes',headers=ah,json={'prefix':'procurement'}); assert added.status_code==200
    assert any(x['prefix']=='procurement' for x in client.get('/settings/generic-mailbox-prefixes',headers=ah).json())
    assert not any(x['prefix']=='procurement' for x in client.get('/settings/generic-mailbox-prefixes',headers=bh).json())
    assert client.delete(f"/settings/generic-mailbox-prefixes/{added.json()['id']}",headers=ah).status_code==200
    assert not any(x['prefix']=='procurement' for x in client.get('/settings/generic-mailbox-prefixes',headers=ah).json())

def test_client_domain_rules_are_isolated_and_normalized():
    import uuid
    client=TestClient(api.app)
    a=client.post('/auth/register',json={'email':f'domain-a-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}); assert a.status_code==200
    b=client.post('/auth/register',json={'email':f'domain-b-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}); assert b.status_code==200
    ah={'Authorization':f"Bearer {a.json()['token']}"}; bh={'Authorization':f"Bearer {b.json()['token']}"}
    added=client.post('/settings/domain-rules',headers=ah,json={'domain':'https://WWW.Example.com/','rule_type':'blacklist'}); assert added.status_code==200
    assert added.json()['domain']=='example.com'
    assert any(x['domain']=='example.com' for x in client.get('/settings/domain-rules',headers=ah).json())
    assert client.get('/settings/domain-rules',headers=bh).json()==[]
    assert client.delete(f"/settings/domain-rules/{added.json()['id']}",headers=ah).status_code==200

def test_domain_rule_precedence():
    from src.pipeline import _domain_allowed
    assert _domain_allowed('https://example.com/person', [('example.com','whitelist')])
    assert not _domain_allowed('https://other.com/person', [('example.com','whitelist')])
    assert not _domain_allowed('https://example.com/person', [('example.com','whitelist'),('example.com','blacklist')])

def test_generic_mailbox_prefixes_are_client_scoped():
    import uuid
    client=TestClient(api.app)
    a=client.post('/auth/register',json={'email':f'prefix-a-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}).json()['token']
    b=client.post('/auth/register',json={'email':f'prefix-b-{uuid.uuid4().hex}@example.test','password':'StrongTestPassword123!'}).json()['token']
    ha={'Authorization':f'Bearer {a}'}; hb={'Authorization':f'Bearer {b}'}
    added=client.post('/settings/generic-mailbox-prefixes',headers=ha,json={'prefix':'procurement'}); assert added.status_code==200
    assert any(x['prefix']=='procurement' for x in client.get('/settings/generic-mailbox-prefixes',headers=ha).json())
    assert not any(x['prefix']=='procurement' for x in client.get('/settings/generic-mailbox-prefixes',headers=hb).json())
    denied=client.delete(f"/settings/generic-mailbox-prefixes/{added.json()['id']}",headers=hb); assert denied.status_code==404

def test_custom_generic_mailbox_prefix_changes_validation():
    from src.extract.email import is_personal_email
    assert is_personal_email('procurement@example.com')
    assert not is_personal_email('procurement@example.com', {'procurement'})
    assert not is_personal_email('procurement-team@example.com', {'procurement'})

def test_extension_login_cors_allows_persistence_header():
    client=TestClient(api.app)
    response=client.options('/auth/login',headers={'Origin':'chrome-extension://abcdefghijklmnopabcdefghijklmnop','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,x-scrappee-extension'})
    assert response.status_code==200
    assert 'X-Scrappee-Extension' in response.headers.get('access-control-allow-headers','')
