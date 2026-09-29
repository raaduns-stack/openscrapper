import streamlit as st


def render_header(title, subtitle=None, *, badge=None):
    """Render the shared page header with the Deposit action aligned top-right."""
    cols = st.columns([1, 0.24, 0.22] if badge else [1, 0.22])
    with cols[0]:
        st.title(title)
        if subtitle:
            st.caption(subtitle)
    if badge:
        with cols[1]:
            st.caption(badge)
    with cols[-1]:
        if st.button('DEPOSIT', key=f'deposit-header-{title}', type='primary', use_container_width=True):
            deposit_page = (st.session_state.get('navigation_pages') or {}).get('Deposit')
            if deposit_page is not None:
                st.switch_page(deposit_page)
