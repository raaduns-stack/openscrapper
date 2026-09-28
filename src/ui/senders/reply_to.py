from __future__ import annotations

import streamlit as st


def render_reply_to(api, api_error, senders):
    notice=st.session_state.pop('reply_to_notice',None)
    if notice: st.success(notice)
    st.subheader('Reply To')
    st.caption('Set the reply address independently for each sender. Campaign-specific Reply-To overrides this sender default when configured.')
    if not senders:
        st.info('Configure a sender first.')
        return
    for sender in senders:
        try:
            detail=api('GET',f"/senders/{sender['id']}"); detail.raise_for_status(); detail=detail.json()
            config=detail.get('config') or {}
            custom=config.get('reply_to') or ''
            effective=custom or detail['email']
            with st.container(border=True):
                st.markdown(f"**{detail['display_name']}** · {detail['email']} · {detail['provider']}")
                st.caption(f"Current effective Reply-To: {effective}")
                with st.form(f"reply-to-form-{sender['id']}"):
                    reply_to=st.text_input('Reply-To email',value=custom,placeholder=detail['email'],help='Leave blank to use the sender email as Reply-To.')
                    save=st.form_submit_button('SAVE REPLY-TO',type='primary',use_container_width=True)
                if save:
                    try:
                        response=api('PATCH',f"/senders/{sender['id']}/reply-to",json={'reply_to':reply_to.strip() or None})
                        response.raise_for_status()
                        st.session_state['reply_to_notice']=f"Reply-To saved for {detail['display_name']}."
                        st.rerun()
                    except Exception as exc:
                        st.error(api_error(exc,'Could not save Reply-To.'))
        except Exception as exc:
            st.error(api_error(exc,'Could not load sender Reply-To configuration.'))
