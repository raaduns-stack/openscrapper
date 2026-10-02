from dotenv import load_dotenv
load_dotenv()
import asyncio, secrets, time, uuid, os, math, logging, re, subprocess, smtplib, ssl, base64, threading
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from typing import Literal
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, model_validator
from src.models.criteria import CrawlerConfig, SearchCriteria
from src.models.lead import Lead
from src.pipeline import LeadDiscoveryPipeline
from src.extract.adaptive import AdaptiveLeadExtractor
from src.extract.evidence import EvidenceBuilder
from src.extract.email import is_personal_email
from src.agent.qualification import LeadQualifier
from src.agent.query_interpreter import QueryInterpreter
from src.agent.geography import GeographyResolver
from src.dedupe.leads import persist_lead, dedupe, exclude_existing
from src.observability.job_events import JobEventSink, emit_event
from src.search.strategy import SearchStrategyEngine
from src.search.template_engine import SearchTemplateEngine, VARIABLES
from src.search.premium import HttpPremiumSerpProvider, parse_search_url, SUPPORTED_PROVIDERS, provider_statuses, save_provider_config
from src.db import db, init_db, purge_expired_history, get_client_policies
from src.auth import create_user, login_user, current_user, create_session, request_password_reset, reset_password
from src.payments_btcpay import configured as btcpay_configured, create_invoice as btcpay_create_invoice, get_invoice as btcpay_get_invoice, verify_webhook as btcpay_verify_webhook, payment_btc as btcpay_payment_btc
import hashlib
from psycopg.types.json import Jsonb
from psycopg.errors import UniqueViolation
from src.senders import service as sender_service
from src.senders import gmail as gmail_oauth
from src import support_service

MIN_DEPOSIT_CENTS = 5000

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
_PAGE_GEOGRAPHY = GeographyResolver()
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
    country: str | None = Field(default=None, min_length=2, max_length=2)

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

class EnrichmentRequest(BaseModel):
    lead_ids: list[str] = Field(min_length=1,max_length=200)
    discover_new_leads: bool = False

class SenderRequest(BaseModel):
    display_name: str = Field(min_length=1,max_length=200)
    email: str | None = Field(default=None,min_length=3,max_length=320)
    provider: Literal["smtp","gmail_oauth","microsoft_oauth"]

    @model_validator(mode='after')
    def validate_sender_identity(self):
        if self.provider == 'smtp' and not self.email:
            raise ValueError('Sender email is required for SMTP senders')
        return self
    enabled: bool = True
    config: dict = Field(default_factory=dict)
    password: str | None = Field(default=None,max_length=500)

class SenderUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None,min_length=1,max_length=200)
    email: str | None = Field(default=None,min_length=3,max_length=320)
    enabled: bool | None = None
    config: dict | None = None
    password: str | None = Field(default=None,max_length=500)

class ReplyToRequest(BaseModel):
    reply_to: str | None = Field(default=None,max_length=320)

class LetterRequest(BaseModel):
    name: str = Field(min_length=1,max_length=200)
    subject: str = Field(min_length=1,max_length=500)
    body_text: str = Field(min_length=1)
    body_html: str | None = None
    variables: list[str] = Field(default_factory=list)
    active: bool = True

class CampaignRequest(BaseModel):
    name: str = Field(min_length=1,max_length=200)
    sender_id: str
    letter_id: str
    lead_ids: list[str] = Field(default_factory=list,max_length=10000)
    audience_scrap_id: str | None = None
    config: dict = Field(default_factory=dict)

class SearchTemplateCategoryRequest(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    active: bool = True

class SearchTemplateRequest(BaseModel):
    category_id: str
    provider: Literal["google","bing"]
    family: str = Field(min_length=1,max_length=100)
    template: str = Field(min_length=1,max_length=2000)
    active: bool = True

class SupportTicketRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    category: Literal["payment","account","login","system","scraping","billing","other"]
    description: str = Field(min_length=3, max_length=20000)
    priority: Literal["low","normal","high","urgent"] = "normal"

class SupportMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20000)

class SupportStatusRequest(BaseModel):
    status: Literal["new","open","waiting_user","waiting_internal","resolved","closed"]

class SupportAssignmentRequest(BaseModel):
    assigned_to: str | None = None

class SupportRatingRequest(BaseModel):
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=5000)

def _support_admin(req: Request):
    user = current_user(req)
    admins = {x.strip().lower() for x in os.getenv("ADMIN_EMAILS", "").split(",") if x.strip()}
    if user["email"].lower() not in admins:
        raise HTTPException(403, "Admin access required")
    return user

@app.get("/support/tickets")
def support_tickets(req: Request, status: str | None = None, category: str | None = None):
    user = current_user(req)
    return support_service.list_tickets(uuid.UUID(user["id"]), status=status, category=category)

@app.post("/support/tickets")
def support_create_ticket(request: SupportTicketRequest, req: Request):
    user = current_user(req)
    return support_service.create_ticket(uuid.UUID(user["id"]), request.subject, request.category, request.description, request.priority)

@app.get("/support/tickets/{ticket_id}/attachments/{attachment_id}")
def support_attachment_download(ticket_id: str, attachment_id: str, req: Request):
    user = current_user(req)
    try:
        tid = uuid.UUID(ticket_id); aid = uuid.UUID(attachment_id)
    except ValueError:
        raise HTTPException(422, "Invalid ticket id")
    item = support_service.get_attachment(uuid.UUID(user["id"]), tid, aid)
    if not item:
        raise HTTPException(404, "Attachment not found")
    path = Path(item["storage_path"])
    if not path.is_file():
        raise HTTPException(404, "Attachment file not found")
    return FileResponse(path, media_type=item["content_type"] or "application/octet-stream", filename=item["filename"])

