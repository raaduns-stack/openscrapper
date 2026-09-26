import streamlit as st

def render_wallets(api, api_json, api_error, **kwargs):
        st.subheader('Wallet Adjustments')
        st.caption('Add or remove wallet credit for any user.')
        try:
            wallets=api_json('GET','/admin/wallets')
            st.dataframe([{'Email':w['email'],'Balance':f"${w['balance_cents']/100:.2f}"} for w in wallets],use_container_width=True,hide_index=True)
            with st.form('admin-wallet-adjust'):
                wallet_emails=[w['email'] for w in wallets]
                wallet_email=st.selectbox('User',wallet_emails) if wallet_emails else st.text_input('User email')
                wallet_amount=st.number_input('Adjustment ($)',value=0.0,step=1.0,help='Positive adds credit; negative removes credit.')
                if st.form_submit_button('APPLY WALLET ADJUSTMENT',type='primary'):
                    cents=round(wallet_amount*100)
                    if cents==0: raise ValueError('Adjustment cannot be zero.')
                    r=api('POST','/admin/wallet-adjust',json={'user_email':wallet_email,'amount_cents':cents});r.raise_for_status();st.rerun()
        except Exception as exc: st.error(f'Could not load wallet administration: {exc}')
