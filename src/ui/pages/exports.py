import requests
import streamlit as st
from src.ui.components.header import render_header


def render_exports(api, api_json):
    render_header('Exports')
    exports=api_json('GET','/exports')
    if not exports: st.info('No completed exports yet.')
    else:
        grouped={}
        for ex in exports: grouped.setdefault((ex['scrap_id'],ex['scrap_name']),[]).append(ex)
        for (scrap_id,scrap_name),items in grouped.items():
            st.subheader(scrap_name)
            for ex in items:
                st.write(f"{ex['format'].upper()} — {ex['created_at'][:19].replace('T',' ')}")
                if ex['format'] in ('csv','xlsx'):
                    try:
                        data=api('GET',f"/scraps/{scrap_id}/exports/{ex['id']}/download").content
                        st.download_button(f"DOWNLOAD {ex['format'].upper()}",data=data,file_name=f"scrappee-{scrap_id}.{ex['format']}",key=f"download-{ex['id']}")
                    except requests.RequestException as exc:
                        st.caption(f"Download unavailable: {exc}")
