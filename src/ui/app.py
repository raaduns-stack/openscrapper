import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv
load_dotenv()
import json, os, time, requests, streamlit as st
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
from src.ui.components.footer import render_footer
API=os.getenv('API_URL','http://127.0.0.1:8000').rstrip('/')
PUBLIC_API_URL=os.getenv('PUBLIC_API_URL','https://api.scrapee.uk').rstrip('/')
st.set_page_config(page_title='Scrappee',page_icon='🕷️',layout='wide')
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
def restore_web_session():
    try:
        token=st.context.cookies.get("scrappee_web_session")
    except Exception:
        token=None
    if not token:return False
    try:
        r=requests.get(f'{API}/auth/me',headers={'Authorization':f'Bearer {token}'},timeout=10)
        if not r.ok:return False
        data=r.json();st.session_state.token=token;st.session_state.user={'email':data['email']};return True
    except requests.RequestException:
        return False

def login(email,password,register=False):
    r=requests.post(f'{API}/auth/{"register" if register else "login"}',json={'email':email,'password':password},timeout=20); r.raise_for_status(); data=r.json(); st.session_state.token=data['token']; st.session_state.user={'email':data['email']}

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

if not st.session_state.token: restore_web_session()
if not st.session_state.token:
    st.markdown("<style>section[data-testid='stSidebar']{display:none!important;}[data-testid='collapsedControl']{display:none!important;}</style>", unsafe_allow_html=True)
    st.title('Scrappee');st.caption('Lead research workspace')
    tab1,tab2=st.tabs(['Sign in','Create account'])
    with tab1:
        with st.form('login'):
            e=st.text_input('Email');p=st.text_input('Password',type='password');ok=st.form_submit_button('Sign in',type='primary')
        if ok:
            try:login(e,p);st.rerun()
            except Exception as exc:st.error('Sign in failed. Check your email and password.')
    with tab2:
        with st.form('register'):
            e=st.text_input('Email',key='reg_e');p=st.text_input('Password',type='password',key='reg_p');ok=st.form_submit_button('Create account',type='primary')
        if ok:
            try: login(e,p,True); st.rerun()
            except requests.HTTPError as exc:
                detail=(exc.response.json().get('detail') if exc.response is not None else None) or 'Account creation failed.'
                st.error(f'Could not create account: {detail}')
            except Exception as exc: st.error(f'Could not create account: {exc}')
    st.stop()

import_payload()
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
    st.markdown(f'<div data-scrappee-serp-bridge="{st.session_state.serp_token}" style="display:none" aria-hidden="true"></div>', unsafe_allow_html=True)
page=render_sidebar(api_json=api_json)
billing=st.session_state.get('billing')

if page=='Senders':
    render_senders(api, api_json, api_error)

elif page=='Dashboard':
    render_dashboard(api_json)

elif page=='New Scrap':
    render_new_scrap(api, api_json, billing, ensure_serp_session)

elif page=='Lead Workstation':
    render_lead_workstation(api, api_json, billing, api_error)

elif page=='Current Scrap':
    render_current_scrap(api, api_json, refresh_current, billing, job_telemetry, auto_refresh_job)

elif page=='Scrap History':
    render_scrap_history(api, api_json)

elif page=='Exports':
    render_exports(api, api_json)
elif page=='Settings':
    render_settings(api, api_json)
elif page=='Admin':
    render_admin(api, api_json, api_error)
render_footer()
