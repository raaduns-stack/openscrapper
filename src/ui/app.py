from dotenv import load_dotenv
load_dotenv()
import json, os, time, requests, streamlit as st
from src.agent.query_interpreter import QueryInterpreter
from src.models.criteria import SearchCriteria
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
billing=None
with st.sidebar:
    st.title('Scrappee');st.caption(st.session_state.user['email'])
    try:
        billing=api_json('GET','/billing'); st.metric('Balance',f"${billing['balance_cents']/100:.2f}"); st.caption(f"New Scrap: ${billing['scrap_creation_price_cents']/100:.2f}")
    except requests.RequestException as exc:
        st.caption(f'Billing unavailable: {exc}')
    except (KeyError, TypeError, ValueError) as exc:
        st.caption(f'Billing data unavailable: {exc}')
    nav_options=['Dashboard','New Scrap','Current Scrap','Scrap History','Exports','Settings']
    page=st.radio('Navigation',nav_options,index=nav_options.index(st.session_state.nav_page))
    if page != st.session_state.nav_page: st.session_state.nav_page=page
    if st.button('Sign out',key='sign-out'):
        try:
            token=st.session_state.get('token')
            if token: requests.post(f'{API}/auth/logout',headers={'Authorization':f'Bearer {token}'},timeout=10)
        finally:
            st.session_state.clear()
            st.rerun()

if page=='Dashboard':
    st.title('Dashboard');st.write('Start a new lead-research scrap or continue your current workspace.')
    try:
        scraps=api_json('GET','/scraps')
        current=api_json('GET','/scraps/current')
        st.metric('Scraps',len(scraps));st.metric('Current captured results',(current or {}).get('counts',{}).get('serp_results',0));st.info('Use New Scrap to define what you want to find.')
    except Exception as exc: st.error(f'Could not load dashboard: {exc}'); st.stop()
    if scraps:st.dataframe(scraps[:20],use_container_width=True,hide_index=True)

elif page=='New Scrap':
    st.title('New Scrap');st.caption('Describe the leads. Scrappee builds the discovery strategy for you.')
    if st.session_state.scrap_id:
        try:
            existing=api_json('GET',f"/scraps/{st.session_state.scrap_id}")
            if existing.get('status') in ('active','running'):
                st.warning('A Current Scrap is already open. Complete URL submission before creating another Scrap.')
                st.stop()
            st.session_state.scrap_id=None
            st.session_state.serp_token=None
            st.session_state.parameters=[]
            st.session_state.job=None
            st.session_state.selected=[]
            st.session_state.manual_sources=[]
            st.session_state.submission_completed=False
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                st.session_state.scrap_id=None
            else:
                st.error(f'Could not check the previous Scrap: {exc}')
                st.stop()
        except requests.RequestException as exc:
            st.error(f'Could not check the previous Scrap: {exc}')
            st.stop()
    with st.form('search'):
        request=st.text_area('What leads are you looking for?',placeholder='e.g. gold buyers in India',height=100)
        c1,c2=st.columns(2)
        with c1:target=st.selectbox('Target type',['people','companies','both']);geography=st.text_input('Geography')
        with c2:roles=st.text_input('Roles / job titles');keywords=st.text_input('Keywords')
        max_lead_default=int((billing or {}).get('research_default_max_leads',100));max_lead_limit=int((billing or {}).get('research_max_leads',10000));max_leads=st.number_input('Maximum leads',1,max_lead_limit,max_lead_default);max_queries=st.number_input('Maximum search parameters',1,500,20)
        with st.expander('Advanced controls'):
            limit_pages=st.checkbox('Limit crawl pages',value=False);max_pages=st.number_input('Maximum crawl pages',1,10000,1000,disabled=not limit_pages);limit_urls=st.checkbox('Limit crawl URL occurrences',value=False);max_urls=st.number_input('Maximum crawl URL occurrences',1,100000,10000,disabled=not limit_urls);limit_depth=st.checkbox('Limit crawl depth',value=False);max_depth=st.number_input('Maximum crawl depth',0,100,2,disabled=not limit_depth);limit_pagination=st.checkbox('Limit pagination pages',value=False);max_pagination=st.number_input('Maximum pagination pages',1,1000,100,disabled=not limit_pagination);provider_failures=st.number_input('Provider failure limit',1,20,2);url_validity=st.checkbox('URL validity checks',value=True);exhaustion_enabled=st.checkbox('Stop after duplicate/no-progress exhaustion',value=True);exhaustion_threshold=st.number_input('Duplicate/no-progress threshold',1,100,3)
        name=st.text_input('Scrap name',value=request or 'Current Scrap')
        submitted=st.form_submit_button('Create scrap & generate searches',type='primary')
    if submitted:
        try:
            if not request.strip(): raise ValueError('Describe the leads you are looking for.')
            criteria=QueryInterpreter().interpret(request)
            if geography.strip():criteria.geography=geography.strip()
            if roles.strip():criteria.roles=[x.strip() for x in roles.split(',') if x.strip()]
            if keywords.strip():criteria.keywords=[x.strip() for x in keywords.split(',') if x.strip()]
            criteria.target_type=target;criteria.max_leads=int(max_leads);criteria=SearchCriteria.model_validate(criteria.model_dump())
            criteria_data=criteria.model_dump()
            crawler_data={'max_queries':int(max_queries),'provider_failure_limit':int(provider_failures),'url_validity_checks':bool(url_validity),'max_crawl_pages':int(max_pages) if limit_pages else None,'max_crawl_urls':int(max_urls) if limit_urls else None,'max_crawl_depth':int(max_depth) if limit_depth else None,'max_pagination_pages':int(max_pagination) if limit_pagination else None,'duplicate_exhaustion_enabled':bool(exhaustion_enabled),'duplicate_exhaustion_threshold':int(exhaustion_threshold)}
            r=api('POST','/scraps',json={'name':name.strip() or 'Current Scrap','criteria':criteria_data,'crawler':crawler_data});r.raise_for_status()
            st.session_state.scrap_id=r.json()['id']
            pr=api('POST','/search/parameters',json={'scrap_id':st.session_state.scrap_id,'criteria':criteria_data,'max_queries':int(max_queries)});pr.raise_for_status()
            st.session_state.parameters=pr.json().get('parameters',[])
            if not st.session_state.parameters: raise ValueError('No search parameters were generated for this request.')
            st.session_state.selected=[];st.session_state.job=None;st.session_state.serp_token=None;st.session_state.manual_sources=[];ensure_serp_session();st.session_state.nav_page='Current Scrap';st.rerun()
        except Exception as exc:
            msg=str(exc)
            if '429' in msg or 'rate_limit_exceeded' in msg or 'Rate limit reached' in msg:
                import re
                wait=re.search(r'Please try again in ([^.]+)',msg)
                delay=wait.group(1) if wait else 'a few minutes'
                st.warning(f'AI search generation is temporarily rate-limited. Please retry in {delay}. Your Scrap was not created or charged.')
            else:
                st.error(f'Could not create scrap: {exc}')

