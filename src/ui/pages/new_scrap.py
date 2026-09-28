import re
import requests
import streamlit as st
from src.agent.query_interpreter import QueryInterpreter
from src.models.criteria import SearchCriteria
from src.ui.components.header import render_header


def _criteria_to_review(criteria, default_max_leads):
    return {
        "industry": criteria.industry or "",
        "product": criteria.product or "",
        "geography": criteria.geography or "",
        "target_type": criteria.target_type,
        "roles": ", ".join(criteria.roles),
        "keywords": ", ".join(criteria.keywords),
        "max_leads": int(default_max_leads),
    }


def _review_to_criteria(review):
    return SearchCriteria.model_validate({
        "industry": review["industry"].strip(),
        "product": review["product"].strip() or None,
        "geography": review["geography"].strip() or None,
        "target_type": review["target_type"],
        "roles": [x.strip() for x in review["roles"].split(",") if x.strip()],
        "keywords": [x.strip() for x in review["keywords"].split(",") if x.strip()],
        "max_leads": int(review["max_leads"]),
    })


def render_new_scrap(api, api_json, billing, ensure_serp_session):
    render_header("New Scrap", "Describe the leads. Review the AI interpretation before searches are generated.")

    if st.session_state.scrap_id:
        try:
            existing = api_json("GET", f"/scraps/{st.session_state.scrap_id}")
            if existing.get("status") in ("active", "running"):
                st.warning("A Current Scrap is already open. Complete URL submission before creating another Scrap.")
                st.stop()
            st.session_state.scrap_id = None
            st.session_state.serp_token = None
            st.session_state.parameters = []
            st.session_state.job = None
            st.session_state.selected = []
            st.session_state.manual_sources = []
            st.session_state.submission_completed = False
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                st.session_state.scrap_id = None
            else:
                st.error(f"Could not check the previous Scrap: {exc}")
                st.stop()
        except requests.RequestException as exc:
            st.error(f"Could not check the previous Scrap: {exc}")
            st.stop()

    max_lead_default = int((billing or {}).get("research_default_max_leads", 100))
    max_lead_limit = int((billing or {}).get("research_max_leads", 10000))

    if "new_scrap_interpretation" not in st.session_state:
        st.session_state.new_scrap_interpretation = None
    if "new_scrap_request" not in st.session_state:
        st.session_state.new_scrap_request = ""

    st.markdown("### 1. Describe your lead search")
    st.caption("AI will interpret your request first. Nothing is created or charged at this stage.")

    request = st.text_area(
        "What leads are you looking for?",
        value=st.session_state.new_scrap_request,
        placeholder="e.g. doctors in India",
        height=100,
        key="new-scrap-request",
    )

    if st.button("Interpret request", type="primary", use_container_width=True):
        try:
            if not request.strip():
                raise ValueError("Describe the leads you are looking for.")
            criteria = QueryInterpreter().interpret(request)
            st.session_state.new_scrap_request = request.strip()
            st.session_state.new_scrap_interpretation = _criteria_to_review(criteria, max_lead_default)
            st.rerun()
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "rate_limit_exceeded" in msg or "Rate limit reached" in msg:
                wait = re.search(r"Please try again in ([^.]+)", msg)
                delay = wait.group(1) if wait else "a few minutes"
                st.warning(f"AI interpretation is temporarily rate-limited. Please retry in {delay}.")
            else:
                st.error(f"Could not interpret request: {exc}")

    review = st.session_state.new_scrap_interpretation
    if not review:
        st.info("Enter a request and click Interpret request. You will be able to review and edit the interpretation before anything is created.")
        return

    st.markdown("### 2. Review AI interpretation")
    st.warning("Review these fields carefully. The approved values will drive deterministic search-template generation.")

    with st.container(border=True):
        industry = st.text_input("Industry", value=review["industry"], key="review-industry")
        product = st.text_input("Product", value=review["product"], key="review-product")
        geography = st.text_input("Geography", value=review["geography"], key="review-geography")
        target_type = st.selectbox(
            "Target type",
            ["people", "companies", "both"],
            index=["people", "companies", "both"].index(review["target_type"]),
            key="review-target-type",
        )
        roles = st.text_input("Roles / job titles", value=review["roles"], key="review-roles", help="Separate multiple roles with commas.")
        keywords = st.text_input("Keywords", value=review["keywords"], key="review-keywords", help="Separate multiple keywords with commas.")
        max_leads = st.number_input(
            "Maximum leads",
            min_value=1,
            max_value=max_lead_limit,
            value=min(max(1, int(review["max_leads"])), max_lead_limit),
            key="review-max-leads",
        )

        st.markdown("### 3. Create Scrap")
        st.caption("Your approved interpretation will generate searches from the administrator-owned templates.")

        with st.expander("Advanced crawl controls", expanded=False):
            limit_pages = st.checkbox("Limit crawl pages", value=False)
            max_pages = st.number_input("Maximum crawl pages", 1, 10000, 1000, disabled=not limit_pages)
            limit_urls = st.checkbox("Limit crawl URL occurrences", value=False)
            max_urls = st.number_input("Maximum crawl URL occurrences", 1, 100000, 10000, disabled=not limit_urls)
            limit_depth = st.checkbox("Limit crawl depth", value=False)
            max_depth = st.number_input("Maximum crawl depth", 0, 100, 2, disabled=not limit_depth)
            limit_pagination = st.checkbox("Limit pagination pages", value=False)
            max_pagination = st.number_input("Maximum pagination pages", 1, 1000, 100, disabled=not limit_pagination)
            provider_failures = st.number_input("Provider failure limit", 1, 20, 2)
            url_validity = st.checkbox("URL validity checks", value=True)
            exhaustion_enabled = st.checkbox("Stop after duplicate/no-progress exhaustion", value=True)
            exhaustion_threshold = st.number_input("Duplicate/no-progress threshold", 1, 100, 3)

        name = st.text_input("Scrap name", value=st.session_state.new_scrap_request or "Current Scrap", key="approved-scrap-name")

        c1, c2 = st.columns(2)
        with c1:
            reinterpret = st.button("Re-interpret request", use_container_width=True)
        with c2:
            approve = st.button("Approve & Open Current Scrap", type="primary", use_container_width=True)

    if reinterpret:
        st.session_state.new_scrap_interpretation = None
        st.rerun()

    if not approve:
        return

    try:
        review_data = {
            "industry": industry,
            "product": product,
            "geography": geography,
            "target_type": target_type,
            "roles": roles,
            "keywords": keywords,
            "max_leads": max_leads,
        }
        criteria = _review_to_criteria(review_data)
        criteria_data = criteria.model_dump()
        crawler_data = {
            "provider_failure_limit": int(provider_failures),
            "url_validity_checks": bool(url_validity),
            "max_crawl_pages": int(max_pages) if limit_pages else None,
            "max_crawl_urls": int(max_urls) if limit_urls else None,
            "max_crawl_depth": int(max_depth) if limit_depth else None,
            "max_pagination_pages": int(max_pagination) if limit_pagination else None,
            "duplicate_exhaustion_enabled": bool(exhaustion_enabled),
            "duplicate_exhaustion_threshold": int(exhaustion_threshold),
        }

        r = api("POST", "/scraps", json={
            "name": name.strip() or "Current Scrap",
            "criteria": criteria_data,
            "crawler": crawler_data,
        })
        r.raise_for_status()
        st.session_state.scrap_id = r.json()["id"]

        pr = api("POST", "/search/parameters", json={
            "scrap_id": st.session_state.scrap_id,
            "criteria": criteria_data,
        })
        pr.raise_for_status()
        st.session_state.parameters = pr.json().get("parameters", [])
        if not st.session_state.parameters:
            raise ValueError("No search parameters were generated for this request.")

        st.session_state.selected = []
        st.session_state.job = None
        st.session_state.serp_token = None
        st.session_state.manual_sources = []
        st.session_state.submission_completed = False
        st.session_state.new_scrap_interpretation = None
        ensure_serp_session()
        st.session_state.nav_page = "Current Scrap"
        st.rerun()
    except Exception as exc:
        st.error(f"Could not create Scrap: {exc}")
