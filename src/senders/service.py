import os, re, smtplib, ssl, uuid
from email.message import EmailMessage
from cryptography.fernet import Fernet
from src.db import db
from psycopg.types.json import Jsonb

def _fernet():
    key = os.getenv("SCRAPPEE_SENDER_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("SCRAPPEE_SENDER_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode())

def encrypt_secret(value):
    return _fernet().encrypt(value.encode()).decode()

def decrypt_secret(value):
    return _fernet().decrypt(value.encode()).decode()

def sender_dict(row):
    return {
        "id": str(row[0]), "display_name": row[1], "email": row[2],
        "provider": row[3], "enabled": row[4], "health": row[5],
        "created_at": row[6].isoformat(), "updated_at": row[7].isoformat(),
    }

def create_sender(user_id, payload):
    sender_id = uuid.uuid4()
    secret = payload.get("password") or payload.get("app_password")
    encrypted = encrypt_secret(secret) if secret else None
    with db() as conn:
        row = conn.execute("""
            INSERT INTO sender_accounts
            (id,user_id,display_name,email,provider,enabled,health,config,secret_encrypted)
            VALUES(%s,%s,%s,%s,%s,%s,'unknown',%s,%s)
            RETURNING id,display_name,email,provider,enabled,health,created_at,updated_at
        """, (sender_id, user_id, payload["display_name"], payload["email"],
              payload["provider"], payload.get("enabled", True),
              Jsonb(payload.get("config", {})), encrypted)).fetchone()
        conn.commit()
    return sender_dict(row)

def list_senders(user_id):
    with db() as conn:
        rows=conn.execute("""
            SELECT id,display_name,email,provider,enabled,health,created_at,updated_at
            FROM sender_accounts WHERE user_id=%s ORDER BY created_at DESC
        """,(user_id,)).fetchall()
    return [sender_dict(r) for r in rows]

def get_sender(user_id, sender_id):
    with db() as conn:
        return conn.execute("""
            SELECT id,display_name,email,provider,enabled,health,created_at,updated_at,
                   config,secret_encrypted FROM sender_accounts
            WHERE id=%s AND user_id=%s
        """,(sender_id,user_id)).fetchone()

def sender_config(user_id, sender_id):
    row=get_sender(user_id,sender_id)
    if not row: return None
    return {
        "id":str(row[0]), "display_name":row[1], "email":row[2], "provider":row[3],
        "enabled":row[4], "health":row[5], "config":row[8] or {}
    }

def update_sender(user_id, sender_id, payload):
    row=get_sender(user_id,sender_id)
    if not row: return None
    config=Jsonb(payload.get("config", row[8]))
    secret=row[9]
    if payload.get("password") or payload.get("app_password"):
        secret=encrypt_secret(payload.get("password") or payload.get("app_password"))
    fields=["display_name=%s","email=%s","enabled=%s","config=%s","secret_encrypted=%s","updated_at=now()"]
    values=[payload.get("display_name",row[1]),payload.get("email",row[2]),
            payload.get("enabled",row[4]),config,secret]
    values += [sender_id,user_id]
    with db() as conn:
        out=conn.execute(f"""
            UPDATE sender_accounts SET {",".join(fields)}
            WHERE id=%s AND user_id=%s
            RETURNING id,display_name,email,provider,enabled,health,created_at,updated_at
        """,values).fetchone()
        conn.commit()
    return sender_dict(out) if out else None

def delete_sender(user_id, sender_id):
    with db() as conn:
        row=conn.execute("DELETE FROM sender_accounts WHERE id=%s AND user_id=%s RETURNING id",
                         (sender_id,user_id)).fetchone()
        conn.commit()
    return bool(row)
def test_smtp(user_id, sender_id):
    row=get_sender(user_id,sender_id)
    if not row: raise LookupError("Sender not found")
    if row[3] != "smtp": raise ValueError("SMTP test is only available for SMTP senders")
    cfg=row[8] or {}
    secret=decrypt_secret(row[9]) if row[9] else None
    host=cfg.get("host")
    port=int(cfg.get("port",587))
    username=cfg.get("username") or row[2]
    if not host or not secret: raise ValueError("SMTP host and password/app-password are required")
    use_ssl=bool(cfg.get("ssl",False))
    use_tls=bool(cfg.get("tls",not use_ssl))
    context=ssl._create_unverified_context() if bool(cfg.get('allow_self_signed_certificate',True)) else ssl.create_default_context()
    if use_ssl:
        server=smtplib.SMTP_SSL(host,port,context=context,timeout=15)
    else:
        server=smtplib.SMTP(host,port,timeout=15)
    stage="connect"
    try:
        server.ehlo()
        stage="starttls" if use_tls else "authentication"
        if use_tls: server.starttls(context=context); server.ehlo()
        stage="authentication"
        server.login(username,secret)
    except Exception as exc:
        raise RuntimeError(f"SMTP {stage} failed: {exc}") from exc
    finally:
        try:
            server.quit()
        except smtplib.SMTPServerDisconnected:
            pass
    with db() as conn:
        conn.execute("UPDATE sender_accounts SET health='healthy',updated_at=now() WHERE id=%s AND user_id=%s",(sender_id,user_id))
        conn.commit()
    return {"ok":True,"health":"healthy"}

