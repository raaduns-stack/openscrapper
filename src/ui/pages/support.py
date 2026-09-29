import html

import streamlit as st

from src.ui.components.header import render_header

CATEGORIES = {
    "Payment": "payment", "Account": "account", "Login & Security": "login",
    "System Down / Incident": "system", "Scraping / Leads": "scraping",
    "Billing / Subscription": "billing", "Other": "other",
}
STATUS_LABELS = {
    "new": "New", "open": "Open", "waiting_user": "Waiting for you",
    "waiting_internal": "Waiting internally", "resolved": "Resolved", "closed": "Closed",
}


def _support_css():
    st.markdown("""
    <style>
    .support-thread {
        margin: 12px 0 18px;
        padding: 18px 18px 8px;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        background: #ffffff;
    }
    .support-message-row {
        display: flex;
        width: 100%;
        margin: 0 0 16px;
    }
    .support-message-row.customer { justify-content: flex-end; }
    .support-message-row.agent { justify-content: flex-start; }
    .support-message {
        max-width: 76%;
        padding: 11px 14px 9px;
        border-radius: 16px;
        box-sizing: border-box;
    }
    .support-message.customer {
        background: #fff0f0;
        border: 1px solid #ffd7d7;
        border-bottom-right-radius: 5px;
    }
    .support-message.agent {
        background: #f3f4f6;
        border: 1px solid #e5e7eb;
        border-bottom-left-radius: 5px;
    }
    .support-sender {
        font-size: 0.76rem;
        font-weight: 700;
        margin-bottom: 4px;
        color: #4b5563;
    }
    .support-body {
        font-size: 0.94rem;
        line-height: 1.5;
        color: #111827;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }
    .support-time {
        margin-top: 5px;
        font-size: 0.68rem;
        color: #9ca3af;
        text-align: right;
    }
    .support-attachment {
        margin-top: 7px;
        padding: 7px 9px;
        border-radius: 8px;
        background: rgba(255,255,255,.72);
        font-size: .76rem;
        color: #4b5563;
    }
    .support-status-line {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 2px 0 14px;
        color: #6b7280;
        font-size: .78rem;
    }
    </style>
    """, unsafe_allow_html=True)