@app.get("/support/tickets/{ticket_id}")
def support_get_ticket(ticket_id: str, req: Request):
    user = current_user(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    item = support_service.get_ticket(uuid.UUID(user["id"]), tid)
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.post("/support/tickets/{ticket_id}/messages")
def support_message(ticket_id: str, request: SupportMessageRequest, req: Request):
    user = current_user(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    item = support_service.add_message(uuid.UUID(user["id"]), tid, request.body)
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.post("/support/tickets/{ticket_id}/resolve")
def support_resolve(ticket_id: str, req: Request):
    user = current_user(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    item = support_service.set_status(uuid.UUID(user["id"]), tid, "resolved")
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.post("/support/tickets/{ticket_id}/rating")
def support_rate(ticket_id: str, request: SupportRatingRequest, req: Request):
    user = current_user(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    try:
        item = support_service.rate_ticket(uuid.UUID(user["id"]), tid, request.score, request.comment)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.post("/support/tickets/{ticket_id}/attachments")
async def support_attachment(ticket_id: str, req: Request):
    from fastapi import UploadFile, File
    user = current_user(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    form = await req.form()
    upload = form.get("file")
    if not upload or not hasattr(upload, "read"):
        raise HTTPException(422, "Attachment file is required")
    data = await upload.read()
    try:
        item = support_service.save_attachment(uuid.UUID(user["id"]), tid, upload.filename or "attachment", upload.content_type or "application/octet-stream", data)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.get("/admin/support/tickets/{ticket_id}/attachments/{attachment_id}")
def admin_support_attachment_download(ticket_id: str, attachment_id: str, req: Request):
    user = _support_admin(req)
    try:
        tid = uuid.UUID(ticket_id); aid = uuid.UUID(attachment_id)
    except ValueError:
        raise HTTPException(422, "Invalid ticket id")
    item = support_service.get_attachment(uuid.UUID(user["id"]), tid, aid, admin=True)
    if not item:
        raise HTTPException(404, "Attachment not found")
    path = Path(item["storage_path"])
    if not path.is_file():
        raise HTTPException(404, "Attachment file not found")
    return FileResponse(path, media_type=item["content_type"] or "application/octet-stream", filename=item["filename"])

@app.get("/admin/support/tickets")
def admin_support_tickets(req: Request):
    _support_admin(req)
    raw_limit = req.query_params.get("limit", "50")
    raw_offset = req.query_params.get("offset", "0")
    try:
        limit = max(1, min(int(raw_limit), 200))
        offset = max(0, int(raw_offset))
    except ValueError:
        raise HTTPException(422, "Invalid pagination")
    rows = support_service.list_tickets(
        admin=True,
        status=req.query_params.get("status") or None,
        category=req.query_params.get("category") or None,
        search=req.query_params.get("q") or None,
        limit=limit,
        offset=offset,
    )
    with db() as conn:
        for item in rows:
            row = conn.execute("SELECT u.email, a.email FROM users u LEFT JOIN users a ON a.id= (SELECT assigned_to FROM support_tickets WHERE id=%s) WHERE u.id=%s", (uuid.UUID(item["id"]), uuid.UUID(item["user_id"]))).fetchone()
            item["user_email"] = row[0] if row else None
            item["assigned_to_email"] = row[1] if row else None
    return rows

@app.get("/admin/support/metrics")
def admin_support_metrics(req: Request):
    _support_admin(req)
    with db() as conn:
        rows = conn.execute("SELECT status,count(*) FROM support_tickets GROUP BY status").fetchall()
        rating = conn.execute("SELECT count(*) FROM support_ticket_ratings").fetchone()[0]
    out = {k: 0 for k in support_service.STATUSES}
    out.update({r[0]: r[1] for r in rows}); out["ratings"] = rating
    return out

@app.get("/admin/support/tickets/{ticket_id}")
def admin_support_ticket(ticket_id: str, req: Request):
    _support_admin(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    item = support_service.get_ticket(uuid.uuid4(), tid, admin=True)
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.post("/admin/support/tickets/{ticket_id}/messages")
def admin_support_message(ticket_id: str, request: SupportMessageRequest, req: Request, background_tasks: BackgroundTasks):
    user = _support_admin(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    item = support_service.add_message(uuid.UUID(user["id"]), tid, request.body, admin=True)
    if not item: raise HTTPException(404, "Ticket not found")
    with db() as conn:
        row = conn.execute("SELECT u.email,t.subject FROM support_tickets t JOIN users u ON u.id=t.user_id WHERE t.id=%s", (tid,)).fetchone()
    if row and row[0]:
        background_tasks.add_task(_send_support_reply_email_safe, row[0], str(tid), row[1] or "Support request", request.body)
    return item

@app.post("/admin/support/tickets/{ticket_id}/internal-note")
def admin_support_note(ticket_id: str, request: SupportMessageRequest, req: Request):
    user = _support_admin(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    item = support_service.add_message(uuid.UUID(user["id"]), tid, request.body, admin=True, internal=True)
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.post("/admin/support/tickets/{ticket_id}/status")
def admin_support_status(ticket_id: str, request: SupportStatusRequest, req: Request):
    user = _support_admin(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    item = support_service.set_status(uuid.UUID(user["id"]), tid, request.status, admin=True)
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.get("/admin/support/assignees")
def admin_support_assignees(req: Request):
    _support_admin(req)
    emails = [x.strip().lower() for x in os.getenv("ADMIN_EMAILS", "").split(",") if x.strip()]
    if not emails:
        return []
    with db() as conn:
        rows = conn.execute("SELECT id,email FROM users WHERE lower(email)=ANY(%s) ORDER BY lower(email)", (emails,)).fetchall()
    return [{"id": str(row[0]), "email": row[1]} for row in rows]

@app.post("/admin/support/tickets/{ticket_id}/assignment")
def admin_support_assignment(ticket_id: str, request: SupportAssignmentRequest, req: Request):
    user = _support_admin(req)
    try: tid = uuid.UUID(ticket_id)
    except ValueError: raise HTTPException(422, "Invalid ticket id")
    assigned = None
    if request.assigned_to:
        try: assigned = uuid.UUID(request.assigned_to)
        except ValueError: raise HTTPException(422, "Invalid assignee id")
        with db() as conn:
            row = conn.execute("SELECT lower(email) FROM users WHERE id=%s", (assigned,)).fetchone()
        admins = {x.strip().lower() for x in os.getenv("ADMIN_EMAILS", "").split(",") if x.strip()}
        if not row or row[0] not in admins:
            raise HTTPException(403, "Assignee must be an authorized support administrator")
    item = support_service.set_assignment(uuid.UUID(user["id"]), tid, str(assigned) if assigned else None)
    if not item: raise HTTPException(404, "Ticket not found")
    return item

@app.get("/auth/countries")
def auth_countries():
    import json
    path=Path(__file__).resolve().parents[1] / "data" / "geography" / "countriesminified.json"
    try:
        rows=json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(500,"Country list unavailable") from exc
    return [{"name":x["name"],"iso2":x["iso2"]} for x in rows if x.get("name") and x.get("iso2")]

@app.get("/auth/country")
def auth_country(req: Request):
    code=(req.headers.get("CF-IPCountry") or req.headers.get("X-Country-Code") or "").strip().upper()
    if len(code)==2 and code.isalpha(): return {"iso2":code,"source":"proxy"}
    client_ip=(req.client.host if req.client else "").strip()
    if not client_ip or client_ip in {"127.0.0.1","::1"}: return {"iso2":None,"source":"unavailable"}
    try:
        from urllib.request import Request as UrlRequest,urlopen
        payload=urlopen(UrlRequest("https://ipapi.co/"+client_ip+"/country/",headers={"User-Agent":"Scrappee/1.0"}),timeout=3).read().decode().strip().upper()
        if len(payload)==2 and payload.isalpha(): return {"iso2":payload,"source":"ipapi"}
    except Exception:
        pass
    return {"iso2":None,"source":"unavailable"}

@app.post("/auth/register")
def register(request: AuthRequest):
    country=request.country.upper() if request.country else None
    if country and not country.isalpha(): raise HTTPException(422,"Invalid country code")
    try: user_id=create_user(request.email,request.password,country=country)
    except Exception as exc: raise HTTPException(409,"Email already registered") from exc
    return {"user_id":user_id,"email":request.email.lower().strip(),"registered":True}

class PasswordResetRequest(BaseModel):
    email: str

class PasswordResetConfirm(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=200)

def _send_password_reset_email(email, token):
    base_url=os.getenv("SCRAPPEE_APP_URL","https://scrapee.uk").rstrip("/")
    from_address=os.getenv("SCRAPPEE_MAIL_FROM","Scrappee <noreply@scrapee.uk>")
    link=f"{base_url}/login?reset_token={token}"
    msg=f"""From: {from_address}
To: {email}
Subject: Reset your Scrappee password
Content-Type: text/plain; charset=UTF-8

We received a request to reset your Scrappee password.

Reset your password:
{link}

This link expires in 60 minutes and can only be used once.

If you did not request this, you can safely ignore this email.
"""
    smtp_host=os.getenv("SCRAPPEE_SMTP_HOST","")
    smtp_port=int(os.getenv("SCRAPPEE_SMTP_PORT","465"))
    smtp_user=os.getenv("SCRAPPEE_SMTP_USER","")
    smtp_password=os.getenv("SCRAPPEE_SMTP_PASSWORD","") or base64.b64decode(os.getenv("SCRAPPEE_SMTP_PASSWORD_B64","")).decode()
    if not smtp_host or not smtp_user or not smtp_password:
        raise RuntimeError("SMTP password reset delivery is not configured")
    context=ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host,smtp_port,context=context,timeout=15) as smtp:
        smtp.login(smtp_user,smtp_password)
        smtp.sendmail(from_address,[email],msg)

def _send_support_reply_email(email, ticket_id, subject, reply_body):
    base_url=os.getenv("SCRAPPEE_APP_URL","https://scrapee.uk").rstrip("/")
    from_address=os.getenv("SCRAPPEE_MAIL_FROM","Scrappee <noreply@scrapee.uk>")
    ticket_link=f"{base_url}/support"
    preview=reply_body.strip()
    if len(preview) > 1200:
        preview=preview[:1200].rstrip()+"…"
    msg=f"""From: {from_address}
To: {email}
Subject: Scrappee support ticket responded to: {subject}
Content-Type: text/plain; charset=UTF-8

Your Scrappee support ticket has been responded to by our support team.

Ticket: {subject}
Ticket ID: {ticket_id}

Support response:
{preview}

Action required:
Please log in to Scrappee and review the response. If the issue is not resolved, reply to the ticket from your Support Centre.

Open Support Centre:
{ticket_link}

This is an automated notification from Scrappee.
"""
    smtp_host=os.getenv("SCRAPPEE_SMTP_HOST","")
    smtp_port=int(os.getenv("SCRAPPEE_SMTP_PORT","465"))
    smtp_user=os.getenv("SCRAPPEE_SMTP_USER","")
    smtp_password=os.getenv("SCRAPPEE_SMTP_PASSWORD","") or base64.b64decode(os.getenv("SCRAPPEE_SMTP_PASSWORD_B64","")).decode()
    if not smtp_host or not smtp_user or not smtp_password:
        raise RuntimeError("SMTP support notification delivery is not configured")
    context=ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host,smtp_port,context=context,timeout=15) as smtp:
        smtp.login(smtp_user,smtp_password)
        smtp.sendmail(from_address,[email],msg)


def _send_support_reply_email_safe(email, ticket_id, subject, reply_body):
    try:
        _send_support_reply_email(email, ticket_id, subject, reply_body)
    except Exception:
        logging.exception("Support reply email delivery failed for ticket %s", ticket_id)


def _send_wallet_adjustment_email(email, amount_cents, reason, new_balance_cents):
    from_address=os.getenv("SCRAPPEE_MAIL_FROM","Scrappee <noreply@scrapee.uk>")
    amount=float(amount_cents)/100
    new_balance=float(new_balance_cents)/100
    subject="Your Scrappee wallet has been credited" if amount_cents >= 0 else "Your Scrappee wallet has been debited"
    action="credited" if amount_cents >= 0 else "debited"
    msg=f"""From: {from_address}
To: {email}
Subject: {subject}
Content-Type: text/plain; charset=UTF-8

Your Scrappee wallet has been {action}.

Amount: ${amount:,.2f}
Remark: {reason}
New wallet balance: ${new_balance:,.2f}

This is an automated notification from Scrappee.
"""
    smtp_host=os.getenv("SCRAPPEE_SMTP_HOST","")
    smtp_port=int(os.getenv("SCRAPPEE_SMTP_PORT","465"))
    smtp_user=os.getenv("SCRAPPEE_SMTP_USER","")
    smtp_password=os.getenv("SCRAPPEE_SMTP_PASSWORD","") or base64.b64decode(os.getenv("SCRAPPEE_SMTP_PASSWORD_B64","")).decode()
    if not smtp_host or not smtp_user or not smtp_password:
        raise RuntimeError("SMTP wallet notification delivery is not configured")
    context=ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host,smtp_port,context=context,timeout=15) as smtp:
        smtp.login(smtp_user,smtp_password)
        smtp.sendmail(from_address,[email],msg)

@app.post("/auth/forgot-password")
def forgot_password(payload: PasswordResetRequest, background_tasks: BackgroundTasks):
    normalized=payload.email.lower().strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",normalized):
        raise HTTPException(422,"Enter a valid email address")
    reset=request_password_reset(normalized)
    if reset:
        try:
            _send_password_reset_email(reset["email"],reset["token"])
        except Exception:
            logging.exception("Password reset email delivery failed")
    return {"message":"If an account exists for that email, a password reset link has been sent."}

@app.post("/auth/reset-password")
def confirm_password_reset(payload: PasswordResetConfirm):
    reset_password(payload.token,payload.password)
    return {"message":"Password updated successfully. You can now sign in."}

@app.post("/auth/login")
def login(request: AuthRequest, req: Request):
    persistent=True
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
    user=current_user(request)
    with db() as conn:
        row=conn.execute("SELECT country FROM users WHERE id=%s",(uuid.UUID(user["id"]),)).fetchone()
    return {"id":user["id"],"email":user["email"],"role":user["role"],"country":row[0] if row else None}

LATEST_EXTENSION_PACKAGE_RE = re.compile(r"^Scrappee-Browser-Import-v(\d+)\.(\d+)\.(\d+)\.zip$")

def _latest_extension_package():
    packages=[]
    for path in DOWNLOADS_DIR.glob("Scrappee-Browser-Import-v*.zip"):
        match=LATEST_EXTENSION_PACKAGE_RE.match(path.name)
        if match:
            packages.append(((int(match.group(1)),int(match.group(2)),int(match.group(3))),path))
    if not packages:
        raise HTTPException(404,"Extension package not found")
    return max(packages,key=lambda item:item[0])

class ExtensionHeartbeatRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32)

@app.post("/extension/heartbeat")
def extension_heartbeat(request: ExtensionHeartbeatRequest, req: Request):
    user=current_user(req)
    if req.headers.get("X-Scrappee-Extension") != "1":
        raise HTTPException(403,"Extension client required")
    with db() as conn:
        conn.execute("""INSERT INTO extension_connections(user_id,version,last_seen_at,updated_at)
            VALUES(%s,%s,now(),now())
            ON CONFLICT(user_id) DO UPDATE SET version=EXCLUDED.version,last_seen_at=now(),updated_at=now()""",
            (uuid.UUID(user["id"]),request.version))
        conn.commit()
    version,_ = _latest_extension_package()
    latest_version = ".".join(map(str,version))
    return {"ok":True,"version":request.version,"latest_version":latest_version}

@app.get("/extension/status")
def extension_status(req: Request):
    user=current_user(req)
    version,_ = _latest_extension_package()
    latest_version = ".".join(map(str,version))
    with db() as conn:
        row=conn.execute("SELECT version,last_seen_at FROM extension_connections WHERE user_id=%s",(uuid.UUID(user["id"]),)).fetchone()
    if not row:
        return {"connected":False,"version":None,"latest_version":latest_version,"last_seen_at":None,"outdated":False}
    installed_version,last_seen=row
    connected=(time.time()-last_seen.timestamp()) <= 120
    return {"connected":connected,"version":installed_version,"latest_version":latest_version,"last_seen_at":last_seen.isoformat(),"outdated":connected and installed_version != latest_version}

@app.get("/downloads/latest", include_in_schema=False)
def download_extension_latest():
    _,path=_latest_extension_package()
    return FileResponse(path,media_type="application/zip",filename=path.name)

@app.get("/downloads/scrappee-browser-import-v0.6.13.zip", include_in_schema=False)
def download_extension_v0613():
    path=DOWNLOADS_DIR / "Scrappee-Browser-Import-v0.6.13.zip"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Extension package not found")
    return FileResponse(path,media_type="application/zip",filename=path.name)

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

class SearchInterpretRequest(BaseModel):
    request: str = Field(min_length=1, max_length=5000)

@app.post("/search/interpret")
def interpret_search(request: SearchInterpretRequest, req: Request):
    current_user(req)
    try:
        criteria = QueryInterpreter().interpret(request.request)
    except Exception as exc:
        logging.exception("Search interpretation failed")
        raise HTTPException(422, str(exc)) from exc
    return criteria.model_dump()

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
    reason: str = Field(min_length=5, max_length=500)

class AdminPriceRequest(BaseModel):
    amount_cents: int = Field(ge=0)

class AdminPaidEnrichmentPriceRequest(BaseModel):
    unit_micros_usd: int = Field(ge=1)

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
    return user.get("role") == "admin"

def _audit(conn, actor_id, action, module, target_user_id=None, metadata=None, result="success"):
    conn.execute("INSERT INTO admin_audit_events(id,actor_id,target_user_id,action,module,result,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s)",(uuid.uuid4(),uuid.UUID(str(actor_id)) if actor_id else None,uuid.UUID(str(target_user_id)) if target_user_id else None,action,module,result,Jsonb(metadata or {})))

@app.get("/admin/scraps")
def admin_scraps(req: Request, page: int = 1, page_size: int = 50, status: str = "", search: str = ""):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    page=max(1,page); page_size=max(1,min(page_size,200)); clauses=[]; params=[]
    if status.strip(): clauses.append("s.status=%s"); params.append(status.strip())
    if search.strip(): clauses.append("(s.name ILIKE %s OR u.email ILIKE %s)"); params.extend([f"%{search.strip()}%",f"%{search.strip()}%"])
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    with db() as conn:
        total=int(conn.execute("SELECT COUNT(*) FROM scraps s JOIN users u ON u.id=s.user_id"+where,tuple(params)).fetchone()[0])
        off=(page-1)*page_size
        rows=conn.execute("SELECT s.id,s.name,s.status,s.created_at,s.completed_at,u.email,(SELECT count(*) FROM leads l WHERE l.scrap_id=s.id),(SELECT count(*) FROM serp_results sr WHERE sr.scrap_id=s.id) FROM scraps s JOIN users u ON u.id=s.user_id"+where+" ORDER BY s.created_at DESC LIMIT %s OFFSET %s",tuple(params+[page_size,off])).fetchall()
    return {"scraps":[{"id":str(r[0]),"name":r[1],"status":r[2],"created_at":r[3].isoformat(),"completed_at":r[4].isoformat() if r[4] else None,"user_email":r[5],"leads":int(r[6]),"serp_results":int(r[7])} for r in rows],"total":total,"page":page,"page_size":page_size,"total_pages":(total+page_size-1)//page_size}

@app.get("/admin/campaigns")
def admin_campaigns(req: Request, status: str = "", search: str = ""):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    clauses=[]; params=[]
    if status.strip(): clauses.append("c.status=%s"); params.append(status.strip())
    if search.strip(): clauses.append("(c.name ILIKE %s OR u.email ILIKE %s)"); params.extend([f"%{search.strip()}%",f"%{search.strip()}%"])
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    with db() as conn:
        rows=conn.execute("SELECT c.id,c.name,c.status,c.created_at,c.updated_at,u.email,sa.email,sl.name,(SELECT count(*) FROM sender_campaign_leads cl WHERE cl.campaign_id=c.id),(SELECT count(*) FROM sender_messages sm WHERE sm.campaign_id=c.id AND sm.status='sent') FROM sender_campaigns c JOIN users u ON u.id=c.user_id JOIN sender_accounts sa ON sa.id=c.sender_id JOIN sender_letters sl ON sl.id=c.letter_id"+where+" ORDER BY c.updated_at DESC LIMIT 200",tuple(params)).fetchall()
    return [{"id":str(r[0]),"name":r[1],"status":r[2],"created_at":r[3].isoformat(),"updated_at":r[4].isoformat(),"user_email":r[5],"sender_email":r[6],"letter":r[7],"leads":int(r[8]),"sent":int(r[9])} for r in rows]

@app.get("/admin/senders")
def admin_senders(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT s.id,s.display_name,s.email,s.provider,s.enabled,s.health,s.created_at,s.updated_at,u.email,(SELECT count(*) FROM sender_campaigns c WHERE c.sender_id=s.id) FROM sender_accounts s JOIN users u ON u.id=s.user_id ORDER BY s.updated_at DESC LIMIT 500").fetchall()
    return [{"id":str(r[0]),"display_name":r[1],"email":r[2],"provider":r[3],"enabled":bool(r[4]),"health":r[5],"created_at":r[6].isoformat(),"updated_at":r[7].isoformat(),"user_email":r[8],"campaigns":int(r[9])} for r in rows]

@app.get("/admin/system-health")
def admin_system_health(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        users=int(conn.execute("SELECT count(*) FROM users").fetchone()[0])
        active_scraps=int(conn.execute("SELECT count(*) FROM scraps WHERE status IN ('active','running')").fetchone()[0])
        jobs=int(conn.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running','processing')").fetchone()[0])
        extensions=int(conn.execute("SELECT count(*) FROM extension_connections WHERE last_seen_at > now()-interval '15 minutes'").fetchone()[0])
        tickets=int(conn.execute("SELECT count(*) FROM support_tickets WHERE status NOT IN ('closed','resolved')").fetchone()[0])
        senders=int(conn.execute("SELECT count(*) FROM sender_accounts WHERE enabled=true").fetchone()[0])
    return {"database":"ok","users":users,"active_scraps":active_scraps,"active_jobs":jobs,"extensions_seen_15m":extensions,"open_tickets":tickets,"enabled_senders":senders}

@app.get("/admin/audit-log")
def admin_audit_log(req: Request, page: int = 1, page_size: int = 50, actor: str = "", target: str = "", module: str = "", action: str = "", result: str = ""):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if page < 1 or page_size < 1 or page_size > 200: raise HTTPException(400,"Invalid pagination")
    clauses=[]; params=[]
    if actor.strip(): clauses.append("a.actor_id IN (SELECT id FROM users WHERE email ILIKE %s)"); params.append("%"+actor.strip()+"%")
    if target.strip(): clauses.append("a.target_user_id IN (SELECT id FROM users WHERE email ILIKE %s)"); params.append("%"+target.strip()+"%")
    if module.strip(): clauses.append("a.module=%s"); params.append(module.strip())
    if action.strip(): clauses.append("a.action=%s"); params.append(action.strip())
    if result.strip(): clauses.append("a.result=%s"); params.append(result.strip())
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    with db() as conn:
        total=int(conn.execute("SELECT COUNT(*) FROM admin_audit_events a"+where,tuple(params)).fetchone()[0])
        offset=(page-1)*page_size
        rows=conn.execute("SELECT a.id,a.created_at,a.action,a.module,a.result,a.metadata,a.actor_id,au.email,a.target_user_id,tu.email FROM admin_audit_events a LEFT JOIN users au ON au.id=a.actor_id LEFT JOIN users tu ON tu.id=a.target_user_id"+where+" ORDER BY a.created_at DESC LIMIT %s OFFSET %s",tuple(params+[page_size,offset])).fetchall()
    return {"events":[{"id":str(r[0]),"timestamp":r[1].isoformat(),"action":r[2],"module":r[3],"result":r[4],"metadata":r[5] or {},"actor_id":str(r[6]) if r[6] else None,"actor_email":r[7],"target_user_id":str(r[8]) if r[8] else None,"target_email":r[9]} for r in rows],"total":total,"page":page,"page_size":page_size,"total_pages":(total+page_size-1)//page_size}

@app.get("/admin/domain-blacklist")
def admin_domain_blacklist(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT id,domain,created_at FROM global_domain_blacklist ORDER BY domain").fetchall()
    return [{"id":str(r[0]),"domain":r[1],"created_at":r[2].isoformat()} for r in rows]

@app.post("/admin/domain-blacklist")
def add_admin_domain_blacklist(request: DomainRuleRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    from src.policy import normalize_domain
    domain=normalize_domain(request.domain)
    if not domain or "." not in domain: raise HTTPException(422,"Valid domain is required")
    with db() as conn:
        row=conn.execute("INSERT INTO global_domain_blacklist(id,domain) VALUES(%s,%s) ON CONFLICT(domain) DO UPDATE SET domain=EXCLUDED.domain RETURNING id,domain,created_at",(uuid.uuid4(),domain)).fetchone(); conn.commit()
    return {"id":str(row[0]),"domain":row[1],"created_at":row[2].isoformat()}

@app.delete("/admin/domain-blacklist/{rule_id}")
def delete_admin_domain_blacklist(rule_id: str, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        row=conn.execute("DELETE FROM global_domain_blacklist WHERE id=%s RETURNING id",(uuid.UUID(rule_id),)).fetchone(); conn.commit()
    if not row: raise HTTPException(404,"Blacklisted domain not found")

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

@app.get("/admin/search-template-categories")
def admin_search_template_categories(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT id,name,stable_key,active,position FROM search_template_categories ORDER BY position,name").fetchall()
    return [{"id":str(r[0]),"name":r[1],"stable_key":r[2],"active":r[3],"position":r[4]} for r in rows]

@app.post("/admin/search-template-categories")
def admin_add_search_template_category(request: SearchTemplateCategoryRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        try:
            row=conn.execute("INSERT INTO search_template_categories(id,name,active,position) VALUES(gen_random_uuid(),%s,%s,(SELECT COALESCE(MAX(position),0)+1 FROM search_template_categories)) RETURNING id,name,active,position",(request.name.strip(),request.active)).fetchone()
            conn.commit()
        except UniqueViolation as exc:
            raise HTTPException(409,"Category already exists") from exc
    return {"id":str(row[0]),"name":row[1],"active":row[2],"position":row[3]}

@app.get("/admin/search-template-categories/{category_id}/templates")
def admin_search_templates(category_id: str, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT id,provider,family,template,active,position FROM search_templates WHERE category_id=%s ORDER BY position,created_at",(uuid.UUID(category_id),)).fetchall()
    return [{"id":str(r[0]),"provider":r[1],"family":r[2],"template":r[3],"active":r[4],"position":r[5]} for r in rows]

@app.post("/admin/search-templates")
def admin_add_search_template(request: SearchTemplateRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if any(v not in VARIABLES for v in __import__("re").findall(r"{([a-z_]+)}",request.template)):
        raise HTTPException(422,"Template contains an unsupported variable")
    with db() as conn:
        category_id=uuid.UUID(request.category_id)
        exists=conn.execute("SELECT 1 FROM search_template_categories WHERE id=%s",(category_id,)).fetchone()
        if not exists: raise HTTPException(404,"Search template category not found")
        duplicate=conn.execute("SELECT 1 FROM search_templates WHERE category_id=%s AND provider=%s AND family=%s AND template=%s LIMIT 1",(category_id,request.provider,request.family.strip(),request.template.strip())).fetchone()
        if duplicate: raise HTTPException(409,"This template already exists in the selected category")
        row=conn.execute("INSERT INTO search_templates(id,category_id,provider,family,template,active,position) VALUES(gen_random_uuid(),%s,%s,%s,%s,%s,(SELECT COALESCE(MAX(position),0)+1 FROM search_templates WHERE category_id=%s)) RETURNING id,provider,family,template,active,position",(category_id,request.provider,request.family.strip(),request.template.strip(),request.active,category_id)).fetchone()
        conn.commit()
    return {"id":str(row[0]),"provider":row[1],"family":row[2],"template":row[3],"active":row[4],"position":row[5]}

@app.patch("/admin/search-templates/{template_id}")
def admin_patch_search_template(template_id: str, request: dict, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    tid=uuid.UUID(template_id)
    with db() as conn:
        row=conn.execute("SELECT category_id FROM search_templates WHERE id=%s",(tid,)).fetchone()
        if not row: raise HTTPException(404,"Search template not found")
        if "active" in request:
            conn.execute("UPDATE search_templates SET active=%s WHERE id=%s",(bool(request["active"]),tid))
        if "provider" in request:
            provider=str(request["provider"]).strip().lower()
            if provider not in ("google","bing"): raise HTTPException(422,"Unsupported search provider")
            current=conn.execute("SELECT category_id,family,template FROM search_templates WHERE id=%s",(tid,)).fetchone()
            duplicate=conn.execute("SELECT 1 FROM search_templates WHERE category_id=%s AND provider=%s AND family=%s AND template=%s AND id<>%s LIMIT 1",(current[0],provider,current[1],current[2],tid)).fetchone()
            if duplicate: raise HTTPException(409,"This template already exists in the selected category")
            conn.execute("UPDATE search_templates SET provider=%s WHERE id=%s",(provider,tid))
        if "family" in request:
            family=str(request["family"]).strip()
            if not family: raise HTTPException(422,"Family cannot be empty")
            current=conn.execute("SELECT category_id,provider,template FROM search_templates WHERE id=%s",(tid,)).fetchone()
            duplicate=conn.execute("SELECT 1 FROM search_templates WHERE category_id=%s AND provider=%s AND family=%s AND template=%s AND id<>%s LIMIT 1",(current[0],current[1],family,current[2],tid)).fetchone()
            if duplicate: raise HTTPException(409,"This template already exists in the selected category")
            conn.execute("UPDATE search_templates SET family=%s WHERE id=%s",(family,tid))
        if "template" in request:
            template=str(request["template"]).strip()
            if not template: raise HTTPException(422,"Template cannot be empty")
            if any(v not in VARIABLES for v in __import__("re").findall(r"{([a-z_]+)}",template)): raise HTTPException(422,"Template contains an unsupported variable")
            conn.execute("UPDATE search_templates SET template=%s WHERE id=%s",(template,tid))
        if "position" in request:
            target=max(0,int(request["position"]))
            ids=[r[0] for r in conn.execute("SELECT id FROM search_templates WHERE category_id=%s ORDER BY position,created_at",(row[0],)).fetchall()]
            if tid in ids:
                target=min(target,len(ids)-1); ids.remove(tid); ids.insert(target,tid)
                for position,item_id in enumerate(ids): conn.execute("UPDATE search_templates SET position=%s WHERE id=%s",(position,item_id))
        conn.commit()
    return {"id":template_id}

@app.patch("/admin/search-template-categories/{category_id}")
def admin_patch_search_template_category(category_id: str, request: dict, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    cid=uuid.UUID(category_id)
    with db() as conn:
        exists=conn.execute("SELECT 1 FROM search_template_categories WHERE id=%s",(cid,)).fetchone()
        if not exists: raise HTTPException(404,"Search template category not found")
        if "active" in request: conn.execute("UPDATE search_template_categories SET active=%s WHERE id=%s",(bool(request["active"]),cid))
        if "name" in request:
            name=str(request["name"]).strip()
            if not name: raise HTTPException(422,"Category name cannot be empty")
            duplicate=conn.execute("SELECT 1 FROM search_template_categories WHERE lower(name)=lower(%s) AND id<>%s LIMIT 1",(name,cid)).fetchone()
            if duplicate: raise HTTPException(409,"A category with this name already exists")
            conn.execute("UPDATE search_template_categories SET name=%s WHERE id=%s",(name,cid))
        if "position" in request:
            target=max(0,int(request["position"]))
            ids=[r[0] for r in conn.execute("SELECT id FROM search_template_categories ORDER BY position,name").fetchall()]
            if cid in ids:
                target=min(target,len(ids)-1); ids.remove(cid); ids.insert(target,cid)
                for position,item_id in enumerate(ids): conn.execute("UPDATE search_template_categories SET position=%s WHERE id=%s",(position,item_id))
        conn.commit()
    return {"id":category_id}

@app.delete("/admin/search-template-categories/{category_id}")
def admin_delete_search_template_category(category_id: str, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    cid=uuid.UUID(category_id)
    with db() as conn:
        row=conn.execute("SELECT stable_key FROM search_template_categories WHERE id=%s",(cid,)).fetchone()
        if not row: raise HTTPException(404,"Search template category not found")
        if row[0]: raise HTTPException(409,"Built-in categories cannot be deleted")
        conn.execute("DELETE FROM search_template_categories WHERE id=%s",(cid,))
        conn.commit()
    return {"deleted": True, "id": category_id}

@app.delete("/admin/search-templates/{template_id}",status_code=204)
def admin_delete_search_template(template_id: str, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        conn.execute("DELETE FROM search_templates WHERE id=%s",(uuid.UUID(template_id),)); conn.commit()

@app.get("/billing")
def billing(req: Request):
    user=current_user(req); uid=uuid.UUID(user["id"])
    with db() as conn:
        balance=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s",(uid,)).fetchone()[0]
        price=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='scrap_creation_price_cents'").fetchone()[0]
        premium_price=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='premium_serp_price_cents'").fetchone()[0]
        paid_unit=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='paid_enrichment_unit_micros_usd'").fetchone()[0]
        page_indexer_price=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='page_indexer_price_cents'").fetchone()[0]
        default_max_leads=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_default_max_leads'").fetchone()[0]
        max_leads=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_max_leads'").fetchone()[0]
        timeout_hours=conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='research_timeout_hours'").fetchone()[0]
    return {"balance_cents":int(balance),"scrap_creation_price_cents":int(price),"premium_serp_price_cents":int(premium_price),"paid_enrichment_unit_micros_usd":int(paid_unit),"page_indexer_price_cents":int(page_indexer_price),"research_default_max_leads":int(default_max_leads),"research_max_leads":int(max_leads),"research_timeout_hours":int(timeout_hours)}

class BtcPayDepositRequest(BaseModel):
    amount_cents: int = Field(ge=MIN_DEPOSIT_CENTS, le=100000000)
    asset: Literal['BTC', 'LTC', 'USDT'] = 'BTC'
    network: Literal['TRON', 'BSC'] | None = None

    @model_validator(mode='after')
    def validate_network(self):
        if self.asset == 'USDT' and self.network not in {'TRON','BSC'}:
            raise ValueError('USDT network must be TRON or BSC')
        if self.asset != 'USDT' and self.network is not None:
            raise ValueError('Network is only valid for USDT')
        return self


@app.post("/billing/deposits/btcpay")
def create_btcpay_deposit(request: BtcPayDepositRequest, req: Request):
    user = current_user(req)
    if not btcpay_configured():
        raise HTTPException(503, "BTCPay is not configured")
    uid = uuid.UUID(user["id"])
    deposit_id = uuid.uuid4()
    order_id = str(deposit_id)
    try:
        with db() as conn:
            store_key = {'LTC': 'btcpay_ltc_store_id', 'USDT': 'btcpay_usdt_store_id'}.get(request.asset)
            store_id = _app_setting(conn, store_key) if store_key else None
        payment_methods = {'LTC': ['LTC'], 'USDT': [f"USDT-{request.network}"]}.get(request.asset)
        invoice = btcpay_create_invoice(f"{request.amount_cents / 100:.2f}", order_id, store_id=store_id, payment_methods=payment_methods)
    except Exception as exc:
        logging.exception("BTCPay invoice creation failed")
        raise HTTPException(502, "Could not create BTCPay invoice") from exc
    invoice_id = str(invoice.get("id") or "").strip()
    checkout_url = str(invoice.get("checkoutLink") or invoice.get("checkoutUrl") or "").strip()
    if not invoice_id or not checkout_url:
        raise HTTPException(502, "BTCPay returned an incomplete invoice")
    with db() as conn:
        conn.execute("INSERT INTO wallet_deposits(id,user_id,btcpay_invoice_id,requested_cents,asset,network,status) VALUES(%s,%s,%s,%s,%s,%s,'pending')", (deposit_id, uid, invoice_id, request.amount_cents, request.asset, request.network))
        conn.commit()
    return {"deposit_id": str(deposit_id), "invoice_id": invoice_id, "requested_cents": request.amount_cents, "asset": request.asset, "network": request.network, "checkout_url": checkout_url, "invoice": invoice}


@app.post("/billing/deposits/{deposit_id}/refresh")
def refresh_btcpay_deposit(deposit_id: str, req: Request):
    user = current_user(req)
    with db() as conn:
        row = conn.execute("SELECT btcpay_invoice_id,asset,network,status FROM wallet_deposits WHERE id=%s AND user_id=%s", (uuid.UUID(deposit_id), uuid.UUID(user["id"]))).fetchone()
        if not row:
            raise HTTPException(404, "Deposit not found")
        invoice_id, asset, network, local_status = row
        store_key = {'LTC': 'btcpay_ltc_store_id', 'USDT': 'btcpay_usdt_store_id'}.get(asset)
        store_id = _app_setting(conn, store_key) if store_key else None
    try:
        invoice = btcpay_get_invoice(invoice_id, store_id=store_id)
    except Exception as exc:
        logging.exception("BTCPay invoice refresh failed")
        raise HTTPException(502, "Could not refresh payment status") from exc
    return {"deposit_id": deposit_id, "invoice_id": invoice_id, "asset": asset, "network": network, "local_status": local_status, "status": invoice.get("status"), "additional_status": invoice.get("additionalStatus"), "payments": invoice.get("payments") or [], "payment_methods": invoice.get("paymentMethods") or []}


@app.get("/billing/deposits")
def list_btcpay_deposits(req: Request):
    user = current_user(req)
    with db() as conn:
        rows = conn.execute("SELECT id,btcpay_invoice_id,requested_cents,asset,network,paid_btc,status,settled_at,created_at FROM wallet_deposits WHERE user_id=%s ORDER BY created_at DESC LIMIT 50", (uuid.UUID(user["id"]),)).fetchall()
    return [{"id": str(r[0]), "invoice_id": r[1], "requested_cents": int(r[2]), "asset": r[3], "network": r[4], "paid_amount": str(r[5]) if r[5] is not None else None, "status": r[6], "settled_at": r[7].isoformat() if r[7] else None, "created_at": r[8].isoformat()} for r in rows]


@app.post("/billing/deposits/btcpay/webhook")
async def btcpay_webhook(req: Request):
    raw = await req.body()
    if not btcpay_verify_webhook(raw, req.headers.get("BTCPay-Sig", "")):
        raise HTTPException(401, "Invalid BTCPay signature")
    try:
        payload = await req.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid webhook payload") from exc
    event_type = str(payload.get("type") or "")
    invoice_id = str(payload.get("invoiceId") or "").strip()
    if not invoice_id:
        return {"ok": True, "ignored": True}
    if event_type not in {"InvoiceProcessing", "InvoiceSettled", "InvoiceExpired", "InvoiceInvalid"}:
        return {"ok": True, "ignored": True}
    notification = None
    with db() as conn:
        row = conn.execute("SELECT d.id,d.user_id,d.requested_cents,d.asset,d.network,d.paid_btc,d.status,u.email FROM wallet_deposits d JOIN users u ON u.id=d.user_id WHERE d.btcpay_invoice_id=%s FOR UPDATE", (invoice_id,)).fetchone()
        if not row:
            return {"ok": True, "ignored": True}
        deposit_id, uid, requested_cents, asset, network, paid_btc, current_status, user_email = row
        if event_type == "InvoiceSettled" and current_status != "settled":
            amount_btc = btcpay_payment_btc(payload) if asset == 'BTC' else None
            balance = conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE", (uid,)).fetchone()
            if not balance: raise HTTPException(500, "Wallet not initialized")
            new_balance = int(balance[0]) + int(requested_cents)
            conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s", (new_balance, uid))
            conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'btcpay_deposit',%s) ON CONFLICT(user_id,transaction_type,reference_id) DO NOTHING", (uuid.uuid4(), uid, requested_cents, new_balance, str(deposit_id)))
            conn.execute("UPDATE wallet_deposits SET status='settled',paid_btc=%s,settled_at=now(),updated_at=now() WHERE id=%s", (amount_btc, deposit_id))
            notification = (user_email, int(requested_cents), f"{asset}{(' / ' + network) if network else ''} deposit received · BTCPay invoice {invoice_id}", new_balance)
        elif event_type == "InvoiceProcessing" and current_status == "pending":
            conn.execute("UPDATE wallet_deposits SET status='processing',updated_at=now() WHERE id=%s", (deposit_id,))
        elif event_type == "InvoiceExpired" and current_status not in ('settled',):
            conn.execute("UPDATE wallet_deposits SET status='expired',updated_at=now() WHERE id=%s", (deposit_id,))
        elif event_type == "InvoiceInvalid" and current_status not in ('settled',):
            conn.execute("UPDATE wallet_deposits SET status='invalid',updated_at=now() WHERE id=%s", (deposit_id,))
        conn.commit()
    if notification:
        try:
            _send_wallet_adjustment_email(*notification)
        except Exception:
            logging.exception("BTCPay deposit notification email failed")
    return {"ok": True}


class ManualDepositRequest(BaseModel):
    method: Literal['usdt_manual', 'bank_transfer']
    amount_cents: int = Field(ge=MIN_DEPOSIT_CENTS, le=100000000)
    reference: str = Field(min_length=2, max_length=200)
    sender_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

class ManualDepositReviewRequest(BaseModel):
    approved: bool

class AdminDepositConfigRequest(BaseModel):
    usdt_manual_enabled: bool = False
    usdt_manual_wallet: str | None = Field(default=None, max_length=200)
    bank_transfer_details: dict[str, str] = Field(default_factory=dict)
    btcpay_ltc_store_id: str | None = Field(default=None, max_length=200)
    btcpay_usdt_store_id: str | None = Field(default=None, max_length=200)


def _app_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM app_settings WHERE key=%s", (key,)).fetchone()
    return row[0] if row else default

@app.get("/billing/deposit-config")
def deposit_config(req: Request):
    current_user(req)
    with db() as conn:
        wallet = _app_setting(conn, 'usdt_manual_wallet')
        enabled = _app_setting(conn, 'usdt_manual_enabled', False)
        bank = _app_setting(conn, 'bank_transfer_details', {})
        ltc_store = _app_setting(conn, 'btcpay_ltc_store_id')
        usdt_store = _app_setting(conn, 'btcpay_usdt_store_id')
    return {"usdt_manual_enabled": bool(enabled), "usdt_manual_wallet": wallet, "bank_transfer_details": bank or {}, "btcpay_ltc_configured": bool(ltc_store), "btcpay_usdt_configured": bool(usdt_store)}

@app.post("/billing/deposits/manual")
def create_manual_deposit(request: ManualDepositRequest, req: Request):
    user = current_user(req)
    uid = uuid.UUID(user['id'])
    with db() as conn:
        if request.method == 'usdt_manual':
            enabled = _app_setting(conn, 'usdt_manual_enabled', False)
            wallet = _app_setting(conn, 'usdt_manual_wallet')
            if not enabled or not wallet:
                raise HTTPException(503, 'Manual USDT deposits are not configured')
        try:
            row = conn.execute("INSERT INTO manual_deposits(id,user_id,method,amount_cents,reference,sender_name,notes) VALUES(gen_random_uuid(),%s,%s,%s,%s,%s,%s) RETURNING id,created_at", (uid,request.method,request.amount_cents,request.reference.strip(),request.sender_name,request.notes)).fetchone()
            conn.commit()
        except UniqueViolation as exc:
            raise HTTPException(409, 'That payment reference has already been submitted') from exc
    return {"id": str(row[0]), "status": "pending", "created_at": row[1].isoformat()}

@app.get("/billing/deposits/manual")
def list_manual_deposits(req: Request):
    user = current_user(req)
    with db() as conn:
        rows = conn.execute("SELECT id,method,amount_cents,reference,sender_name,notes,status,reviewed_at,created_at FROM manual_deposits WHERE user_id=%s ORDER BY created_at DESC LIMIT 50", (uuid.UUID(user['id']),)).fetchall()
    return [{"id":str(r[0]),"method":r[1],"amount_cents":int(r[2]),"reference":r[3],"sender_name":r[4],"notes":r[5],"status":r[6],"reviewed_at":r[7].isoformat() if r[7] else None,"created_at":r[8].isoformat()} for r in rows]

@app.get("/admin/deposits")
def admin_deposits(req: Request, status: str = "pending", page: int = 1, page_size: int = 10, search: str = ""):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if status not in {"pending","settled","failed","all"}: raise HTTPException(422,"Invalid deposit status")
    page=max(1,page); page_size=max(10,min(page_size,100)); search=search.strip()
    status_clause={
        "pending":"status IN ('pending','processing')",
        "settled":"status IN ('approved','settled')",
        "failed":"status IN ('rejected','expired','invalid')",
        "all":"TRUE"
    }[status]
    search_clause=""
    args=[]
    if search:
        search_clause=" AND (email ILIKE %s OR reference ILIKE %s OR COALESCE(sender_name,'') ILIKE %s OR method ILIKE %s)"
        args=[f"%{search}%"]*4
    with db() as conn:
        base=f"""SELECT * FROM (
            SELECT d.id,u.email,d.method,d.amount_cents,d.reference,d.sender_name,d.notes,d.status,d.created_at,'manual' AS source,TRUE AS reviewable
            FROM manual_deposits d JOIN users u ON u.id=d.user_id
            UNION ALL
            SELECT d.id,u.email,'BTCPay / ' || d.asset || COALESCE(' / ' || d.network,''),d.requested_cents,d.btcpay_invoice_id,NULL,NULL,d.status,d.created_at,'btcpay' AS source,FALSE AS reviewable
            FROM wallet_deposits d JOIN users u ON u.id=d.user_id
        ) deposits WHERE {status_clause}{search_clause}"""
        total=int(conn.execute(f"SELECT count(*) FROM ({base}) q",tuple(args)).fetchone()[0])
        rows=conn.execute(f"SELECT id,email,method,amount_cents,reference,sender_name,notes,status,created_at,source,reviewable FROM ({base}) q ORDER BY created_at DESC LIMIT %s OFFSET %s",tuple(args+[page_size,(page-1)*page_size])).fetchall()
    return {"deposits":[{"id":str(r[0]),"email":r[1],"method":r[2],"amount_cents":int(r[3]),"reference":r[4],"sender_name":r[5],"notes":r[6],"status":r[7],"created_at":r[8].isoformat(),"source":r[9],"reviewable":bool(r[10])} for r in rows],"pagination":{"page":page,"page_size":page_size,"total":total,"total_pages":(total+page_size-1)//page_size}}

@app.post("/admin/deposits/{deposit_id}/review")
def review_manual_deposit(deposit_id: str, request: ManualDepositReviewRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        row=conn.execute("SELECT user_id,amount_cents,status FROM manual_deposits WHERE id=%s FOR UPDATE",(uuid.UUID(deposit_id),)).fetchone()
        if not row: raise HTTPException(404,"Deposit not found")
        uid,amount_cents,status=row
        if status != 'pending': raise HTTPException(409,'Deposit has already been reviewed')
        if request.approved:
            balance=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone()
            if not balance: raise HTTPException(500,'Wallet not initialized')
            new_balance=int(balance[0])+int(amount_cents)
            conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s",(new_balance,uid))
            conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(gen_random_uuid(),%s,%s,%s,'manual_deposit',%s) ON CONFLICT(user_id,transaction_type,reference_id) DO NOTHING",(uid,amount_cents,new_balance,deposit_id))
        conn.execute("UPDATE manual_deposits SET status=%s,reviewed_by=%s,reviewed_at=now() WHERE id=%s",('approved' if request.approved else 'rejected',uuid.UUID(user['id']),uuid.UUID(deposit_id)))
        _audit(conn,user['id'],"deposit_"+('approved' if request.approved else 'rejected'),"billing",uid,{"deposit_id":deposit_id,"amount_cents":int(amount_cents)})
        conn.commit()
    return {"id":deposit_id,"status":"approved" if request.approved else "rejected"}

@app.post("/admin/deposit-config")
def save_deposit_config(request: AdminDepositConfigRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        values=(('usdt_manual_enabled',request.usdt_manual_enabled),('usdt_manual_wallet',request.usdt_manual_wallet),('bank_transfer_details',request.bank_transfer_details),('btcpay_ltc_store_id',request.btcpay_ltc_store_id),('btcpay_usdt_store_id',request.btcpay_usdt_store_id))
        for key,value in values:
            conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(%s,%s,now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(key,Jsonb(value)))
        _audit(conn,user['id'],"deposit_config_updated","billing",None,{"usdt_manual_enabled":request.usdt_manual_enabled,"btcpay_ltc_configured":bool(request.btcpay_ltc_store_id),"btcpay_usdt_configured":bool(request.btcpay_usdt_store_id)})
        conn.commit()
    return {"saved":True}

@app.get("/admin/deposit-config")
def admin_deposit_config(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        return {k:_app_setting(conn,k) for k in ('usdt_manual_enabled','usdt_manual_wallet','bank_transfer_details','btcpay_ltc_store_id','btcpay_usdt_store_id')}

@app.post("/admin/scrap-price")
def set_scrap_price(amount_cents: int, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if amount_cents < 0: raise HTTPException(422,"Price cannot be negative")
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('scrap_creation_price_cents',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(amount_cents,)); _audit(conn,user['id'],"scrap_price_updated","configuration",None,{"amount_cents":amount_cents}); conn.commit()
    return {"scrap_creation_price_cents":amount_cents}

@app.post("/admin/paid-enrichment-price")
def admin_paid_enrichment_price(request: AdminPaidEnrichmentPriceRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    unit_micros = request.unit_micros_usd
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('paid_enrichment_unit_micros_usd',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(unit_micros,)); _audit(conn,user['id'],"paid_enrichment_price_updated","configuration",None,{"unit_micros_usd":unit_micros}); conn.commit()
    return {"paid_enrichment_unit_micros_usd":unit_micros}

@app.post("/admin/premium-serp-price")
def admin_premium_serp_price(request: AdminPriceRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    amount_cents=request.amount_cents
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('premium_serp_price_cents',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(amount_cents,)); _audit(conn,user['id'],"premium_serp_price_updated","configuration",None,{"amount_cents":amount_cents}); conn.commit()
    return {"premium_serp_price_cents":amount_cents}

@app.post("/admin/page-indexer-price")
def admin_page_indexer_price(request: AdminPriceRequest, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    if request.amount_cents < 0: raise HTTPException(422,"Price cannot be negative")
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('page_indexer_price_cents',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(request.amount_cents,)); _audit(conn,user['id'],"page_indexer_price_updated","configuration",None,{"amount_cents":request.amount_cents}); conn.commit()
    return {"page_indexer_price_cents":request.amount_cents}


@app.post("/admin/serp-limit")
def admin_serp_limit(request: dict, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    try: limit=int(request.get("limit",0))
    except (TypeError,ValueError): raise HTTPException(400,"limit must be an integer")
    if limit < 1 or limit > 1000000: raise HTTPException(400,"limit must be between 1 and 1000000")
    with db() as conn:
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('serp_result_limit',to_jsonb(%s::bigint),now()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",(limit,)); _audit(conn,user['id'],"serp_limit_updated","configuration",None,{"limit":limit}); conn.commit()
    return {"serp_result_limit":limit}

@app.get("/admin/users")
def admin_users(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT u.id,u.email,u.role,u.country,u.created_at,u.last_login_at,COALESCE(w.balance_cents,0) FROM users u LEFT JOIN wallets w ON w.user_id=u.id ORDER BY u.created_at DESC,u.email").fetchall()
    return [{"id":str(r[0]),"email":r[1],"role":r[2],"country":r[3],"created_at":r[4].isoformat(),"last_login_at":r[5].isoformat() if r[5] else None,"balance_cents":int(r[6])} for r in rows]

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
        rows=conn.execute("SELECT u.id,u.email,u.role,u.country,u.created_at,u.last_login_at,COALESCE(w.balance_cents,0) FROM users u LEFT JOIN wallets w ON w.user_id=u.id WHERE u.email ILIKE %s ORDER BY u.created_at DESC,u.email LIMIT %s OFFSET %s",(pattern,page_size,offset)).fetchall()
    return {"users":[{"id":str(r[0]),"email":r[1],"role":r[2],"country":r[3],"created_at":r[4].isoformat(),"last_login_at":r[5].isoformat() if r[5] else None,"balance_cents":int(r[6])} for r in rows],"total":total,"page":page,"page_size":page_size,"total_pages":(total+page_size-1)//page_size}

@app.patch("/admin/users/{user_id}/role")
async def admin_change_user_role(user_id: str, req: Request):
    admin=current_user(req)
    if not _is_admin(admin): raise HTTPException(403,"Admin access required")
    try: uid=uuid.UUID(user_id)
    except ValueError as exc: raise HTTPException(422,"Invalid user id") from exc
    body=await req.json()
    role=body.get("role")
    if role not in {"user","admin"}: raise HTTPException(422,"Role must be user or admin")
    if uid == uuid.UUID(admin["id"]) and role != "admin": raise HTTPException(409,"You cannot remove your own admin role")
    with db() as conn:
        row=conn.execute("SELECT email,role FROM users WHERE id=%s",(uid,)).fetchone()
        if not row: raise HTTPException(404,"User not found")
        if row[1]==role: return {"updated":False,"role":role}
        if role=="user":
            admins=int(conn.execute("SELECT count(*) FROM users WHERE role='admin'").fetchone()[0])
            if admins<=1: raise HTTPException(409,"At least one admin account must remain")
        conn.execute("UPDATE users SET role=%s WHERE id=%s",(role,uid))
        _audit(conn,admin["id"],"user_role_changed","users",str(uid),{"target_email":row[0],"from_role":row[1],"to_role":role})
        conn.commit()
    return {"updated":True,"role":role}

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
        _audit(conn,user['id'],"users_bulk_deleted","users",None,{"requested":len(ids),"deleted":len(rows),"emails":[r[0] for r in rows]})
        conn.commit()
    return {"deleted":len(rows),"emails":[r[0] for r in rows],"requested":len(ids)}

@app.get("/admin/users/{user_id}")
def admin_user_detail(user_id: str, req: Request, wallet_page: int = 1, wallet_page_size: int = 10):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    try: uid=uuid.UUID(user_id)
    except ValueError as exc: raise HTTPException(422,"Invalid user id") from exc
    wallet_page=max(1,wallet_page); wallet_page_size=max(5,min(wallet_page_size,50))
    with db() as conn:
        row=conn.execute("SELECT u.id,u.email,u.country,u.created_at,u.last_login_at,COALESCE(w.balance_cents,0) FROM users u LEFT JOIN wallets w ON w.user_id=u.id WHERE u.id=%s",(uid,)).fetchone()
        if not row: raise HTTPException(404,"User not found")
        wallet_total=int(conn.execute("SELECT count(*) FROM wallet_transactions WHERE user_id=%s",(uid,)).fetchone()[0])
        wallet_offset=(wallet_page-1)*wallet_page_size
        tx=conn.execute("SELECT id,amount_cents,balance_after_cents,transaction_type,reference_id,created_at FROM wallet_transactions WHERE user_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",(uid,wallet_page_size,wallet_offset)).fetchall()
        scraps=conn.execute("SELECT count(*),count(*) FILTER (WHERE status IN ('active','running')),count(*) FILTER (WHERE status IN ('completed','complete')) FROM scraps WHERE user_id=%s",(uid,)).fetchone()
    return {"user":{"id":str(row[0]),"email":row[1],"country":row[2],"created_at":row[3].isoformat(),"last_login_at":row[4].isoformat() if row[4] else None,"balance_cents":int(row[5])},"wallet_transactions":[{"id":str(r[0]),"amount_cents":int(r[1]),"balance_after_cents":int(r[2]),"transaction_type":r[3],"reference_id":r[4],"created_at":r[5].isoformat()} for r in tx],"wallet_pagination":{"page":wallet_page,"page_size":wallet_page_size,"total":wallet_total,"total_pages":(wallet_total+wallet_page_size-1)//wallet_page_size},"scraps":{"total":int(scraps[0]),"active":int(scraps[1]),"completed":int(scraps[2])}}

@app.get("/admin/users/{user_id}/activity")
def admin_user_activity(user_id: str, req: Request, page: int = 1, page_size: int = 20):
    admin=current_user(req)
    if not _is_admin(admin): raise HTTPException(403,"Admin access required")
    try: uid=uuid.UUID(user_id)
    except ValueError as exc: raise HTTPException(422,"Invalid user id") from exc
    page=max(1,page)
    page_size=max(10,min(page_size,100))
    limit=200
    events=[]
    with db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=%s",(uid,)).fetchone(): raise HTTPException(404,"User not found")
        rows=conn.execute("SELECT created_at,'wallet'::text,'wallet'::text,transaction_type,amount_cents,reference_id FROM wallet_transactions WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",(uid,limit)).fetchall()
        events += [{"timestamp":r[0].isoformat(),"source":"wallet","action":r[3],"module":r[2],"result":"success","metadata":{"amount_cents":int(r[4]),"reference_id":r[5]}} for r in rows]
        rows=conn.execute("SELECT created_at,status,name,id FROM scraps WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",(uid,limit)).fetchall()
        events += [{"timestamp":r[0].isoformat(),"source":"scrap","action":"scrap_"+str(r[1]),"module":"research","result":"success","metadata":{"name":r[2],"scrap_id":str(r[3])}} for r in rows]
        rows=conn.execute("SELECT a.created_at,a.action,a.metadata,u.email FROM support_audit_events a JOIN support_tickets t ON t.id=a.ticket_id LEFT JOIN users u ON u.id=a.actor_id WHERE t.user_id=%s ORDER BY a.created_at DESC LIMIT %s",(uid,limit)).fetchall()
        events += [{"timestamp":r[0].isoformat(),"source":"support","action":r[1],"module":"support","result":"success","metadata":{**(r[2] or {}),"actor_email":r[3]}} for r in rows]
        rows=conn.execute("SELECT created_at,action,module,result,metadata,actor_id FROM admin_audit_events WHERE target_user_id=%s ORDER BY created_at DESC LIMIT %s",(uid,limit)).fetchall()
        events += [{"timestamp":r[0].isoformat(),"source":"admin","action":r[1],"module":r[2],"result":r[3],"metadata":{**(r[4] or {}),"actor_id":str(r[5]) if r[5] else None}} for r in rows]
        rows=conn.execute("SELECT created_at,expires_at,persistent FROM sessions WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",(uid,limit)).fetchall()
        events += [{"timestamp":r[0].isoformat(),"source":"auth","action":"session_created","module":"authentication","result":"success","metadata":{"persistent":bool(r[2]),"expires_at":r[1].isoformat()}} for r in rows]
    events.sort(key=lambda x:x["timestamp"],reverse=True)
    total=len(events)
    start=(page-1)*page_size
    return {"events":events[start:start+page_size],"pagination":{"page":page,"page_size":page_size,"total":total,"total_pages":(total+page_size-1)//page_size}}

@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: str, req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    try: uid=uuid.UUID(user_id)
    except ValueError as exc: raise HTTPException(422,"Invalid user id") from exc
    if uid == uuid.UUID(user["id"]): raise HTTPException(409,"The logged-in admin cannot delete itself")
    with db() as conn:
        row=conn.execute("SELECT email FROM users WHERE id=%s",(uid,)).fetchone()
        if not row: raise HTTPException(404,"User not found")
        _audit(conn,user["id"],"user_deleted","users",None,{"target_user_id":str(uid),"target_email":row[0]})
        conn.execute("DELETE FROM users WHERE id=%s",(uid,))
        conn.commit()
    return {"deleted":True,"email":row[0]}

@app.get("/admin/settings")
def admin_settings(req: Request):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        rows=conn.execute("SELECT key,value FROM app_settings WHERE key IN ('scrap_creation_price_cents','premium_serp_price_cents','paid_enrichment_unit_micros_usd','page_indexer_price_cents','serp_result_limit','research_default_max_leads','research_max_leads','research_timeout_hours')").fetchall()
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
        _audit(conn,user['id'],"research_settings_updated","configuration",None,{"default_max_leads":request.default_max_leads,"max_leads":request.max_leads,"timeout_hours":request.timeout_hours})
        conn.commit()
    return {"default_max_leads":request.default_max_leads,"max_leads":request.max_leads,"timeout_hours":request.timeout_hours}

@app.get("/admin/wallets")
def admin_wallets(req: Request, page: int = 1, page_size: int = 25, search: str = ""):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    page=max(1,page); page_size=max(10,min(page_size,100)); search=search.strip()
    with db() as conn:
        where="WHERE u.email ILIKE %s" if search else ""
        args=(f"%{search}%",) if search else ()
        total=int(conn.execute(f"SELECT count(*) FROM users u JOIN wallets w ON w.user_id=u.id {where}",args).fetchone()[0])
        rows=conn.execute(f"SELECT u.id,u.email,w.balance_cents FROM users u JOIN wallets w ON w.user_id=u.id {where} ORDER BY u.email LIMIT %s OFFSET %s",args+(page_size,(page-1)*page_size)).fetchall()
    return {"wallets":[{"id":str(r[0]),"email":r[1],"balance_cents":int(r[2])} for r in rows],"pagination":{"page":page,"page_size":page_size,"total":total,"total_pages":(total+page_size-1)//page_size}}

@app.post("/admin/wallet-adjust")
def adjust_wallet(request: WalletAdjustmentRequest, req: Request, background_tasks: BackgroundTasks):
    user=current_user(req)
    if not _is_admin(user): raise HTTPException(403,"Admin access required")
    with db() as conn:
        row=conn.execute("SELECT id,email FROM users WHERE email=%s",(request.user_email.lower().strip(),)).fetchone()
        if not row: raise HTTPException(404,"User not found")
        uid,customer_email=row
        balance=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone()[0]
        new_balance=int(balance)+request.amount_cents
        if new_balance < 0: raise HTTPException(422,"Wallet balance cannot become negative")
        conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s",(new_balance,uid))
        conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type) VALUES(%s,%s,%s,%s,'admin_adjustment')",(uuid.uuid4(),uid,request.amount_cents,new_balance))
        _audit(conn,user["id"],"wallet_adjustment","billing",uid,{"amount_cents":request.amount_cents,"balance_after_cents":new_balance,"reason":request.reason})
        conn.commit()
    background_tasks.add_task(_send_wallet_adjustment_email,customer_email,request.amount_cents,request.reason,new_balance)
    return {"balance_cents":new_balance}

@app.get("/scraps/current")
def current_scrap(req: Request):
    user=current_user(req)
    with db() as conn:
        row=conn.execute("SELECT id,name,status,criteria,crawler_config FROM scraps WHERE user_id=%s AND status IN ('active','running') ORDER BY created_at DESC LIMIT 1",(uuid.UUID(user["id"]),)).fetchone()
        if not row: return None
        sid=uuid.UUID(str(row[0]))
        counts=conn.execute("SELECT (SELECT count(*) FROM serp_results WHERE scrap_id=%s),(SELECT count(*) FROM url_occurrences WHERE scrap_id=%s),(SELECT count(*) FROM leads WHERE scrap_id=%s),(SELECT count(DISTINCT l.id) FROM leads l JOIN lead_sources ls ON ls.lead_id=l.id JOIN evidence e ON e.id=ls.evidence_id WHERE l.scrap_id=%s AND e.source_type='page_indexer' AND NULLIF(trim(l.data->>'email'),'') IS NOT NULL)",(sid,sid,sid,sid)).fetchone()
        serp_limit=_serp_limit(conn)
    return {"id":str(row[0]),"name":row[1],"status":row[2],"criteria":row[3],"crawler":row[4],"counts":{"serp_results":int(counts[0]),"url_occurrences":int(counts[1]),"leads":int(counts[2]),"email_indexed":int(counts[3])},"serp_limit":serp_limit}

@app.post("/scraps/{scrap_id}/complete-submission")
def complete_submission(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    with db() as conn:
        row=conn.execute("SELECT status FROM scraps WHERE id=%s AND user_id=%s FOR UPDATE",(sid,uuid.UUID(user["id"]))).fetchone()
        if not row: raise HTTPException(404,"Scrap not found")
        if row[0] not in ('active','running'): raise HTTPException(409,"Scrap is already closed")
        conn.execute("UPDATE scraps SET status='submitted',completed_at=now() WHERE id=%s",(sid,)); conn.commit()
    return {"scrap_id":scrap_id,"status":"submitted"}

@app.post("/scraps/{scrap_id}/cancel")
def cancel_scrap(scrap_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id); uid=uuid.UUID(user["id"])
    canceled_jobs=[]
    with db() as conn:
        row=conn.execute("SELECT status FROM scraps WHERE id=%s AND user_id=%s FOR UPDATE",(sid,uid)).fetchone()
        if not row: raise HTTPException(404,"Scrap not found")
        if row[0] == "canceled": return {"scrap_id":scrap_id,"status":"canceled"}
        if row[0] not in ("active","running"): raise HTTPException(409,"Only an active Current Scrap can be canceled")
        jobs=conn.execute("SELECT id FROM jobs WHERE scrap_id=%s AND status IN ('queued','running')",(sid,)).fetchall()
        for (jid,) in jobs:
            CANCEL_FLAGS.add(str(jid)); canceled_jobs.append(str(jid))
            conn.execute("UPDATE jobs SET status='canceled',stage='Canceled',result=result || %s,updated_at=now() WHERE id=%s",(Jsonb({"message":"Scrap canceled by user"}),jid))
        conn.execute("UPDATE scraps SET status='canceled',completed_at=now() WHERE id=%s",(sid,))
        conn.execute("DELETE FROM serp_sessions WHERE scrap_id=%s",(sid,))
        conn.commit()
    return {"scrap_id":scrap_id,"status":"canceled","canceled_jobs":canceled_jobs}


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
        rows=conn.execute("SELECT id,data,status,approved_at,created_at FROM leads WHERE scrap_id=%s ORDER BY created_at DESC",(uuid.UUID(scrap_id),)).fetchall()
    return [{"id":str(r[0]),"data":r[1],"status":r[2],"approved_at":r[3].isoformat() if r[3] else None,"created_at":r[4].isoformat()} for r in rows]

class WorkstationLeadUpdate(BaseModel):
    data: dict


class WorkstationLeadSelection(BaseModel):
    lead_ids: list[str] = Field(default_factory=list)


@app.get("/scraps/{scrap_id}/workstation")
def lead_workstation(scrap_id: str, req: Request):
    user = current_user(req)
    sid = uuid.UUID(scrap_id)
    with db() as conn:
        owned = conn.execute("SELECT id,name,status FROM scraps WHERE id=%s AND user_id=%s", (sid, uuid.UUID(user["id"]))).fetchone()
        if not owned:
            raise HTTPException(404, "Scrap not found")
        rows = conn.execute(
            "SELECT id,data,status,approved_at,approved_by,created_at FROM leads WHERE scrap_id=%s ORDER BY created_at,id",
            (sid,),
        ).fetchall()
        source_rows = conn.execute(
            "SELECT ls.lead_id,e.id,e.source_type,e.data,e.created_at "
            "FROM lead_sources ls JOIN evidence e ON e.id=ls.evidence_id "
            "WHERE ls.lead_id = ANY(%s) ORDER BY e.created_at DESC",
            ([row[0] for row in rows],),
        ).fetchall() if rows else []
    sources_by_lead = {}
    for row in source_rows:
        sources_by_lead.setdefault(str(row[0]), []).append({
            "id": str(row[1]), "source_type": row[2], "data": row[3],
            "created_at": row[4].isoformat(),
        })
    leads = [
        {"id": str(row[0]), "data": row[1], "status": row[2], "approved_at": row[3].isoformat() if row[3] else None,
         "approved_by": str(row[4]) if row[4] else None, "created_at": row[5].isoformat(),
         "sources": sources_by_lead.get(str(row[0]), [])}
        for row in rows
    ]
    return {
        "scrap": {"id": str(owned[0]), "name": owned[1], "status": owned[2]},
        "leads": leads,
        "counts": {"total": len(leads), "working": sum(x["status"] == "working" for x in leads), "completed": sum(x["status"] == "completed" for x in leads)},
    }


@app.patch("/scraps/{scrap_id}/leads/{lead_id}")
def update_workstation_lead(scrap_id: str, lead_id: str, request: WorkstationLeadUpdate, req: Request):
    user = current_user(req)
    sid = uuid.UUID(scrap_id); lid = uuid.UUID(lead_id); uid = uuid.UUID(user["id"])
    with db() as conn:
        row = conn.execute(
            "SELECT l.data,l.status FROM leads l JOIN scraps s ON s.id=l.scrap_id WHERE l.id=%s AND l.scrap_id=%s AND s.user_id=%s",
            (lid, sid, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Lead not found")
        if row[1] == "completed":
            raise HTTPException(409, "Completed Leads cannot be edited")
        data = dict(request.data or {})
        data.pop("status", None); data.pop("approved_at", None); data.pop("approved_by", None); data.pop("id", None); data.pop("created_at", None)
        prefixes, _ = get_client_policies(str(uid))
        try:
            lead = Lead.model_validate(data, context={"generic_prefixes": prefixes})
        except Exception as exc:
            raise HTTPException(422, f"Invalid Lead data: {exc}") from exc
        clean = jsonable_encoder(lead.model_dump())
        conn.execute("UPDATE leads SET data=%s WHERE id=%s AND scrap_id=%s", (Jsonb(clean), lid, sid))
        conn.commit()
    return {"id": lead_id, "data": clean, "status": "working"}


@app.delete("/scraps/{scrap_id}/leads/{lead_id}", status_code=204)
def delete_workstation_lead(scrap_id: str, lead_id: str, req: Request):
    user = current_user(req)
    sid = uuid.UUID(scrap_id); lid = uuid.UUID(lead_id)
    with db() as conn:
        owned = conn.execute(
            "SELECT 1 FROM leads l JOIN scraps s ON s.id=l.scrap_id WHERE l.id=%s AND l.scrap_id=%s AND s.user_id=%s",
            (lid, sid, uuid.UUID(user["id"])),
        ).fetchone()
        if not owned:
            raise HTTPException(404, "Lead not found")
        conn.execute("DELETE FROM leads WHERE id=%s AND scrap_id=%s", (lid, sid)); conn.commit()


@app.post("/scraps/{scrap_id}/leads/{lead_id}/approve")
def approve_workstation_lead(scrap_id: str, lead_id: str, req: Request):
    user = current_user(req)
    sid = uuid.UUID(scrap_id); lid = uuid.UUID(lead_id); uid = uuid.UUID(user["id"])
    with db() as conn:
        row = conn.execute(
            "SELECT l.status FROM leads l JOIN scraps s ON s.id=l.scrap_id WHERE l.id=%s AND l.scrap_id=%s AND s.user_id=%s",
            (lid, sid, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Lead not found")
        if row[0] == "completed":
            return {"id": lead_id, "status": "completed"}
        conn.execute("UPDATE leads SET status='completed',approved_at=now(),approved_by=%s WHERE id=%s AND scrap_id=%s", (uid, lid, sid)); conn.commit()
    return {"id": lead_id, "status": "completed"}


@app.post("/scraps/{scrap_id}/leads/approve")
def approve_workstation_leads(scrap_id: str, request: WorkstationLeadSelection, req: Request):
    user = current_user(req); sid = uuid.UUID(scrap_id); uid = uuid.UUID(user["id"])
    lead_ids = [uuid.UUID(value) for value in request.lead_ids]
    if not lead_ids:
        raise HTTPException(422, "Select at least one Lead")
    with db() as conn:
        owned = conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s", (sid, uid)).fetchone()
        if not owned:
            raise HTTPException(404, "Scrap not found")
        conn.execute("UPDATE leads SET status='completed',approved_at=now(),approved_by=%s WHERE scrap_id=%s AND id=ANY(%s) AND status='working'", (uid, sid, lead_ids))
        conn.commit()
    return {"approved": len(lead_ids)}


@app.post("/scraps/{scrap_id}/enrich", status_code=202)
async def enrich_scrap(scrap_id: str, background_tasks: BackgroundTasks, req: Request, request: EnrichmentRequest, mode: Literal["paid"] = "paid"):
    user = current_user(req)
    sid = uuid.UUID(scrap_id)
    with db() as conn:
        owned = conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s", (sid, uuid.UUID(user["id"]))).fetchone()
        if not owned:
            raise HTTPException(404, "Scrap not found")
        running = conn.execute(
            "SELECT 1 FROM jobs WHERE scrap_id=%s AND status IN ('queued','running') LIMIT 1",
            (sid,),
        ).fetchone()
        if running:
            raise HTTPException(409, "A research or enrichment job is already running for this Scrap")
        if mode == "paid":
            unit_row = conn.execute("SELECT value #>> '{}' FROM app_settings WHERE key='paid_enrichment_unit_micros_usd'").fetchone()
            if not unit_row or unit_row[0] is None:
                raise HTTPException(409, "Paid enrichment pricing is not configured")
            if not os.getenv("GROQ_API_KEY", "").strip():
                raise HTTPException(409, "Paid enrichment is not configured")
        try:
            selected_ids = [uuid.UUID(x) for x in request.lead_ids]
        except ValueError as exc:
            raise HTTPException(422, "Invalid Lead ID") from exc
        lead_rows = conn.execute("SELECT id FROM leads WHERE scrap_id=%s AND status='working' AND id=ANY(%s) ORDER BY created_at,id", (sid, selected_ids)).fetchall()
        if len(lead_rows) != len(set(selected_ids)):
            raise HTTPException(409, "One or more selected Leads are no longer available for enrichment")
        if not lead_rows:
            raise HTTPException(409, "No working Leads selected for enrichment")
        job_id = uuid.uuid4().hex
        charged_cents = 0
        if mode == "paid":
            unit_micros = int(unit_row[0])
            charged_cents = max(1, math.ceil(unit_micros * len(lead_rows) / 10000))
            wallet = conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE", (uuid.UUID(user["id"]),)).fetchone()
            if not wallet:
                raise HTTPException(500, "Wallet not initialized")
            if int(wallet[0]) < charged_cents:
                raise HTTPException(402, f"Insufficient wallet balance for Paid Enrichment: ${charged_cents / 100:.2f} required")
            balance_after = int(wallet[0]) - charged_cents
            conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s", (balance_after, uuid.UUID(user["id"])))
            conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'paid_enrichment',%s)", (uuid.uuid4(), uuid.UUID(user["id"]), -charged_cents, balance_after, job_id))
        conn.execute(
            "INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,'queued','Queued',%s,%s)",
            (uuid.UUID(job_id), sid, Jsonb({"type": f"{mode}_enrichment", "lead_count": len(lead_rows), "lead_ids": [str(x[0]) for x in lead_rows], "charged_cents": charged_cents, "discover_new_leads": bool(request.discover_new_leads)}), Jsonb({"message": f"{mode.title()} enrichment queued", "counts": {}, "events": []})),
        )
        conn.commit()
    background_tasks.add_task(_run_enrich_scrap_job, job_id, scrap_id, mode, [str(x[0]) for x in lead_rows], request.discover_new_leads)
    return {"job_id": job_id, "status": "queued", "mode": mode, "lead_count": len(lead_rows), "charged_cents": charged_cents, "discover_new_leads": bool(request.discover_new_leads)}


@app.post("/scraps/{scrap_id}/leads/{lead_id}/enrich", status_code=410)
async def enrich_lead(scrap_id: str, lead_id: str, background_tasks: BackgroundTasks, req: Request):
    raise HTTPException(410, "Single-lead enrichment is retired. Use Paid Enrichment from the Lead Workstation.")


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
    max_queries: int=Field(default=0, ge=0)
    scrap_id: str|None=None

class SerpSessionRequest(BaseModel):
    scrap_id: str|None=None
    ttl_seconds: int=Field(default=SERP_SESSION_TTL,ge=60,le=86400)

class PageIndexerRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    html: str = Field(min_length=1, max_length=1500000)
    title: str = Field(default="", max_length=1000)
    auto: bool = False
    email_only: bool = True


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


def _page_indexer_eligible(url: str, html: str, title: str) -> bool:
    parsed=urlparse(url)
    if parsed.scheme not in ("http","https") or not parsed.netloc:
        return False
    host=(parsed.hostname or "").casefold()
    if host == "scrapee.uk" or host.endswith(".scrapee.uk") or "google." in host or "bing." in host:
        return False
    text=(title+" "+html[:500000]).casefold()
    if re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",text,re.I):
        return True
    if re.search(r"(?:mailto:|tel:|contact|team|staff|employee|leadership|management|director|manager|founder|ceo|owner|partner|sales|business development)",text,re.I):
        return True
    return False


def _page_indexer_evidence(scrap_id, url: str, html: str):
    evidence=EvidenceBuilder().build(url=url,html=html)
    evidence_id=uuid.uuid4()
    with db() as conn:
        conn.execute("INSERT INTO evidence(id,scrap_id,source_type,source_id,data) VALUES(%s,%s,'page_indexer',NULL,%s)",(evidence_id,uuid.UUID(str(scrap_id)),Jsonb(evidence.model_dump(mode="json"))))
        conn.commit()
    return evidence,evidence_id


@app.get("/page-indexer/usage")
def page_indexer_usage(req: Request):
    user=current_user(req); uid=uuid.UUID(user["id"])
    with db() as conn:
        row=conn.execute("SELECT COUNT(*),COALESCE(SUM(charged_cents),0),COALESCE(SUM(leads_count),0) FROM page_indexer_jobs WHERE user_id=%s AND status='completed'",(uid,)).fetchone()
        recent=conn.execute("SELECT url,leads_count,charged_cents,created_at FROM page_indexer_jobs WHERE user_id=%s AND status='completed' ORDER BY created_at DESC LIMIT 10",(uid,)).fetchall()
    return {"pages":int(row[0]),"charged_cents":int(row[1]),"leads":int(row[2]),"recent":[{"url":r[0],"leads":int(r[1]),"charged_cents":int(r[2]),"created_at":r[3].isoformat()} for r in recent]}


@app.get("/page-indexer/leads")
def page_indexer_leads(req: Request, job_id: str | None = None, url: str | None = None, email_only: bool = True):
    user=current_user(req); uid=uuid.UUID(user["id"])
    with db() as conn:
        if job_id:
            try: jid=uuid.UUID(job_id)
            except ValueError as exc: raise HTTPException(422,"Invalid page-indexer job id") from exc
            job=conn.execute("SELECT id,scrap_id,url,status,leads_count,charged_cents,result,created_at FROM page_indexer_jobs WHERE id=%s AND user_id=%s",(jid,uid)).fetchone()
        elif url:
            job=conn.execute("SELECT id,scrap_id,url,status,leads_count,charged_cents,result,created_at FROM page_indexer_jobs WHERE user_id=%s AND url=%s AND status='completed' ORDER BY created_at DESC LIMIT 1",(uid,url.strip())).fetchone()
        else:
            job=conn.execute("SELECT id,scrap_id,url,status,leads_count,charged_cents,result,created_at FROM page_indexer_jobs WHERE user_id=%s AND status='completed' ORDER BY created_at DESC LIMIT 1",(uid,)).fetchone()
        if not job: raise HTTPException(404,"Page indexer job not found")
        rows=conn.execute("SELECT data FROM leads WHERE scrap_id=%s AND data->>'source_url'=%s ORDER BY created_at DESC LIMIT 100",(job[1],job[2])).fetchall()
    leads=[r[0] for r in rows]
    if email_only:
        leads=[lead for lead in leads if lead.get("email") and is_personal_email(str(lead.get("email")), None)]
    return {"job_id":str(job[0]),"scrap_id":str(job[1]),"url":job[2],"status":job[3],"leads":len(leads),"charged_cents":int(job[5]),"result":job[6] or {},"created_at":job[7].isoformat(),"lead_preview":leads}


@app.post("/page-indexer/process")
def process_page_index(request: PageIndexerRequest, req: Request):
    user=current_user(req); uid=uuid.UUID(user["id"])
    url=request.url.strip()
    if not _page_indexer_eligible(url,request.html,request.title):
        return {"ok":True,"eligible":False,"charged_cents":0,"leads":0,"message":"Page discarded by eligibility gate."}
    with db() as conn:
        scrap=conn.execute("SELECT id,status,criteria FROM scraps WHERE user_id=%s AND status IN ('active','running') ORDER BY created_at DESC LIMIT 1",(uid,)).fetchone()
        if not scrap: raise HTTPException(409,"No active Current Scrap")
        scrap_id,scrap_status,scrap_criteria=scrap
    fingerprint=hashlib.sha256((url+"\n"+hashlib.sha256(request.html.encode('utf-8',errors='ignore')).hexdigest()).encode()).hexdigest()
    with db() as conn:
        existing=conn.execute("SELECT id,status,leads_count,charged_cents,result FROM page_indexer_jobs WHERE user_id=%s AND scrap_id=%s AND fingerprint=%s",(uid,scrap_id,fingerprint)).fetchone()
        if existing and existing[1]=='completed':
            result=existing[4] or {}
            return {"ok":True,"eligible":True,"duplicate":True,"job_id":str(existing[0]),"charged_cents":0,"leads":int(existing[2]),"result":result}
        price=int(conn.execute("SELECT (value #>> '{}')::bigint FROM app_settings WHERE key='page_indexer_price_cents'").fetchone()[0])
        wallet=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone()
        if not wallet or int(wallet[0]) < price: raise HTTPException(402,f"Insufficient balance. Page Lead Indexer costs ${price/100:.2f} per page")
        job_id=existing[0] if existing else uuid.uuid4()
        balance_after=int(wallet[0])-price
        conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s",(balance_after,uid))
        conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'page_indexer',%s)",(uuid.uuid4(),uid,-price,balance_after,str(job_id)+':'+str(uuid.uuid4())))
        conn.execute("INSERT INTO page_indexer_jobs(id,user_id,scrap_id,url,fingerprint,status,charged_cents,leads_count,result,error,updated_at) VALUES(%s,%s,%s,%s,%s,'processing',%s,0,'{}',NULL,now()) ON CONFLICT(user_id,scrap_id,fingerprint) DO UPDATE SET scrap_id=EXCLUDED.scrap_id,url=EXCLUDED.url,status='processing',charged_cents=EXCLUDED.charged_cents,leads_count=0,result='{}',error=NULL,updated_at=now()",(job_id,uid,scrap_id,url,fingerprint,price))
        conn.commit()
    try:
        criteria=SearchCriteria.model_validate(scrap_criteria or {})
        prefixes,rules=get_client_policies(user["id"])
        evidence,evidence_id=_page_indexer_evidence(scrap_id,url,request.html)
        extractor=AdaptiveLeadExtractor(generic_prefixes=prefixes)
        extracted=asyncio.run(extractor.extract(request.html,url,evidence=evidence))
        if request.email_only:
            extracted=[lead for lead in extracted if lead.email and is_personal_email(str(lead.email), prefixes)]
        qualified=[]
        qualifier=LeadQualifier()
        for lead in extracted:
            geo=_PAGE_GEOGRAPHY.classify(city=lead.city,state=lead.state,country=lead.country)
            lead=lead.model_copy(update={"city":geo.get("city"),"state":geo.get("state"),"country":geo.get("country")})
            if qualifier.qualify(lead,criteria).relevant:
                qualified.append(lead)
        final=exclude_existing(scrap_id, dedupe(qualified))
        persisted=0
        for lead in final:
            if persist_lead(scrap_id,lead,evidence_id=evidence_id): persisted+=1
        result={"url":url,"extracted":len(extracted),"qualified":len(qualified),"leads":len(final),"persisted":persisted,"charged_cents":price,"email_only":request.email_only,"lead_preview":[lead.model_dump(mode="json") for lead in final[:20]]}
        with db() as conn:
            conn.execute("UPDATE page_indexer_jobs SET status='completed',leads_count=%s,result=%s,error=NULL,updated_at=now() WHERE id=%s",(len(final),Jsonb(result),job_id)); conn.commit()
        return {"ok":True,"eligible":True,"duplicate":bool(qualified) and not final,"job_id":str(job_id),**result}
    except Exception as exc:
        with db() as conn:
            wallet=conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE",(uid,)).fetchone(); new_balance=int(wallet[0])+price
            conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s",(new_balance,uid))
            conn.execute("INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'page_indexer_refund',%s)",(uuid.uuid4(),uid,price,new_balance,str(job_id)+':refund:'+str(uuid.uuid4())))
            conn.execute("UPDATE page_indexer_jobs SET status='refunded',charged_cents=0,error=%s,updated_at=now() WHERE id=%s",(str(exc),job_id)); conn.commit()
        raise HTTPException(502,f"Page Lead Indexer failed; charge refunded: {exc}") from exc


@app.post("/serp/sync")
def sync_serp(request: SerpSyncRequest, req: Request):
    user=current_user(req)
    scrap_id=req.headers.get("X-Scrap-Id")
    if not scrap_id:
        scrap_id=current_scrap(req)["id"]
    with db() as conn:
        owned=conn.execute("SELECT status FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(403,"Scrap does not belong to this user")
        if owned[0] not in ("active","running"): raise HTTPException(409,"Scrap is no longer active")
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


@app.post("/scraps/{scrap_id}/exports/generate/{fmt}")
def generate_scrap_export(scrap_id: str, fmt: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    if fmt not in ("csv", "xlsx"):
        raise HTTPException(400, "Export format must be csv or xlsx")
    with db() as conn:
        owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s", (sid, uuid.UUID(user["id"]))).fetchone()
        if not owned: raise HTTPException(404, "Scrap not found")
        rows=conn.execute("SELECT data FROM leads WHERE scrap_id=%s ORDER BY created_at,id", (sid,)).fetchall()
    leads=[Lead.model_construct(**(row[0] or {})) for row in rows]
    export_id=uuid.uuid4()
    output=_write_export(leads, export_id.hex, fmt)
    with db() as conn:
        conn.execute("INSERT INTO exports(id,scrap_id,format,location) VALUES(%s,%s,%s,%s)", (export_id,sid,fmt,output))
        conn.commit()
    return {"id":str(export_id),"scrap_id":scrap_id,"format":fmt,"location":output,"lead_count":len(leads),"download_url":f"/scraps/{scrap_id}/exports/{export_id}/download"}


@app.post("/search/parameters")
def search_parameters(request: SearchParameterRequest, req: Request):
    user=current_user(req) if request.scrap_id else None
    with db() as conn:
        from src.search.provider_google import GoogleQueryAdapter
        from src.search.provider_bing import BingQueryAdapter
        engine=SearchTemplateEngine(conn, {"google":GoogleQueryAdapter(), "bing":BingQueryAdapter()})
        params=engine.generate(request.criteria,request.max_queries)
        if request.scrap_id:
            owned=conn.execute("SELECT 1 FROM scraps WHERE id=%s AND user_id=%s",(uuid.UUID(request.scrap_id),uuid.UUID(user["id"]))).fetchone()
            if not owned: raise HTTPException(404,"Scrap not found")
            conn.execute("DELETE FROM search_parameters WHERE scrap_id=%s",(uuid.UUID(request.scrap_id),))
            for position,item in enumerate(params):
                conn.execute("INSERT INTO search_parameters(id,scrap_id,parameter_id,provider,query,url,family,position,category,template_id,variables,status,completed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',NULL)",(uuid.uuid4(),uuid.UUID(request.scrap_id),item.id,item.provider,item.query,item.url,item.family,position,item.category,uuid.UUID(item.template_id),Jsonb(item.variables)))
            conn.commit()
    return {"parameters":[p.__dict__ for p in params]}

@app.get("/scraps/{scrap_id}/search-parameters")
def scrap_search_parameters(scrap_id: str, req: Request):
    user=current_user(req)
    with db() as conn:
        rows=conn.execute("SELECT p.parameter_id,p.provider,p.query,p.url,p.family,p.category,p.template_id,p.variables,p.status,p.completed_at FROM search_parameters p LEFT JOIN search_template_categories c ON c.name=p.category WHERE p.scrap_id=%s AND EXISTS (SELECT 1 FROM scraps WHERE id=%s AND user_id=%s) ORDER BY COALESCE(c.position,999999),p.position",(uuid.UUID(scrap_id),uuid.UUID(scrap_id),uuid.UUID(user["id"]))).fetchall()
    return [{"id":r[0],"provider":r[1],"query":r[2],"url":r[3],"family":r[4],"category":r[5],"template_id":str(r[6]) if r[6] else None,"variables":r[7],"status":r[8],"completed_at":r[9].isoformat() if r[9] else None} for r in rows]

@app.post("/scraps/{scrap_id}/search-parameters/{parameter_id}/complete")
def complete_search_parameter(scrap_id: str, parameter_id: str, req: Request):
    user=current_user(req); sid=uuid.UUID(scrap_id)
    with db() as conn:
        row=conn.execute("SELECT status FROM search_parameters WHERE scrap_id=%s AND parameter_id=%s AND EXISTS (SELECT 1 FROM scraps WHERE id=%s AND user_id=%s)",(sid,parameter_id,sid,uuid.UUID(user["id"]))).fetchone()
        if not row: raise HTTPException(404,"Search parameter not found")
        conn.execute("UPDATE search_parameters SET status='completed',completed_at=now() WHERE scrap_id=%s AND parameter_id=%s",(sid,parameter_id))
        completed_at=conn.execute("SELECT completed_at FROM search_parameters WHERE scrap_id=%s AND parameter_id=%s",(sid,parameter_id)).fetchone()[0]
        conn.commit()
    return {"scrap_id":scrap_id,"parameter_id":parameter_id,"status":"completed","completed_at":completed_at.isoformat()}

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


_SERP_LEAD_PROCESS_LOCK = threading.Lock()

def _process_serp_leads_background(scrap_id: str, records: list[dict]):
    # SERP imports can arrive faster than contextual lead extraction completes.
    # Keep this expensive pipeline single-flight so multiple concurrent requests
    # cannot instantiate duplicate extractor/model state and exhaust API memory.
    with _SERP_LEAD_PROCESS_LOCK:
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
            sets.append(f"{key}=%s"); vals.append(Jsonb(jsonable_encoder(value)) if key in ("payload","result") else value)
        sets.append("updated_at=now()"); vals.append(uuid.UUID(job_id))
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=%s",vals); conn.commit()

def _event_callback(job_id):
    def on_event(event):
        job=JOBS.get(job_id,{"counts":{},"events":[]})
        if job_id in CANCEL_FLAGS:
            return
        job["stage"]=event.stage; job["message"]=event.message
        if event.stage != "Telemetry":
            if event.stage == "Leads" and event.message == "Paid enrichment result":
                job["counts"]["_current_leads_enriched"] = int(event.counts.get("leads_enriched", 0))
                job["counts"]["_current_new_leads"] = int(event.counts.get("new_leads", 0))
                job["counts"]["fields_changed"] = int(job["counts"].get("fields_changed", 0)) + int(event.counts.get("fields_changed", 0))
            else:
                job["counts"].update(event.counts)
        job["events"].append(event.__dict__); job["events"]=job["events"][-250:]
        JOBS[job_id]=job
        _persist_job(job_id,status="running",stage=event.stage,result={"counts":job["counts"],"message":event.message,"events":job["events"],"lead_count":job["counts"].get("leads",job.get("lead_count",0))})
    return on_event

def _job_from_row(row):
    job_id,status,stage,payload,result,created_at,updated_at=row
    result=result or {}; payload=payload or {}
    return {"job_id":str(job_id),"status":status,"stage":stage,"payload":payload,"message":result.get("message", ""),"counts":result.get("counts",{}),"events":result.get("events",[]),"lead_count":result.get("lead_count",0),"export_format":payload.get("export_format","csv"),"output":result.get("output"),"error":result.get("error"),"created_at":created_at.isoformat() if created_at else None,"updated_at":updated_at.isoformat() if updated_at else None}

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
        snapshot=JOBS[job_id]
        _persist_job(job_id,status="running",stage="Export",result={"message":"Export generated; completing research","lead_count":len(leads),"output":result,"counts":snapshot.get("counts",{}),"events":snapshot.get("events",[])})
        if job_id in CANCEL_FLAGS:
            return
        JOBS[job_id].update(status="completed",lead_count=len(leads),output=result)
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

def _mark_enrichment_provider_called(job_id):
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET payload = jsonb_set(COALESCE(payload,'{}'::jsonb), '{provider_called}', 'true'::jsonb, true) WHERE id=%s",
            (uuid.UUID(job_id),),
        )
        conn.commit()


def _refund_enrichment_if_provider_not_called(job_id, scrap_id):
    sid = uuid.UUID(scrap_id)
    with db() as conn:
        row = conn.execute(
            "SELECT s.user_id,j.payload FROM jobs j JOIN scraps s ON s.id=j.scrap_id WHERE j.id=%s FOR UPDATE",
            (uuid.UUID(job_id),),
        ).fetchone()
        if not row:
            return False
        user_id, payload = row
        payload = payload or {}
        if payload.get("provider_called") or payload.get("refund_applied"):
            return False
        charged_cents = int(payload.get("charged_cents") or 0)
        if charged_cents <= 0:
            return False
        wallet = conn.execute("SELECT balance_cents FROM wallets WHERE user_id=%s FOR UPDATE", (user_id,)).fetchone()
        if not wallet:
            return False
        new_balance = int(wallet[0]) + charged_cents
        conn.execute("UPDATE wallets SET balance_cents=%s,updated_at=now() WHERE user_id=%s", (new_balance, user_id))
        conn.execute(
            "INSERT INTO wallet_transactions(id,user_id,amount_cents,balance_after_cents,transaction_type,reference_id) VALUES(%s,%s,%s,%s,'paid_enrichment_no_provider',%s)",
            (uuid.uuid4(), user_id, charged_cents, new_balance, job_id),
        )
        payload["refund_applied"] = True
        conn.execute("UPDATE jobs SET payload=%s WHERE id=%s", (Jsonb(payload), uuid.UUID(job_id)))
        conn.commit()
        return True


def _run_enrich_scrap_job(job_id, scrap_id, mode, lead_ids, discover_new_leads=False):
    try:
        sid = uuid.UUID(scrap_id)
        with db() as conn:
            row = conn.execute(
                "SELECT s.user_id,s.criteria,s.crawler_config FROM scraps s WHERE s.id=%s",
                (sid,),
            ).fetchone()
            lead_rows = conn.execute(
                "SELECT id,data FROM leads WHERE scrap_id=%s AND status='working' AND id=ANY(%s) ORDER BY created_at,id",
                (sid, [uuid.UUID(x) for x in lead_ids]),
            ).fetchall()
        if not row:
            raise RuntimeError("Scrap not found")
        user_id, raw_criteria, raw_crawler = row
        criteria = SearchCriteria.model_validate(raw_criteria or {})
        crawler = CrawlerConfig.model_validate(raw_crawler or {})
        prefixes, rules = get_client_policies(str(user_id))
        JOBS[job_id] = {
            "job_id": job_id, "status": "running", "stage": "Starting",
            "message": f"{mode.title()} enrichment started", "counts": {
                "leads_seeded": len(lead_rows), "leads_discovered": 0, "leads_enriched": 0,
                "evidence": 0, "pages_collected": 0,
                "firecrawl_search_requests": 0, "firecrawl_scrape_requests": 0,
                "firecrawl_pages_collected": 0, "firecrawl_estimated_credits": 0,
                "llm_calls": 0, "llm_input_tokens": 0, "llm_output_tokens": 0,
                "llm_reasoning_tokens": 0, "llm_cost_usd": 0.0,
            }, "events": [], "lead_count": 0,
        }
        _persist_job(job_id, status="running", stage="Starting", result={"message": f"{mode.title()} enrichment started", "counts": JOBS[job_id]["counts"], "events": []})
        sink = JobEventSink(_event_callback(job_id))
        pipeline = LeadDiscoveryPipeline(
            crawler_config=crawler,
            generic_prefixes=prefixes,
            domain_rules=rules,
            llm_call_counter=lambda: _increment_llm_calls(scrap_id),
        )
        all_results = []
        for index, lead_row in enumerate(lead_rows, 1):
            if job_id in CANCEL_FLAGS:
                break
            lead = Lead.model_construct(**(lead_row[1] or {}))
            emit_event(sink, "Enrichment", f"Processing lead {index}/{len(lead_rows)}", lead_id=str(lead_row[0]), mode=mode)
            if mode == "paid":
                results, firecrawl_usage, llm_usage = asyncio.run(pipeline.enrich_lead_paid(criteria, lead, event_sink=sink, scrap_id=scrap_id, cancel_check=lambda: job_id in CANCEL_FLAGS, provider_started=lambda: _mark_enrichment_provider_called(job_id), discover_new_leads=discover_new_leads))
                counts = JOBS[job_id]["counts"]
                counts["firecrawl_search_requests"] += int(firecrawl_usage.get("search_requests", 0))
                counts["firecrawl_scrape_requests"] += int(firecrawl_usage.get("scrape_requests", 0))
                counts["firecrawl_pages_collected"] += int(firecrawl_usage.get("pages_collected", 0))
                counts["firecrawl_estimated_credits"] += int(firecrawl_usage.get("estimated_credits", 0))
                counts["llm_calls"] += int(llm_usage.get("calls", 0))
                counts["llm_input_tokens"] += int(llm_usage.get("input_tokens", 0))
                counts["llm_output_tokens"] += int(llm_usage.get("output_tokens", 0))
                counts["llm_reasoning_tokens"] += int(llm_usage.get("reasoning_tokens", 0))
                counts["llm_cost_usd"] += float(llm_usage.get("cost_usd", 0.0))
                counts["leads_enriched"] += int(counts.get("_current_leads_enriched", 0))
                counts["leads_discovered"] += int(counts.get("_current_new_leads", 0))
                counts.pop("_current_leads_enriched", None); counts.pop("_current_new_leads", None)
            else:
                results = asyncio.run(pipeline.enrich_lead(criteria, lead, event_sink=sink, scrap_id=scrap_id, cancel_check=lambda: job_id in CANCEL_FLAGS))
            all_results.extend(results)
            JOBS[job_id]["lead_count"] = JOBS[job_id]["counts"].get("leads_enriched", 0) + JOBS[job_id]["counts"].get("leads_discovered", 0)
            _persist_job(job_id, status="running", stage="Enrichment", result={"message": f"{mode.title()} enrichment running", "counts": JOBS[job_id]["counts"], "events": JOBS[job_id]["events"]})
        status = "canceled" if job_id in CANCEL_FLAGS else "completed"
        JOBS[job_id]["status"] = status
        JOBS[job_id]["stage"] = "Complete" if status == "completed" else "Canceled"
        JOBS[job_id]["message"] = f"{mode.title()} enrichment {status}"
        _persist_job(job_id, status=status, stage=JOBS[job_id]["stage"], result={"message": JOBS[job_id]["message"], "counts": JOBS[job_id]["counts"], "events": JOBS[job_id]["events"], "lead_count": JOBS[job_id]["lead_count"]})
    except Exception as exc:
        if mode == "paid":
            _refund_enrichment_if_provider_not_called(job_id, scrap_id)
        JOBS.setdefault(job_id, {"job_id": job_id, "counts": {}, "events": []})
        JOBS[job_id].update(status="failed", stage="Failed", message=f"{mode.title()} enrichment failed", error=str(exc))
        snapshot = JOBS[job_id]
        _persist_job(job_id, status="failed", stage="Failed", result={"error": str(exc), "message": snapshot.get("message"), "counts": snapshot.get("counts", {}), "events": snapshot.get("events", [])})


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
        snapshot=JOBS[job_id]
        _persist_job(job_id,status="running",stage="Finalizing",result={"message":"Lead set returned; finalizing research","lead_count":len(leads),"counts":snapshot.get("counts",{}),"events":snapshot.get("events",[])})
        if request.export_format=="google_sheets":
            from src.exports.google_sheets import export_google_sheets
            result=export_google_sheets(leads,request.google_spreadsheet_id,worksheet=request.google_worksheet)
        else: result=_write_export(leads,job_id,request.export_format)
        snapshot=JOBS[job_id]
        _persist_job(job_id,status="running",stage="Export",result={"message":"Export generated; completing research","lead_count":len(leads),"output":result,"counts":snapshot.get("counts",{}),"events":snapshot.get("events",[])})
        if job_id in CANCEL_FLAGS:
            return
        JOBS[job_id].update(status="completed",lead_count=len(leads),output=result)
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
    with db() as conn: conn.execute("INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,%s,%s,%s,%s)",(uuid.UUID(job_id),uuid.UUID(request.scrap_id),"queued","Queued",Jsonb(request.model_dump(mode="json")),Jsonb({"message":"Job queued","counts":{},"events":[]})));conn.commit()
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
    request.urls=[str(r.url) for r in request.results]
    job_id=uuid.uuid4().hex; JOBS[job_id]={"job_id":job_id,"status":"queued","stage":"Queued","message":"URL crawl queued","counts":{},"events":[],"lead_count":0,"export_format":request.export_format}
    with db() as conn: conn.execute("INSERT INTO jobs(id,scrap_id,status,stage,payload,result) VALUES(%s,%s,%s,%s,%s,%s)",(uuid.UUID(job_id),uuid.UUID(request.scrap_id),"queued","Queued",Jsonb(request.model_dump(mode="json")),Jsonb({"message":"URL crawl queued","counts":{},"events":[]})));conn.commit()
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
