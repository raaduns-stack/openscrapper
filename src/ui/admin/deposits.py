import streamlit as st


def render_deposits(api, api_json, api_error, **kwargs):
    st.subheader("Deposit Configuration")
    try:
        cfg = api_json("GET", "/admin/deposit-config")
        enabled = st.checkbox("Enable static USDT wallet", value=bool(cfg.get("usdt_manual_enabled")))
        wallet = st.text_input("USDT wallet address", value=cfg.get("usdt_manual_wallet") or "")
        ltc_store = st.text_input("BTCPay Litecoin store ID", value=cfg.get("btcpay_ltc_store_id") or "")
        usdt_store = st.text_input("BTCPay USDT store ID", value=cfg.get("btcpay_usdt_store_id") or "")
        bank = cfg.get("bank_transfer_details") or {}
        bank_name = st.text_input("Bank name", value=bank.get("bank_name", ""))
        account_name = st.text_input("Account name", value=bank.get("account_name", ""))
        account_number = st.text_input("Account number", value=bank.get("account_number", ""))
        branch = st.text_input("Branch / code", value=bank.get("branch", ""))
        if st.button("SAVE DEPOSIT CONFIG", type="primary"):
            api("POST", "/admin/deposit-config", json={
                "usdt_manual_enabled": enabled,
                "usdt_manual_wallet": wallet or None,
                "btcpay_ltc_store_id": ltc_store or None,
                "btcpay_usdt_store_id": usdt_store or None,
                "bank_transfer_details": {"bank_name": bank_name, "account_name": account_name, "account_number": account_number, "branch": branch},
            }).raise_for_status()
            st.success("Deposit configuration saved.")
            st.rerun()
    except Exception as exc:
        st.error("Could not load deposit configuration: " + api_error(exc))

    st.divider()
    st.subheader("Pending Manual Deposits")
    try:
        rows = api_json("GET", "/admin/deposits")
        if not rows:
            st.caption("No pending manual deposits.")
        for item in rows:
            with st.container(border=True):
                st.write(item["email"] + " · " + item["method"] + " · $" + f"{item['amount_cents']/100:,.2f}")
                st.caption("Reference: " + item["reference"] + " · Sender: " + (item.get("sender_name") or "-"))
                if item.get("notes"):
                    st.caption(item["notes"])
                left, right = st.columns(2)
                if left.button("APPROVE", key="approve-" + item["id"], type="primary"):
                    api("POST", "/admin/deposits/" + item["id"] + "/review", json={"approved": True}).raise_for_status()
                    st.rerun()
                if right.button("REJECT", key="reject-" + item["id"]):
                    api("POST", "/admin/deposits/" + item["id"] + "/review", json={"approved": False}).raise_for_status()
                    st.rerun()
    except Exception as exc:
        st.error("Could not load pending deposits: " + api_error(exc))
