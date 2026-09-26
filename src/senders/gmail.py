import json, os, secrets, uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import requests

from src.db import db
from .service import encrypt_secret, decrypt_secret

GMAIL_SCOPE="https://www.googleapis.com/auth/gmail.send"
AUTH_URL="https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL="https://oauth2.googleapis.com/token"
REVOKE_URL="https://oauth2.googleapis.com/revoke"
PROFILE_URL="https://gmail.googleapis.com/gmail/v1/users/me/profile"

def _config():
    client_id=os.getenv("SCRAPPEE_GOOGLE_CLIENT_ID")
    client_secret=os.getenv("SCRAPPEE_GOOGLE_CLIENT_SECRET")
    base=os.getenv("SCRAPPEE_PUBLIC_BASE_URL","https://scrapee.uk").rstrip("/")
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth is not configured")
    return client_id,client_secret,f"{base}/oauth/gmail/callback"

def start(user_id,sender_id):
    client_id,_,redirect_uri=_config()
    state=secrets.token_urlsafe(32)
    expires=datetime.now(timezone.utc)+timedelta(minutes=10)
    with db() as conn:
        conn.execute("DELETE FROM sender_oauth_states WHERE expires_at < now()")
        conn.execute("INSERT INTO sender_oauth_states(state,user_id,sender_id,provider,expires_at) VALUES(%s,%s,%s,'gmail_oauth',%s)",(state,user_id,sender_id,expires))
        conn.commit()
    params={"client_id":client_id,"redirect_uri":redirect_uri,"response_type":"code","scope":GMAIL_SCOPE,"access_type":"offline","include_granted_scopes":"true","state":state,"prompt":"consent"}
    return f"{AUTH_URL}?{urlencode(params)}"

def callback(state,code):
    client_id,client_secret,redirect_uri=_config()
    with db() as conn:
        row=conn.execute("SELECT user_id,sender_id FROM sender_oauth_states WHERE state=%s AND expires_at>now()",(state,)).fetchone()
        conn.execute("DELETE FROM sender_oauth_states WHERE state=%s",(state,))
        conn.commit()
    if not row: raise ValueError("Invalid or expired OAuth state")
    user_id,sender_id=row
    token=requests.post(TOKEN_URL,data={"client_id":client_id,"client_secret":client_secret,"code":code,"grant_type":"authorization_code","redirect_uri":redirect_uri},timeout=15)
    token.raise_for_status()
    tokens=token.json()
    if not tokens.get("access_token"): raise RuntimeError("Google OAuth did not return an access token")
    if tokens.get("expires_in"): tokens["expires_at"]=datetime.now(timezone.utc).timestamp()+int(tokens["expires_in"])
    profile=requests.get(PROFILE_URL,headers={"Authorization":f"Bearer {tokens['access_token']}"},timeout=15)
    profile.raise_for_status()
    email=profile.json().get("emailAddress")
    if not email: raise RuntimeError("Google did not return the authorized Gmail address")
    with db() as conn:
        existing=conn.execute("SELECT secret_encrypted FROM sender_accounts WHERE id=%s AND user_id=%s AND provider='gmail_oauth'",(sender_id,user_id)).fetchone()
        if not existing: raise LookupError("Sender not found")
        previous=json.loads(decrypt_secret(existing[0])) if existing[0] else {}
        if not tokens.get("refresh_token") and previous.get("refresh_token"): tokens["refresh_token"]=previous["refresh_token"]
        conn.execute("UPDATE sender_accounts SET email=%s,health='healthy',config=config || %s::jsonb,secret_encrypted=%s,updated_at=now() WHERE id=%s AND user_id=%s",
                     (email,json.dumps({"oauth_email":email,"oauth_scopes":[GMAIL_SCOPE]}),encrypt_secret(json.dumps(tokens)),sender_id,user_id))
        conn.commit()
    return email

def connection(user_id,sender_id):
    with db() as conn:
        row=conn.execute("SELECT provider,health,config,secret_encrypted FROM sender_accounts WHERE id=%s AND user_id=%s",(sender_id,user_id)).fetchone()
    if not row: return None
    cfg=row[2] or {}
    return {"provider":row[0],"health":row[1],"connected":bool(row[3] and cfg.get("oauth_email")),"email":cfg.get("oauth_email")}

def disconnect(user_id,sender_id):
    with db() as conn:
        row=conn.execute("SELECT provider,config,secret_encrypted FROM sender_accounts WHERE id=%s AND user_id=%s",(sender_id,user_id)).fetchone()
        if not row: raise LookupError("Sender not found")
        if row[0]!="gmail_oauth": raise ValueError("Not a Gmail OAuth sender")
    if row[2]:
        try:
            tokens=json.loads(decrypt_secret(row[2]))
            token=tokens.get("refresh_token") or tokens.get("access_token")
            if token: requests.post(REVOKE_URL,data={"token":token},timeout=10)
        except Exception:
            pass
    with db() as conn:
        conn.execute("UPDATE sender_accounts SET health='unknown',config=config - 'oauth_email' - 'oauth_scopes',secret_encrypted=NULL,updated_at=now() WHERE id=%s AND user_id=%s",(sender_id,user_id))
        conn.commit()
def token_for_send(user_id,sender_id):
    with db() as conn:
        row=conn.execute("SELECT provider,secret_encrypted FROM sender_accounts WHERE id=%s AND user_id=%s",(sender_id,user_id)).fetchone()
    if not row or row[0]!="gmail_oauth" or not row[1]: raise ValueError("Gmail OAuth sender is not connected")
    tokens=json.loads(decrypt_secret(row[1]))
    access=tokens.get("access_token")
    expiry=tokens.get("expires_at")
    if access and (not expiry or float(expiry)>datetime.now(timezone.utc).timestamp()+60): return access
    refresh=tokens.get("refresh_token")
    if not refresh: raise RuntimeError("Gmail authorization requires reconnect")
    client_id,client_secret,_=_config()
    resp=requests.post(TOKEN_URL,data={"client_id":client_id,"client_secret":client_secret,"refresh_token":refresh,"grant_type":"refresh_token"},timeout=15)
    resp.raise_for_status()
    fresh=resp.json()
    tokens.update(fresh)
    tokens["refresh_token"]=fresh.get("refresh_token",refresh)
    if fresh.get("expires_in"): tokens["expires_at"]=datetime.now(timezone.utc).timestamp()+int(fresh["expires_in"])
    with db() as conn:
        conn.execute("UPDATE sender_accounts SET secret_encrypted=%s,updated_at=now() WHERE id=%s AND user_id=%s",(encrypt_secret(json.dumps(tokens)),sender_id,user_id)); conn.commit()
    return tokens["access_token"]
