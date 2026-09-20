from dotenv import load_dotenv
load_dotenv()
import asyncio, secrets, time, uuid, os
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import Literal
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from src.models.criteria import CrawlerConfig, SearchCriteria
from src.models.lead import Lead
from src.pipeline import LeadDiscoveryPipeline
from src.dedupe.leads import persist_lead
from src.observability.job_events import JobEventSink
from src.search.strategy import SearchStrategyEngine
from src.search.premium import HttpPremiumSerpProvider, parse_search_url, SUPPORTED_PROVIDERS, provider_statuses, save_provider_config
from src.db import db, init_db, purge_expired_history, get_client_policies
from src.auth import create_user, login_user, current_user, create_session
import hashlib
from psycopg.types.json import Jsonb

@asynccontextmanager
async def lifespan(_app):
    init_db()
    _reconcile_jobs_on_startup()
    yield

app=FastAPI(title="Scrappee API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["https://scrapee.uk"], allow_origin_regex=r"^chrome-extension://[a-p]{32}$", allow_credentials=False, allow_methods=["GET","POST","DELETE","OPTIONS"], allow_headers=["Authorization","Content-Type","X-Scrap-Id","X-Scrappee-Extension"])
init_db()
purge_expired_history()
JOBS={}
CANCEL_FLAGS=set()
SERP_SESSIONS={}
SERP_SESSION_TTL=1800
DOWNLOADS_DIR=Path(__file__).resolve().parents[2] / 'downloads'

@app.get('/downloads/scrappee-browser-import-v0.5.0.zip', include_in_schema=False)
def download_extension():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.5.0.zip'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.1.zip', include_in_schema=False)
def download_extension_v060():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.1.zip'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.2.zip', include_in_schema=False)
def download_extension_v062():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.2.zip'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.3.zip', include_in_schema=False)
def download_extension_v063():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.3.zip'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.4.zip', include_in_schema=False)
def download_extension_v064():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.4.zip'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.6.zip', include_in_schema=False)
def download_extension_v066():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.6.zip'
    if not path.exists(): raise HTTPException(404,'Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.5.zip', include_in_schema=False)
def download_extension_v065():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.5.zip'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.7.zip', include_in_schema=False)
def download_extension_v067():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.7.zip'
    if not path.is_file(): raise HTTPException(404,'Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

@app.get('/downloads/scrappee-browser-import-v0.6.8.zip', include_in_schema=False)
def download_extension_v068():
    path=DOWNLOADS_DIR / 'Scrappee-Browser-Import-v0.6.8.zip'
    if not path.is_file(): raise HTTPException(404,'Extension package not found')
    return FileResponse(path, media_type='application/zip', filename=path.name)

class AuthRequest(BaseModel):
    email: str
    password: str=Field(min_length=8,max_length=200)

class MailboxPrefixRequest(BaseModel):
    prefix: str = Field(min_length=1, max_length=100)

class DomainRuleRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    rule_type: Literal["blacklist", "whitelist"]

class ScrapRequest(BaseModel):
    name: str=Field(default="Current Scrap",min_length=1,max_length=200)
    criteria: dict = Field(default_factory=dict)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)

class AdminBulkDeleteUsersRequest(BaseModel):
    user_ids: list[str] = Field(min_length=1,max_length=200)

@app.post("/auth/register")
def register(request: AuthRequest):
    try: user_id=create_user(request.email,request.password)
    except Exception as exc: raise HTTPException(409,"Email already registered") from exc
    token,expires=login_user(request.email,request.password)
    return {"user_id":user_id,"email":request.email.lower().strip(),"token":token,"expires_at":expires.isoformat()}

@app.post("/auth/login")
def login(request: AuthRequest, req: Request):
    persistent=req.headers.get("X-Scrappee-Extension") == "1"
    token,expires=login_user(request.email,request.password,persistent=persistent)
    return {"email":request.email.lower().strip(),"token":token,"expires_at":expires.isoformat()}

@app.post("/auth/web-session")
def web_session(req: Request):
    user=current_user(req)
    token,expires=create_session(uuid.UUID(user["id"]), persistent=True)
    return {"email":user["email"],"token":token,"expires_at":expires.isoformat()}

@app.post("/auth/logout")
def logout(request: Request):
    token=request.headers.get("Authorization","").removeprefix("Bearer " ).strip()
    if token:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=%s",(hashlib.sha256(token.encode()).hexdigest(),)); conn.commit()
    return {"ok":True}

@app.get("/auth/me")
def me(request: Request):
    user=current_user(request); return {"id":user["id"],"email":user["email"]}


@app.get("/settings/generic-mailbox-prefixes")
def get_mailbox_prefixes(req: Request):
    user=current_user(req)
    with db() as conn:
        rows=conn.execute("SELECT id,prefix,created_at FROM generic_mailbox_prefixes WHERE user_id=%s ORDER BY prefix",(uuid.UUID(user["id"]),)).fetchall()
    return [{"id":str(r[0]),"prefix":r[1],"created_at":r[2].isoformat()} for r in rows]

@app.post("/settings/generic-mailbox-prefixes")
def add_mailbox_prefix(request: MailboxPrefixRequest, req: Request):
    user=current_user(req)
    from src.policy import normalize_mailbox_prefix
    prefix=normalize_mailbox_prefix(request.prefix)
    if not prefix: raise HTTPException(422,"Prefix cannot be empty")
    with db() as conn:
        row=conn.execute("INSERT INTO generic_mailbox_prefixes(id,user_id,prefix) VALUES(%s,%s,%s) ON CONFLICT(user_id,prefix) DO UPDATE SET prefix=EXCLUDED.prefix RETURNING id,prefix,created_at",(uuid.uuid4(),uuid.UUID(user["id"]),prefix)).fetchone(); conn.commit()
    return {"id":str(row[0]),"prefix":row[1],"created_at":row[2].isoformat()}

