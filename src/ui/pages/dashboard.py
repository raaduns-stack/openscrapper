import streamlit as st

from src.ui.components.header import render_header


def _status(scrap):
    return str(scrap.get("status") or "unknown").replace("_", " ").title()


def _counts(scrap):
    return scrap.get("counts") or {}


def render_dashboard(api_json, api=None):
    render_header("Dashboard", "Your lead-research workspace and current Scrap activity.")

    try:
        extension = api_json("GET", "/extension/status") or {}
    except Exception:
        extension = {"connected": False, "outdated": False, "latest_version": "0.6.11"}

    if not extension.get("connected") or extension.get("outdated"):
        latest = extension.get("latest_version") or "0.6.11"
        if extension.get("outdated"):
            title = "Browser extension update required"
            message = f"Your Scrappee Browser Extension is v{extension.get('version')}. Update to v{latest} to stay compliant and capture Google/Bing SERP results."
        else:
            title = "Browser extension not connected"
            message = "Connect the Scrappee Browser Extension to capture Google/Bing SERP results into your Current Scrap."
        st.markdown(f"""
        <div style="border:1px solid #e3a008;background:#fff8e1;border-radius:10px;padding:18px 20px;margin:4px 0 24px 0;">
          <div style="font-size:18px;font-weight:700;color:#7a4b00;margin-bottom:6px;">{title}</div>
          <div style="font-size:14px;color:#4a3b20;line-height:1.5;margin-bottom:14px;">{message}</div>
          <a href="https://api.scrapee.uk/downloads/scrappee-browser-import-v{latest}.zip" target="_blank" style="display:inline-block;background:#ff4b4b;color:white;text-decoration:none;padding:9px 14px;border-radius:7px;font-weight:600;margin-right:8px;">Download latest extension · v{latest}</a>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Refresh extension status", key="refresh-extension-status"):
            st.rerun()

    try:
        scraps = api_json("GET", "/scraps") or []
        current = api_json("GET", "/scraps/current")
    except Exception as exc:
        st.error(f"Could not load dashboard: {exc}")
        return

    current_counts = _counts(current or {})
    completed = sum(
        1 for scrap in scraps
        if str(scrap.get("status", "")).lower() in {"completed", "complete"}
    )
    serp_results = current_counts.get("serp_results", 0)
    urls = current_counts.get("url_occurrences", current_counts.get("urls", 0))
    leads = current_counts.get("leads", 0)

    st.subheader("Primary actions")
    action_cols = st.columns(2)
    with action_cols[0]:
        if st.button("New Scrap", type="primary", use_container_width=True):
            st.session_state.nav_page = "New Scrap"
            st.rerun()
    with action_cols[1]:
        if current:
            if st.button("Continue Current Scrap", use_container_width=True):
                st.session_state.scrap_id = current.get("id")
                st.session_state.nav_page = "Current Scrap"
                st.rerun()
        else:
            st.button("Continue Current Scrap", disabled=True, use_container_width=True)

    st.subheader("Operational metrics")
    metrics = st.columns(5)
    metrics[0].metric("Active Scrap", "Yes" if current else "None")
    metrics[1].metric("SERP Results", serp_results)
    metrics[2].metric("URLs", urls)
    metrics[3].metric("Leads", leads)
    metrics[4].metric("Completed Scraps", completed)

    st.subheader("Active work")
    if current:
        c = st.columns([2, 1, 1, 1])
        c[0].write(f"**{current.get('name') or current.get('title') or current.get('id', 'Current Scrap')}**")
        c[1].caption("Stage")
        c[1].write(_status(current))
        c[2].caption("SERP / URLs")
        c[2].write(f"{serp_results} / {urls}")
        c[3].caption("Leads")
        c[3].write(str(leads))
        if st.button("View Current Scrap", key="dashboard-view-current"):
            st.session_state.scrap_id = current.get("id")
            st.session_state.nav_page = "Current Scrap"
            st.rerun()
    else:
        st.info("No active Scrap. Start a New Scrap when you are ready.")

    st.subheader("Recent scraps")
    if scraps:
        rows = []
        for scrap in scraps[:20]:
            counts = _counts(scrap)
            rows.append({
                "Scrap": scrap.get("name") or scrap.get("title") or scrap.get("id", ""),
                "Status": _status(scrap),
                "Results": counts.get("serp_results", 0),
                "Leads": counts.get("leads", 0),
                "Date": scrap.get("created_at") or scrap.get("updated_at") or "",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No Scraps yet.")

    if api:
        st.subheader("Deposit History")
        try:
            btcpay = api_json("GET", "/billing/deposits") or []
        except Exception:
            btcpay = []
        try:
            manual = api_json("GET", "/billing/deposits/manual") or []
        except Exception:
            manual = []

        deposits = [
            {
                "Method": item.get("asset", "BTC"),
                "Amount": f"$" + f"{item.get('requested_cents', 0) / 100:.2f}",
                "Status": str(item.get("status", "")).title(),
                "Reference": item.get("invoice_id", ""),
                "Date": item.get("settled_at") or item.get("created_at", ""),
            }
            for item in btcpay
        ]
        deposits += [
            {
                "Method": "USDT" if item.get("method") == "usdt_manual" else "Bank Transfer",
                "Amount": f"$" + f"{item.get('amount_cents', 0) / 100:.2f}",
                "Status": str(item.get("status", "")).title(),
                "Reference": item.get("reference", ""),
                "Date": item.get("reviewed_at") or item.get("created_at", ""),
            }
            for item in manual
        ]
        deposits.sort(key=lambda item: item["Date"], reverse=True)

        if deposits:
            st.dataframe(deposits[:50], use_container_width=True, hide_index=True)
        else:
            st.info("No deposits yet.")
