import requests
import streamlit as st
from src.ui.components.header import render_header


def render_settings(api, api_json):
    render_header('Settings')
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
