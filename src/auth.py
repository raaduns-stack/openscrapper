import os
import secrets
import hashlib
import uuid
import os
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import HTTPException, Request
from pwdlib import PasswordHash
from src.db import db

SECRET = os.getenv("SCRAPPEE_AUTH_SECRET", "change-me-in-production")
ALGORITHM = "HS256"
SESSION_IDLE_MINUTES = int(os.getenv("SCRAPPEE_SESSION_IDLE_MINUTES", "20"))
PERSISTENT_SESSION_DAYS = int(os.getenv("SCRAPPEE_PERSISTENT_SESSION_DAYS", "30"))
password_hash = PasswordHash.recommended()

def hash_token(token): return hashlib.sha256(token.encode()).hexdigest()

def create_user(email, password, country=None):
    user_id = uuid.uuid4()
    with db() as conn:
        role="admin" if email.lower().strip() in {x.strip().lower() for x in os.getenv("ADMIN_EMAILS","").split(",") if x.strip()} else "user"
        conn.execute("INSERT INTO users(id,email,password_hash,role,country) VALUES(%s,%s,%s,%s,%s)", (user_id,email.lower().strip(),password_hash.hash(password),role,country))
        conn.execute("INSERT INTO wallets(user_id) VALUES(%s)", (user_id,))
        conn.commit()
    return str(user_id)

def create_session(user_id, persistent=False):
    raw=secrets.token_urlsafe(48); expires=datetime.now(timezone.utc)+(timedelta(days=PERSISTENT_SESSION_DAYS) if persistent else timedelta(minutes=SESSION_IDLE_MINUTES))
    with db() as conn:
        conn.execute("INSERT INTO sessions(id,user_id,token_hash,expires_at,persistent) VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4(),user_id,hash_token(raw),expires,persistent)); conn.commit()
    return raw, expires

def login_user(email, password, persistent=False):
    with db() as conn:
        row = conn.execute("SELECT id,password_hash FROM users WHERE email=%s", (email.lower().strip(),)).fetchone()
        if not row or not password_hash.verify(password,row[1]): raise HTTPException(401,"Invalid email or password")
        conn.execute("UPDATE users SET last_login_at=now() WHERE id=%s", (row[0],))
        conn.commit()
    return create_session(row[0], persistent=persistent)

def current_user(request: Request):
    token=request.headers.get("Authorization","").removeprefix("Bearer ").strip()
    if not token: raise HTTPException(401,"Authentication required")
    with db() as conn:
        row=conn.execute("UPDATE sessions SET expires_at=CASE WHEN sessions.persistent THEN sessions.expires_at ELSE now() + make_interval(mins => %s) END FROM users u WHERE sessions.user_id=u.id AND sessions.token_hash=%s AND (sessions.persistent OR sessions.expires_at>now()) RETURNING u.id,u.email,u.role",(SESSION_IDLE_MINUTES,hash_token(token))).fetchone()
        conn.commit()
    if not row: raise HTTPException(401,"Session expired or invalid")
    return {"id":str(row[0]),"email":row[1],"role":row[2],"token":token}


PASSWORD_RESET_MINUTES = int(os.getenv("SCRAPPEE_PASSWORD_RESET_MINUTES", "60"))

def request_password_reset(email):
    normalized=email.lower().strip()
    with db() as conn:
        row=conn.execute("SELECT id,email FROM users WHERE email=%s",(normalized,)).fetchone()
        if not row:
            return None
        raw=secrets.token_urlsafe(48)
        conn.execute("DELETE FROM password_reset_tokens WHERE user_id=%s OR expires_at<=now()",(row[0],))
        conn.execute(
            "INSERT INTO password_reset_tokens(id,user_id,token_hash,expires_at) VALUES(%s,%s,%s,now()+make_interval(mins => %s))",
            (uuid.uuid4(),row[0],hash_token(raw),PASSWORD_RESET_MINUTES)
        )
        conn.commit()
    return {"email":row[1],"token":raw}

def reset_password(token,new_password):
    token=(token or "").strip()
    if not token:
        raise HTTPException(400,"Invalid or expired password reset link")
    with db() as conn:
        row=conn.execute(
            """SELECT id,user_id FROM password_reset_tokens
               WHERE token_hash=%s AND used_at IS NULL AND expires_at>now()""",
            (hash_token(token),)
        ).fetchone()
        if not row:
            raise HTTPException(400,"Invalid or expired password reset link")
        conn.execute("UPDATE users SET password_hash=%s WHERE id=%s",(password_hash.hash(new_password),row[1]))
        conn.execute("UPDATE password_reset_tokens SET used_at=now() WHERE id=%s",(row[0],))
        conn.execute("DELETE FROM sessions WHERE user_id=%s",(row[1],))
        conn.commit()
    return True
