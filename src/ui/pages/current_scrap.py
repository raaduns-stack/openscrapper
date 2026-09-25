import requests
import streamlit as st

from src.ui.components.header import render_header


def render_current_scrap(api, api_json, refresh_current, billing, job_telemetry, auto_refresh_job):
    render_header('Current Scrap')
    if not st.session_state.scrap_id:st.info('No current scrap. Create one from New Scrap.');st.stop()
    try:
        live_data=api_json('GET',f'/scraps/{st.session_state.scrap_id}')
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            st.session_state.scrap_id=None;st.session_state.serp_token=None;st.session_state.parameters=[];st.info('The current Scrap is no longer available. Create or select another Scrap.');st.stop()
        st.error(f'Could not load current Scrap: {exc}');st.stop()
    if not st.session_state.serp_token:
        refresh_current()
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
    candidate_count=(current_job or {}).get('counts',{}).get('lead_candidates',0)
    final_count=live['counts']['leads']
    a,b,c,d,e,f=st.columns(6);a.metric('SERP results',live['counts']['serp_results']);b.metric('URL occurrences',live['counts']['url_occurrences']);c.metric('Lead candidates',candidate_count);d.metric('Final leads',final_count);e.metric('LLM calls',live['counts'].get('llm_calls',0));f.metric('SERP capacity',f"{live['counts']['serp_results']} / {live['serp_limit']}")
    if live['counts']['serp_results'] >= live['serp_limit']: st.warning('SERP capacity reached. Further SERP imports are blocked until this Scrap is closed.')
    research_running = live['status']=='running' and current_job and current_job.get('status') in ('queued','running')
    if research_running:
        st.success('Research is running. Collection is closed for this Scrap.')
        if current_job:
            st.subheader('Ongoing Research')
            jc1,jc2,jc3=st.columns(3);jc1.metric('Job status',current_job.get('status','').title());jc2.metric('Current stage',current_job.get('stage','—'));jc3.metric('Final leads',current_job.get('lead_count') or current_job.get('counts',{}).get('leads') or live['counts']['leads'])
            if current_job.get('message'): st.info(current_job['message'])
            latest,collection_counts=job_telemetry(current_job);counts=current_job.get('counts') or {};mc=st.columns(4)
            mc[0].metric('URLs',collection_counts.get('urls_submitted',counts.get('urls',counts.get('url_occurrences',live['counts']['url_occurrences']))));mc[1].metric('Pages',collection_counts.get('pages_collected',counts.get('pages',counts.get('crawl_pages',live['counts']['crawl_pages']))));mc[2].metric('Evidence',counts.get('evidence',live['counts'].get('evidence',0)));mc[3].metric('Lead candidates',counts.get('lead_candidates',0))
            st.caption(f"Final deduplicated leads: **{current_job.get('lead_count') or counts.get('leads') or live['counts']['leads']}**")
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
        st.success("{} lead(s) have been captured and saved.".format(len(captured_leads)))
        captured_leads_data = [r["data"] for r in captured_leads]
        if st.button("OPEN LEAD WORKSTATION", type="primary", use_container_width=True, key="open-lead-workstation"):
            st.session_state.nav_page='Lead Workstation'; st.rerun()
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
                    r=api('POST',f"/scraps/{st.session_state.scrap_id}/complete-submission"); r.raise_for_status()
                    st.session_state.submission_completed=True
                    st.success('URL submission completed. Research is now ready to start.')
                    st.rerun()
                except Exception as exc: st.error(f'Could not complete URL submission: {exc}')
        else:
            st.button('URL SUBMISSION COMPLETED',disabled=True,use_container_width=True)
    elif live['status']=='submitted' and current_urls:
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
        job_type=(job.get("payload") or {}).get("type","research")
        st.subheader("Enrichment job" if "enrichment" in job_type else "Research job")
        jc1,jc2,jc3=st.columns(3)
        jc1.metric('Status',job.get('status','').title())
        jc2.metric('Stage',job.get('stage','—'))
        jc3.metric('Leads',job.get('lead_count') or (job.get('counts') or {}).get('leads') or live['counts']['leads'])
        if job.get('message'): st.info(job['message'])
        counts=job.get('counts') or {}
        if counts:
            labels=[('URLs',counts.get('urls_submitted') or counts.get('urls') or counts.get('url_occurrences')),('Pages',counts.get('pages_collected') or counts.get('pages') or counts.get('crawl_pages')),('Evidence',counts.get('evidence')),('Leads',job.get('lead_count') or counts.get('leads') or live['counts']['leads'])]
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
