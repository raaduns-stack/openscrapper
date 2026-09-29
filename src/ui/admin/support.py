import html

import streamlit as st

STATUS_LABELS = {
    "new": "New",
    "open": "Open",
    "waiting_user": "Waiting for customer",
    "waiting_internal": "Waiting internally",
    "resolved": "Resolved",
    "closed": "Closed",
}

STATUS_ICONS = {
    "new": "●",
    "open": "●",
    "waiting_user": "◷",
    "waiting_internal": "◌",
    "resolved": "✓",
    "closed": "✓",
}

VIEWS = [
    ("Waiting for me", "new,open"),
    ("Waiting for customer", "waiting_user"),
    ("Waiting internally", "waiting_internal"),
    ("Resolved", "resolved"),
    ("Closed", "closed"),
]


def _css():
    st.markdown("""
    <style>
    .support-legend {display:flex;gap:18px;flex-wrap:wrap;margin:8px 0 18px;color:#667085;font-size:.78rem}
    .support-legend span {display:inline-flex;align-items:center;gap:6px}
    .support-dot {font-size:14px}
    .support-list {border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;background:#fff}
    .support-row {padding:13px 15px;border-bottom:1px solid #eef0f2}
    .support-row:last-child {border-bottom:0}
    .support-row-head {display:flex;align-items:center;gap:10px}
    .support-subject {font-weight:650;color:#172033;flex:1;min-width:0}
    .support-meta {margin-top:5px;color:#7b8494;font-size:.76rem}
    .support-pill {display:inline-block;border-radius:999px;padding:3px 8px;font-size:.69rem;font-weight:700;white-space:nowrap}
    .support-priority {background:#f3f4f6;color:#4b5563}
    .support-priority.urgent {background:#fee2e2;color:#b42318}
    .support-priority.high {background:#fff1d6;color:#9a6700}
    .support-priority.low {background:#eef4ff;color:#315ea8}
    .support-status {background:#eef2ff;color:#4355b9}
    .support-status.waiting {background:#fff4e5;color:#9a6700}
    .support-status.resolved {background:#ecfdf3;color:#087443}
    .support-status.closed {background:#f2f4f7;color:#667085}
    .support-empty {padding:30px;text-align:center;color:#7b8494;border:1px dashed #d8dde5;border-radius:12px}
    .support-chat {padding:16px;border:1px solid #e5e7eb;border-radius:12px;background:#fafafa;margin:10px 0 16px}
    .support-bubble {max-width:78%;padding:10px 13px;border-radius:15px;margin:0 0 10px}
    .support-bubble.customer {margin-left:auto;background:#fff0f0;border:1px solid #ffd7d7;border-bottom-right-radius:5px}
    .support-bubble.agent {margin-right:auto;background:#fff;border:1px solid #e1e5ea;border-bottom-left-radius:5px}
    .support-bubble.internal {margin-right:auto;background:#fff8e8;border:1px dashed #e5b94b}
    .support-author {font-size:.72rem;font-weight:700;color:#596273;margin-bottom:4px}
    .support-body {font-size:.9rem;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere;color:#172033}
    .support-time {font-size:.66rem;color:#98a2b3;text-align:right;margin-top:4px}
    </style>
    """, unsafe_allow_html=True)


def _status_pill(status):
    label = html.escape(STATUS_LABELS.get(status, status))
    cls = "waiting" if status in ("waiting_user", "waiting_internal") else status
    return f'<span class="support-pill support-status {cls}">{STATUS_ICONS.get(status, "●")} {label}</span>'


def _priority_pill(priority):
    p = html.escape(priority or "normal")
    return f'<span class="support-pill support-priority {p}">{p.title()}</span>'


