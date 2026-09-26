import streamlit as st


def render_header(title, subtitle=None, *, badge=None):
    """Render the shared page header without owning page/business logic."""
    cols = st.columns([1, 0.22]) if badge else st.columns([1])
    with cols[0]:
        st.title(title)
        if subtitle:
            st.caption(subtitle)
    if badge:
        with cols[1]:
            st.caption(badge)
