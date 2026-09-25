from __future__ import annotations
import streamlit as st
from src.ui.senders.campaigns import render_campaigns
from src.ui.senders.configuration import render_configuration
from src.ui.senders.letters import render_letters
from src.ui.senders.reply_to import render_reply_to

def render_summary(summary, senders):
    st.subheader('Sending Summary')
    a,b,c,d=st.columns(4); a.metric('Senders',summary['senders']['total']); b.metric('Healthy',summary['senders']['healthy']); c.metric('Campaigns',summary['campaigns']['total']); d.metric('Sent',summary['messages']['sent'])
    st.divider(); left,right=st.columns(2)
    with left:
        st.markdown('### Sender Health')
        if senders: st.dataframe([{'Sender':x['display_name'],'Email':x['email'],'Provider':x['provider'],'Health':x['health'],'Enabled':x['enabled']} for x in senders],use_container_width=True,hide_index=True)
        else: st.info('No sender accounts configured.')
    with right:
        st.markdown('### Message Activity'); st.metric('Queued',summary['messages']['queued']); st.metric('Sent',summary['messages']['sent']); st.metric('Failed',summary['messages']['failed']); st.metric('Replies',summary['messages']['replied'])

def render_senders(api, api_json, api_error):
    sections=['Sending Summary','Sender Configuration','Campaign Details','Letters','Reply To']
    current=st.session_state.get('sender_section','Sending Summary')
    if current not in sections: current=sections[0]
    st.markdown('''<style>.sender-hero{padding:24px 28px;border:1px solid rgba(128,128,128,.18);border-radius:18px;background:linear-gradient(135deg,rgba(255,255,255,.06),rgba(128,128,128,.04));margin-bottom:18px}.sender-hero h1{margin:0;font-size:30px;letter-spacing:-.6px}.sender-hero p{margin:5px 0 0;opacity:.65}div[data-testid="stRadio"] > label{display:none}div[data-testid="stRadio"] div[role="radiogroup"]{gap:6px;padding:5px;border:1px solid rgba(128,128,128,.18);border-radius:14px;background:rgba(128,128,128,.05)}div[data-testid="stRadio"] div[role="radiogroup"] label{border-radius:10px;padding:8px 14px;min-height:0;background:transparent;border:1px solid transparent}div[data-testid="stRadio"] div[role="radiogroup"] label:hover{background:rgba(128,128,128,.08)}div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked){background:var(--primary-color);color:white;border-color:var(--primary-color)}</style>''',unsafe_allow_html=True)
    st.markdown('<div class="sender-hero"><h1>Senders</h1><p>Configure identities, campaigns, message templates and reply routing.</p></div>',unsafe_allow_html=True)
    selected_section=st.radio('Workspace',sections,index=sections.index(current),horizontal=True,key='sender-workspace',label_visibility='collapsed'); st.session_state.sender_section=selected_section
    try: summary=api_json('GET','/sending-summary'); senders=api_json('GET','/senders'); letters=api_json('GET','/letters'); campaigns=api_json('GET','/campaigns')
    except Exception as exc: st.error(f'Could not load Senders: {api_error(exc)}'); st.stop()
    if selected_section=='Sending Summary': render_summary(summary,senders)
    elif selected_section=='Sender Configuration': render_configuration(api,api_error,senders)
    elif selected_section=='Campaign Details': render_campaigns(api,api_json,api_error,senders,letters,campaigns)
    elif selected_section=='Letters': render_letters(api,api_error,letters)
    elif selected_section=='Reply To': render_reply_to(senders)
