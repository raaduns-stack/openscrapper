import pandas as pd
import streamlit as st

from src.ui.components.header import render_header


def render_lead_workstation(api, api_json, billing, api_error):
    render_header('Lead Workstation')
    try:
        current=api_json('GET','/scraps/current')
        if current and current.get('id') != st.session_state.scrap_id:
            st.session_state.scrap_id=current['id']; st.session_state.serp_token=None
        elif not current:
            st.session_state.scrap_id=None
    except Exception as exc:
        st.error(f'Could not resolve Current Scrap: {api_error(exc)}')
        st.stop()
    if not st.session_state.scrap_id:
        st.info('No current Scrap. Create one from New Scrap.')
        st.stop()
    try:
        workstation=api_json('GET',f'/scraps/{st.session_state.scrap_id}/workstation')
    except Exception as exc:
        st.error(f'Could not load Lead Workstation: {api_error(exc)}')
        st.stop()
    scrap=workstation['scrap']; leads=workstation['leads']; counts=workstation['counts']
    import pandas as pd
    if st.session_state.get('workstation_notice'):
        st.success(st.session_state.pop('workstation_notice'))
    workstation_job = None
    if st.session_state.get('job'):
        try:
            workstation_job = api_json('GET', f"/jobs/{st.session_state.job}")
        except Exception:
            workstation_job = None
    if workstation_job and workstation_job.get('status') == 'failed':
        st.error(f"Paid Enrichment failed: {workstation_job.get('error') or workstation_job.get('message') or 'unknown error'}")
        st.caption(f"Job `{workstation_job.get('job_id')}` · Stage: {workstation_job.get('stage','Failed')}")
    elif workstation_job and workstation_job.get('status') == 'canceled':
        st.warning(f"Paid Enrichment canceled. Job `{workstation_job.get('job_id')}`.")
    elif workstation_job and workstation_job.get('status') == 'completed':
        c=workstation_job.get('counts',{}); st.success(f"Paid Enrichment completed · {c.get('leads_enriched',0)} Lead(s) enriched · {c.get('leads_discovered',0)} new Lead(s) discovered.")
        payload = workstation_job.get('payload') or {}
        result = workstation_job.get('result') or {}
        enrichment_counts = result.get('counts') or {}
        st.subheader('Last Enrichment')
        lc1, lc2, lc3, lc4, lc5 = st.columns(5)
        lead_ids = payload.get('lead_ids') or []
        lead_label = ', '.join(str(x) for x in lead_ids) if lead_ids else 'Unknown'
        if len(lead_ids) == 1:
            lead_rows = [x for x in leads if str(x.get('id')) == str(lead_ids[0])]
            if lead_rows:
                d = lead_rows[0].get('data') or {}
                lead_label = f"{d.get('first_name') or ''} {d.get('last_name') or ''}".strip() or lead_label
        lc1.metric('Lead', lead_label)
        lc2.metric('Status', 'Completed')
        lc3.metric('Existing Enriched', enrichment_counts.get('leads_enriched', 0))
        lc4.metric('New Leads', enrichment_counts.get('leads_discovered', 0))
        lc5.metric('Charge', '$' + f"{payload.get('charged_cents', 0) / 100:.2f}")
        changed = [e for e in (result.get('events') or []) if e.get('message') == 'Evidence-backed Lead corrections applied']
        if changed:
            st.subheader('Enrichment Changes')
            for event in changed:
                fields = event.get('counts', {}).get('changed_fields') or event.get('changed_fields') or {}
                if fields:
                    st.dataframe(pd.DataFrame([{"Field": field, "Before": values.get('before'), "After": values.get('after')} for field, values in fields.items()]), hide_index=True, use_container_width=True)
        else:
            st.info('Enrichment completed, but no Lead fields were changed.')
    elif workstation_job and workstation_job.get('status') in ('queued','running'):
        c=workstation_job.get('counts',{}); st.info(f"Paid Enrichment is {workstation_job.get('status')}. Stage: {workstation_job.get('stage','Starting')} · {c.get('leads_enriched',0)} enriched · {c.get('leads_discovered',0)} new.")
        payload = workstation_job.get('payload') or {}
        lead_ids = payload.get('lead_ids') or []
        if lead_ids:
            submitted_labels = []
            for lead_id in lead_ids:
                row = next((x for x in leads if str(x.get('id')) == str(lead_id)), None)
                if row:
                    data = row.get('data') or {}
                    name = f"{data.get('first_name') or ''} {data.get('last_name') or ''}".strip()
                    submitted_labels.append(name or str(lead_id))
                else:
                    submitted_labels.append(str(lead_id))
            st.caption("Submitted Lead(s): " + ", ".join(submitted_labels))
        if st.button('↻ REFRESH ENRICHMENT STATUS', key='refresh-workstation-enrichment'):
            st.rerun()
    st.caption(f"Scrap: **{scrap['name']}** · `{scrap['id']}` · Status: **{scrap['status'].title()}**")
    c1,c2,c3=st.columns(3); c1.metric('Total Leads',counts['total']); c2.metric('Working',counts['working']); c3.metric('Completed',counts['completed'])
    st.info('Review, clean, edit, delete and approve Leads for this Scrap. Completed Leads are locked from further automatic processing.')
    if not leads:
        st.info('No Leads are available for this Scrap.')
    else:
        editable_fields=['first_name','last_name','email','position','company_name','phone','city','state','country','website','source_url']
        working=[x for x in leads if x['status']=='working']
        completed=[x for x in leads if x['status']=='completed']
        original={x['id']: {field: x['data'].get(field) for field in editable_fields} for x in working}
        working_by_id={str(x['id']): x for x in working}
        if 'workstation_selection_epoch' not in st.session_state:
            st.session_state.workstation_selection_epoch=0
        st.subheader('Working Leads')
        if working:
            if billing:
                st.caption(f"Paid Enrichment: ${billing['paid_enrichment_unit_micros_usd']/1000000:.3f} per selected Lead · 10,000 Leads = ${billing['paid_enrichment_unit_micros_usd']*10000/1000000:.2f}")
            selection_key=f"workstation-selection-{st.session_state.scrap_id}-{st.session_state.workstation_selection_epoch}"
            select_all=st.checkbox('SELECT ALL WORKING LEADS',key=f"{selection_key}-all")
            rows=[]
            for item in working:
                row={'Select':select_all,'Lead ID':str(item['id'])}
                row.update({field:item['data'].get(field) for field in editable_fields})
                rows.append(row)
            editor=st.data_editor(pd.DataFrame(rows),use_container_width=True,hide_index=True,num_rows='fixed',key=selection_key,column_config={'Select':st.column_config.CheckboxColumn('Select'),'Lead ID':None})
            selected_ids=[str(row['Lead ID']) for _,row in editor.iterrows() if bool(row.get('Select',False)) and str(row['Lead ID']) in working_by_id]
            if selected_ids:
                selected_labels=[f"{working_by_id[lead_id]['data'].get('first_name') or ''} {working_by_id[lead_id]['data'].get('last_name') or ''}".strip() for lead_id in selected_ids]
                st.caption(f"Selected Lead(s): {', '.join(selected_labels)} · IDs verified against current Working Leads")
            if billing and selected_ids:
                selected_charge=max(0.01, billing['paid_enrichment_unit_micros_usd']*len(selected_ids)/1000000)
                st.caption(f"Selected: {len(selected_ids)} Lead(s) · Estimated charge: ${selected_charge:.2f}")
            discover_new_leads=st.checkbox('DISCOVER NEW LEADS DURING ENRICHMENT',value=False,key='workstation-discover-new-leads',help='When enabled, qualifying new Leads discovered by paid research may be added to this Scrap. Personal email alone is sufficient when it passes the existing personal-email qualification rule.')
            st.caption('Off: enrich only the selected Leads. On: also allow qualifying new Leads to be discovered and added.')
            actions=st.columns(5)
            if actions[0].button('PAID ENRICHMENT', use_container_width=True, key='workstation-paid-enrichment', disabled=not selected_ids):
                try:
                    response=api('POST',f'/scraps/{st.session_state.scrap_id}/enrich?mode=paid',json={'lead_ids':selected_ids,'discover_new_leads':bool(discover_new_leads)}); response.raise_for_status(); st.session_state.job=response.json()['job_id']; st.session_state.workstation_selection_epoch+=1; st.session_state.workstation_notice=f"Paid enrichment started for {len(selected_ids)} Lead(s)."; st.rerun()
                except Exception as exc: st.error(api_error(exc,'Could not start Paid Enrichment.'))
            if actions[1].button('SAVE CHANGES',type='primary',use_container_width=True,key='workstation-save'):
                saved=0; errors=[]
                for _,row in editor.iterrows():
                    lead_id=str(row['Lead ID']); data={field:(None if pd.isna(row.get(field)) else row.get(field)) for field in editable_fields}
                    if data == original.get(lead_id): continue
                    try:
                        response=api('PATCH',f'/scraps/{st.session_state.scrap_id}/leads/{lead_id}',json={'data':data}); response.raise_for_status(); saved+=1
                    except Exception as exc: errors.append(f'{lead_id}: {api_error(exc,"Could not save Lead.")}')
                if errors:
                    for error in errors: st.error(error)
                if saved: st.session_state.workstation_notice=f'Saved {saved} Lead(s) successfully.'; st.rerun()
                elif not errors: st.info('No Lead changes to save.')
            if actions[2].button('APPROVE SELECTED',use_container_width=True,key='workstation-approve',disabled=not selected_ids):
                try:
                    response=api('POST',f'/scraps/{st.session_state.scrap_id}/leads/approve',json={'lead_ids':selected_ids}); response.raise_for_status(); st.session_state.workstation_notice=f"Approved {response.json().get('approved',0)} Lead(s) successfully."; st.rerun()
                except Exception as exc: st.error(api_error(exc,'Could not approve selected Leads.'))
            if actions[3].button('DELETE SELECTED',use_container_width=True,key='workstation-delete',disabled=not selected_ids):
                try:
                    for lead_id in selected_ids:
                        response=api('DELETE',f'/scraps/{st.session_state.scrap_id}/leads/{lead_id}'); response.raise_for_status()
                    st.session_state.workstation_notice=f'Deleted {len(selected_ids)} Lead(s) successfully.'; st.rerun()
                except Exception as exc: st.error(api_error(exc,'Could not delete selected Leads.'))
            if actions[4].button('APPROVE ALL WORKING',use_container_width=True,key='workstation-approve-all',disabled=not working):
                try:
                    response=api('POST',f'/scraps/{st.session_state.scrap_id}/leads/approve',json={'lead_ids':[x['id'] for x in working]}); response.raise_for_status(); st.session_state.workstation_notice=f"Approved {response.json().get('approved',0)} Lead(s) successfully."; st.rerun()
                except Exception as exc: st.error(api_error(exc,'Could not approve working Leads.'))
        else:
            st.info('All Leads in this Scrap are completed.')
        st.subheader('Download Leads')
        export_rows=[item['data'] for item in leads]
        export_df=pd.DataFrame(export_rows)
        d1,d2=st.columns(2)
        d1.download_button('DOWNLOAD CSV',data=export_df.to_csv(index=False).encode('utf-8'),file_name=f"scrap-leads-{st.session_state.scrap_id}.csv",mime='text/csv',use_container_width=True,key='workstation-download-csv')
        xlsx_buffer=__import__('io').BytesIO()
        with pd.ExcelWriter(xlsx_buffer,engine='openpyxl') as writer: export_df.to_excel(writer,index=False,sheet_name='Leads')
        d2.download_button('DOWNLOAD XLSX',data=xlsx_buffer.getvalue(),file_name=f"scrap-leads-{st.session_state.scrap_id}.xlsx",mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True,key='workstation-download-xlsx')
        if completed:
            st.subheader('Completed Leads')
            completed_rows=[]
            for item in completed:
                row={'Lead ID':item['id']}; row.update({field:item['data'].get(field) for field in editable_fields}); completed_rows.append(row)
            st.dataframe(pd.DataFrame(completed_rows),use_container_width=True,hide_index=True,column_config={'Lead ID':None})