elif page=='Current Scrap':
    st.title('Current Scrap')
    if not st.session_state.scrap_id:st.info('No current scrap. Create one from New Scrap.');st.stop()
    try:
        live_data=api_json('GET',f'/scraps/{st.session_state.scrap_id}')
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            st.session_state.scrap_id=None;st.session_state.serp_token=None;st.session_state.parameters=[];st.info('The current Scrap is no longer available. Create or select another Scrap.');st.stop()
        st.error(f'Could not load current Scrap: {exc}');st.stop()
    if not st.session_state.serp_token:
        refresh_current()
    if page=='Current Scrap':
        if not st.session_state.parameters:
            rr=api('GET',f'/scraps/{st.session_state.scrap_id}/search-parameters')
            if rr.ok: st.session_state.parameters=rr.json()
        try:
            live=live_data
            serp_results=api_json('GET',f'/scraps/{st.session_state.scrap_id}/serp-results')
            url_rows=api_json('GET',f'/scraps/{st.session_state.scrap_id}/url-occurrences')
            current_urls=[row['url'] for row in url_rows]
            current_results=serp_results
        except requests.RequestException as exc:
            st.error(f'Could not load this Scrap: {exc}'); st.stop()
        except (KeyError, TypeError, ValueError) as exc:
            st.error(f'This Scrap returned invalid data: {exc}'); st.stop()
        current_job=None
        try: current_job=api_json('GET',f'/scraps/{st.session_state.scrap_id}/job')
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code != 404: st.warning(f'Could not load research job: {exc}')
        except requests.RequestException as exc:
            st.warning(f'Could not reach API while loading research job: {exc}')
        if current_job: st.session_state.job=current_job['job_id']
        st.header(live.get('name') or 'Current Scrap')
        st.caption(f"Status: **{live['status'].title()}** · Scrap ID: `{live['id']}`")
        if st.button('↻ Refresh Current Scrap',key='refresh-current'):
            st.rerun()
        st.info('Work on this Scrap until you have finished collecting Google/Bing results. Your collection is saved to Scrappee as it arrives.')
        a,b,c,d,e=st.columns(5);a.metric('SERP results',live['counts']['serp_results']);b.metric('URL occurrences',live['counts']['url_occurrences']);c.metric('Leads',live['counts']['leads']);d.metric('LLM calls',live['counts'].get('llm_calls',0));e.metric('SERP capacity',f"{live['counts']['serp_results']} / {live['serp_limit']}")
        if live['counts']['serp_results'] >= live['serp_limit']: st.warning('SERP capacity reached. Further SERP imports are blocked until this Scrap is closed.')
        research_running = live['status']=='running' and current_job and current_job.get('status') in ('queued','running')
        if research_running:
            st.success('Research is running. Collection is closed for this Scrap.')
            if current_job:
                st.subheader('Ongoing Research')
                jc1,jc2,jc3=st.columns(3);jc1.metric('Job status',current_job.get('status','').title());jc2.metric('Current stage',current_job.get('stage','—'));jc3.metric('Leads',current_job.get('counts',{}).get('leads',live['counts']['leads']))
                if current_job.get('message'): st.info(current_job['message'])
                latest,collection_counts=job_telemetry(current_job);counts=current_job.get('counts') or {};mc=st.columns(4)
                mc[0].metric('URLs',collection_counts.get('urls_submitted',counts.get('urls',counts.get('url_occurrences',live['counts']['url_occurrences']))));mc[1].metric('Pages',collection_counts.get('pages_collected',counts.get('pages',counts.get('crawl_pages',live['counts']['crawl_pages']))));mc[2].metric('Evidence',counts.get('evidence',live['counts'].get('evidence',0)));mc[3].metric('Leads',current_job.get('lead_count',live['counts']['leads']))
                if latest: st.caption(f"Scrapy: **{latest.get('state','running').title()}** · {latest.get('message','')}")
                if current_job.get('events'): st.caption(f"Pipeline events recorded: {len(current_job['events'])}")
                if st.button('↻ Refresh Ongoing Research',key='refresh-current-running'): st.rerun()
                if st.button('CANCEL RESEARCH',type='secondary',key='cancel-current-running'):
                    api('POST',f"/jobs/{current_job['job_id']}/cancel").raise_for_status();st.rerun()
                auto_refresh_job(current_job, 'current-running')
            else: st.warning('Scrap is marked Running but its Job record could not be loaded.')
            st.stop()
        st.subheader('1. Collect SERP results')
        st.caption('Choose a search below. Manual search is free; Premium extracts a pasted Google/Bing search URL for the configured fee.')
        left,right=st.columns(2)
        with left:
            st.markdown('### Manual SERP Discovery — Free')
            st.caption('Open Google/Bing in your normal browser. Use the extension to capture rendered result cards.')
            if st.session_state.parameters:
                for p in st.session_state.parameters:
                    cols=st.columns([1,8,2]);provider=p['provider'].lower();label='Google' if provider=='google' else 'Bing';cols[0].write(label);cols[1].text_area('Search query',p['query'],height=90,key=f"query-{p['id']}",label_visibility='collapsed');cols[2].link_button(f'Open in {label}',p['url'],use_container_width=True)
        with right:
            premium_price_cents=(billing or {}).get('premium_serp_price_cents',100)
            premium_price=f'${premium_price_cents/100:.2f}'
            st.markdown(f'### Premium SERP Extraction — {premium_price} per extraction')
            st.caption('Paste a Google/Bing search URL. Premium collects all available SERP pages up to the configured SERP capacity; it does not use the browser extension.')
            with st.form('premium-serp'):
                u=st.text_input('Google / Bing search URL',placeholder='https://www.google.com/search?q=...')
                ok=st.form_submit_button(f'EXTRACT SERP — {premium_price}')
            if ok:
                search_url=u.strip()
                if not search_url:
                    st.error('Enter a Google or Bing search URL before starting Premium extraction.')
                else:
                    try:
                        import uuid as _uuid
                        r=api('POST','/serp/premium',timeout=60,json={'scrap_id':st.session_state.scrap_id,'search_url':search_url,'idempotency_key':_uuid.uuid4().hex});r.raise_for_status();data=r.json();st.session_state.premium_notice=f"Premium extraction completed: {data['found_results']} SERP results found; {data['results']} new results added. Charged ${data['charged_cents']/100:.2f}.";st.rerun()
                    except Exception as exc:st.error(f'Premium extraction failed: {exc}')
            if st.session_state.premium_notice:
                st.success(st.session_state.premium_notice)
                st.session_state.premium_notice=None
        st.subheader('2. Review what has been collected')
        if current_urls:
            st.success(f"{len(current_results)} SERP result occurrences and {len(current_urls)} URL occurrences are saved to this Scrap.")
        else:
            st.info('No SERP results have been saved yet. Open a Google/Bing search and use the extension to capture results.')
        if current_results:
            st.dataframe(current_results[:5000],use_container_width=True,hide_index=True)
        captured_leads=api_json("GET",f"/scraps/{st.session_state.scrap_id}/results")
        st.subheader("SERP leads captured")
        if captured_leads:
            st.success("{} lead(s) have been captured and saved. Scrapy will enrich these records after URL submission.".format(len(captured_leads)))
            captured_leads_data = [r["data"] for r in captured_leads]
            col_download, col_cancel = st.columns([1, 1])
            with col_download:
                st.download_button(
                    "Download captured leads CSV",
                    data=__import__("pandas").DataFrame(captured_leads_data).to_csv(index=False).encode("utf-8"),
                    file_name=f"serp-leads-{st.session_state.scrap_id}.csv",
                    mime="text/csv",
                    key="download-captured-leads-csv",
                    use_container_width=True,
                )
            with col_cancel:
                if live['status'] in ('active','running') and st.button('CANCEL SCRAP',use_container_width=True,key='cancel-current-scrap'):
                    try:
                        r=api('POST',f"/scraps/{st.session_state.scrap_id}/cancel"); r.raise_for_status()
                        st.session_state.scrap_id=None; st.session_state.serp_token=None; st.session_state.parameters=[]; st.session_state.selected=[]; st.session_state.job=None; st.session_state.manual_sources=[]
                        st.session_state.nav_page='New Scrap'; st.rerun()
                    except Exception as exc: st.error(f'Could not cancel Current Scrap: {exc}')
            st.dataframe(captured_leads_data,use_container_width=True,hide_index=True)
        else:
            st.info("No qualified leads captured from SERP yet. Leads will appear here as SERP processing validates and saves them.")
        if live['status'] in ('active','running'):
            st.subheader('3. Finish URL submission')
            st.caption('When you have finished browsing and collecting results, click the button below. This ends the active collection phase and releases the Current Scrap lock.')
            if current_urls:
                if st.button('URL SUBMISSION COMPLETED',type='primary',use_container_width=True):
                    try:
                        r=api('POST',f"/scraps/{st.session_state.scrap_id}/complete-submission"); r.raise_for_status(); st.session_state.submission_completed=True; st.success('URL submission completed. Research is now ready to start.'); st.rerun()
                    except Exception as exc: st.error(f'Could not complete URL submission: {exc}')
            else:
                st.button('URL SUBMISSION COMPLETED',disabled=True,use_container_width=True)
        if live['status']=='submitted' and current_urls:
            st.subheader('3. Start research')
            export_format=st.selectbox('Export format',['csv','xlsx','google_sheets'],key='research-export-format')
            google_spreadsheet_id=st.text_input('Google Spreadsheet ID',key='research-sheet-id') if export_format=='google_sheets' else None
            if st.button('START RESEARCH',type='primary',use_container_width=True):
                payload={'scrap_id':st.session_state.scrap_id,'criteria':live.get('criteria') or {},'urls':current_urls,'results':current_results,'crawler':live.get('crawler') or {'max_crawl_pages':None,'max_crawl_urls':None,'max_crawl_depth':None,'max_pagination_pages':None,'url_validity_checks':True},'export_format':export_format,'google_spreadsheet_id':google_spreadsheet_id}
                try:
                    r=api('POST','/jobs/from-urls',json=payload); r.raise_for_status(); st.session_state.job=r.json()['job_id']; st.success('Research started')
                except Exception as exc: st.error(f'Could not start research: {exc}')
        if st.session_state.job:
            try: job=api_json('GET',f"/jobs/{st.session_state.job}")
            except Exception as exc: st.error(f'Could not load research status: {exc}'); st.stop()
            st.divider()
            st.subheader('Research job')
            jc1,jc2,jc3=st.columns(3)
            jc1.metric('Status',job.get('status','').title())
            jc2.metric('Stage',job.get('stage','—'))
            jc3.metric('Leads',job.get('lead_count',live['counts']['leads']))
            if job.get('message'): st.info(job['message'])
            counts=job.get('counts') or {}
            if counts:
                labels=[('URLs',counts.get('urls') or counts.get('url_occurrences')),('Pages',counts.get('pages') or counts.get('crawl_pages')),('Evidence',counts.get('evidence')),('Leads',job.get('lead_count',counts.get('leads')))]
                mc=st.columns(4)
                for col,(label,value) in zip(mc,labels): col.metric(label,value if value is not None else 0)
            if job.get('status') in ('queued','running'):
                if st.button('↻ Refresh Job Status',key='refresh-job'): st.rerun()
                if st.button('CANCEL RESEARCH',type='secondary'):
                    r=api('POST',f"/jobs/{st.session_state.job}/cancel"); r.raise_for_status()
                    st.session_state.job=None
                    st.session_state.submission_completed=True
                    st.success('Research canceled. You can start a new research pass.')
                    st.rerun()
                auto_refresh_job(job, 'job')
            elif job.get('status')=='completed':
                st.success('Research completed.')
            elif job.get('status') in ('failed','canceled'):
                st.error(job.get('error') or f"Research {job.get('status')}.")
                if st.button('START NEW RESEARCH',type='primary',key='restart-research'):
                    r=api('POST',f"/scraps/{st.session_state.scrap_id}/restart-research"); r.raise_for_status()
                    st.session_state.job=None
                    st.session_state.submission_completed=True
                    st.rerun()
    else:
        rows=api_json('GET',f'/scraps/{st.session_state.scrap_id}/results')
        if rows: st.dataframe([r['data'] for r in rows],use_container_width=True,hide_index=True)
        else: st.info('No qualified leads yet. Start research from Current Scrap.')

