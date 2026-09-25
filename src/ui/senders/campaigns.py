from __future__ import annotations

import streamlit as st

def render_campaigns(api, api_json, api_error, senders, letters, campaigns):
    st.subheader('Campaign Details'); st.caption('Create campaigns from existing completed Leads.')
    if senders and letters:
        available=api_json('GET','/campaign-leads'); lead_map={x['id']:x for x in available}
        def lead_label(i):
            x=lead_map[i]; q=x.get('data') or {}; return f"{q.get('first_name') or ''} {q.get('last_name') or ''} · {q.get('email') or 'no email'} · {q.get('company_name') or '—'}"
        with st.expander('Create campaign',expanded=not bool(campaigns)):
            with st.form('campaign-create'):
                cname=st.text_input('Campaign name'); sender_choice=st.selectbox('Sender',senders,format_func=lambda x:f"{x['display_name']} <{x['email']}>"); letter_choice=st.selectbox('Letter',letters,format_func=lambda x:x['name']); selected_leads=st.multiselect('Completed Leads',list(lead_map),format_func=lead_label); save=st.form_submit_button('CREATE CAMPAIGN',type='primary')
            if save:
                try:
                    if not selected_leads: raise ValueError('Select at least one completed Lead.')
                    api('POST','/campaigns',json={'name':cname,'sender_id':sender_choice['id'],'letter_id':letter_choice['id'],'lead_ids':selected_leads}).raise_for_status(); st.success('Campaign created as draft.'); st.rerun()
                except Exception as exc: st.error(api_error(exc,'Could not create campaign.'))
    else: st.info('Configure a sender and a letter before creating a campaign.')
    st.divider()
    if campaigns:
        for campaign in campaigns:
            selected=api_json('GET',f"/campaigns/{campaign['id']}/leads")
            with st.container(border=True):
                st.markdown(f"**{campaign['name']}**"); st.caption(f"{campaign['status'].upper()} · {len(selected)} selected Lead(s)")
                if campaign['status']=='draft' and selected:
                    choices={x['id']:x for x in selected}; choice=st.selectbox('Test recipient',list(choices),format_func=lambda i:f"{(choices[i].get('data') or {}).get('first_name') or ''} {(choices[i].get('data') or {}).get('last_name') or ''} · {(choices[i].get('data') or {}).get('email') or 'no email'}",key=f"campaign-test-lead-{campaign['id']}")
                    if st.button('SEND TEST EMAIL',key=f"campaign-test-send-{campaign['id']}",type='primary'):
                        try: api('POST',f"/campaigns/{campaign['id']}/send-test",json={'lead_id':choice}).raise_for_status(); st.success('Test email sent.'); st.rerun()
                        except Exception as exc: st.error(api_error(exc,'Could not send test email.'))
    else: st.info('No campaigns yet.')
