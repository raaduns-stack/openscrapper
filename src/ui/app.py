import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv()
import json, os, time, requests, streamlit as st
from src.ui.auth.session import controller as auth_controller, restore as restore_web_session
from src.ui.auth.login import render as render_login
from src.ui.components.sidebar import render_sidebar
from src.ui.components.header import render_header
from src.ui.pages.lead_workstation import render_lead_workstation
from src.ui.pages.scrap_history import render_scrap_history
from src.ui.pages.dashboard import render_dashboard
from src.ui.senders.summary import render_senders
from src.ui.admin.dashboard import render_admin
from src.ui.pages.current_scrap import render_current_scrap
from src.ui.pages.new_scrap import render_new_scrap
from src.ui.pages.exports import render_exports
from src.ui.pages.settings import render_settings
from src.ui.pages.deposit import render_deposit
from src.ui.pages.support import render_support
from src.ui.components.footer import render_footer
API=os.getenv('API_URL','http://127.0.0.1:8000').rstrip('/')
PUBLIC_API_URL=os.getenv('PUBLIC_API_URL','https://api.scrapee.uk').rstrip('/')
st.set_page_config(page_title='Scrappee',page_icon='🕷️',layout='wide',initial_sidebar_state='collapsed')
auth_cookies=auth_controller()
for k,v in [('token',None),('user',None),('scrap_id',None),('nav_page','Dashboard'),('parameters',[]),('selected',[]),('job',None),('serp_token',None),('manual_sources',[]),('submission_completed',False),('admin_user_page',1),('admin_user_page_size',50),('admin_selected_users',set()),('pending_delete_scrap',None),('pending_delete_user',None),('pending_bulk_delete_users',None),('premium_notice',None)]: st.session_state.setdefault(k,v)

def headers(): return {'Authorization':f'Bearer {st.session_state.token}'}

def toggle_admin_user(user_id):
    selected=st.session_state.admin_selected_users
    key=f'admin-select-user-{user_id}'
    if st.session_state.get(key,False):
        if len(selected) < 200: selected.add(user_id)
        else: st.session_state[key]=False
    else: selected.discard(user_id)
def api(method,path,**kwargs):
    timeout=kwargs.pop('timeout',20)
    r=requests.request(method,f'{API}{path}',headers=headers(),timeout=timeout,**kwargs)
    if r.status_code==401:
        st.session_state.clear(); st.rerun()
    return r

def api_error(exc, fallback='Request failed.'):
    response=getattr(exc,'response',None)
    if response is not None:
        try:
            detail=response.json().get('detail')
            if detail: return str(detail)
        except (ValueError, TypeError): pass
        if response.status_code >= 500: return 'The server could not complete the request.'
        if response.status_code == 401: return 'Your session has expired. Please sign in again.'
        if response.status_code == 403: return 'You are not authorized to perform this action.'
        if response.status_code == 404: return 'The requested resource was not found.'
        if response.status_code == 409: return 'This action conflicts with the current Scrap state.'
        if response.status_code == 422: return 'The submitted data is invalid.'
    if isinstance(exc, requests.RequestException): return 'Could not reach the server.'
    return fallback

def api_json(method,path,**kwargs):
    r=api(method,path,**kwargs); r.raise_for_status()
    try: return r.json()
    except ValueError as exc: raise RuntimeError(f'API returned invalid JSON ({r.status_code})') from exc

def auto_refresh_job(job, key='job'):
    if not job or job.get('status') not in ('queued','running'):
        return
    interval=st.session_state.get(f'{key}-poll-interval',3)
    last=st.session_state.get(f'{key}-last-poll',0.0)
    if time.monotonic()-last >= interval:
        st.session_state[f'{key}-last-poll']=time.monotonic()
        st.rerun()

def job_telemetry(job):
    events=job.get('events') or []
    latest=events[-1] if events else {}
    return latest,job.get('counts') or {}
def ensure_serp_session():
    if st.session_state.serp_token:return
    if not st.session_state.scrap_id: raise RuntimeError('Cannot create a SERP session without a Current Scrap')
    r=api('POST','/serp/sessions',json={'ttl_seconds':86400,'scrap_id':st.session_state.scrap_id});r.raise_for_status();st.session_state.serp_token=r.json()['token']

def refresh_current():
    if not st.session_state.scrap_id or st.session_state.serp_token:return
    try:
        existing=api_json('GET',f'/scraps/{st.session_state.scrap_id}/serp-session')
        st.session_state.serp_token=existing.get('token') if existing else None
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404: st.session_state.serp_token=None
        else: raise RuntimeError(f'Could not restore SERP session: {exc}') from exc
    except requests.RequestException as exc:
        raise RuntimeError(f'Could not reach API while restoring SERP session: {exc}') from exc

