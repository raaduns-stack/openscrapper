from __future__ import annotations

import streamlit as st

def render_reply_to(senders):
    st.subheader('Reply To'); st.caption('Default reply addresses for outbound messages.')
    if senders:
        for sender in senders:
            config=sender.get('config') or {}
            with st.container(border=True):
                st.markdown(f"**{sender['display_name']}** · {sender['email']}")
                st.write(f"Default Reply-To: {config.get('reply_to') or sender['email']}")
    else: st.info('Configure a sender first.')
