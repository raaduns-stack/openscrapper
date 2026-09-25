import requests
import streamlit as st

def render_client_policies(api, api_json, api_error, **kwargs):
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