def create_letter(user_id,payload):
    letter_id=uuid.uuid4()
    with db() as conn:
        row=conn.execute("""
            INSERT INTO sender_letters(id,user_id,name,subject,body_text,body_html,variables,active)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id,name,subject,body_text,body_html,variables,active,created_at,updated_at
        """,(letter_id,user_id,payload["name"],payload["subject"],payload["body_text"],
             payload.get("body_html"),Jsonb(payload.get("variables",[])),payload.get("active",True))).fetchone()
        conn.commit()
    return dict(zip(["id","name","subject","body_text","body_html","variables","active","created_at","updated_at"],row))

def list_letters(user_id):
    with db() as conn:
        rows=conn.execute("""
            SELECT id,name,subject,body_text,body_html,variables,active,created_at,updated_at
            FROM sender_letters WHERE user_id=%s ORDER BY created_at DESC
        """,(user_id,)).fetchall()
    return [dict(zip(["id","name","subject","body_text","body_html","variables","active","created_at","updated_at"],r)) for r in rows]

def delete_letter(user_id,letter_id):
    with db() as conn:
        row=conn.execute("DELETE FROM sender_letters WHERE id=%s AND user_id=%s RETURNING id",(letter_id,user_id)).fetchone()
        conn.commit()
    return bool(row)
def available_leads(user_id):
    with db() as conn:
        rows=conn.execute("""
            SELECT l.id,l.scrap_id,l.data,l.status,s.name
            FROM leads l JOIN scraps s ON s.id=l.scrap_id
            WHERE s.user_id=%s AND l.status='completed'
            ORDER BY l.created_at DESC
        """,(user_id,)).fetchall()
    return [{"id":str(r[0]),"scrap_id":str(r[1]),"data":r[2],"status":r[3],"scrap_name":r[4]} for r in rows]

def create_campaign(user_id,payload):
    campaign_id=uuid.uuid4()
    with db() as conn:
        row=conn.execute("""
            INSERT INTO sender_campaigns(id,user_id,name,sender_id,letter_id,status,config)
            VALUES(%s,%s,%s,%s,%s,'draft',%s)
            RETURNING id,name,sender_id,letter_id,status,config,created_at,updated_at
        """,(campaign_id,user_id,payload["name"],payload["sender_id"],payload["letter_id"],Jsonb(payload.get("config",{})))).fetchone()
        lead_ids=list(dict.fromkeys(payload.get("lead_ids",[])))
        if lead_ids:
            try: lead_uuid=[uuid.UUID(x) for x in lead_ids]
            except ValueError as exc: raise ValueError("Invalid Lead id") from exc
            rows=conn.execute("""
                SELECT l.id FROM leads l JOIN scraps s ON s.id=l.scrap_id
                WHERE s.user_id=%s AND l.id=ANY(%s) AND l.status='completed'
            """,(user_id,lead_uuid)).fetchall()
            valid={str(r[0]) for r in rows}
            if len(valid)!=len(lead_uuid): raise ValueError("All selected Leads must belong to the authenticated user and be completed")
            conn.executemany("INSERT INTO sender_campaign_leads(campaign_id,lead_id,user_id) VALUES(%s,%s,%s)",[(campaign_id,x,user_id) for x in lead_uuid])
        conn.commit()
    return dict(zip(["id","name","sender_id","letter_id","status","config","created_at","updated_at"],row))

def campaign_leads(user_id,campaign_id):
    with db() as conn:
        rows=conn.execute("""
            SELECT l.id,l.scrap_id,l.data,l.status,s.name
            FROM sender_campaign_leads cl JOIN leads l ON l.id=cl.lead_id
            JOIN scraps s ON s.id=l.scrap_id
            WHERE cl.user_id=%s AND cl.campaign_id=%s ORDER BY cl.created_at
        """,(user_id,campaign_id)).fetchall()
    return [{"id":str(r[0]),"scrap_id":str(r[1]),"data":r[2],"status":r[3],"scrap_name":r[4]} for r in rows]

def list_campaigns(user_id):
    with db() as conn:
        rows=conn.execute("""
            SELECT id,name,sender_id,letter_id,status,config,created_at,updated_at
            FROM sender_campaigns WHERE user_id=%s ORDER BY created_at DESC
        """,(user_id,)).fetchall()
    return [dict(zip(["id","name","sender_id","letter_id","status","config","created_at","updated_at"],r)) for r in rows]

def _render(value, data):
    if value is None: return None
    return re.sub(r"\\{\\{\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*\\}\\}", lambda m: str(data.get(m.group(1),"" ) or ""), value)