def _render_ticket(api, api_json, api_error, item):
    tid = item["id"]
    detail = api_json("GET", f"/admin/support/tickets/{tid}")
    messages = detail.get("messages", [])
    ticket_user_id = detail.get("user_id")
    st.markdown("**Conversation**")
    st.markdown('<div class="support-chat">', unsafe_allow_html=True)
    for message in messages:
        if message.get("is_internal"):
            side, label = "internal", "Internal note"
        elif message.get("author_id") == ticket_user_id:
            side, label = "customer", "Customer"
        else:
            side, label = "agent", message.get("email") or "Support"
        body = html.escape(message.get("body") or "")
        created = html.escape((message.get("created_at") or "").replace("T", " ")[:16])
        st.markdown(
            f'<div class="support-bubble {side}"><div class="support-author">{html.escape(label)}</div>'
            f'<div class="support-body">{body}</div><div class="support-time">{created}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)
    attachments = detail.get("attachments", [])
    if attachments:
        st.markdown("**Attachments**")
        for att in attachments:
            download = api("GET", f"/admin/support/tickets/{tid}/attachments/{att['id']}")
            if download.ok:
                st.download_button(
                    f"DOWNLOAD {att['filename']}", download.content,
                    file_name=att["filename"], mime=att.get("content_type") or "application/octet-stream",
                    key=f"admin-download-{att['id']}",
                )
    assignees = api_json("GET", "/admin/support/assignees")
    options = {"Unassigned": None}
    options.update({x["email"]: x["id"] for x in assignees})
    current = item.get("assigned_to")
    selected = next((name for name, value in options.items() if value == current), "Unassigned")
    c1, c2, c3 = st.columns(3)
    new_status = c1.selectbox("Status", list(STATUS_LABELS), index=list(STATUS_LABELS).index(item["status"]), format_func=lambda x: STATUS_LABELS[x], key=f"status-{tid}")
    assignment = c2.selectbox("Assignee", list(options), index=list(options).index(selected), key=f"assignee-{tid}")
    if c3.button("SAVE", key=f"save-meta-{tid}", type="primary", use_container_width=True):
        api("POST", f"/admin/support/tickets/{tid}/status", json={"status": new_status}).raise_for_status()
        api("POST", f"/admin/support/tickets/{tid}/assignment", json={"assigned_to": options[assignment]}).raise_for_status()
        st.rerun()
    n1, n2 = st.columns(2)
    note = n1.text_area("Internal note", key=f"note-{tid}", height=90, placeholder="Visible to support staff only…")
    reply = n2.text_area("Customer reply", key=f"reply-{tid}", height=90, placeholder="Reply to the customer…")
    a1, a2 = st.columns(2)
    if a1.button("ADD INTERNAL NOTE", key=f"addnote-{tid}", use_container_width=True):
        if note.strip():
            api("POST", f"/admin/support/tickets/{tid}/internal-note", json={"body": note}).raise_for_status(); st.rerun()
        st.warning("Write an internal note first.")
    if a2.button("SEND CUSTOMER REPLY", key=f"adminreply-{tid}", type="primary", use_container_width=True):
        if reply.strip():
            api("POST", f"/admin/support/tickets/{tid}/messages", json={"body": reply}).raise_for_status(); st.rerun()
        st.warning("Write a customer reply first.")


def _ticket_rows(api_json, api_error, status, category, search, offset, page_size=25):
    from urllib.parse import quote_plus
    query = f"/admin/support/tickets?limit={page_size + 1}&offset={offset}&status={status}"
    if category != "All": query += f"&category={category}"
    if search.strip(): query += f"&q={quote_plus(search.strip())}"
    try:
        rows = api_json("GET", query)
    except Exception as exc:
        st.error("Could not load support tickets: " + api_error(exc)); return [], False
    return rows[:page_size], len(rows) > page_size


def render_support_admin(api, api_json, api_error):
    _css()
    st.subheader("Support Centre")
    try:
        metrics = api_json("GET", "/admin/support/metrics")
    except Exception as exc:
        st.error("Could not load support administration: " + api_error(exc)); return
    waiting = metrics.get("new", 0) + metrics.get("open", 0)
    a, b, c, d = st.columns(4)
    a.metric("Waiting for me", waiting); b.metric("Waiting for customer", metrics.get("waiting_user", 0))
    c.metric("Resolved", metrics.get("resolved", 0)); d.metric("Closed", metrics.get("closed", 0))
    st.markdown('<div class="support-legend"><span><b class="support-dot">●</b> New / needs action</span><span><b class="support-dot">◷</b> Waiting for customer</span><span><b class="support-dot">◌</b> Waiting internally</span><span><b class="support-dot">✓</b> Resolved / closed</span></div>', unsafe_allow_html=True)
    search = st.text_input("Search", placeholder="Search ticket subject or customer email…", label_visibility="collapsed")
    category = st.selectbox("Category", ["All", "payment", "account", "login", "system", "scraping", "billing", "other"], format_func=lambda x: "All categories" if x == "All" else x.title())
    tab_labels = [f"{name} ({waiting if name == 'Waiting for me' else metrics.get(key, 0)})" for name, key in VIEWS]
    tabs = st.tabs(tab_labels)
    for tab, (name, status) in zip(tabs, VIEWS):
        with tab:
            state_key = f"support-admin-offset-{status}"; offset = st.session_state.get(state_key, 0)
            rows, has_next = _ticket_rows(api_json, api_error, status, category, search, offset)
            if not rows:
                st.markdown('<div class="support-empty">No tickets in this view.</div>', unsafe_allow_html=True); continue
            st.caption(f"Showing {offset + 1}–{offset + len(rows)}")
            st.markdown('<div class="support-list">', unsafe_allow_html=True)
            for item in rows:
                status_html = _status_pill(item["status"]); priority_html = _priority_pill(item["priority"])
                subject = html.escape(item["subject"]); user_email = html.escape(item.get("user_email") or "Unknown customer")
                assignee = html.escape(item.get("assigned_to_email") or "Unassigned"); updated = html.escape((item.get("updated_at") or "").replace("T", " ")[:16])
                st.markdown(f'<div class="support-row"><div class="support-row-head">{status_html}{priority_html}<span class="support-subject">{subject}</span></div><div class="support-meta">{user_email} · Assigned: {assignee} · Updated {updated} · #{item["id"][:8]}</div></div>', unsafe_allow_html=True)
                if st.button("OPEN", key=f"open-{item['id']}"): st.session_state["support-admin-selected"] = item["id"]
            st.markdown('</div>', unsafe_allow_html=True)
            selected_id = st.session_state.get("support-admin-selected")
            if selected_id and any(x["id"] == selected_id for x in rows):
                selected = next(x for x in rows if x["id"] == selected_id); st.divider(); st.markdown(f"### {selected['subject']}")
                _render_ticket(api, api_json, api_error, selected)
                if st.button("CLOSE TICKET VIEW", key=f"close-view-{selected_id}"):
                    st.session_state.pop("support-admin-selected", None); st.rerun()
            p1, p2 = st.columns(2)
            if p1.button("← Previous", key=f"prev-{status}", disabled=offset == 0, use_container_width=True):
                st.session_state[state_key] = max(0, offset - 25); st.rerun()
            if p2.button("Next →", key=f"next-{status}", disabled=not has_next, use_container_width=True):
                st.session_state[state_key] = offset + 25; st.rerun()
