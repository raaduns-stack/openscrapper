import streamlit as st


def render_add_funds(api, api_json):
    st.subheader('Add Funds')
    st.caption('Create a Bitcoin payment for your Scrappee USD balance.')
    amount = st.number_input('Amount (USD)', min_value=1.00, max_value=1000000.00, value=25.00, step=5.00, format='%.2f')
    if st.button('Generate BTC Payment', type='primary', key='generate-btcpay'):
        try:
            response = api('POST', '/billing/deposits/btcpay', json={'amount_cents': int(round(amount * 100))})
            response.raise_for_status()
            st.session_state['btcpay_deposit'] = response.json()
            st.rerun()
        except Exception as exc:
            st.error(f'Could not create Bitcoin payment: {exc}')
    deposit = st.session_state.get('btcpay_deposit')
    if deposit:
        st.divider()
        st.write(f"Requested credit: **${deposit['requested_cents'] / 100:.2f}**")
        st.link_button('Open BTC Payment', deposit['checkout_url'])
        st.caption('Payment is credited only after BTCPay reports InvoiceSettled.')
