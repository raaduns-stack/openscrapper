import asyncio
import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.models.criteria import SearchCriteria
from src.pipeline import LeadDiscoveryPipeline

st.set_page_config(page_title="Scrappee", page_icon="🕷️", layout="wide")

st.title("Scrappee")
st.caption("AI-powered lead discovery")

with st.form("search"):
    industry = st.text_input("Industry", placeholder="e.g. mining")
    product = st.text_input("Product", placeholder="e.g. gold")
    geography = st.text_input("Geography", placeholder="e.g. Nigeria")
    target_type = st.selectbox("Target type", ["people", "companies", "both"])
    roles = st.text_input("Roles", placeholder="e.g. procurement manager, buyer")
    keywords = st.text_input("Keywords", placeholder="e.g. supplier, distributor")
    max_leads = st.number_input("Maximum leads", min_value=1, max_value=500, value=25)
    submitted = st.form_submit_button("Find Leads", type="primary")

if submitted:
    try:
        criteria = SearchCriteria(
            industry=industry,
            product=product or None,
            geography=geography or None,
            target_type=target_type,
            roles=[x.strip() for x in roles.split(",") if x.strip()],
            keywords=[x.strip() for x in keywords.split(",") if x.strip()],
            max_leads=max_leads,
        )

        with st.status("Discovering leads...", expanded=True) as status:
            pipeline = LeadDiscoveryPipeline(max_pages=25)
            leads = asyncio.run(pipeline.run(criteria))
            status.update(label=f"Completed — {len(leads)} leads found", state="complete")

        if leads:
            rows = [lead.model_dump(mode="json") for lead in leads]
            st.dataframe(rows, use_container_width=True)

            csv_data = __import__("pandas").DataFrame(rows).to_csv(index=False)
            st.download_button(
                "Download CSV",
                csv_data,
                "scrappee-leads.csv",
                "text/csv",
            )
        else:
            st.warning("No leads found. Try broader search criteria.")

    except Exception as exc:
        st.error(f"Search failed: {exc}")