def import_payload():
    token=st.query_params.get('serp_token') or st.session_state.serp_token
    raw=st.query_params.get('serp_urls');raw_results=st.query_params.get('serp_results');page=st.query_params.get('serp_page')
    if not raw and not raw_results:return
    if not st.session_state.token or not st.session_state.scrap_id:return
    if not token:
        try:
            ensure_serp_session()
            token=st.session_state.serp_token
        except Exception as exc:
            st.error(f'Could not initialize SERP import session: {exc}')
            return
    try: urls=json.loads(raw) if raw else []
    except json.JSONDecodeError as exc:
        st.warning(f'Invalid captured URL payload: {exc}'); urls=[]
    try: results=json.loads(raw_results) if raw_results else []
    except json.JSONDecodeError as exc:
        st.warning(f'Invalid captured result payload: {exc}'); results=[]
    if results and not urls:urls=[x.get('url') for x in results if isinstance(x,dict) and x.get('url')]
    try:
        r=api('POST','/serp/import',json={'token':token,'urls':urls if not results else [],'results':results,'page_url':page});r.raise_for_status();st.session_state.serp_token=token;st.toast(f'Captured {len(results) or len(urls)} SERP results')
    except requests.RequestException as exc:
        st.error(f'Capture failed: {exc}')
    except (KeyError, TypeError, ValueError) as exc:
        st.error(f'Capture payload was invalid: {exc}')
    st.query_params.clear()

def _make_page(title, icon, render_fn, *, default=False):
    def runner():
        render_fn()
        render_footer()
    return st.Page(runner, title=title, icon=icon, default=default, url_path=title.lower().replace(' ', '-'))

def _build_pages():
    pages={
        'Dashboard': _make_page('Dashboard', ':material/dashboard:', lambda: render_dashboard(api_json, api), default=True),
        'New Scrap': _make_page('New Scrap', ':material/add_circle:', lambda: render_new_scrap(api, api_json, billing, ensure_serp_session)),
        'Current Scrap': _make_page('Current Scrap', ':material/radio_button_checked:', lambda: render_current_scrap(api, api_json, refresh_current, billing, job_telemetry, auto_refresh_job)),
        'Lead Workstation': _make_page('Lead Workstation', ':material/workspaces:', lambda: render_lead_workstation(api, api_json, billing, api_error)),
        'Scrap History': _make_page('Scrap History', ':material/history:', lambda: render_scrap_history(api, api_json)),
        'Exports': _make_page('Exports', ':material/download:', lambda: render_exports(api, api_json)),
        'Senders': _make_page('Senders', ':material/mail:', lambda: render_senders(api, api_json, api_error)),
        'Deposit': _make_page('Deposit', ':material/account_balance_wallet:', lambda: render_deposit(api, api_json, api_error)),
        'Support Centre': _make_page('Support Centre', ':material/support_agent:', lambda: render_support(api, api_json, api_error)),
        'Settings': _make_page('Settings', ':material/settings:', lambda: render_settings(api, api_json)),
    }
    admins={x.strip().lower() for x in os.getenv('ADMIN_EMAILS', '').split(',') if x.strip()}
    user=st.session_state.get('user') or {}
    email=user.get('email', '') if isinstance(user, dict) else str(user)
    if email.lower() in admins:
        pages['Admin']=_make_page('Admin', ':material/admin_panel_settings:', lambda: render_admin(api, api_json, api_error))
    return pages

if not st.session_state.token:
    restore_web_session(API, auth_cookies)

billing=None
login_page=st.Page(lambda: render_login(API, auth_cookies), title='Login', icon=':material/login:', default=True)
pages=_build_pages() if st.session_state.token else {}
pg=st.navigation(list(pages.values()) if pages else [login_page], position='hidden')
if not st.session_state.token:
    pg.run()
    st.stop()
if st.session_state.token and not st.session_state.scrap_id:
    try:
        current=api_json('GET','/scraps/current')
        if current:
            st.session_state.scrap_id=current['id']; st.session_state.submission_completed=current.get('status')=='submitted'
            rr=api('GET',f"/scraps/{current['id']}/search-parameters")
            if rr.ok: st.session_state.parameters=rr.json()
            sr=api('GET',f"/scraps/{current['id']}/serp-session")
            if sr.ok and sr.json(): st.session_state.serp_token=sr.json()['token']
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            st.session_state.scrap_id=None
        else:
            st.warning(f'Could not restore current Scrap: {exc}')
    except requests.RequestException as exc:
        st.warning(f'Could not reach API while restoring current Scrap: {exc}')
    except (KeyError, ValueError, TypeError) as exc:
        st.warning(f'Current Scrap data is invalid: {exc}')
if st.session_state.token and st.session_state.scrap_id and st.session_state.serp_token:
    st.html(f'<div data-scrappee-serp-bridge="{st.session_state.serp_token}" style="display:none" aria-hidden="true"></div>')

st.session_state['navigation_pages']=pages
render_sidebar(pages, api_json=api_json, auth_cookies=auth_cookies)
billing=st.session_state.get('billing')
pg.run()