def _render_message(message, ticket_id, attachments):
    customer = message.get("author_id") == message.get("ticket_user_id")
    side = "customer" if customer else "agent"
    sender = "You" if customer else (message.get("email") or "Support")
    sender = html.escape(sender)
    body = html.escape(message.get("body") or "")
    created = html.escape((message.get("created_at") or "").replace("T", " ")[:16])
    related = [x for x in attachments if x.get("message_id") == message.get("id")]
    attachment_html = "".join(
        f'<div class="support-attachment">📎 {html.escape(x["filename"])} · {x["size_bytes"] / 1024:.0f} KB</div>'
        for x in related
    )
    st.markdown(
        f'<div class="support-message-row {side}">'
        f'<div class="support-message {side}">'
        f'<div class="support-sender">{sender}</div>'
        f'<div class="support-body">{body}</div>'
        f'{attachment_html}'
        f'<div class="support-time">{created}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_support(api, api_json, api_error):
    _support_css()
    render_header("Support Centre", "Get help, report an issue, and track your support requests.")
    try:
        tickets = api_json("GET", "/support/tickets")
    except Exception as exc:
        st.error("Could not load support tickets: " + api_error(exc))
        return

    a, b, c = st.columns(3)
    a.metric("Active", sum(x["status"] not in ("resolved", "closed") for x in tickets))
    b.metric("Resolved", sum(x["status"] == "resolved" for x in tickets))
    c.metric("Closed", sum(x["status"] == "closed" for x in tickets))

    tab_new, tab_tickets = st.tabs(["Create ticket", "My tickets"])
    with tab_new:
        st.markdown("### How can we help?")
        with st.form("support-create"):
            category_label = st.selectbox("Issue category", list(CATEGORIES))
            subject = st.text_input("Subject", placeholder="Briefly describe the issue")
            description = st.text_area("Describe the problem", height=180)
            priority = st.select_slider("Priority", options=["low", "normal", "high", "urgent"], value="normal")
            uploads = st.file_uploader(
                "Screenshots / images / evidence", accept_multiple_files=True,
                type=["png", "jpg", "jpeg", "webp", "gif", "pdf", "txt"],
            )
            submit = st.form_submit_button("CREATE TICKET", type="primary", use_container_width=True)
        if submit:
            if not subject.strip() or not description.strip():
                st.error("Subject and description are required.")
            else:
                try:
                    ticket = api_json("POST", "/support/tickets", json={
                        "subject": subject, "category": CATEGORIES[category_label],
                        "description": description, "priority": priority,
                    })
                    for upload in uploads or []:
                        api("POST", f"/support/tickets/{ticket['id']}/attachments",
                            files={"file": (upload.name, upload.getvalue(), upload.type or "application/octet-stream")}).raise_for_status()
                    st.success(f"Ticket {ticket['id']} created.")
                    st.rerun()
                except Exception as exc:
                    st.error("Could not create ticket: " + api_error(exc))

    with tab_tickets:
        # Waiting for me is deliberately first and is the default view.
        status_filter = st.selectbox(
            "View",
            ["Waiting for me", "New / Open", "All", "Resolved", "Closed"],
            index=0,
        )
        selected_status = {
            "New / Open": "open", "Waiting for me": "waiting_user",
            "Resolved": "resolved", "Closed": "closed",
        }.get(status_filter)
        filtered = [
            x for x in tickets
            if selected_status is None or x["status"] == selected_status
            or (status_filter == "New / Open" and x["status"] == "new")
        ]
        if not filtered:
            st.info("Nothing is waiting for you right now.")

        for item in filtered:
            status = STATUS_LABELS.get(item["status"], item["status"])
            with st.expander(f'{status} · {item["subject"]} · #{item["id"][:8]}', expanded=True):
                st.caption(f'{item["category"].title()} · Priority: {item["priority"]} · Updated {item["updated_at"]}')
                detail = api_json("GET", f'/support/tickets/{item["id"]}')
                messages = detail.get("messages", [])
                attachments = detail.get("attachments", [])
                for message in messages:
                    message["ticket_user_id"] = detail.get("user_id")

                st.markdown('<div class="support-thread">', unsafe_allow_html=True)
                for message in messages:
                    _render_message(message, item["id"], attachments)
                if not messages:
                    st.caption("No messages yet.")
                st.markdown('</div>', unsafe_allow_html=True)

                # Attachment controls remain outside the bubbles so files are easy to find/download.
                for att in attachments:
                    download = api("GET", f'/support/tickets/{item["id"]}/attachments/{att["id"]}')
                    if download.ok:
                        st.download_button(
                            f'DOWNLOAD {att["filename"]}', download.content,
                            file_name=att["filename"], mime=att.get("content_type") or "application/octet-stream",
                            key=f'download-{att["id"]}',
                        )

                if item["status"] not in ("resolved", "closed"):
                    st.markdown("**Reply to support**")
                    reply = st.text_area("", key=f"reply-{item['id']}", height=100,
                                         placeholder="Write your reply…", label_visibility="collapsed")
                    left, right = st.columns(2)
                    if left.button("SEND REPLY", key=f"send-{item['id']}", type="primary", use_container_width=True):
                        if not reply.strip():
                            st.warning("Write a reply first.")
                        else:
                            api("POST", f'/support/tickets/{item["id"]}/messages', json={"body": reply}).raise_for_status()
                            st.rerun()
                    if right.button("MARK RESOLVED", key=f"resolve-{item['id']}", use_container_width=True):
                        api("POST", f'/support/tickets/{item["id"]}/resolve').raise_for_status()
                        st.rerun()

                if detail.get("status") in ("resolved", "closed"):
                    st.markdown("**How was your support experience?**")
                    score = st.slider("Rating", 1, 5, 5, key=f"score-{item['id']}", label_visibility="collapsed")
                    comment = st.text_area("Feedback (optional)", key=f"rating-comment-{item['id']}", height=70)
                    if st.button("SUBMIT RATING", key=f"rating-{item['id']}"):
                        api("POST", f'/support/tickets/{item["id"]}/rating',
                            json={"score": score, "comment": comment}).raise_for_status()
                        st.success("Thank you for the feedback.")
