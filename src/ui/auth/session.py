import requests
import streamlit as st
from streamlit_cookies_controller import CookieController

COOKIE_NAME='scrappee_web_session'
COOKIE_MAX_AGE=30*24*60*60

def controller():
    return CookieController(key='scrappee_auth_cookies')

def restore(api, cookies=None):
    cookies=cookies or controller()
    token=st.context.cookies.get(COOKIE_NAME) or cookies.get(COOKIE_NAME)
    if not token:return False
    try:
        r=requests.get(f'{api}/auth/me',headers={'Authorization':f'Bearer {token}'},timeout=10)
        if not r.ok:
            try: cookies.remove(COOKIE_NAME,path='/',secure=True,same_site='lax')
            except KeyError: pass
            return False
        data=r.json()
        st.session_state.token=token
        st.session_state.user={'email':data['email']}
        return True
    except requests.RequestException:
        return False

def persist(token, cookies=None):
    (cookies or controller()).set(COOKIE_NAME,token,path='/',max_age=COOKIE_MAX_AGE,secure=True,same_site='lax')

def clear(cookies=None):
    (cookies or controller()).remove(COOKIE_NAME,path='/',secure=True,same_site='lax')