elif page=='Scrap History':
    st.title('Scrap History');rows=api_json('GET','/scraps')
    if not rows: st.info('No Scraps in history.')
    for row in rows:
        cols=st.columns([3,2,2,1,1,1])
        cols[0].write(row['name'])
        cols[1].write(row['status'].title())
        cols[2].write(row['created_at'][:19].replace('T',' '))
        if cols[3].button('DETAILS',key=f"details-scrap-{row['id']}"):
            st.session_state.history_detail=row['id'];st.rerun()
        if row['status'] in ('submitted','failed','canceled') and cols[4].button('REOPEN',key=f"reopen-scrap-{row['id']}"):
            try:
                r=api('POST',f"/scraps/{row['id']}/reopen");r.raise_for_status();st.session_state.scrap_id=row['id'];st.session_state.serp_token=None;st.session_state.parameters=[];st.rerun()
            except Exception as exc: st.error(f'Could not reopen Scrap: {exc}')
        if cols[5].button('DELETE',key=f"delete-scrap-{row['id']}"):
            st.session_state.pending_delete_scrap=row['id'];st.rerun()
        if st.session_state.pending_delete_scrap==row['id']:
            st.warning(f"Delete Scrap '{row['name']}' permanently? This cannot be undone.")
            confirm,cancel=st.columns(2)
            if confirm.button('CONFIRM DELETE',key=f"confirm-delete-scrap-{row['id']}",type='primary'):
                try:
                    r=api('DELETE',f"/scraps/{row['id']}");r.raise_for_status();st.session_state.pending_delete_scrap=None
                    if st.session_state.scrap_id==row['id']: st.session_state.scrap_id=None
                    st.success('Scrap deleted.');st.rerun()
                except requests.RequestException as exc: st.error(f'Could not delete Scrap: {exc}')
            if cancel.button('CANCEL',key=f"cancel-delete-scrap-{row['id']}"): st.session_state.pending_delete_scrap=None;st.rerun()
    detail_id=st.session_state.get('history_detail')
    if detail_id:
        try:
            detail=api_json('GET',f'/scraps/{detail_id}'); job=api_json('GET',f'/scraps/{detail_id}/job')
            st.divider();st.subheader(f"Scrap details — {detail['name']}")
            c1,c2,c3,c4=st.columns(4);c1.metric('Scrap status',detail['status'].title());c2.metric('SERP results',detail['counts']['serp_results']);c3.metric('Pages crawled',detail['counts']['crawl_pages']);c4.metric('Leads',detail['counts']['leads'])
            st.caption(f"Scrap ID: `{detail['id']}` · Created: {detail['created_at'][:19].replace('T',' ')} · Completed: {(detail['completed_at'] or '—')[:19].replace('T',' ')}")
            st.subheader('Research Job')
            j1,j2,j3=st.columns(3);j1.metric('Job status',job.get('status','').title());j2.metric('Final stage',job.get('stage','—'));j3.metric('Lead count',job.get('lead_count',detail['counts']['leads']))
            jc=job.get('counts') or {};m=st.columns(4)
            m[0].metric('URLs',jc.get('urls',jc.get('url_occurrences',detail['counts']['url_occurrences'])));m[1].metric('Pages',jc.get('pages',jc.get('crawl_pages',detail['counts']['crawl_pages'])));m[2].metric('Evidence',jc.get('evidence',0));m[3].metric('Leads',job.get('lead_count',detail['counts']['leads']))
            if job.get('message'): st.info(job['message'])
            if job.get('events'): st.caption(f"Pipeline events recorded: {len(job['events'])}")
            lead_rows=api_json('GET',f'/scraps/{detail_id}/results')
            if lead_rows: st.dataframe([r['data'] for r in lead_rows],use_container_width=True,hide_index=True)
            else: st.warning('The job completed, but no qualified leads were produced.')
        except Exception as exc: st.error(f'Could not load Scrap details: {exc}')
    st.caption('History is retained for 31 days; older completed Scraps are automatically purged.')
