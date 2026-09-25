import requests
import streamlit as st

from src.ui.components.header import render_header


def render_scrap_history(api, api_json):
    render_header('Scrap History')
    rows=api_json('GET','/scraps')
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
            j1,j2,j3=st.columns(3);j1.metric('Job status',job.get('status','').title());j2.metric('Final stage',job.get('stage','—'));j3.metric('Lead count',job.get('lead_count') or (job.get('counts') or {}).get('leads') or detail['counts']['leads'])
            jc=job.get('counts') or {};m=st.columns(4)
            m[0].metric('URLs',jc.get('urls_submitted') or jc.get('urls') or jc.get('url_occurrences') or detail['counts']['url_occurrences']);m[1].metric('Pages',jc.get('pages_collected') or jc.get('pages') or jc.get('crawl_pages') or detail['counts']['crawl_pages']);m[2].metric('Evidence',jc.get('evidence',0));m[3].metric('Leads',job.get('lead_count') or jc.get('leads') or detail['counts']['leads'])
            if job.get('message'): st.info(job['message'])
            if job.get('events'): st.caption(f"Pipeline events recorded: {len(job['events'])}")
            lead_rows=api_json('GET',f'/scraps/{detail_id}/results')
            if lead_rows: st.dataframe([r['data'] for r in lead_rows],use_container_width=True,hide_index=True)
            else: st.warning('The job completed, but no qualified leads were produced.')
        except Exception as exc: st.error(f'Could not load Scrap details: {exc}')
    st.caption('History is retained for 31 days; older completed Scraps are automatically purged.')
