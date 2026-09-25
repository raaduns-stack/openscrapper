import streamlit as st

from src.ui.components.header import render_header


def render_dashboard(api_json):
    render_header('Dashboard', 'Start a new lead-research scrap or continue your current workspace.')
    try:
        scraps=api_json('GET','/scraps')
        current=api_json('GET','/scraps/current')
        st.metric('Scraps',len(scraps));st.metric('Current captured results',(current or {}).get('counts',{}).get('serp_results',0));st.info('Use New Scrap to define what you want to find.')
    except Exception as exc: st.error(f'Could not load dashboard: {exc}'); st.stop()
    if scraps:st.dataframe(scraps[:20],use_container_width=True,hide_index=True)