elif page=='Exports':
    st.title('Exports')
    exports=api_json('GET','/exports')
    if not exports: st.info('No completed exports yet.')
    else:
        grouped={}
        for ex in exports: grouped.setdefault((ex['scrap_id'],ex['scrap_name']),[]).append(ex)
        for (scrap_id,scrap_name),items in grouped.items():
            st.subheader(scrap_name)
            for ex in items:
                st.write(f"{ex['format'].upper()} — {ex['created_at'][:19].replace('T',' ')}")
                if ex['format'] in ('csv','xlsx'):
                    try:
                        data=api('GET',f"/scraps/{scrap_id}/exports/{ex['id']}/download").content
                        st.download_button(f"DOWNLOAD {ex['format'].upper()}",data=data,file_name=f"scrappee-{scrap_id}.{ex['format']}",key=f"download-{ex['id']}")
                    except requests.RequestException as exc:
                        st.caption(f"Download unavailable: {exc}")
elif page=='Settings':
    st.title('Settings')
    st.subheader('Generic Mailbox Prefixes')
    st.caption('Add mailbox prefixes you do not want captured. These exclusions apply only to your account.')
    with st.form('add-prefix'):
        prefix=st.text_input('Mailbox prefix to exclude',placeholder='e.g. info, sales, support')
        if st.form_submit_button('ADD PREFIX'):
            try:
                r=api('POST','/settings/generic-mailbox-prefixes',json={'prefix':prefix});r.raise_for_status();st.success('Prefix added.');st.rerun()
            except Exception as exc: st.error(f'Could not add prefix: {exc}')
    try: prefixes=api_json('GET','/settings/generic-mailbox-prefixes')
    except Exception as exc: st.error(f'Could not load mailbox prefixes: {exc}'); prefixes=[]
    if prefixes:
        for item in prefixes:
            cols=st.columns([6,1]);cols[0].code(item['prefix'])
            if cols[1].button('REMOVE',key=f"prefix-{item['id']}"):
                r=api('DELETE',f"/settings/generic-mailbox-prefixes/{item['id']}");r.raise_for_status();st.rerun()
    else:
        st.caption('No mailbox prefixes excluded.')
    st.divider()
    st.subheader('Domain Rules')
    st.caption('Control which domains are excluded or allowed during lead collection. Blacklist always wins.')
    with st.form('add-domain-rule'):
        domain=st.text_input('Domain',placeholder='example.com')
        rule_type=st.selectbox('Rule',['blacklist','whitelist'])
        if st.form_submit_button('ADD DOMAIN RULE'):
            try:
                r=api('POST','/settings/domain-rules',json={'domain':domain,'rule_type':rule_type});r.raise_for_status();st.success('Domain rule added.');st.rerun()
            except Exception as exc: st.error(f'Could not add domain rule: {exc}')
    try: rules=api_json('GET','/settings/domain-rules')
    except Exception as exc: st.error(f'Could not load domain rules: {exc}'); rules=[]
    if rules:
        for item in rules:
            cols=st.columns([5,2,1]);cols[0].code(item['domain']);cols[1].write(item['rule_type'].upper())
            if cols[2].button('REMOVE',key=f"domain-rule-{item['id']}"):
                r=api('DELETE',f"/settings/domain-rules/{item['id']}");r.raise_for_status();st.rerun()
    else:
        st.caption('No domain rules configured.')
    st.divider()
    admin_emails={x.strip().lower() for x in os.getenv('ADMIN_EMAILS','').split(',') if x.strip()}
    if st.session_state.user['email'].lower() in admin_emails:
        admin_tabs=st.tabs(['Billing & Limits','Wallets','Users','SERP Providers','Client Policies','Browser Extension'])
        with admin_tabs[0]:
            st.subheader('Billing & Research Limits')
            try:
                bill=api_json('GET','/billing')
                with st.form('admin-limits'):
                    scrap_price=st.number_input('New Scrap price ($)',min_value=0.0,value=bill['scrap_creation_price_cents']/100,step=0.01)
                    premium_price=st.number_input('Premium SERP price ($)',min_value=0.0,value=bill['premium_serp_price_cents']/100,step=0.01)
                    admin_research=api_json('GET','/admin/settings')
                    serp_limit=st.number_input('SERP result limit',min_value=1,max_value=1000000,value=int(admin_research.get('serp_result_limit',1000)),step=100)
                    default_max_leads=st.number_input('Default leads per Scrap',min_value=1,max_value=100000,value=int(admin_research.get('research_default_max_leads',100)),step=10)
                    max_leads_limit=st.number_input('Maximum leads allowed per Scrap',min_value=1,max_value=100000,value=int(admin_research.get('research_max_leads',10000)),step=10)
                    timeout_hours=st.number_input('Research timeout (hours)',min_value=1,max_value=720,value=int(admin_research.get('research_timeout_hours',48)),step=1)
                    st.caption('A Scrap stops when it reaches its lead target or the research timeout, whichever comes first.')
                    if st.form_submit_button('SAVE BILLING & LIMITS',type='primary'):
                        if default_max_leads > max_leads_limit: st.error('Default leads cannot exceed the maximum allowed leads.')
                        else:
                            api('POST','/admin/scrap-price',params={'amount_cents':round(scrap_price*100)}).raise_for_status()
                            api('POST','/admin/premium-serp-price',json={'amount_cents':round(premium_price*100)}).raise_for_status()
                            api('POST','/admin/serp-limit',json={'limit':int(serp_limit)}).raise_for_status()
                            api('POST','/admin/research-settings',json={'default_max_leads':int(default_max_leads),'max_leads':int(max_leads_limit),'timeout_hours':int(timeout_hours)}).raise_for_status();st.success('Billing and research limits saved.');st.rerun()
            except Exception as exc: st.error(f'Could not load admin billing settings: {exc}')
        with admin_tabs[1]:
            st.subheader('Wallet Adjustments')
            st.caption('Add or remove wallet credit for any user.')
            try:
                wallets=api_json('GET','/admin/wallets')
                st.dataframe([{'Email':w['email'],'Balance':f"${w['balance_cents']/100:.2f}"} for w in wallets],use_container_width=True,hide_index=True)
                with st.form('admin-wallet-adjust'):
                    wallet_emails=[w['email'] for w in wallets]
                    wallet_email=st.selectbox('User',wallet_emails) if wallet_emails else st.text_input('User email')
                    wallet_amount=st.number_input('Adjustment ($)',value=0.0,step=1.0,help='Positive adds credit; negative removes credit.')
                    if st.form_submit_button('APPLY WALLET ADJUSTMENT',type='primary'):
                        cents=round(wallet_amount*100)
                        if cents==0: raise ValueError('Adjustment cannot be zero.')
                        r=api('POST','/admin/wallet-adjust',json={'user_email':wallet_email,'amount_cents':cents});r.raise_for_status();st.rerun()
            except Exception as exc: st.error(f'Could not load wallet administration: {exc}')
        with admin_tabs[2]:
            st.subheader('Users')
            st.caption('Delete test or unwanted accounts. Deletion cascades all owned data. The logged-in admin cannot delete itself.')
            try:
                user_filter=st.text_input('Filter users by email',key='admin-user-filter',placeholder='e.g. test@ or @example.com')
                page_size=st.selectbox('Users per page',[25,50,100,200],index=[25,50,100,200].index(st.session_state.admin_user_page_size),key='admin-user-page-size')
                if page_size != st.session_state.admin_user_page_size:
                    st.session_state.admin_user_page_size=page_size;st.session_state.admin_user_page=1;st.rerun()
                data=api_json('GET','/admin/users/paged',params={'page':st.session_state.admin_user_page,'page_size':page_size,'search':user_filter.strip()})
                users=data['users'];total=data['total'];total_pages=max(1,data['total_pages'])
                if st.session_state.admin_user_page > total_pages:
                    st.session_state.admin_user_page=total_pages;st.rerun()
                visible_ids={u['id'] for u in users if u['email'].lower()!=st.session_state.user['email'].lower()}
                selected_count=len(st.session_state.admin_selected_users)
                st.write(f"{total} users found · page {data['page']} of {total_pages}")
                top=st.columns([2,2,4])
                new_ids=visible_ids-st.session_state.admin_selected_users
                if top[0].button('SELECT ALL ON PAGE',key='admin-select-page',disabled=(not new_ids or selected_count + len(new_ids) > 200)):
                    st.session_state.admin_selected_users.update(new_ids)
                    for uid in new_ids: st.session_state[f'admin-select-user-{uid}']=True
                    st.rerun()
                if top[1].button('CLEAR SELECTION',key='admin-clear-users',disabled=not st.session_state.admin_selected_users):
                    for uid in list(st.session_state.admin_selected_users): st.session_state[f'admin-select-user-{uid}']=False
                    st.session_state.admin_selected_users.clear();st.rerun()
                if selected_count:
                    st.warning(f'{selected_count} user(s) selected')
                    if selected_count > 200: st.error('Selection cannot exceed 200 users.')
                    elif st.button(f'DELETE SELECTED ({selected_count})',key='admin-delete-selected',type='primary',disabled=selected_count==0):
                        st.session_state.pending_bulk_delete_users=list(st.session_state.admin_selected_users);st.rerun()
                    if st.session_state.pending_bulk_delete_users:
                        ids=st.session_state.pending_bulk_delete_users
                        st.warning(f'Delete {len(ids)} selected user(s) permanently? This cannot be undone.')
                        confirm,cancel=st.columns(2)
                        if confirm.button('CONFIRM BULK DELETE',key='confirm-bulk-delete-users',type='primary'):
                            try:
                                r=api('POST','/admin/users/bulk-delete',json={'user_ids':ids});r.raise_for_status();deleted=r.json()['deleted']
                                for uid in ids: st.session_state.pop(f'admin-select-user-{uid}',None)
                                st.session_state.admin_selected_users.clear();st.session_state.pending_bulk_delete_users=None;st.success(f'Deleted {deleted} user(s).');st.rerun()
                            except requests.RequestException as exc: st.error(f'Could not delete selected users: {exc}')
                        if cancel.button('CANCEL',key='cancel-bulk-delete-users'): st.session_state.pending_bulk_delete_users=None;st.rerun()
                for u in users:
                    cols=st.columns([1,5,2,1])
                    is_self=u['email'].lower()==st.session_state.user['email'].lower()
                    cols[0].checkbox('Select',value=(u['id'] in st.session_state.admin_selected_users),key=f"admin-select-user-{u['id']}",label_visibility='collapsed',disabled=is_self,on_change=toggle_admin_user,args=(u['id'],))
                    cols[1].write(u['email']);cols[2].write(f"${u['balance_cents']/100:.2f}")
                    if cols[3].button('DELETE',key=f"admin-delete-user-{u['id']}"):
                        st.session_state.pending_delete_user=u['id'];st.rerun()
                    if st.session_state.pending_delete_user==u['id']:
                        st.warning(f"Delete user '{u['email']}' permanently? This cannot be undone.")
                        confirm,cancel=st.columns(2)
                        if confirm.button('CONFIRM DELETE',key=f"confirm-delete-user-{u['id']}",type='primary'):
                            try:
                                r=api('DELETE',f"/admin/users/{u['id']}");r.raise_for_status();st.session_state.admin_selected_users.discard(u['id']);st.session_state.pending_delete_user=None;st.rerun()
                            except requests.RequestException as exc: st.error(f'Could not delete user: {exc}')
                        if cancel.button('CANCEL',key=f"cancel-delete-user-{u['id']}"): st.session_state.pending_delete_user=None;st.rerun()
                nav=st.columns([1,1,2,1,1])
                if nav[0].button('FIRST',disabled=data['page']<=1,key='admin-users-first'): st.session_state.admin_user_page=1;st.rerun()
                if nav[1].button('PREVIOUS',disabled=data['page']<=1,key='admin-users-prev'): st.session_state.admin_user_page-=1;st.rerun()
                nav[2].write(f"Page {data['page']} / {total_pages}")
                if nav[3].button('NEXT',disabled=data['page']>=total_pages,key='admin-users-next'): st.session_state.admin_user_page+=1;st.rerun()
                if nav[4].button('LAST',disabled=data['page']>=total_pages,key='admin-users-last'): st.session_state.admin_user_page=total_pages;st.rerun()
            except Exception as exc: st.error(f'Could not load users: {exc}')
        with admin_tabs[3]:
            st.subheader('Premium SERP Providers')
            st.caption('Exactly four providers are supported. Credentials are stored encrypted server-side.')
            try: providers=api_json('GET','/admin/premium-providers')
            except Exception as exc: providers=[]; st.error(f'Could not load Premium providers: {exc}')
            for cfg in providers:
                provider=cfg['provider']; label={'serper':'Serper','dataforseo':'DataForSEO','serpapi':'SerpApi','brightdata':'Bright Data'}[provider]
                status='CONFIGURED' if cfg.get('configured') else 'NOT CONFIGURED'
                default=' — DEFAULT' if cfg['is_default'] else ''
                with st.expander(f"{label} — {status}{default}",expanded=cfg['is_default']):
                    enabled=st.checkbox('Enabled',value=cfg['enabled'],key=f'prov-enabled-{provider}')
                    make_default=st.checkbox('Make default',value=cfg['is_default'],key=f'prov-default-{provider}')
                    creds={};settings=dict(cfg.get('settings') or {})
                    if provider=='serper':
                        if cfg.get('configured'): st.caption('Credential configured — leave blank to keep the existing key.')
                        creds['api_key']=st.text_input('API key',type='password',placeholder='Configured — leave blank to keep',key=f'prov-key-{provider}')
                        settings['endpoint']=st.text_input('API URL',value=settings.get('endpoint','https://google.serper.dev/search'),key=f'prov-url-{provider}')
                    elif provider=='dataforseo':
                        if cfg.get('configured'): st.caption('Credentials configured — leave blank to keep the existing credentials.')
                        creds['login']=st.text_input('API login',type='password',placeholder='Configured — leave blank to keep',key=f'prov-login-{provider}')
                        creds['password']=st.text_input('API password',type='password',placeholder='Configured — leave blank to keep',key=f'prov-password-{provider}')
                        settings['base_url']=st.text_input('API URL',value=settings.get('base_url','https://api.dataforseo.com'),key=f'prov-url-{provider}')
                        settings['location_code']=st.number_input('Location code',value=int(settings.get('location_code',2840)),min_value=1,key=f'prov-location-{provider}')
                        settings['language_code']=st.text_input('Language code',value=settings.get('language_code','en'),key=f'prov-language-{provider}')
                    elif provider=='serpapi':
                        if cfg.get('configured'): st.caption('Credential configured — leave blank to keep the existing key.')
                        creds['api_key']=st.text_input('API key',type='password',placeholder='Configured — leave blank to keep',key=f'prov-key-{provider}')
                        settings['endpoint']=st.text_input('API URL',value=settings.get('endpoint','https://serpapi.com/search.json'),key=f'prov-url-{provider}')
                    else:
                        if cfg.get('configured'): st.caption('Credential configured — leave blank to keep the existing key.')
                        creds['api_key']=st.text_input('API key',type='password',placeholder='Configured — leave blank to keep',key=f'prov-key-{provider}')
                        settings['endpoint']=st.text_input('API URL',value=settings.get('endpoint','https://api.brightdata.com/request'),key=f'prov-url-{provider}')
                        settings['zone']=st.text_input('SERP zone',value=settings.get('zone','serp_api1'),key=f'prov-zone-{provider}')
                    if st.button('SAVE PROVIDER',key=f'prov-save-{provider}',type='primary'):
                        try: api('POST',f'/admin/premium-providers/{provider}',json={'credentials':creds,'settings':settings,'enabled':enabled,'make_default':make_default}).raise_for_status();st.rerun()
                        except Exception as exc: st.error(f'Could not save {label}: {exc}')
        with admin_tabs[4]:
            st.subheader('Client Policies')
            st.caption('Client-specific Generic Mailbox Prefixes and Domain Rules.')
            st.subheader('Generic Mailbox Prefixes')
            st.caption('Blocked mailbox prefixes are client-specific. Add or remove prefixes without affecting other clients.')
            with st.form('admin-add-prefix'):
                prefix=st.text_input('Add generic mailbox prefix',placeholder='e.g. procurement',key='admin-generic-mailbox-prefix')
                if st.form_submit_button('ADD PREFIX'):
                    try:
                        r=api('POST','/settings/generic-mailbox-prefixes',json={'prefix':prefix});r.raise_for_status();st.success('Prefix added.');st.rerun()
                    except Exception as exc: st.error(f'Could not add prefix: {exc}')
            try: prefixes=api_json('GET','/settings/generic-mailbox-prefixes')
            except Exception as exc: st.error(f'Could not load mailbox prefixes: {exc}'); prefixes=[]
            for item in prefixes:
                cols=st.columns([6,1]);cols[0].code(item['prefix'])
                if cols[1].button('REMOVE',key=f"admin-prefix-{item['id']}"):
                    r=api('DELETE',f"/settings/generic-mailbox-prefixes/{item['id']}");r.raise_for_status();st.rerun()
            st.divider()
            st.subheader('Domain Rules')
            st.caption('Blacklist rejects matching domains. If whitelist rules exist, only whitelisted domains are eligible; blacklist always wins.')
            with st.form('admin-add-domain-rule'):
                domain=st.text_input('Domain',placeholder='example.com',key='admin-domain-rule-domain')
                rule_type=st.selectbox('Rule',['blacklist','whitelist'],key='admin-domain-rule-type')
                if st.form_submit_button('ADD DOMAIN RULE'):
                    try:
                        r=api('POST','/settings/domain-rules',json={'domain':domain,'rule_type':rule_type});r.raise_for_status();st.success('Domain rule added.');st.rerun()
                    except Exception as exc: st.error(f'Could not add domain rule: {exc}')
            try: rules=api_json('GET','/settings/domain-rules')
            except Exception as exc: st.error(f'Could not load domain rules: {exc}'); rules=[]
            for item in rules:
                cols=st.columns([5,2,1]);cols[0].code(item['domain']);cols[1].write(item['rule_type'].upper())
                if cols[2].button('REMOVE',key=f"admin-domain-rule-{item['id']}"):
                    r=api('DELETE',f"/settings/domain-rules/{item['id']}");r.raise_for_status();st.rerun()
        with admin_tabs[5]:
            st.subheader('Browser Extension')
            st.code(PUBLIC_API_URL);st.caption('Authenticated API endpoint used by the browser extension for SERP capture sync.')