def send_test_lead(user_id, campaign_id, lead_id):
    with db() as conn:
        row=conn.execute("""
            SELECT c.id,c.status,c.config,s.id,s.display_name,s.email,s.provider,s.enabled,s.health,s.config,s.secret_encrypted,
                   l.id,l.data,le.subject,le.body_text,le.body_html
            FROM sender_campaigns c
            JOIN sender_accounts s ON s.id=c.sender_id
            JOIN sender_letters le ON le.id=c.letter_id
            JOIN sender_campaign_leads cl ON cl.campaign_id=c.id AND cl.user_id=c.user_id AND cl.lead_id=%s
            JOIN leads l ON l.id=cl.lead_id
            WHERE c.id=%s AND c.user_id=%s
        """,(lead_id,campaign_id,user_id)).fetchone()
        if not row: raise LookupError("Campaign or selected Lead not found")
        if row[1] != 'draft': raise ValueError("Only draft campaigns can send a test message")
        if row[6] != 'smtp': raise ValueError("SMTP is the only outbound provider currently enabled")
        if not row[7]: raise ValueError("Sender is disabled")
        recipient=(row[12] or {}).get('email')
        if not recipient: raise ValueError("Selected Lead has no email address")
        key=f"test:{campaign_id}:{lead_id}"
        existing=conn.execute("SELECT status,provider_message_id,error FROM sender_messages WHERE user_id=%s AND idempotency_key=%s",(user_id,key)).fetchone()
        if existing:
            if existing[0]=='sent': return {"status":"sent","provider_message_id":existing[1],"already_sent":True}
            if existing[0]=='sending': raise ValueError("This test send is already in an uncertain sending state; do not retry automatically")
        msg_id=uuid.uuid4(); conn.execute("INSERT INTO sender_messages(id,user_id,campaign_id,lead_id,sender_id,recipient_email,status,idempotency_key) VALUES(%s,%s,%s,%s,%s,%s,'sending',%s)",(msg_id,user_id,campaign_id,lead_id,row[3],recipient,key)); conn.commit()
    try:
        secret=decrypt_secret(row[10]) if row[10] else None
        cfg=row[9] or {}
        host=cfg.get('host'); port=int(cfg.get('port',587)); username=cfg.get('username') or row[5]
        if not host or not secret: raise ValueError("SMTP host and password/app-password are required")
        data=row[12] or {}
        subject=_render(row[13],data); body=_render(row[14],data); html=_render(row[15],data)
        message=EmailMessage(); message['From']=f"{row[4]} <{row[5]}>"; message['To']=recipient; message['Subject']=subject
        reply_to=(row[2] or {}).get('reply_to') or cfg.get('reply_to') or row[5]; message['Reply-To']=reply_to
        message['Message-ID']=f"<{msg_id}@scrappee.local>"; message.set_content(body)
        if html: message.add_alternative(html,subtype='html')
        context=ssl._create_unverified_context() if bool(cfg.get('allow_self_signed_certificate',True)) else ssl.create_default_context(); use_ssl=bool(cfg.get('ssl',False)); use_tls=bool(cfg.get('tls',not use_ssl))
        server=smtplib.SMTP_SSL(host,port,context=context,timeout=20) if use_ssl else smtplib.SMTP(host,port,timeout=20)
        try:
            server.ehlo()
            if use_tls: server.starttls(context=context); server.ehlo()
            server.login(username,secret); server.send_message(message)
        finally: server.quit()
        with db() as conn:
            conn.execute("UPDATE sender_messages SET status='sent',provider_message_id=%s,reply_to=%s,updated_at=now() WHERE id=%s AND user_id=%s",(message['Message-ID'],reply_to,msg_id,user_id))
            conn.execute("UPDATE sender_accounts SET health='healthy',updated_at=now() WHERE id=%s AND user_id=%s",(row[3],user_id)); conn.commit()
        return {"status":"sent","provider_message_id":message['Message-ID'],"already_sent":False}
    except Exception as exc:
        with db() as conn:
            conn.execute("UPDATE sender_messages SET status='failed',error=%s,updated_at=now() WHERE id=%s AND user_id=%s",(str(exc)[:1000],msg_id,user_id));
            conn.execute("UPDATE sender_accounts SET health='unhealthy',updated_at=now() WHERE id=%s AND user_id=%s",(row[3],user_id)); conn.commit()
        raise

def summary(user_id):
    with db() as conn:
        senders=conn.execute("SELECT count(*),count(*) FILTER(WHERE enabled),count(*) FILTER(WHERE health='healthy') FROM sender_accounts WHERE user_id=%s",(user_id,)).fetchone()
        campaigns=conn.execute("SELECT count(*),count(*) FILTER(WHERE status='active') FROM sender_campaigns WHERE user_id=%s",(user_id,)).fetchone()
        messages=conn.execute("SELECT count(*),count(*) FILTER(WHERE status='sent'),count(*) FILTER(WHERE status='failed'),count(*) FILTER(WHERE status='replied') FROM sender_messages WHERE user_id=%s",(user_id,)).fetchone()
    return {"senders":{"total":senders[0],"active":senders[1],"healthy":senders[2]},
            "campaigns":{"total":campaigns[0],"active":campaigns[1]},
            "messages":{"queued":messages[0]-messages[1]-messages[2]-messages[3],"sent":messages[1],"failed":messages[2],"replied":messages[3]}}