@app.delete("/settings/generic-mailbox-prefixes/{prefix_id}")
def delete_mailbox_prefix(prefix_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        row=conn.execute("DELETE FROM generic_mailbox_prefixes WHERE id=%s AND user_id=%s RETURNING id",(uuid.UUID(prefix_id),uuid.UUID(user["id"]))).fetchone(); conn.commit()
    if not row: raise HTTPException(404,"Prefix not found")

@app.get("/settings/domain-rules")
def get_domain_rules(req: Request):
    user=current_user(req)
    with db() as conn:
        rows=conn.execute("SELECT id,domain,rule_type,created_at FROM domain_rules WHERE user_id=%s ORDER BY rule_type,domain",(uuid.UUID(user["id"]),)).fetchall()
    return [{"id":str(r[0]),"domain":r[1],"rule_type":r[2],"created_at":r[3].isoformat()} for r in rows]

@app.post("/settings/domain-rules")
def add_domain_rule(request: DomainRuleRequest, req: Request):
    user=current_user(req)
    from src.policy import normalize_domain
    domain=normalize_domain(request.domain)
    if not domain or "." not in domain: raise HTTPException(422,"Valid domain is required")
    with db() as conn:
        row=conn.execute("INSERT INTO domain_rules(id,user_id,domain,rule_type) VALUES(%s,%s,%s,%s) ON CONFLICT(user_id,domain,rule_type) DO UPDATE SET domain=EXCLUDED.domain RETURNING id,domain,rule_type,created_at",(uuid.uuid4(),uuid.UUID(user["id"]),domain,request.rule_type)).fetchone(); conn.commit()
    return {"id":str(row[0]),"domain":row[1],"rule_type":row[2],"created_at":row[3].isoformat()}

@app.delete("/settings/domain-rules/{rule_id}")
def delete_domain_rule(rule_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        row=conn.execute("DELETE FROM domain_rules WHERE id=%s AND user_id=%s RETURNING id",(uuid.UUID(rule_id),uuid.UUID(user["id"]))).fetchone(); conn.commit()
    if not row: raise HTTPException(404,"Domain rule not found")

@app.post("/scraps")
def create_scrap(request: ScrapRequest, req: Request):
    user=current_user(req); scrap_id=uuid.uuid4().hex; uid=uuid.UUID(user["id"])
    with db() as conn:
        current=conn.execute("SELECT id FROM scraps WHERE user_id=%s AND status IN ('active','running') ORDER BY created_at DESC LIMIT 1",(uid,)).fetchone()
        if current: raise HTTPException(409,"Finish the Current Scrap by clicking URL SUBMISSION COMPLETED before creating a new Scrap")
        price=int(conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='scrap_creation_price_cents'").fetchone()[0])
        default_max_leads=int(conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_default_max_leads'").fetchone()[0])
        max_leads_limit=int(conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_max_leads'").fetchone()[0])
        timeout_hours=int(conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_timeout_hours'").fetchone()[0])
        criteria=dict(request.criteria or {})
        requested_max_leads=int(criteria.get("max_leads", default_max_leads))
        if requested_max_leads < 1 or requested_max_leads > max_leads_limit: raise HTTPException(422, f"Maximum leads must be between 1 and {max_leads_limit}")
        criteria["max_leads"]=requested_max_leads
        crawler_data=request.crawler.model_dump(); crawler_data["max_duration_hours"]=timeout_hours
        wallet=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone()
        if not wallet: raise HTTPException(500,"Wallet not initialized")
        balance=int(wallet[0])
        if balance < price: raise HTTPException(402,f"Insufficient balance. Scrap costs ${price/100:.2f}")
        conn.execute("UPDATE wallets SET balance_cents=balance_cents-%s,updated_at=now() WHERE user_id=%s",(price,uid))
        new_balance=balance-price
        conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'scrap_creation',%s)",(uuid.uuid4(),uid,-price,new_balance,scrap_id))
        conn.execute("INSERT INTO scraps(id,user_id,name,criteria,crawler_config) VALUES(%s,%s,%s,%s,%s)",(uuid.UUID(scrap_id),uid,request.name,Jsonb(criteria),Jsonb(crawler_data)))
        conn.commit()
    return {"id":scrap_id,"name":request.name,"status":"active","charged_cents":price,"balance_cents":new_balance}

class WalletAdjustmentRequest(BaseModel):
    user_email: str
    amount_cents: int

class AdminPriceRequest(BaseModel):
    amount_cents: int = Field(ge=0)

class AdminResearchSettingsRequest(BaseModel):
    default_max_leads: int = Field(ge=1, le=100000)
    max_leads: int = Field(ge=1, le=100000)
    timeout_hours: int = Field(ge=1, le=720)

class AdminPremiumProviderRequest(BaseModel):
    credentials: dict[str, str] = Field(default_factory=dict)
    settings: dict[str, object] = Field(default_factory=dict)
    enabled: bool = True
    make_default: bool = False


def _is_admin(user):
    admins={x.strip().lower() for x in os.getenv("ADMIN_EMAILS","").split(",") if x.strip()}
    return user["email"].lower() in admins

@app.get("/admin/premium-providers")
def admin_premium_providers(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    return provider_statuses()

@app.post("/admin/premium-providers/{provider}")
def admin_premium_provider(provider: str, request: AdminPremiumProviderRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    provider=provider.lower().strip()
    if provider not in SUPPORTED_PROVIDERS: raise HTTPException(422,"Unsupported Premium SERP provider")
    try:
        save_provider_config(provider, {str(k):str(v) for k,v in request.credentials.items() if str(v).strip()}, request.settings, request.enabled, request.make_default)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    return next(x for x in provider_statuses() if x["provider"]==provider)

@app.get("/billing")
def billing(req: Request):
    user=current_user(req); uid=uuid.UUID(user["id"])
    with db() as conn:
        balance=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s",(uid,)).fetchone()[0]
        price=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='scrap_creation_price_cents'").fetchone()[0]
        premium_price=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='premium_serp_price_cents'").fetchone()[0]
        default_max_leads=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_default_max_leads'").fetchone()[0]
        max_leads=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_max_leads'").fetchone()[0]
        timeout_hours=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_timeout_hours'").fetchone()[0]
    return {"balance_cents":int(balance),"scrap_creation_price_cents":int(price),"premium_serp_price_cents":int(premium_price),"research_default_max_leads":int(default_max_leads),"research_max_leads":int(max_leads),"research_timeout_hours":int(timeout_hours)}

@app.post("/admin/scrap-price")
def set_scrap_price(amount_cents: int, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if amount_cents < 0: raise HTTPException(422,"Price cannot be negative")
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('scrap_creation_price_cents',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(amount_cents,)); conn.commit()
    return {"scrap_creation_price_cents":amount_cents}

@app.post("/admin/premium-serp-price")
def admin_premium_serp_price(request: AdminPriceRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    amount_cents=request.amount_cents
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('premium_serp_price_cents',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(amount_cents,)); conn.commit()
    return {"premium_serp_price_cents":amount_cents}

@app.post("/admin/serp-limit")
def admin_serp_limit(request: dict, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    try: limit=int(request.get("limit",0))
    except (TypeError,ValueError): raise HTTPException(400,"limit must be an integer")
    if limit < 1 or limit > 1000000: raise HTTPException(400,"limit must be between 1 and 1000000")
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('serp_result_limit',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(limit,)); conn.commit()
    return {"serp_result_limit":limit}

@app.get("/admin/users")
def admin_users(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT u.id,u.email,u.created_at,COALESCE(w.balance_cents,0) FROM users u LEFT JOIN wallets w ON w.user_id=u.id ORDER BY u.created_at DESC,u.email").fetchall()
    return [{"id":str(r[0]),"email":r[1],"created_at":r[2].isoformat(),"balance_cents":int(r[3])} for r in rows]

@app.get("/admin/users/paged")
def admin_users_paged(req: Request, page: int = 1, page_size: int = 50, search: str = ""):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if page < 1: raise HTTPException(400,"page must be at least 1")
    if page_size < 1 or page_size > 200: raise HTTPException(400,"page_size must be between 1 and 200")
    search=search.strip()
    pattern=f"%{search}%"
    with db() as conn:
        total=int(conn.execute("SELECT COUNT(*) FROM users WHERE email ILIKE %s",(pattern,)).fetchone()[0])
        offset=(page-1)*page_size
        rows=conn.execute("SELECT u.id,u.email,u.created_at,COALESCE(w.balance_cents,0) FROM users u LEFT JOIN wallets w ON w.user_id=u.id WHERE u.email ILIKE %s ORDER BY u.created_at DESC,u.email LIMIT %s OFFSET %s",(pattern,page_size,offset)).fetchall()
    return {"users":[{"id":str(r[0]),"email":r[1],"created_at":r[2].isoformat(),"balance_cents":int(r[3])} for r in rows],"total":total,"page":page,"page_size":page_size,"total_pages":(total+page_size-1)//page_size}

@app.post("/admin/users/bulk-delete")
def admin_bulk_delete_users(request: AdminBulkDeleteUsersRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    try: ids=[uuid.UUID(x) for x in request.user_ids]
    except ValueError as exc: raise HTTPException(422,"Invalid user id") from exc
    if len(set(ids)) != len(ids): raise HTTPException(422,"Duplicate user ids are not allowed")
    admin_id=uuid.UUID(user["id"])
    if admin_id in ids: raise HTTPException(409,"The logged-in admin cannot be deleted")
    placeholders=",".join(["%s"]*len(ids))
    with db() as conn:
        rows=conn.execute(f"DELETE FROM users WHERE id IN ({placeholders}) RETURNING email",tuple(ids)).fetchall()
        conn.commit()
    return {"deleted":len(rows),"emails":[r[0] for r in rows],"requested":len(ids)}

@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: str, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    try: uid=uuid.UUID(user_id)
    except ValueError as exc: raise HTTPException(422,"Invalid user id") from exc
    if uid == uuid.UUID(user["id"]): raise HTTPException(409,"The logged-in admin cannot delete itself")
    with db() as conn:
        row=conn.execute("DELETE FROM users WHERE id=%s RETURNING email",(uid,)).fetchone()
        if not row: raise HTTPException(404,"User not found")
        conn.commit()
    return {"deleted":True,"email":row[0]}

@app.get("/admin/settings")
def admin_settings(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT key,value FROM app_settings WHERE key IN ('scrap_creation_price_cents','premium_serp_price_cents','serp_result_limit','research_default_max_leads','research_max_leads','research_timeout_hours')").fetchall()
    values={r[0]:int(r[1]) for r in rows}
    return values

@app.post("/admin/research-settings")
def admin_research_settings(request: AdminResearchSettingsRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if request.default_max_leads > request.max_leads: raise HTTPException(422,"Default maximum leads cannot exceed the maximum allowed leads")
    with db() as conn:
        for key,value in (("research_default_max_leads",request.default_max_leads),("research_max_leads",request.max_leads),("research_timeout_hours",request.timeout_hours)):
            conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(%s,to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(key,value))
        conn.commit()
    return {"default_max_leads":request.default_max_leads,"max_leads":request.max_leads,"timeout_hours":request.timeout_hours}

@app.get("/admin/wallets")
def admin_wallets(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT u.email,w.balance_cents FROM users u JOIN wallets w ON w.user_id=u.id ORDER BY u.email").fetchall()
    return [{"email":r[0],"balance_cents":int(r[1])} for r in rows]

@app.post("/admin/wallet-adjust")
def adjust_wallet(request: WalletAdjustmentRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        row=conn.execute("SELECT id FROM users WHERE email=%s",(request.user_email.lower().strip(),)).fetchone()
        if not row: raise HTTPException(404,"User not found")
        uid=row[0]
        balance=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone()[0]
        new_balance=int(balance)+request.amount_cents
        if new_balance < 0: raise HTTPException(422,"Wallet balance cannot become negative")
        conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s",(new_balance,uid))
        conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type) VALUES(%s,%s,%s,%s,'admin_adjustment')",(uuid.uuid4(),uid,request.amount_cents,new_balance))
        conn.commit()
    return {"balance_cents":new_balance}

@app.get("/scraps/current")
def current_scrap(req: Request):
    user=current_user(req)
    with db() as conn:
        row=conn.execute("SELECT id,name,status,criteria,crawler_config FROM scraps WHERE user_id=%s AND status IN ('active','running') ORDER BY created_at DESC LIMIT 1",(uuid.UUID(user["id"]),)).fetchone()
    if not row: return None
    return {"id":str(row[0]),"name":row[1],"status":row[2],"criteria":row[3],"crawler":row[4]}

@app.post("/scraps/{scrap_id}/complete-submission")
def complete_submission(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    with db() as conn:
        row=conn.execute("SELECT status FROM scraps WHERE id=%s AND user_id=%s FOR UPDATE",(sid,uuid.UUID(user["id"]))).fetchone()
        if not row: raise HTTPException(404,"Scrap not found")
        if row[0] not in ('active','running'): raise HTTPException(409,"Scrap is already closed")
        conn.execute("UPDATE scraps SET status='submitted',completed_at=now() WHERE id=%s",(sid,)); conn.commit()
    return {"scrap_id":scrap_id,"status":"submitted"}

@app.post("/scraps/{scrap_id}/reopen")
def reopen_scrap(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id); uid=uuid.UUID(user["id"])
    with db() as conn:
        row=conn.execute("SELECT status FROM scraps WHERE id=%s AND user_id=%s FOR UPDATE",(sid,uid)).fetchone()
        if not row: raise HTTPException(404,"Scrap not found")
        current=conn.execute("SELECT id FROM scraps WHERE user_id=%s AND status IN ('active','running') AND id<>%s LIMIT 1",(uid,sid)).fetchone()
        if current: raise HTTPException(409,"Another Current Scrap is already active")
        if row[0] not in ('submitted','failed','canceled'): raise HTTPException(409,"Only submitted, failed, or canceled Scraps can be reopened")
        conn.execute("UPDATE scraps SET status='active',completed_at=NULL WHERE id=%s",(sid,)); conn.commit()
    return {"scrap_id":scrap_id,"status":"active"}

@app.get("/scraps/{scrap_id}/results")
def scrap_results(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        rows=conn.execute("SELECT id,data,created_at FROM leads WHERE scrap_id=%s ORDER BY created_at DESC",(uuid.UUID(scrap_id),)).fetchall()
    return [{"id":str(r[0]),"data":r[1],"created_at":r[2].isoformat()} for r in rows]

@app.post("/scraps/{scrap_id}/leads/{lead_id}/enrich", status_code=202)
async def enrich_lead(scrap_id: str, lead_id: str, background_tasks: BackgroundTasks, req: Request):
    user = current_user(req)
    sid = uuid.UUID(scrap_id)
    with db() as conn:
        row = conn.execute(
            "SELECT l.data FROM leads l JOIN scraps s ON s.id=l.scrap_id "
            "WHERE l.id=%s AND l.scrap_id=%s AND s.user_id=%s",
            (uuid.UUID(lead_id), sid, uuid.UUID(user["id"])),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Lead not found")
        running = conn.execute(
            "SELECT 1 FROM jobs WHERE scrap_id=%s AND status IN ('queued','running') LIMIT 1",
            (sid,),
        ).fetchone()
        if running:
            raise HTTPException(409, "Research is already running for this Scrap")
        job_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,'queued','Queued',%s,%s)",
            (uuid.UUID(job_id), sid, Jsonb({"type": "enrich_lead", "lead_id": lead_id}), Jsonb({"message": "Enrichment queued", "counts": {}, "events": []})),
        )
        conn.commit()
    background_tasks.add_task(_run_enrich_job, job_id, scrap_id, lead_id)
    return {"job_id": job_id, "status": "queued", "lead_id": lead_id}


@app.get("/scraps/{scrap_id}/serp-results")
def scrap_serp_results(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(sid,uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        rows=conn.execute("SELECT id,url,title,snippet,raw_text,provider,page_url,captured_at FROM serp_results WHERE scrap_id=%s ORDER BY captured_at,id",(sid,)).fetchall()
    return [{"id":str(r[0]),"url":r[1],"title":r[2],"snippet":r[3],"raw_text":r[4],"provider":r[5],"page_url":r[6],"created_at":r[7].isoformat()} for r in rows]

@app.get("/scraps/{scrap_id}/url-occurrences")
def scrap_url_occurrences(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(sid,uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        rows=conn.execute("SELECT id,url,created_at FROM url_occurrences WHERE scrap_id=%s ORDER BY created_at,id",(sid,)).fetchall()
    return [{"id":str(r[0]),"url":r[1],"created_at":r[2].isoformat()} for r in rows]

@app.get("/scraps")
def list_scraps(req: Request):
    user=current_user(req)
    with db() as conn:
        rows=conn.execute("SELECT id,name,status,created_at,completed_at FROM scraps WHERE user_id=%s ORDER BY created_at DESC",(uuid.UUID(user["id"]),)).fetchall()
    return [{"id":str(r[0]),"name":r[1],"status":r[2],"created_at":r[3].isoformat(),"completed_at":r[4].isoformat() if r[4] else None} for r in rows]

@app.delete("/scraps/{scrap_id}",status_code=204)
def delete_scrap(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        running=conn.execute("SELECT 1 FROM jobs WHERE scrap_id=%s AND status IN ('queued','running') LIMIT 1",(uuid.UUID(scrap_id),)).fetchone()
        if running: raise HTTPException(409,"Cannot delete a running Scrap; cancel the Job first")
        conn.execute("DELETE FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"])))
        conn.commit()

@app.get("/scraps/{scrap_id}")
def get_scrap(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        row=conn.execute("SELECT id,name,status,criteria,crawler_config,created_at,completed_at FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not row: raise HTTPException(404,"Scrap not found")
        counts=conn.execute("SELECT (SELECT count(*) FROM serp_results WHERE scrap_id=%s),(SELECT count(*) FROM url_occurrences WHERE scrap_id=%s),(SELECT count(*) FROM leads WHERE scrap_id=%s),(SELECT count(*) FROM crawl_pages WHERE scrap_id=%s),llm_calls FROM scraps WHERE id=%s",(uuid.UUID(scrap_id),)*5).fetchone()
        serp_limit=_serp_limit(conn)
    return {"id":str(row[0]),"name":row[1],"status":row[2],"criteria":row[3],"crawler":row[4],"created_at":row[5].isoformat(),"completed_at":row[6].isoformat() if row[6] else None,"counts":{"serp_results":counts[0],"url_occurrences":counts[1],"leads":counts[2],"crawl_pages":counts[3],"llm_calls":counts[4]},"serp_limit":serp_limit}

class EnrichLeadRequest(BaseModel):
    lead_id: str = Field(min_length=1, max_length=64)


class JobRequest(BaseModel):
    scrap_id: str|None=None
    criteria: SearchCriteria
    crawler: CrawlerConfig=Field(default_factory=CrawlerConfig)
    export_format: Literal["csv","xlsx","google_sheets"]="csv"
    google_spreadsheet_id: str|None=None
    google_worksheet: str=Field(default="Leads",min_length=1)
    @model_validator(mode="after")
    def validate_export_target(self):
        if self.export_format=="google_sheets" and not (self.google_spreadsheet_id or "").strip(): raise ValueError("google_spreadsheet_id is required for Google Sheets export")
        return self

class SearchParameterRequest(BaseModel):
    criteria: SearchCriteria
    max_queries: int=Field(default=20,ge=1,le=500)
    scrap_id: str|None=None

class SerpSessionRequest(BaseModel):
    scrap_id: str|None=None
    ttl_seconds: int=Field(default=SERP_SESSION_TTL,ge=60,le=86400)

class SerpResult(BaseModel):
    url: str=Field(min_length=1,max_length=8192)
    title: str=""
    snippet: str=""
    raw_text: str=""
    provider: Literal["google","bing"]|None=None
    page_url: str|None=None

class SerpImportRequest(BaseModel):
    token: str=Field(min_length=32,max_length=128)
    urls: list[str]=Field(default_factory=list)
    results: list[SerpResult]=Field(default_factory=list)
    page_url: str|None=None

class SerpSyncRequest(BaseModel):
    results: list[SerpResult]=Field(default_factory=list)

class PremiumSerpRequest(BaseModel):
    scrap_id: str
    search_url: str = Field(min_length=1, max_length=8192)
    idempotency_key: str = Field(min_length=16, max_length=128)

    @model_validator(mode="after")
    def validate_search_url(self):
        parse_search_url(self.search_url)
        return self


class SerpSourceRequest(BaseModel):
    token: str=Field(min_length=32,max_length=128)
    url: str=Field(min_length=1,max_length=8192)

    @model_validator(mode="after")
    def validate_search_url(self):
        parsed=urlparse(self.url.strip())
        host=(parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https": raise ValueError("Search URL must use HTTPS")
        google=host == "google.com" or host.endswith(".google.com")
        bing=host == "bing.com" or host.endswith(".bing.com")
        if not (google or bing): raise ValueError("Only Google or Bing search URLs are supported")
        if parsed.path.rstrip("/") != "/search": raise ValueError("URL must be a Google or Bing /search URL")
        if not parse_qs(parsed.query).get("q", [""])[0].strip(): raise ValueError("Search URL must contain a q query parameter")
        return self

@app.post("/serp/premium")
def premium_serp(request: PremiumSerpRequest, req: Request):
    user=current_user(req); uid=uuid.UUID(user["id"]); sid=uuid.UUID(request.scrap_id); provider, query=parse_search_url(request.search_url)
    with db() as conn:
        scrap=conn.execute("SELECT id,status FROM scraps WHERE id=%s AND user_id=%s FOR UPDATE",(sid,uid)).fetchone()
        if not scrap: raise HTTPException(404,"Scrap not found")
        existing=conn.execute("SELECT status,result FROM premium_serp_extractions WHERE user_id=%s AND idempotency_key=%s",(uid,request.idempotency_key)).fetchone()
        if existing:
            if existing[0] == "completed": return existing[1]
            raise HTTPException(409,"Premium extraction request is already in progress or failed; use a new idempotency key")
        price=int(conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='premium_serp_price_cents'").fetchone()[0])
        limit=_serp_limit(conn); used=conn.execute("SELECT count(*) FROM serp_results WHERE scrap_id=%s",(sid,)).fetchone()[0]
        remaining=limit-used
        if remaining <= 0: raise HTTPException(409,f"SERP result limit reached: {used}/{limit}")
        wallet=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone()
        if not wallet or int(wallet[0]) < price: raise HTTPException(402,f"Insufficient balance. Premium SERP Extraction costs ${price/100:.2f}")
        extraction_id=uuid.uuid4()
        conn.execute("UPDATE wallets SET balance_cents=balance_cents-%s,updated_at=now() WHERE user_id=%s",(price,uid))
        balance_after=int(wallet[0])-price
        conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'premium_serp_extraction',%s)",(extraction_id,uid,-price,balance_after,str(extraction_id)))
        conn.execute("INSERT INTO premium_serp_extractions(id,user_id,scrap_id,idempotency_key,search_url,provider,status,charged_cents) VALUES(%s,%s,%s,%s,%s,%s,'pending',%s)",(extraction_id,uid,sid,request.idempotency_key,request.search_url.strip(),provider,price))
        conn.commit()
    try:
        provider_client = HttpPremiumSerpProvider()
        if hasattr(provider_client, "search_all"):
            items = provider_client.search_all(request.search_url.strip(), limit=remaining)
        else:
            items = provider_client.search(request.search_url.strip(), limit=remaining)
        if len(items)>remaining: raise RuntimeError("Premium SERP provider exceeded the requested result limit")
        valid=[x for x in items if urlparse(x.url).scheme in ("http","https") and urlparse(x.url).netloc]
        if not valid: raise RuntimeError("Premium SERP provider returned no valid destination URLs")
        with db() as conn:
            conn.execute("SELECT id FROM scraps WHERE id=%s FOR UPDATE",(sid,))
            current_used=conn.execute("SELECT count(*) FROM serp_results WHERE scrap_id=%s",(sid,)).fetchone()[0]
            limit=_serp_limit(conn)
            if current_used + len(valid) > limit:
                raise HTTPException(409,f"SERP result limit reached during persistence: {current_used}/{limit}")
            for item in valid:
                rid=uuid.uuid4(); conn.execute("INSERT INTO serp_results(id,scrap_id,url,title,snippet,raw_text,provider,page_url) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",(rid,sid,item.url,item.title,item.snippet,item.raw_text,provider,item.page_url or request.search_url))
                conn.execute("INSERT INTO url_occurrences(id,scrap_id,url,serp_result_id) VALUES(%s,%s,%s,%s)",(uuid.uuid4(),sid,item.url,rid))
            conn.execute("INSERT INTO serp_sources(id,scrap_id,provider,query,url) VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4(),sid,provider,query,request.search_url.strip()))
            result={"extraction_id":str(extraction_id),"scrap_id":str(sid),"provider":provider,"query":query,"search_url":request.search_url.strip(),"found_results":len(valid),"results":len(valid),"charged_cents":price,"balance_cents":balance_after}
            conn.execute("UPDATE premium_serp_extractions SET status='completed',result=%s,updated_at=now() WHERE id=%s",(Jsonb(result),extraction_id)); conn.commit()
        return result
    except Exception as exc:
        with db() as conn:
            wallet=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone(); new_balance=int(wallet[0])+price
            conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s",(new_balance,uid))
            conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'premium_serp_refund',%s)",(uuid.uuid4(),uid,price,new_balance,str(extraction_id)))
            conn.execute("UPDATE premium_serp_extractions SET status='failed',result=%s,charged_cents=0,updated_at=now() WHERE id=%s",(Jsonb({"error":str(exc)}),extraction_id)); conn.commit()
        if isinstance(exc, HTTPException): raise
        raise HTTPException(502,f"Premium SERP provider failed: {exc}") from exc


@app.post("/serp/sync")
def sync_serp(request: SerpSyncRequest, req: Request):
    user=current_user(req)
    scrap_id=req.headers.get("X-Scrap-Id")
    if not scrap_id:
        scrap_id=current_scrap(req)["id"]
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(403,"Scrap does not belong to this user")
        limit=_serp_limit(conn)
        conn.execute("SELECT id FROM scraps WHERE id=%s FOR UPDATE",(uuid.UUID(scrap_id),))
        used=conn.execute("SELECT count(*) FROM serp_results WHERE scrap_id=%s",(uuid.UUID(scrap_id),)).fetchone()[0]
        if used + len(request.results) > limit: raise HTTPException(409,f"SERP result limit reached: {used}/{limit}; import rejected")
        for item in request.results:
            rid=uuid.uuid4(); conn.execute("INSERT INTO serp_results(id,scrap_id,url,title,snippet,raw_text,provider,page_url) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",(rid,uuid.UUID(scrap_id),item.url,item.title[:1000],item.snippet[:5000],item.raw_text[:10000],item.provider,item.page_url))
            conn.execute("INSERT INTO url_occurrences(id,scrap_id,url,serp_result_id) VALUES(%s,%s,%s,%s)",(uuid.uuid4(),uuid.UUID(scrap_id),item.url,rid))
        conn.commit()
    return {"scrap_id":scrap_id,"results":len(request.results),"urls":len(request.results)}


class UrlImportRequest(BaseModel):
    scrap_id: str|None=None
    criteria: SearchCriteria
    urls: list[str]=Field(default_factory=list)
    crawler: CrawlerConfig=Field(default_factory=CrawlerConfig)
    export_format: Literal["csv","xlsx","google_sheets"]="csv"
    google_spreadsheet_id: str|None=None
    google_worksheet: str=Field(default="Leads",min_length=1)
    results: list[SerpResult]=Field(default_factory=list)
    @model_validator(mode="after")
    def validate_export_target(self):
        if self.export_format=="google_sheets" and not (self.google_spreadsheet_id or "").strip(): raise ValueError("google_spreadsheet_id is required for Google Sheets export")
        return self

def _serp_limit(conn):
    return int(conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='serp_result_limit'").fetchone()[0])

def _serp_session(token: str, user_id: str|None=None):
    with db() as conn:
        row=conn.execute("SELECT user_id,scrap_id,created_at,expires_at,urls,results,imports,sources FROM serp_sessions WHERE token=%s",(token,)).fetchone()
    if not row or row[3].timestamp() <= time.time():
        with db() as conn: conn.execute("DELETE FROM serp_sessions WHERE token=%s",(token,)); conn.commit()
        raise HTTPException(404,"SERP import session not found or expired")
    owner=str(row[0]) if row[0] else None
    if owner and not user_id: raise HTTPException(401,"Authentication required for this SERP session")
    if owner and owner != user_id: raise HTTPException(403,"Session belongs to another user")
    return {"user_id":owner,"scrap_id":str(row[1]) if row[1] else None,"created_at":row[2].timestamp(),"expires_at":row[3].timestamp(),"urls":row[4] or [],"results":row[5] or [],"imports":row[6] or [],"sources":row[7] or []}

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/scraps/{scrap_id}/crawl-pages")
def scrap_crawl_pages(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        rows=conn.execute("SELECT id,url,status,content,error,content_type,created_at FROM crawl_pages WHERE scrap_id=%s ORDER BY created_at,id",(uuid.UUID(scrap_id),)).fetchall()
    return [{"id":str(r[0]),"url":r[1],"status":r[2],"content":r[3],"error":r[4],"content_type":r[5],"created_at":r[6].isoformat()} for r in rows]

@app.get("/scraps/{scrap_id}/crawl-report")
def scrap_crawl_report(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(sid,uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        rows=conn.execute("SELECT url,status,error,content_type,created_at FROM crawl_pages WHERE scrap_id=%s ORDER BY created_at,id",(sid,)).fetchall()
    failures=[{"url":r[0],"status":r[1],"error":r[2],"content_type":r[3],"created_at":r[4].isoformat()} for r in rows if r[2] or (r[1] is not None and int(r[1]) >= 400) or r[1] in (None,0)]
    reasons={}
    for item in failures:
        status=item["status"]
        reason=item["error"] or (f"HTTP {status}" if status else "Unknown collection failure")
        reasons[reason]=reasons.get(reason,0)+1
    return {"attempted":len(rows),"collected":sum(1 for r in rows if not r[2] and r[1] is not None and int(r[1]) < 400),"failed":len(failures),"failure_reasons":sorted(({"reason":k,"count":v} for k,v in reasons.items()),key=lambda x:(-x["count"],x["reason"])),"failures":failures[:5000]}

@app.get("/scraps/{scrap_id}/evidence")
def scrap_evidence(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        rows=conn.execute("SELECT id,source_type,source_id,data,created_at FROM evidence WHERE scrap_id=%s ORDER BY created_at,id",(uuid.UUID(scrap_id),)).fetchall()
    return [{"id":str(r[0]),"source_type":r[1],"source_id":str(r[2]) if r[2] else None,"data":r[3],"created_at":r[4].isoformat()} for r in rows]

@app.get("/scraps/{scrap_id}/exports")
def scrap_exports(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        rows=conn.execute("SELECT id,format,location,created_at FROM exports WHERE scrap_id=%s ORDER BY created_at DESC",(uuid.UUID(scrap_id),)).fetchall()
    return [{"id":str(r[0]),"format":r[1],"location":r[2],"created_at":r[3].isoformat()} for r in rows]


@app.get("/exports")
def all_exports(req: Request):
    user=current_user(req)
    with db() as conn:
        rows=conn.execute("SELECT e.id,e.scrap_id,s.name,e.format,e.location,e.created_at FROM exports e JOIN scraps s ON s.id=e.scrap_id WHERE s.user_id=%s ORDER BY e.created_at DESC",(uuid.UUID(user["id"]),)).fetchall()
    return [{"id":str(r[0]),"scrap_id":str(r[1]),"scrap_name":r[2],"format":r[3],"location":r[4],"created_at":r[5].isoformat()} for r in rows]


@app.get("/scraps/{scrap_id}/exports/{export_id}/download")
def download_export(scrap_id: str, export_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id); eid=uuid.UUID(export_id)
    with db() as conn:
        row=conn.execute("SELECT e.format,e.location FROM exports e JOIN scraps s ON s.id=e.scrap_id WHERE e.id=%s AND e.scrap_id=%s AND s.user_id=%s",(eid,sid,uuid.UUID(user["id"]))).fetchone()
    if not row: raise HTTPException(404,"Export not found")
    if row[0]=='google_sheets': raise HTTPException(409,"Google Sheets exports do not have a file download")
    output=Path(row[1])
    if not output.exists(): raise HTTPException(404,"Export file not found")
    media='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if row[0]=='xlsx' else 'text/csv'
    return FileResponse(output,media_type=media,filename=f"scrappee-{sid}.{row[0]}")


@app.post("/search/parameters")
def search_parameters(request: SearchParameterRequest, req: Request):
    user=current_user(req) if request.scrap_id else None
    params=SearchStrategyEngine().generate(request.criteria,request.max_queries)
    if request.scrap_id:
        with db() as conn:
            owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(request.scrap_id),uuid.UUID(user["id"]))).fetchone()
            if not owned: raise HTTPException(404,"Scrap not found")
            conn.execute("DELETE FROM search_parameters WHERE scrap_id=%s",(uuid.UUID(request.scrap_id),))
            for position, item in enumerate(params):
                conn.execute("INSERT INTO search_parameters(id,scrap_id,parameter_id,provider,query,url,family,position) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",(uuid.uuid4(),uuid.UUID(request.scrap_id),item.id,item.provider,item.query,item.url,item.family,position))
            conn.commit()
    return {"parameters":[p.__dict__ for p in params]}

@app.get("/scraps/{scrap_id}/search-parameters")
def scrap_search_parameters(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        rows=conn.execute("SELECT parameter_id,provider,query,url,family FROM search_parameters WHERE scrap_id=%s AND EXISTS (SELECT 1 FROM scraps WHERE id=%s AND user_id=%s) ORDER BY position",(uuid.UUID(scrap_id),uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchall()
    return [{"id":r[0],"provider":r[1],"query":r[2],"url":r[3],"family":r[4]} for r in rows]

@app.get("/scraps/{scrap_id}/serp-session")
def scrap_serp_session(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(sid,uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
        row=conn.execute("SELECT token FROM serp_sessions WHERE scrap_id=%s AND expires_at>now() ORDER BY created_at DESC LIMIT 1",(sid,)).fetchone()
    return {"token":row[0]} if row else None

@app.post("/serp/sessions")
def create_serp_session(request: SerpSessionRequest=SerpSessionRequest(), req: Request=None):
    user=current_user(req) if req and req.headers.get("Authorization") else None
    if request.scrap_id:
        if not user: raise HTTPException(401,"Authentication required for a Scrap SERP session")
        with db() as conn:
            owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(request.scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404,"Scrap not found")
    token=secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute("INSERT INTO serp_sessions(token,user_id,scrap_id,expires_at) VALUES(%s,%s,%s,now()+(%s * interval '1 second'))",(token,uuid.UUID(user["id"]) if user else None,uuid.UUID(request.scrap_id) if request.scrap_id else None,request.ttl_seconds)); conn.commit()
    return {"token":token,"expires_in":request.ttl_seconds}

@app.get("/serp/sessions/{token}")
def get_serp_session(token: str, req: Request):
    auth=req.headers.get("Authorization")
    user=current_user(req) if auth else None
    session=_serp_session(token,user["id"] if user else None)
    return {"token":token,"urls":session["urls"],"results":session["results"],"count":len(session["urls"]),"imports":session["imports"],"sources":session["sources"]}

@app.post("/serp/sources")
def add_serp_source(request: SerpSourceRequest, req: Request):
    auth=req.headers.get("Authorization")
    user=current_user(req) if auth else None
    session=_serp_session(request.token,user["id"] if user else None)
    parsed=urlparse(request.url.strip())
    host=(parsed.hostname or "").lower().rstrip(".")
    provider="google" if host == "google.com" or host.endswith(".google.com") else "bing"
    query=parse_qs(parsed.query).get("q", [""])[0].strip()
    source={"provider":provider,"query":query,"url":request.url.strip()}
    session["sources"].append(source)
    with db() as conn:
        conn.execute("UPDATE serp_sessions SET sources=%s WHERE token=%s",(Jsonb(session["sources"]),request.token)); conn.commit()
    if session.get("scrap_id"):
        with db() as conn:
            conn.execute("INSERT INTO serp_sources(id,scrap_id,provider,query,url) VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4(),uuid.UUID(session["scrap_id"]),provider,query,request.url.strip()));conn.commit()
    return source

def _increment_llm_calls(scrap_id: str):
    with db() as conn:
        conn.execute("UPDATE scraps SET llm_calls=llm_calls+1 WHERE id=%s", (uuid.UUID(scrap_id),))
        conn.commit()


def _process_serp_leads_background(scrap_id: str, records: list[dict]):
    try:
        with db() as conn:
            row = conn.execute("SELECT user_id,criteria,crawler_config FROM scraps WHERE id=%s", (uuid.UUID(scrap_id),)).fetchone()
        if not row:
            return
        user_id, raw_criteria, raw_crawler = row
        criteria = SearchCriteria.model_validate(raw_criteria or {})
        crawler = CrawlerConfig.model_validate(raw_crawler or {})
        prefixes, rules = get_client_policies(str(user_id))
        pipeline = LeadDiscoveryPipeline(crawler_config=crawler, generic_prefixes=prefixes, domain_rules=rules, llm_call_counter=lambda: _increment_llm_calls(scrap_id))
        asyncio.run(pipeline.process_serp_records(criteria, records, scrap_id=scrap_id))
    except Exception as exc:
        print(f"serp_lead_processing_error={scrap_id}: {type(exc).__name__}: {exc}")


@app.post("/serp/import")
def import_serp_urls(request: SerpImportRequest, req: Request, background_tasks: BackgroundTasks):
    auth=req.headers.get("Authorization")
    user=current_user(req) if auth else None
    session=_serp_session(request.token,user["id"] if user else None)
    results=[item.model_dump() for item in request.results]
    urls=list(request.urls)+[item["url"] for item in results]
    session["urls"].extend(urls)
    session["results"].extend(results)
    session["imports"].append({"page_url":request.page_url or (results[0].get("page_url") if results else None),"count":len(urls),"results":len(results),"at":time.time()})
    session["imports"]=session["imports"][-100:]
    with db() as conn:
        if session.get("scrap_id"):
            scrap_id=uuid.UUID(session["scrap_id"])
            conn.execute("SELECT id FROM scraps WHERE id=%s FOR UPDATE",(scrap_id,))
            limit=_serp_limit(conn); used=conn.execute("SELECT count(*) FROM serp_results WHERE scrap_id=%s",(scrap_id,)).fetchone()[0]
            added=0
            new_results=[]
            for item in results:
                duplicate=conn.execute("SELECT 1 FROM serp_results WHERE scrap_id=%s AND url=%s LIMIT 1",(scrap_id,item["url"])).fetchone()
                if duplicate: continue
                if used + added >= limit: raise HTTPException(409,f"SERP result limit reached: {used}/{limit}; import rejected")
                rid=uuid.uuid4(); conn.execute("INSERT INTO serp_results(id,scrap_id,url,title,snippet,raw_text,provider,page_url) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",(rid,scrap_id,item["url"],item.get("title","")[:1000],item.get("snippet","")[:5000],item.get("raw_text","")[:10000],item.get("provider"),item.get("page_url")))
                conn.execute("INSERT INTO url_occurrences(id,scrap_id,url,serp_result_id) VALUES(%s,%s,%s,%s)",(uuid.uuid4(),scrap_id,item["url"],rid)); added+=1; new_results.append(item)
        conn.execute("UPDATE serp_sessions SET urls=%s,results=%s,imports=%s WHERE token=%s",(Jsonb(session["urls"]),Jsonb(session["results"]),Jsonb(session["imports"]),request.token))
        conn.commit()
    if new_results and session.get("scrap_id"):
        background_tasks.add_task(_process_serp_leads_background, session["scrap_id"], new_results)
    return {"count":len(urls),"results":len(results),"new_results":len(new_results),"total":len(session["urls"]),"page_url":request.page_url}

def _persist_job(job_id, **fields):
    with db() as conn:
        sets=[]; vals=[]
        for key,value in fields.items():
            sets.append(f"{key}=%s"); vals.append(Jsonb(value) if key in ("payload","result") else value)
        sets.append("updated_at=now()"); vals.append(uuid.UUID(job_id))
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=%s",vals); conn.commit()

def _event_callback(job_id):
    def on_event(event):
        job=JOBS.get(job_id,{"counts":{},"events":[]})
        if job_id in CANCEL_FLAGS:
            return
        job["stage"]=event.stage; job["message"]=event.message; job["counts"].update(event.counts); job["events"].append(event.__dict__); job["events"]=job["events"][-250:]
        JOBS[job_id]=job
        _persist_job(job_id,status="running",stage=event.stage,result={"counts":job["counts"],"message":event.message,"events":job["events"],"lead_count":job["counts"].get("leads",job.get("lead_count",0))})
    return on_event

def _job_from_row(row):
    job_id,status,stage,payload,result,created_at,updated_at=row
    result=result or {}; payload=payload or {}
    return {"job_id":str(job_id),"status":status,"stage":stage,"message":result.get("message", ""),"counts":result.get("counts",{}),"events":result.get("events",[]),"lead_count":result.get("lead_count",0),"export_format":payload.get("export_format","csv"),"output":result.get("output"),"error":result.get("error"),"created_at":created_at.isoformat() if created_at else None,"updated_at":updated_at.isoformat() if updated_at else None}

def _load_job(job_id, user_id=None):
    try: jid=uuid.UUID(job_id)
    except ValueError: raise HTTPException(404,"Job not found")
    with db() as conn:
        row=conn.execute("SELECT j.id,j.status,j.stage,j.payload,j.result,j.created_at,j.updated_at FROM jobs j JOIN scraps s ON s.id=j.scrap_id WHERE j.id=%s AND (%s IS NULL OR s.user_id=%s)",(jid, user_id, user_id)).fetchone()
    if not row: raise HTTPException(404,"Job not found")
    return _job_from_row(row)

def _reconcile_jobs_on_startup():
    with db() as conn:
        rows=conn.execute("SELECT id FROM jobs WHERE status IN ('queued','running')").fetchall()
        for (job_id,) in rows:
            conn.execute("UPDATE jobs SET status='failed',stage='Failed',result=result || %s,updated_at=now() WHERE id=%s",(Jsonb({"message":"Job interrupted by API restart","error":"Job did not survive process restart"}),job_id))
        conn.commit()

def _write_export(leads,job_id,fmt):
    output=Path(f"output/{job_id}.{'xlsx' if fmt=='xlsx' else 'csv'}")
    if fmt=='xlsx':
        from src.exports.xlsx_export import export_xlsx; export_xlsx(leads,str(output))
    else:
        from src.exports.csv_export import export_csv; export_csv(leads,str(output))
    return str(output)

def _run_job(job_id,request):
    try:
        with db() as conn:
            user_id=conn.execute("SELECT user_id FROM scraps WHERE id=%s",(uuid.UUID(request.scrap_id),)).fetchone()[0]
        if job_id in CANCEL_FLAGS: return
        JOBS[job_id]["status"]="running"; _persist_job(job_id,status="running",stage="Starting",result={"message":"Job started"});
        with db() as conn: conn.execute("UPDATE scraps SET status='running' WHERE id=%s AND status IN ('active','submitted')",(uuid.UUID(request.scrap_id),)); conn.commit()
        sink=JobEventSink(_event_callback(job_id))
        leads=asyncio.run(LeadDiscoveryPipeline(crawler_config=request.crawler, generic_prefixes=get_client_policies(user_id)[0], domain_rules=get_client_policies(user_id)[1]).run(request.criteria,event_sink=sink,scrap_id=request.scrap_id,cancel_check=lambda: job_id in CANCEL_FLAGS))
        _persist_leads(request.scrap_id,leads)
        if request.export_format=="google_sheets":
            from src.exports.google_sheets import export_google_sheets
            result=export_google_sheets(leads,request.google_spreadsheet_id,worksheet=request.google_worksheet)
        else: result=_write_export(leads,job_id,request.export_format)
        if job_id in CANCEL_FLAGS:
            return
        JOBS[job_id].update(status="completed",lead_count=len(leads),output=result)
        snapshot=JOBS[job_id]
        _persist_job(job_id,status="completed",stage="Export",result={"lead_count":len(leads),"output":result,"counts":snapshot.get("counts",{}),"events":snapshot.get("events",[])})
        with db() as conn: conn.execute("UPDATE scraps SET status='completed',completed_at=now() WHERE id=%s",(uuid.UUID(request.scrap_id),)); conn.commit()
        if request.scrap_id:
            with db() as conn:
                conn.execute("INSERT INTO exports(id,scrap_id,format,location) VALUES(%s,%s,%s,%s)",(uuid.uuid4(),uuid.UUID(request.scrap_id),request.export_format,str(result)))
                conn.commit()
    except Exception as exc:
        if job_id in CANCEL_FLAGS: return
        JOBS[job_id].update(status="failed",message="Job failed",error=str(exc))
        snapshot=JOBS[job_id]
        _persist_job(job_id,status="failed",stage="Failed",result={"error":str(exc),"message":"Job failed","counts":snapshot.get("counts",{}),"events":snapshot.get("events",[])})
        if request.scrap_id:
            with db() as conn: conn.execute("UPDATE scraps SET status='failed',completed_at=now() WHERE id=%s",(uuid.UUID(request.scrap_id),)); conn.commit()

def _persist_leads(scrap_id, leads):
    if not scrap_id:
        return
    for lead in leads:
        persist_lead(scrap_id, lead)

def _run_enrich_job(job_id, scrap_id, lead_id):
    try:
        sid = uuid.UUID(scrap_id)
        lid = uuid.UUID(lead_id)
        with db() as conn:
            row = conn.execute(
                "SELECT s.user_id,s.criteria,s.crawler_config,l.data "
                "FROM scraps s JOIN leads l ON l.scrap_id=s.id "
                "WHERE s.id=%s AND l.id=%s",
                (sid, lid),
            ).fetchone()
        if not row:
            raise RuntimeError("Lead or Scrap not found")
        user_id, raw_criteria, raw_crawler, data = row
        lead = Lead.model_construct(**(data or {}))
        if not str(getattr(lead, "source_url", "") or "").strip():
            raise RuntimeError("Lead has no source_url to enrich")
        criteria = SearchCriteria.model_validate(raw_criteria or {})
        crawler = CrawlerConfig.model_validate(raw_crawler or {})
        prefixes, rules = get_client_policies(str(user_id))
        JOBS[job_id] = {
            "job_id": job_id, "status": "running", "stage": "Starting",
            "message": "Lead enrichment started", "counts": {}, "events": [],
            "lead_count": 0,
        }
        _persist_job(job_id, status="running", stage="Starting", result={"message": "Lead enrichment started"})
        sink = JobEventSink(_event_callback(job_id))
        leads = asyncio.run(
            LeadDiscoveryPipeline(
                crawler_config=crawler,
                generic_prefixes=prefixes,
                domain_rules=rules,
                llm_call_counter=lambda: _increment_llm_calls(scrap_id),
            ).enrich_lead(
                criteria,
                lead,
                event_sink=sink,
                scrap_id=scrap_id,
                cancel_check=lambda: job_id in CANCEL_FLAGS,
            )
        )
        snapshot = JOBS[job_id]
        JOBS[job_id].update(status="completed", lead_count=len(leads), output=None)
        _persist_job(
            job_id,
            status="completed",
            stage="Complete",
            result={
                "lead_count": len(leads),
                "counts": snapshot.get("counts", {}),
                "events": snapshot.get("events", []),
                "message": "Lead enrichment completed",
            },
        )
    except Exception as exc:
        JOBS.setdefault(job_id, {}).update(status="failed", message="Lead enrichment failed", error=str(exc))
        snapshot = JOBS[job_id]
        _persist_job(
            job_id,
            status="failed",
            stage="Failed",
            result={
                "error": str(exc),
                "message": "Lead enrichment failed",
                "counts": snapshot.get("counts", {}),
                "events": snapshot.get("events", []),
            },
        )


def _run_url_job(job_id,request):
    try:
        with db() as conn:
            user_id=conn.execute("SELECT user_id FROM scraps WHERE id=%s",(uuid.UUID(request.scrap_id),)).fetchone()[0]
        if job_id in CANCEL_FLAGS: return
        JOBS[job_id]["status"]="running"; _persist_job(job_id,status="running",stage="Starting",result={"message":"Job started"});
        with db() as conn: conn.execute("UPDATE scraps SET status='running' WHERE id=%s AND status IN ('active','submitted')",(uuid.UUID(request.scrap_id),)); conn.commit()
        sink=JobEventSink(_event_callback(job_id))
        leads=asyncio.run(LeadDiscoveryPipeline(crawler_config=request.crawler, generic_prefixes=get_client_policies(user_id)[0], domain_rules=get_client_policies(user_id)[1]).run_harvested(request.criteria,request.results or [{"url":u} for u in request.urls],event_sink=sink,scrap_id=request.scrap_id,cancel_check=lambda: job_id in CANCEL_FLAGS))
        _persist_leads(request.scrap_id,leads)
        if request.export_format=="google_sheets":
            from src.exports.google_sheets import export_google_sheets
            result=export_google_sheets(leads,request.google_spreadsheet_id,worksheet=request.google_worksheet)
        else: result=_write_export(leads,job_id,request.export_format)
        if job_id in CANCEL_FLAGS:
            return
        JOBS[job_id].update(status="completed",lead_count=len(leads),output=result)
        snapshot=JOBS[job_id]
        _persist_job(job_id,status="completed",stage="Export",result={"lead_count":len(leads),"output":result,"counts":snapshot.get("counts",{}),"events":snapshot.get("events",[])})
        with db() as conn: conn.execute("UPDATE scraps SET status='completed',completed_at=now() WHERE id=%s",(uuid.UUID(request.scrap_id),)); conn.commit()
        if request.scrap_id:
            with db() as conn:
                conn.execute("INSERT INTO exports(id,scrap_id,format,location) VALUES(%s,%s,%s,%s)",(uuid.uuid4(),uuid.UUID(request.scrap_id),request.export_format,str(result)))
                conn.commit()
    except Exception as exc:
        if job_id in CANCEL_FLAGS: return
        JOBS[job_id].update(status="failed",message="Job failed",error=str(exc))
        snapshot=JOBS[job_id]
        _persist_job(job_id,status="failed",stage="Failed",result={"error":str(exc),"message":"Job failed","counts":snapshot.get("counts",{}),"events":snapshot.get("events",[])})
        if request.scrap_id:
            with db() as conn: conn.execute("UPDATE scraps SET status='failed',completed_at=now() WHERE id=%s",(uuid.UUID(request.scrap_id),)); conn.commit()

@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, req: Request):
    user=current_user(req)
    try: jid=uuid.UUID(job_id)
    except ValueError: raise HTTPException(404,"Job not found")
    with db() as conn:
        row=conn.execute("SELECT j.status,j.scrap_id FROM jobs j JOIN scraps s ON s.id=j.scrap_id WHERE j.id=%s AND s.user_id=%s",(jid,uuid.UUID(user["id"]))).fetchone()
        if not row: raise HTTPException(404,"Job not found")
        if row[0] in ("completed","failed","canceled"): return {"job_id":job_id,"status":row[0]}
        CANCEL_FLAGS.add(job_id)
        scrap_id = row[1]
        conn.execute("UPDATE jobs SET status='canceled',stage='Canceled',result=result || %s,updated_at=now() WHERE id=%s",(Jsonb({"message":"Job canceled by user"}),jid))
        # Release the Scrap back to submitted so the user can immediately start
        # another research pass against the already-collected SERP occurrences.
        conn.execute("UPDATE scraps SET status='submitted',completed_at=NULL WHERE id=%s AND status IN ('running','active')",(scrap_id,))
        conn.commit()
    JOBS.setdefault(job_id,{})["status"]="canceled"
    return {"job_id":job_id,"status":"canceled"}

@app.post("/scraps/{scrap_id}/restart-research")
def restart_research(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id); uid=uuid.UUID(user["id"])
    with db() as conn:
        row=conn.execute("SELECT status FROM scraps WHERE id=%s AND user_id=%s FOR UPDATE",(sid,uid)).fetchone()
        if not row: raise HTTPException(404,"Scrap not found")
        running=conn.execute("SELECT 1 FROM jobs WHERE scrap_id=%s AND status IN ('queued','running') LIMIT 1",(sid,)).fetchone()
        if running: raise HTTPException(409,"Research is still running; cancel it first")
        serp=conn.execute("SELECT 1 FROM serp_results WHERE scrap_id=%s LIMIT 1",(sid,)).fetchone()
        if not serp: raise HTTPException(422,"No SERP results are available for research")
        conn.execute("UPDATE scraps SET status='submitted',completed_at=NULL WHERE id=%s",(sid,)); conn.commit()
    return {"scrap_id":scrap_id,"status":"submitted"}

@app.post("/jobs",status_code=202)
async def create_job(request: JobRequest,background_tasks: BackgroundTasks, req: Request):
    user=current_user(req)
    if not request.scrap_id: raise HTTPException(422,"scrap_id is required")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(request.scrap_id),uuid.UUID(user["id"]))).fetchone(): raise HTTPException(404,"Scrap not found")
    job_id=uuid.uuid4().hex; JOBS[job_id]={"job_id":job_id,"status":"queued","stage":"Queued","message":"Job queued","counts":{},"events":[],"lead_count":0,"export_format":request.export_format}
    with db() as conn: conn.execute("INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,%s,%s,%s,%s)",(uuid.UUID(job_id),uuid.UUID(request.scrap_id),"queued","Queued",Jsonb(request.model_dump()),Jsonb({"message":"Job queued","counts":{},"events":[]})));conn.commit()
    background_tasks.add_task(_run_job,job_id,request); return JOBS[job_id]

@app.post("/jobs/from-urls",status_code=202)
async def create_url_job(request: UrlImportRequest,background_tasks: BackgroundTasks, req: Request):
    user=current_user(req)
    if not request.scrap_id: raise HTTPException(422,"scrap_id is required")
    with db() as conn:
        row=conn.execute("SELECT status,criteria,crawler_config FROM scraps WHERE id=%s AND user_id=%s FOR UPDATE",(uuid.UUID(request.scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not row: raise HTTPException(404,"Scrap not found")
        if row[0] != 'submitted': raise HTTPException(409,"Scrap must be submitted before research can start")
        serp_rows=conn.execute("SELECT url,title,snippet,raw_text,provider,page_url FROM serp_results WHERE scrap_id=%s ORDER BY id",(uuid.UUID(request.scrap_id),)).fetchall()
    if not serp_rows: raise HTTPException(422,"At least one collected SERP result is required")
    request.criteria=SearchCriteria.model_validate(row[1] or {})
    request.crawler=CrawlerConfig.model_validate(row[2] or {})
    request.results=[SerpResult(url=r[0],title=r[1] or '',snippet=r[2] or '',raw_text=r[3] or '',provider=r[4],page_url=r[5]) for r in serp_rows]
    request.urls=[r.url for r in request.results]
    job_id=uuid.uuid4().hex; JOBS[job_id]={"job_id":job_id,"status":"queued","stage":"Queued","message":"URL crawl queued","counts":{},"events":[],"lead_count":0,"export_format":request.export_format}
    with db() as conn: conn.execute("INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,%s,%s,%s,%s)",(uuid.UUID(job_id),uuid.UUID(request.scrap_id),"queued","Queued",Jsonb(request.model_dump()),Jsonb({"message":"URL crawl queued","counts":{},"events":[]})));conn.commit()
    background_tasks.add_task(_run_url_job,job_id,request); return JOBS[job_id]

@app.get("/scraps/{scrap_id}/job")
def get_scrap_job(scrap_id: str, req: Request):
    user=current_user(req)
    sid=uuid.UUID(scrap_id); uid=uuid.UUID(user["id"])
    with db() as conn:
        row=conn.execute("SELECT j.id,j.status,j.stage,j.payload,j.result,j.created_at,j.updated_at FROM jobs j JOIN scraps s ON s.id=j.scrap_id WHERE j.scrap_id=%s AND s.user_id=%s ORDER BY j.created_at DESC LIMIT 1",(sid,uid)).fetchone()
        if not row: raise HTTPException(404,"No job found for Scrap")
        # Reconcile a stale Scrap lock whenever its latest Job is terminal.
        if row[1] in ("failed","canceled"):
            conn.execute("UPDATE scraps SET status='submitted',completed_at=NULL WHERE id=%s AND status='running'",(sid,))
            conn.commit()
        elif row[1]=="completed":
            conn.execute("UPDATE scraps SET status='completed',completed_at=COALESCE(completed_at,now()) WHERE id=%s AND status='running'",(sid,))
            conn.commit()
    return _job_from_row(row)

@app.get("/jobs/{job_id}")
def get_job(job_id: str, req: Request):
    user=current_user(req)
    return _load_job(job_id, uuid.UUID(user["id"]))

@app.get("/jobs/{job_id}/download")
def download_job(job_id: str, req: Request):
    user=current_user(req)
    job=_load_job(job_id, uuid.UUID(user["id"]))
    if job["status"]!="completed": raise HTTPException(409,"Job is not completed")
    if job.get("export_format")=="google_sheets": raise HTTPException(409,"Google Sheets jobs do not have a file download")
    output=Path(job["output"] or "")
    if not output.exists(): raise HTTPException(404,"Output file not found")
    media="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if output.suffix==".xlsx" else "text/csv"
    return FileResponse(output,media_type=media,filename=f"scrappee-{job_id}{output.suffix}")
