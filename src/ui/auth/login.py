import time
import requests
import streamlit as st
from .session import persist


def login(api, email, password, register=False, cookies=None):
    endpoint = "register" if register else "login"
    r = requests.post(f"{api}/auth/{endpoint}", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    data = r.json()
    st.session_state.token = data["token"]
    st.session_state.user = {"email": data["email"]}
    persist(data["token"], cookies)


def _styles():
    st.markdown("""
<style>
[data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="collapsedControl"] { display:none !important; }
[data-testid="stAppViewContainer"] { background:#f7f8fa; }
section.main > div { padding-top:0 !important; }
section.main .block-container { max-width:1280px !important; padding-top:8px !important; padding-bottom:16px !important; }
.auth-brand { min-height:620px; box-sizing:border-box; padding:64px; background:#111827; color:#fff; border-radius:26px 0 0 26px; display:flex; flex-direction:column; justify-content:space-between; }
.auth-logo { font-size:22px; font-weight:800; letter-spacing:.08em; }
.auth-kicker { margin-top:72px; color:#9ca3af; font-size:13px; font-weight:700; letter-spacing:.12em; text-transform:uppercase; }
.auth-title { margin:16px 0 20px; font-size:50px; line-height:1.04; font-weight:800; letter-spacing:-.045em; }
.auth-copy { max-width:580px; color:#cbd5e1; font-size:18px; line-height:1.65; }
.auth-capabilities { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:34px; }
.auth-capability { padding:15px 17px; border:1px solid #374151; border-radius:12px; color:#e5e7eb; font-size:14px; }
.auth-foot { color:#94a3b8; font-size:12px; }
.auth-form-panel { min-height:620px; box-sizing:border-box; padding:64px 56px; background:#fff; border:1px solid #e5e7eb; border-left:0; border-radius:0 26px 26px 0; }
.auth-form-title { font-size:34px; font-weight:800; letter-spacing:-.035em; color:#111827; margin-bottom:7px; }
.auth-form-copy { color:#6b7280; margin-bottom:30px; font-size:15px; }
.auth-switch { text-align:center; color:#6b7280; font-size:14px; margin-top:24px; }
.auth-divider { display:flex; align-items:center; gap:12px; color:#9ca3af; font-size:12px; margin:24px 0; }
.auth-divider:before,.auth-divider:after { content:""; height:1px; background:#e5e7eb; flex:1; }
.auth-legal { text-align:center; color:#9ca3af; font-size:12px; margin-top:14px; }
@media (max-width:800px) { section.main .block-container { padding-top:4px !important; } .auth-brand { min-height:auto; border-radius:26px 26px 0 0; padding:40px; } .auth-form-panel { min-height:auto; padding:40px 32px; border-left:1px solid #e5e7eb; border-top:0; border-radius:0 0 26px 26px; } .auth-kicker { margin-top:42px; } .auth-title { font-size:38px; } }
</style>
""", unsafe_allow_html=True)


def _brand():
    st.markdown("""
<div class="auth-brand">
  <div>
    <div class="auth-logo">SCRAPPEE</div>
    <div class="auth-kicker">Lead intelligence platform</div>
    <div class="auth-title">Turn the web into actionable leads.</div>
    <div class="auth-copy">Discover prospects, capture web data, enrich records and build targeted lead lists from one operational workspace.</div>
    <div class="auth-capabilities">
      <div class="auth-capability">01 · Discover</div>
      <div class="auth-capability">02 · Capture</div>
      <div class="auth-capability">03 · Enrich</div>
      <div class="auth-capability">04 · Qualify</div>
    </div>
  </div>
  <div class="auth-foot">AI-assisted lead research · SERP intelligence · Browser capture</div>
</div>
""", unsafe_allow_html=True)


def _signin(api, cookies=None):
    st.markdown('<div class="auth-form-title">Welcome back</div>', unsafe_allow_html=True)
    st.markdown('<div class="auth-form-copy">Sign in to continue your lead research workspace.</div>', unsafe_allow_html=True)
    with st.form("login"):
        email = st.text_input("Work email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if ok:
        try:
            login(api, email, password, cookies=cookies)
            time.sleep(0.3)
            st.rerun()
        except Exception:
            st.error("Sign in failed. Check your email and password.")
    st.markdown('<div class="auth-switch">Don\'t have an account?</div>', unsafe_allow_html=True)
    if st.button("Create account", key="show-register", use_container_width=True):
        st.session_state.auth_mode = "register"
        st.rerun()


def _register(api, cookies=None):
    st.markdown('<div class="auth-form-title">Create your account</div>', unsafe_allow_html=True)
    st.markdown('<div class="auth-form-copy">Start building your lead research workspace.</div>', unsafe_allow_html=True)
    with st.form("register"):
        email = st.text_input("Work email", key="reg-email", autocomplete="email")
        password = st.text_input("Create password", type="password", key="reg-password", autocomplete="new-password")
        ok = st.form_submit_button("Create account", type="primary", use_container_width=True)
    if ok:
        try:
            login(api, email, password, register=True, cookies=cookies)
            time.sleep(0.3)
            st.rerun()
        except Exception:
            st.error("Account creation failed. Check your details or use another email.")
    st.markdown('<div class="auth-switch">Already have an account?</div>', unsafe_allow_html=True)
    if st.button("Back to sign in", key="show-login", use_container_width=True):
        st.session_state.auth_mode = "signin"
        st.rerun()


def render(api, cookies=None):
    _styles()
    st.session_state.setdefault("auth_mode", "signin")
    left, right = st.columns([1.12, .88], gap="small")
    with left:
        _brand()
    with right:
        with st.container(border=True):
            if st.session_state.auth_mode == "register":
                _register(api, cookies)
            else:
                _signin(api, cookies)
    st.markdown('<div class="auth-legal">Scrappee · Secure customer access · Privacy · Terms</div>', unsafe_allow_html=True)
