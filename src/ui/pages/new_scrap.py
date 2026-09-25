import re
import streamlit as st
from src.agent.query_interpreter import QueryInterpreter
from src.models.criteria import SearchCriteria
from src.ui.components.header import render_header


def render_new_scrap(api, api_json, billing, ensure_serp_session):
    render_header('New Scrap', 'Describe the leads. Scrappee builds the discovery strategy for you.')
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
