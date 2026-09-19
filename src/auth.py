import os
import secrets
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import HTTPException, Request
from pwdlib import PasswordHash
from src.db import db

SECRET = os.getenv("SCRAPPEE_AUTH_SECRET", "change-me-in-production")
ALGORITHM = "HS256"
SESSION_IDLE_MINUTES = int(os.getenv("SCRAPPEE_SESSION_IDLE_MINUTES", "20"))
password_hash = PasswordHash.recommended()

def hash_token(token): return hashlib.sha256(token.encode()).hexdigest()

def create_user(email, password):
    user_id = uuid.uuid4()
    with db() as conn:
        conn.execute("INSERT INTO users(id,email,password_hash) VALUES(%s,%s,%s)", (user_id,email.lower().strip(),password_hash.hash(password)))
        conn.execute("INSERT INTO wallets(user_id) VALUES(%s)", (user_id,))
        conn.commit()
    return str(user_id)

def create_session(user_id, persistent=False):
    raw=secrets.token_urlsafe(48); expires=datetime.now(timezone.utc)+(timedelta(days=36525) if persistent else timedelta(minutes=SESSION_IDLE_MINUTES))
    with db() as conn:
        conn.execute("INSERT INTO sessions(id,user_id,token_hash,expires_at,persistent) VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4(),user_id,hash_token(raw),expires,persistent)); conn.commit()
    return raw, expires

def login_user(email, password, persistent=False):
    with db() as conn:
        row = conn.execute("SELECT id,password_hash FROM users WHERE email=%s", (email.lower().strip(),)).fetchone()
        if not row or not password_hash.verify(password,row[1]): raise HTTPException(401,"Invalid email or password")
    return create_session(row[0], persistent=persistent)

def current_user(request: Request):
    token=request.headers.get("Authorization","").removeprefix("Bearer ").strip()
    if not token: raise HTTPException(401,"Authentication required")
    with db() as conn:
        row=conn.execute("UPDATE sessions SET expires_at=CASE WHEN sessions.persistent THEN sessions.expires_at ELSE now() + make_interval(mins => %s) END FROM users u WHERE sessions.user_id=u.id AND sessions.token_hash=%s AND (sessions.persistent OR sessions.expires_at>now()) RETURNING u.id,u.email",(SESSION_IDLE_MINUTES,hash_token(token))).fetchone()
        conn.commit()
    if not row: raise HTTPException(401,"Session expired or invalid")
    return {"id":str(row[0]),"email":row[1],"token":token}
