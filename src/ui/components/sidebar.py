import os
import requests
import streamlit as st

API = os.getenv('API_URL', 'http://127.0.0.1:8000').rstrip('/')


def render_sidebar(api_json=None):
    billing = None
    with st.sidebar:
        st.title('Scrappee')
        user = st.session_state.get('user') or {}
        email = user.get('email', '') if isinstance(user, dict) else str(user)
        st.caption(email)
        if api_json:
            try:
                billing = api_json('GET', '/billing')
                st.metric('Balance', f"${billing['balance_cents']/100:.2f}")
                st.caption(
                    f"New Scrap: ${billing['scrap_creation_price_cents']/100:.2f} · "
                    f"Enrichment: ${billing['paid_enrichment_unit_micros_usd']/1000000:.3f}/Lead"
                )
            except requests.RequestException as exc:
                st.caption(f'Billing unavailable: {exc}')
            except (KeyError, TypeError, ValueError) as exc:
                st.caption(f'Billing data unavailable: {exc}')

        st.session_state['billing'] = billing

        admins={x.strip().lower() for x in os.getenv('ADMIN_EMAILS','').split(',') if x.strip()}
        is_admin=email.lower() in admins
        nav_options = [
            'Dashboard',
            'New Scrap',
            'Current Scrap',
            'Lead Workstation',
            'Senders',
            'Scrap History',
            'Exports',
            'Settings',
        ]
        if is_admin:
            nav_options.append('Admin')
        current_page = st.session_state.get('nav_page', 'Dashboard')
        index = nav_options.index(current_page) if current_page in nav_options else 0
        page = st.radio('Navigation', nav_options, index=index)
        if page != st.session_state.nav_page:
            st.session_state.nav_page = page

        if st.button('Sign out', key='sign-out'):
            try:
                token = st.session_state.get('token')
                if token:
                    requests.post(f'{API}/auth/logout', headers={'Authorization': f'Bearer {token}'}, timeout=10)
            finally:
                st.session_state.clear()
                st.rerun()

    return page
