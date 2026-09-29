import os
import requests
import streamlit as st

API = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")

NAV_SECTIONS = [
    ("WORKSPACE", [("Dashboard", ":material/dashboard:")]),
    ("SCRAP", [
        ("New Scrap", ":material/add_circle:"),
        ("Current Scrap", ":material/radio_button_checked:"),
        ("Lead Workstation", ":material/workspaces:"),
        ("Scrap History", ":material/history:"),
        ("Exports", ":material/download:"),
    ]),
    ("OUTREACH", [("Senders", ":material/mail:")]),
    ("ACCOUNT", [
        ("Deposit", ":material/account_balance_wallet:"),
        ("Support Centre", ":material/support_agent:"),
        ("Settings", ":material/settings:"),
    ]),
]

SIDEBAR_JS = """
export default function(component) {
    const { data, setTriggerValue, parentElement } = component;
    const root = parentElement.querySelector("#scrappee-sidebar-root");
    const icons = {
        ":material/dashboard:":"▦", ":material/add_circle:":"+",
        ":material/radio_button_checked:":"◉", ":material/workspaces:":"⊞",
        ":material/history:":"↺", ":material/download:":"↓",
        ":material/mail:":"✉", ":material/account_balance_wallet:":"▱",
        ":material/support_agent:":"◌", ":material/settings:":"⚙",
        ":material/admin_panel_settings:":"⌘"
    };
    root.replaceChildren();
    const nav = document.createElement("div");
    nav.className = "scrappee-nav";
    const brand = document.createElement("div");
    brand.className = "scrappee-brand";
    brand.textContent = "Scrappee";
    nav.appendChild(brand);
    const email = document.createElement("div");
    email.className = "scrappee-email";
    email.textContent = data.email || "";
    nav.appendChild(email);

    for (const section of data.sections || []) {
        const title = document.createElement("div");
        title.className = "scrappee-section";
        title.textContent = section.title;
        nav.appendChild(title);
        const links = document.createElement("div");
        links.className = "scrappee-links";
        for (const item of section.items || []) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "scrappee-link";
            const icon = document.createElement("span");
            icon.className = "scrappee-icon";
            icon.textContent = icons[item.icon] || "•";
            const label = document.createElement("span");
            label.textContent = item.label;
            button.append(icon, label);
            button.onclick = () => setTriggerValue("navigate", item.label);
            const path = data.paths && data.paths[item.label];
            const current = window.location.pathname.replace(/\/$/, "") || "";
            if (current === (path ? "/" + path : "")) button.classList.add("active");
            links.appendChild(button);
        }
        nav.appendChild(links);
    }

    const spacer = document.createElement("div");
    spacer.className = "scrappee-spacer";
    nav.appendChild(spacer);

    const footer = document.createElement("div");
    footer.className = "scrappee-footer";
    const account = document.createElement("div");
    account.className = "scrappee-account";
    const avatar = document.createElement("div");
    avatar.className = "scrappee-avatar";
    avatar.textContent = data.initials || "A";
    const copy = document.createElement("div");
    copy.className = "scrappee-account-copy";
    const accountEmail = document.createElement("div");
    accountEmail.className = "scrappee-account-email";
    accountEmail.textContent = data.email || "Account";
    const balance = document.createElement("div");
    balance.className = "scrappee-balance";
    balance.textContent = data.balance || "";
    copy.append(accountEmail, balance);
    account.append(avatar, copy);
    footer.appendChild(account);

    const signout = document.createElement("button");
    signout.type = "button";
    signout.className = "scrappee-signout";
    signout.textContent = "Sign out";
    signout.onclick = () => setTriggerValue("signout", true);
    footer.appendChild(signout);
    nav.appendChild(footer);
    root.appendChild(nav);

    const main = document.querySelector('section[data-testid="stMain"]');
    if (main) {
        main.style.marginLeft = "0";
        main.style.width = "100%";
        main.style.boxSizing = "border-box";
        main.style.paddingLeft = "336px";
    }
    const block = document.querySelector('[data-testid="stMainBlockContainer"]');
    if (block) {
        block.style.maxWidth = "none";
        block.style.boxSizing = "border-box";
    }
}
"""

