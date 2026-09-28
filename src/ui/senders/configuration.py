from __future__ import annotations

import streamlit as st

def render_configuration(api, api_error, senders):
    oauth_status=st.query_params.get('sender_oauth')
    if oauth_status=='success': st.success('Google account connected successfully.')
    elif oauth_status=='error': st.error('Google authorization was not completed. No Gmail credentials were stored.')
    if oauth_status: st.query_params.clear()
    test_notice=st.session_state.pop('smtp_test_notice',None)
    if test_notice: st.success(test_notice)
    st.subheader('Sender Configuration'); st.caption('Configure and test sender accounts. Secrets remain server-side.')
    with st.expander('＋ Add sender',expanded=not bool(senders)):
        provider=st.selectbox('Provider',['smtp','gmail_oauth','microsoft_oauth'],format_func=lambda value:{'smtp':'SMTP','gmail_oauth':'Gmail','microsoft_oauth':'Microsoft / Hotmail'}[value],key='sender-create-provider')
        with st.form('sender-create'):
            if provider=='smtp':
                st.markdown('**Sender identity**')
                c1,c2=st.columns(2)
                with c1: name=st.text_input('Display name')
                with c2: email=st.text_input('Sender email')
            else:
                name='Gmail' if provider=='gmail_oauth' else 'Microsoft'
                email=None
            if provider=='smtp':
                st.markdown('**SMTP connection**')
                c1,c2=st.columns(2)
                with c1: host=st.text_input('SMTP host'); username=st.text_input('SMTP username')
                with c2: port=st.number_input('SMTP port',1,65535,587); password=st.text_input('SMTP password / app password',type='password')
                o1,o2=st.columns(2)
                with o1: tls=st.checkbox('STARTTLS',True)
                with o2: ssl_mode=st.checkbox('SSL',False)
                allow_self_signed=st.checkbox('Allow self-signed certificate (security exception)',True,help='Certificate verification is disabled for this sender. Turn this off when the SMTP server has a trusted certificate.')
                st.markdown('**Send throttle**')
                t1,t2=st.columns(2)
                with t1: throttle_value=st.number_input('Interval',1,86400,60,step=1,help='Minimum time between successful outbound sends from this SMTP sender.')
                with t2: throttle_unit=st.selectbox('Unit',['Seconds','Minutes'])
            else:
                host=''; port=587; username=''; password=''; tls=False; ssl_mode=False; allow_self_signed=False
                if provider=='gmail_oauth':
                    st.markdown('**Connect your Google account**')
                    st.caption('Choose the Google account you want Scrappee to use for sending. Your Gmail address is filled in automatically after authorization. No Google password is shared with Scrappee.')
                else:
                    st.markdown('**Connect your Microsoft account**')
                    st.caption('Choose the Microsoft account you want Scrappee to use for sending. Your mailbox address is filled in automatically after authorization.')
                    st.markdown("""
                    <style>
                    .st-key-microsoft-connect button {
                        position:relative !important;
                        width:400px !important;max-width:100% !important;min-height:40px !important;
                        margin:0 auto !important;background:#fff !important;color:#1f1f1f !important;
                        border:1px solid #747775 !important;border-radius:4px !important;
                        font-family:Segoe UI,Arial,sans-serif !important;font-size:14px !important;font-weight:600 !important;
                        box-shadow:none !important;padding:0 48px !important;
                    }
                    .st-key-microsoft-connect button:hover {
                        background:#f8fafd !important;border-color:#5f6368 !important;
                    }
                    .st-key-microsoft-connect button::before {
                        content:"" !important;position:absolute !important;left:14px !important;top:50% !important;
                        transform:translateY(-50%) !important;width:18px !important;height:18px !important;
                        background:url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0MSA0MSI+PHJlY3QgeD0iMTEiIHk9IjExIiB3aWR0aD0iOSIgaGVpZ2h0PSI5IiBmaWxsPSIjZjI1MDIyIi8+PHJlY3QgeD0iMTEiIHk9IjIxIiB3aWR0aD0iOSIgaGVpZ2h0PSI5IiBmaWxsPSIjMDBhNGVmIi8+PHJlY3QgeD0iMjEiIHk9IjExIiB3aWR0aD0iOSIgaGVpZ2h0PSI5IiBmaWxsPSIjN2ZiYTAwIi8+PHJlY3QgeD0iMjEiIHk9IjIxIiB3aWR0aD0iOSIgaGVpZ2h0PSI5IiBmaWxsPSIjZmZiOTAwIi8+PC9zdmc+") center/18px 18px no-repeat !important;
                    }
                    </style>
                    """,unsafe_allow_html=True)
            if provider=='smtp':
                create=False
                create_test=st.form_submit_button('TEST AND SAVE SMTP',type='primary',use_container_width=True)
            elif provider=='gmail_oauth':
                create=False
                st.markdown("""
                <style>
                .st-key-gmail-connect button {
                    position:relative !important;
                    width:400px !important;max-width:100% !important;min-height:40px !important;
                    margin:0 auto !important;background:#fff !important;color:#1f1f1f !important;
                    border:1px solid #747775 !important;border-radius:4px !important;
                    font-family:Roboto,Arial,sans-serif !important;font-size:14px !important;font-weight:500 !important;
                    box-shadow:none !important;padding:0 48px !important;
                }
                .st-key-gmail-connect button:hover {
                    background:#f8fafd !important;border-color:#5f6368 !important;
                }
                .st-key-gmail-connect button::before {
                    content:"" !important;position:absolute !important;left:14px !important;top:50% !important;
                    transform:translateY(-50%) !important;width:18px !important;height:18px !important;
                    background:url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0OCA0OCI+PHBhdGggZmlsbD0iI0ZGQzEwNyIgZD0iTTQzLjYxMSAyMC4wODNINDJWMjBIMjR2OGgxMS4zMDNDMzMuNjU0IDMyLjY1NyAyOS4wOCAzNiAyNCAzNmMtNi42MjcgMC0xMi01LjM3My0xMi0xMnM1LjM3My0xMiAxMi0xMmMzLjA1OSAwIDUuODQyIDEuMTU0IDcuOTYxIDMuMDM5TDM3LjYxOCA5LjM4MkMzNC4wNDYgNi4wNTMgMjkuMjY4IDQgMjQgNCAxMi45NTUgNCA0IDEyLjk1NSA0IDI0czguOTU1IDIwIDIwIDIwIDIwLTguOTU1IDIwLTIwYzAtMS4zNDEtLjEzOC0yLjY1LS4zODktMy45MTd6Ii8+PHBhdGggZmlsbD0iI0ZGM0QwMCIgZD0iTTYuMzA2IDE0LjY5MWw2LjU3MSA0LjgxOUMxNC42NTUgMTYuMTA4IDE4Ljk2MSAxMiAyNCAxMmMzLjA1OSAwIDUuODQyIDEuMTU0IDcuOTYxIDMuMDM5TDM3LjYxOCA5LjM4MkMzNC4wNDYgNi4wNTMgMjkuMjY4IDQgMjQgNCAxNi4zMTggNCA5LjY1NiA4LjMzNyA2LjMwNiAxNC42OTF6Ii8+PHBhdGggZmlsbD0iIzRDQUY1MCIgZD0iTTI0IDQ0YzUuMTY2IDAgOS44Ni0xLjk3NyAxMy40MDktNS4xOTdsLTYuMTktNS4yMzhDMjkuMjExIDM1LjA5MSAyNi43MTUgMzYgMjQgMzZjLTUuMDYgMC05LjYyNS0zLjMyNC0xMS4zMDMtOGwtNi41MjUgNS4wMjVDOS4xOTMgMzkuNTU2IDE2LjAwMSA0NCAyNCA0NHoiLz48cGF0aCBmaWxsPSIjMTk3NkQyIiBkPSJNNDMuNjExIDIwLjA4M0g0MlYyMEgyNHY4aDExLjMwM2MtLjc5MiAyLjIzNy0yLjIzMSA0LjE2Ni00LjA4NCA1LjU2NWwuMDAzLS0wMDIgNi4xOSA1LjIzOEMzNi45NzEgMzkuMjA1IDQ0IDM0IDQ0IDI0YzAtMS4zNDEtLjEzOC0yLjY1LS4zODktMy45MTd6Ii8+PC9zdmc+") center/18px 18px no-repeat !important;
                }
                </style>
                """,unsafe_allow_html=True)
                create_test=st.form_submit_button('Continue with Google',key='gmail-connect',use_container_width=True)
            else:
                create=False
                create_test=st.form_submit_button('Sign in with Microsoft',key='microsoft-connect',use_container_width=True)
        if create or create_test:
            try:
                if provider=='gmail_oauth':
                    auth=api('POST','/oauth/gmail/start',json={'display_name':name}); auth.raise_for_status()
                    authorization_url=auth.json()['authorization_url']
                    import json
                    st.markdown(f"<script>window.top.location.href={json.dumps(authorization_url)};</script>",unsafe_allow_html=True)
                    st.stop()
                throttle_seconds=int(throttle_value)*(60 if throttle_unit=='Minutes' else 1) if provider=='smtp' else 60
                payload={'display_name':name,'email':email,'provider':provider,'config':{'host':host,'port':port,'username':username,'tls':tls,'ssl':ssl_mode,'allow_self_signed_certificate':allow_self_signed,'throttle_seconds':throttle_seconds},'password':password}
                if provider=='smtp':
                    response=api('POST','/senders/test-and-save',json=payload)
                    response.raise_for_status()
                    st.success('Sender added and SMTP connection verified successfully.')
                else:
                    response=api('POST','/senders',json=payload)
                    response.raise_for_status()
                    st.success('Sender added. Use the provider connection control on the sender card.')
                st.rerun()
            except Exception as exc:
                st.error(api_error(exc,'Could not add/test sender. Failed configuration was not retained.'))
    for sender in senders:
        with st.container(border=True):
            status_icon='🟢' if sender['health']=='healthy' else ('🔴' if sender['health']=='unhealthy' else '⚪')
            x,e,y,z=st.columns([6,1,1,1])
            x.markdown(f"**{sender['display_name']}**  \
{sender['email']} · {sender['provider']} · {status_icon}")
            if e.button('EDIT',key=f"edit-{sender['id']}"):
                st.session_state[f"edit_sender_{sender['id']}"]=not st.session_state.get(f"edit_sender_{sender['id']}",False)
            if sender['provider']=='smtp' and y.button('TEST',key=f"test-{sender['id']}"):
                try:
                    api('POST',f"/senders/{sender['id']}/test").raise_for_status()
                    st.session_state['smtp_test_notice']='SMTP connection successful.'
                    st.rerun()
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
                    edit_name=st.text_input('Display name',value=detail['display_name'])
                    if detail['provider']=='smtp':
                        edit_email=st.text_input('Sender email',value=detail['email'] or '')
                    else:
                        edit_email=None
                    edit_host=st.text_input('SMTP host',value=cfg.get('host',''),disabled=detail['provider']!='smtp')
                    edit_port=st.number_input('SMTP port',1,65535,int(cfg.get('port',587)),disabled=detail['provider']!='smtp')
                    edit_username=st.text_input('SMTP username',value=cfg.get('username',''),disabled=detail['provider']!='smtp')
                    edit_password=st.text_input('New SMTP password / app password (leave blank to keep current)',type='password',disabled=detail['provider']!='smtp')
                    q1,q2=st.columns(2)
                    with q1: edit_tls=st.checkbox('STARTTLS',bool(cfg.get('tls',True)),disabled=detail['provider']!='smtp')
                    with q2: edit_ssl=st.checkbox('SSL',bool(cfg.get('ssl',False)),disabled=detail['provider']!='smtp')
                    edit_self_signed=st.checkbox('Allow self-signed certificate (security exception)',bool(cfg.get('allow_self_signed_certificate',True)),disabled=detail['provider']!='smtp')
                    reply_to=st.text_input('Sender Reply-To',value=cfg.get('reply_to',detail.get('email') or ''),help='Leave as the sender email to use the default. Campaigns may override this per campaign.')
                    if detail['provider']=='smtp':
                        current_throttle=int(cfg.get('throttle_seconds',60))
                        edit_unit='Minutes' if current_throttle % 60 == 0 and current_throttle >= 60 else 'Seconds'
                        edit_value=current_throttle//60 if edit_unit=='Minutes' else current_throttle
                        et1,et2=st.columns(2)
                        with et1: edit_throttle_value=st.number_input('Send interval',1,86400,edit_value,step=1,help='Minimum time between successful outbound sends from this SMTP sender.')
                        with et2: edit_throttle_unit=st.selectbox('Interval unit',['Seconds','Minutes'],index=1 if edit_unit=='Minutes' else 0)
                    else:
                        edit_throttle_value=60; edit_throttle_unit='Seconds'
                    save_edit=st.form_submit_button('TEST AND SAVE SMTP' if detail['provider']=='smtp' else 'SAVE CHANGES',type='primary',use_container_width=True)
                if save_edit:
                    edit_throttle_seconds=int(edit_throttle_value)*(60 if edit_throttle_unit=='Minutes' else 1)
                    payload={'display_name':edit_name,'email':edit_email,'config':{'host':edit_host,'port':edit_port,'username':edit_username,'tls':edit_tls,'ssl':edit_ssl,'allow_self_signed_certificate':edit_self_signed,'throttle_seconds':edit_throttle_seconds,'reply_to':reply_to.strip()}}
                    if edit_password: payload['password']=edit_password
                    try:
                        if detail['provider']=='smtp':
                            updated=api('POST',f"/senders/{sender['id']}/test-and-save",json=payload)
                        else:
                            updated=api('PATCH',f"/senders/{sender['id']}",json=payload)
                        updated.raise_for_status()
                        st.success('SMTP tested and saved successfully.' if detail['provider']=='smtp' else 'Sender updated.')
                        st.session_state[f"edit_sender_{sender['id']}"]=False
                        st.rerun()
                    except Exception as exc: st.error(api_error(exc,'Could not test and save sender.'))
            except Exception as exc: st.error(api_error(exc,'Could not load sender configuration.'))
    if not senders: st.info('No sender accounts configured.')
