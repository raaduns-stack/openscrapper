import os
import streamlit as st

def render_browser_extension(api, api_json, api_error, **kwargs):
        st.subheader('Browser Extension')
        st.code(os.getenv("PUBLIC_API_URL", "https://api.scrapee.uk").rstrip("/"));st.caption('Authenticated API endpoint used by the browser extension for SERP capture sync.')