SIDEBAR = st.components.v2.component(
    name="scrappee_app_sidebar",
    html='<aside class="scrappee-shell"><div id="scrappee-sidebar-root"></div></aside>',
    css="""
    .scrappee-shell { position:fixed; inset:0 auto 0 0; width:336px; z-index:999999; box-sizing:border-box; background:#f8f9fb; border-right:1px solid #e5e7eb; color:#101828; font-family:var(--st-font-family,Inter,sans-serif); }
    #scrappee-sidebar-root { height:100%; }
    .scrappee-nav { height:100%; display:flex; flex-direction:column; box-sizing:border-box; padding:24px 16px 16px; }
    .scrappee-brand { padding:0 10px; font-size:21px; line-height:26px; font-weight:700; letter-spacing:-.03em; }
    .scrappee-email { padding:3px 10px 24px; color:#667085; font-size:12px; line-height:18px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .scrappee-section { margin:15px 10px 7px; color:#98a2b3; font-size:10px; line-height:14px; font-weight:700; letter-spacing:.13em; }
    .scrappee-section:first-child { margin-top:0; }
    .scrappee-links { display:flex; flex-direction:column; gap:1px; }
    .scrappee-link { display:flex; align-items:center; width:100%; min-height:38px; box-sizing:border-box; padding:0 10px; border:0; border-radius:8px; background:transparent; color:#344054; font:500 14px/20px inherit; cursor:pointer; text-align:left; }
    .scrappee-link:hover { background:#eef0f4; color:#101828; }
    .scrappee-link.active { background:#e9eaff; color:#3730a3; font-weight:600; box-shadow:inset 2px 0 0 #6366f1; }
    .scrappee-icon { width:20px; margin-right:9px; text-align:center; color:inherit; font-size:16px; line-height:1; }
    .scrappee-spacer { flex:1; min-height:16px; }
    .scrappee-footer { padding:14px 10px 0; border-top:1px solid #e5e7eb; }
    .scrappee-account { display:flex; align-items:center; gap:10px; margin-bottom:10px; }
    .scrappee-avatar { width:38px; height:38px; flex:0 0 38px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:#e9eaff; color:#3730a3; font-size:12px; font-weight:700; }
    .scrappee-account-copy { min-width:0; }
    .scrappee-account-email { color:#344054; font-size:12px; line-height:16px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .scrappee-balance { color:#667085; font-size:11px; line-height:16px; }
    .scrappee-signout { width:100%; height:34px; border:1px solid #d0d5dd; border-radius:7px; background:#fff; color:#475467; font:500 12px/32px inherit; cursor:pointer; }
    .scrappee-signout:hover { border-color:#b42318; background:#fef3f2; color:#b42318; }
    section[data-testid="stMain"] { width:100% !important; box-sizing:border-box !important; }
    [data-testid="stAppViewContainer"] > .main { margin-left:0 !important; padding-left:336px !important; box-sizing:border-box !important; }
    [data-testid="stMainBlockContainer"] { max-width:none !important; padding-top:24px !important; }
    section[data-testid="stSidebar"] { display:none !important; }
    header[data-testid="stHeader"] { display:none !important; height:0 !important; }
    @media (max-width:900px) {
        .scrappee-shell { width:280px; }
        [data-testid="stAppViewContainer"] > .main { margin-left:0 !important; padding-left:280px !important; }
    }
    @media (max-width:640px) {
        .scrappee-shell { width:100%; height:auto; max-height:76px; border-right:0; border-bottom:1px solid #e5e7eb; }
        .scrappee-nav { padding:14px 16px; }
        .scrappee-email,.scrappee-section,.scrappee-links,.scrappee-footer { display:none; }
        [data-testid="stAppViewContainer"] > .main { margin-left:0 !important; padding-left:0 !important; padding-top:76px !important; }
    }
    """,
    js=SIDEBAR_JS,
    isolate_styles=False,
)

def _billing(api_json):
    if not api_json:
        return None
    try:
        return api_json("GET", "/billing")
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None

def _admin_authorized(email):
    configured = {v.strip().lower() for v in os.getenv("ADMIN_EMAILS", "").split(",") if v.strip()}
    return bool(email) and email.lower() in configured

def render_sidebar(pages, api_json=None, auth_cookies=None):
    user = st.session_state.get("user") or {}
    email = user.get("email", "") if isinstance(user, dict) else str(user)
    billing = _billing(api_json)
    st.session_state["billing"] = billing
    sections = []
    for section, items in NAV_SECTIONS:
        sections.append({"title": section, "items": [{"label": label, "icon": icon} for label, icon in items if label in pages]})
    if _admin_authorized(email) and "Admin" in pages:
        sections.append({"title": "ADMIN", "items": [{"label": "Admin", "icon": ":material/admin_panel_settings:"}]})
    display_name = user.get("name") or user.get("full_name") or email or "Account"
    initials = "".join(x[0] for x in str(display_name).split()[:2]).upper() or "A"
    balance = billing.get("balance_cents", 0) / 100 if billing else None
    balance_text = f"{chr(36)}{balance:,.2f}" if balance is not None else ""
    data = {"email": email, "initials": initials, "balance": balance_text, "sections": sections, "paths": {label: (page.url_path or "") for label, page in pages.items()}}
    result = SIDEBAR(data=data, on_navigate_change=lambda: None, on_signout_change=lambda: None)
    if result.navigate:
        target = pages.get(result.navigate)
        if target is not None:
            st.switch_page(target)
    if result.signout:
        token = st.session_state.get("token")
        try:
            if token:
                requests.post(f"{API}/auth/logout", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        finally:
            if auth_cookies:
                auth_cookies.remove("scrappee_web_session", path="/", secure=True, same_site="lax")
            st.session_state.clear()
            st.rerun()
    return st.session_state.get("nav_page", "Dashboard")
