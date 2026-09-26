from __future__ import annotations

import streamlit as st

def render_configuration(api, api_error, senders):
    oauth_status=st.query_params.get('sender_oauth')
    if oauth_status=='success': st.success('Google account connected successfully.')
    elif oauth_status=='error': st.error('Google authorization was not completed. No Gmail credentials were stored.')
    if oauth_status: st.query_params.clear()
    st.subheader('Sender Configuration'); st.caption('Configure and test sender accounts. Secrets remain server-side.')
    with st.expander('＋ Add sender',expanded=not bool(senders)):
        provider=st.selectbox('Provider',['smtp','gmail_oauth','microsoft_oauth'],format_func=lambda value:{'smtp':'SMTP','gmail_oauth':'Gmail OAuth','microsoft_oauth':'Microsoft / Hotmail OAuth'}[value],key='sender-create-provider')
        with st.form('sender-create'):
            st.markdown('**Sender identity**')
            c1,c2=st.columns(2)
            with c1: name=st.text_input('Display name')
            with c2: email=st.text_input('Sender email')
            if provider=='smtp':
                st.markdown('**SMTP connection**')
                c1,c2=st.columns(2)
                with c1: host=st.text_input('SMTP host'); username=st.text_input('SMTP username')
                with c2: port=st.number_input('SMTP port',1,65535,587); password=st.text_input('SMTP password / app password',type='password')
                o1,o2=st.columns(2)
                with o1: tls=st.checkbox('STARTTLS',True)
                with o2: ssl_mode=st.checkbox('SSL',False)
                allow_self_signed=st.checkbox('Allow self-signed certificate (security exception)',True,help='Certificate verification is disabled for this sender. Turn this off when the SMTP server has a trusted certificate.')
            else:
                host=''; port=587; username=''; password=''; tls=False; ssl_mode=False; allow_self_signed=False
                provider_name='Gmail' if provider=='gmail_oauth' else 'Microsoft / Hotmail'
                st.info(f'{provider_name} OAuth authorization will be connected after the sender is created. SMTP credentials are not required.')
            b1,b2=st.columns(2)
            with b1: create=st.form_submit_button('ADD SENDER',type='primary',use_container_width=True)
            with b2: create_test=st.form_submit_button('ADD & TEST CONNECTION',use_container_width=True,disabled=provider!='smtp')
        if create or create_test:
            payload={'display_name':name,'email':email,'provider':provider,'config':{'host':host,'port':port,'username':username,'tls':tls,'ssl':ssl_mode,'allow_self_signed_certificate':allow_self_signed},'password':password}
            try:
                response=api('POST','/senders',json=payload); response.raise_for_status()
                sender=response.json()
                if create_test:
                    test=api('POST',f"/senders/{sender['id']}/test")
                    if not test.ok:
                        api('DELETE',f"/senders/{sender['id']}")
                        test.raise_for_status()
                    st.success('Sender added and SMTP connection verified successfully.')
                else:
                    st.success('Sender added. Use TEST on the sender card to verify the connection.')
                st.rerun()
            except Exception as exc:
                st.error(api_error(exc,'Could not add/test sender. Failed test configuration was not retained.'))
    for sender in senders:
        with st.container(border=True):
            status_icon='🟢' if sender['health']=='healthy' else ('🔴' if sender['health']=='unhealthy' else '⚪')
            x,e,y,z=st.columns([6,1,1,1])
            x.markdown(f"**{sender['display_name']}**  \
{sender['email']} · {sender['provider']} · {status_icon}")
            if e.button('EDIT',key=f"edit-{sender['id']}"):
                st.session_state[f"edit_sender_{sender['id']}"]=not st.session_state.get(f"edit_sender_{sender['id']}",False)
            if sender['provider']=='smtp' and y.button('TEST',key=f"test-{sender['id']}"):
                try: api('POST',f"/senders/{sender['id']}/test").raise_for_status(); st.success('SMTP connection successful.'); st.rerun()
                except Exception as exc: st.error(api_error(exc,'SMTP connection failed.'))
            if z.button('DELETE',key=f"delete-{sender['id']}"): api('DELETE',f"/senders/{sender['id']}").raise_for_status(); st.rerun()
        if sender['provider']=='gmail_oauth':
            try:
                oauth=api('GET',f"/senders/{sender['id']}").json()
                connected=bool((oauth.get('config') or {}).get('oauth_email'))
                if connected:
                    st.success(f"Google account connected: {(oauth.get('config') or {}).get('oauth_email')}")
                    if st.button('DISCONNECT GOOGLE',key=f"disconnect-google-{sender['id']}"):
                        api('POST',f"/senders/{sender['id']}/oauth/gmail/disconnect").raise_for_status(); st.rerun()
                else:
                    auth_key=f"gmail-auth-url-{sender['id']}"
                    if st.button('CONNECT GOOGLE ACCOUNT',key=f"connect-google-{sender['id']}",type='primary'):
                        response=api('GET',f"/senders/{sender['id']}/oauth/gmail/start"); response.raise_for_status()
                        st.session_state[auth_key]=response.json()['authorization_url']
                    if st.session_state.get(auth_key):
                        st.link_button('CONTINUE WITH GOOGLE',st.session_state[auth_key],use_container_width=True)
                        st.caption('You will be redirected to Google to authorize Gmail sending. Scrappee never receives your Google password.')
            except Exception as exc:
                st.error(api_error(exc,'Could not load Gmail connection status.'))
        if st.session_state.get(f"edit_sender_{sender['id']}",False):
            try:
                detail=api('GET',f"/senders/{sender['id']}"); detail.raise_for_status(); detail=detail.json()
                cfg=detail.get('config') or {}
                with st.form(f"edit-form-{sender['id']}"):
                    edit_provider=st.selectbox('Provider',['smtp','gmail_oauth','microsoft_oauth'],index=['smtp','gmail_oauth','microsoft_oauth'].index(detail['provider']),format_func=lambda value:{'smtp':'SMTP','gmail_oauth':'Gmail OAuth','microsoft_oauth':'Microsoft / Hotmail OAuth'}[value],disabled=True)
                    a,b=st.columns(2)
                    with a:
                        edit_name=st.text_input('Display name',value=detail['display_name'])
                        edit_email=st.text_input('Sender email',value=detail['email'])
                    with b:
                        edit_host=st.text_input('SMTP host',value=cfg.get('host',''),disabled=detail['provider']!='smtp')
                        edit_port=st.number_input('SMTP port',1,65535,int(cfg.get('port',587)),disabled=detail['provider']!='smtp')
                        edit_username=st.text_input('SMTP username',value=cfg.get('username',''),disabled=detail['provider']!='smtp')
                    edit_password=st.text_input('New SMTP password / app password (leave blank to keep current)',type='password',disabled=detail['provider']!='smtp')
                    q1,q2=st.columns(2)
                    with q1: edit_tls=st.checkbox('STARTTLS',bool(cfg.get('tls',True)),disabled=detail['provider']!='smtp')
                    with q2: edit_ssl=st.checkbox('SSL',bool(cfg.get('ssl',False)),disabled=detail['provider']!='smtp')
                    edit_self_signed=st.checkbox('Allow self-signed certificate (security exception)',bool(cfg.get('allow_self_signed_certificate',True)),disabled=detail['provider']!='smtp')
                    s1,s2=st.columns(2)
                    with s1: save_edit=st.form_submit_button('SAVE CHANGES',type='primary',use_container_width=True)
                    with s2: test_after=st.form_submit_button('SAVE & TEST',use_container_width=True,disabled=detail['provider']!='smtp')
                if save_edit or test_after:
                    payload={'display_name':edit_name,'email':edit_email,'config':{'host':edit_host,'port':edit_port,'username':edit_username,'tls':edit_tls,'ssl':edit_ssl,'allow_self_signed_certificate':edit_self_signed}}
                    if edit_password: payload['password']=edit_password
                    try:
                        updated=api('PATCH',f"/senders/{sender['id']}",json=payload); updated.raise_for_status()
                        if test_after:
                            test=api('POST',f"/senders/{sender['id']}/test")
                            test.raise_for_status()
                            st.success('Sender updated and connection verified.')
                        else: st.success('Sender updated.')
                        st.session_state[f"edit_sender_{sender['id']}"]=False
                        st.rerun()
                    except Exception as exc: st.error(api_error(exc,'Could not update/test sender.'))
            except Exception as exc: st.error(api_error(exc,'Could not load sender configuration.'))
    if not senders: st.info('No sender accounts configured.')
