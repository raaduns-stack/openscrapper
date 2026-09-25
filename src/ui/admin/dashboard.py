import os
import streamlit as st
from src.ui.admin.billing import render_billing
from src.ui.admin.wallets import render_wallets
from src.ui.admin.users import render_users
from src.ui.admin.serp_providers import render_serp_providers
from src.ui.admin.client_policies import render_client_policies
from src.ui.admin.browser_extension import render_browser_extension

def render_admin(api, api_json, api_error):
    admins={x.strip().lower() for x in os.getenv("ADMIN_EMAILS","").split(",") if x.strip()}
    user=st.session_state.get("user") or {}
    if user.get("email","").lower() not in admins:
        return
    tabs=st.tabs(["Billing & Limits","Wallets","Users","SERP Providers","Client Policies","Browser Extension"])
    renderers=[render_billing,render_wallets,render_users,render_serp_providers,render_client_policies,render_browser_extension]
    for tab,renderer in zip(tabs,renderers):
        with tab:
            renderer(api,api_json,api_error)
