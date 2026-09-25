from __future__ import annotations

import streamlit as st

def render_configuration(api, api_error, senders):
    st.subheader('Sender Configuration'); st.caption('Configure and test sender accounts. Secrets remain server-side.')
    with st.expander('＋ Add sender',expanded=not bool(senders)):
        with st.form('sender-create'):
            c1,c2=st.columns(2)
            with c1: name=st.text_input('Display name'); email=st.text_input('Sender email'); provider=st.selectbox('Provider',['smtp','gmail_oauth','microsoft_oauth'])
            with c2: host=st.text_input('SMTP host',disabled=provider!='smtp'); port=st.number_input('SMTP port',1,65535,587,disabled=provider!='smtp'); username=st.text_input('SMTP username',disabled=provider!='smtp')
            password=st.text_input('SMTP password / app password',type='password',disabled=provider!='smtp')
            o1,o2=st.columns(2)
            with o1: tls=st.checkbox('STARTTLS',True,disabled=provider!='smtp')
            with o2: ssl_mode=st.checkbox('SSL',False,disabled=provider!='smtp')
            create=st.form_submit_button('ADD SENDER',type='primary',use_container_width=True)
        if create:
            try: api('POST','/senders',json={'display_name':name,'email':email,'provider':provider,'config':{'host':host,'port':port,'username':username,'tls':tls,'ssl':ssl_mode},'password':password}).raise_for_status(); st.success('Sender added.'); st.rerun()
            except Exception as exc: st.error(api_error(exc,'Could not add sender.'))
    for sender in senders:
        with st.container(border=True):
            x,y,z=st.columns([5,1,1]); x.markdown(f"**{sender['display_name']}**  \
{sender['email']} · {sender['provider']} · {sender['health']}")
            if sender['provider']=='smtp' and y.button('TEST',key=f"test-{sender['id']}"):
                try: api('POST',f"/senders/{sender['id']}/test").raise_for_status(); st.success('SMTP connection successful.'); st.rerun()
                except Exception as exc: st.error(api_error(exc,'SMTP connection failed.'))
            if z.button('DELETE',key=f"delete-{sender['id']}"): api('DELETE',f"/senders/{sender['id']}").raise_for_status(); st.rerun()
    if not senders: st.info('No sender accounts configured.')
