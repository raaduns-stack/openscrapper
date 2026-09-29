import streamlit as st
from src.ui.components.header import render_header


def _money(cents):
    return "$" + f"{int(cents) / 100:,.2f}"


def _submit_manual(api, method, amount, reference, sender, notes):
    payload = {
        "method": method,
        "amount_cents": round(float(amount) * 100),
        "reference": reference.strip(),
        "sender_name": sender.strip() or None,
        "notes": notes.strip() or None,
    }
    r = api("POST", "/billing/deposits/manual", json=payload)
    r.raise_for_status()
    st.success("Deposit confirmation submitted. Credit will be added after admin confirmation.")
    st.rerun()


def render_deposit(api, api_json, api_error):
    render_header("Deposit", "Add funds to your Scrappee wallet securely.")
    try:
        config = api_json("GET", "/billing/deposit-config")
    except Exception as exc:
        st.error("Could not load deposit options: " + api_error(exc))
        return
    st.markdown("### Add funds")
    st.caption("Choose a payment method below. Wallet credit is added only after confirmation.")
    tabs = st.tabs(["Bitcoin", "Litecoin", "USDT", "Bank Transfer"])
    with tabs[0]:
        st.subheader("Bitcoin")
        st.caption("Payment is handled by BTCPay Server.")
        with st.form("deposit-btc"):
            amount = st.number_input("Amount (USD)", min_value=50.0, step=5.0, value=50.0, key="deposit-btc-amount")
            submit = st.form_submit_button("CREATE BTC PAYMENT", type="primary", use_container_width=True)
        if submit:
            try:
                data = api_json("POST", "/billing/deposits/btcpay", json={"amount_cents": round(amount * 100), "asset": "BTC"})
                st.session_state["deposit_checkout"] = data["checkout_url"]
                st.success("BTCPay payment created.")
            except Exception as exc:
                st.error(api_error(exc, "Could not create BTC payment."))
        if st.session_state.get("deposit_checkout"):
            st.link_button("OPEN BTCPAY CHECKOUT", st.session_state["deposit_checkout"], use_container_width=True)

    with tabs[1]:
        st.subheader("Litecoin")
        if not config.get("btcpay_ltc_configured"):
            st.warning("Litecoin BTCPay is not configured by the administrator yet.")
        else:
            st.caption("Payment is handled by the configured Litecoin BTCPay store.")
            with st.form("deposit-ltc"):
                amount = st.number_input("Amount (USD)", min_value=50.0, step=5.0, value=50.0, key="deposit-ltc-amount")
                submit = st.form_submit_button("CREATE LTC PAYMENT", type="primary", use_container_width=True)
            if submit:
                try:
                    data = api_json("POST", "/billing/deposits/btcpay", json={"amount_cents": round(amount * 100), "asset": "LTC"})
                    st.session_state["deposit_ltc_checkout"] = data["checkout_url"]
                    st.success("BTCPay payment created.")
                except Exception as exc:
                    st.error(api_error(exc, "Could not create Litecoin payment."))
            if st.session_state.get("deposit_ltc_checkout"):
                st.link_button("OPEN BTCPAY CHECKOUT", st.session_state["deposit_ltc_checkout"], use_container_width=True)
    with tabs[2]:
        st.subheader("USDT")
        st.caption("Use BTCPay when configured, or the administrator-provided static wallet when enabled.")
        if config.get("btcpay_usdt_configured"):
            with st.form("deposit-usdt-btcpay"):
                amount = st.number_input("Amount (USD)", min_value=50.0, step=5.0, value=50.0, key="deposit-usdt-amount")
                submit = st.form_submit_button("CREATE USDT PAYMENT", type="primary", use_container_width=True)
            if submit:
                try:
                    data = api_json("POST", "/billing/deposits/btcpay", json={"amount_cents": round(amount * 100), "asset": "USDT"})
                    st.session_state["deposit_usdt_checkout"] = data["checkout_url"]
                    st.success("BTCPay payment created.")
                except Exception as exc:
                    st.error(api_error(exc, "Could not create USDT payment."))
            if st.session_state.get("deposit_usdt_checkout"):
                st.link_button("OPEN BTCPAY CHECKOUT", st.session_state["deposit_usdt_checkout"], use_container_width=True)
        elif config.get("usdt_manual_enabled"):
            st.info("USDT wallet: " + str(config.get("usdt_manual_wallet")))
            st.caption("Send USDT to the wallet above, then submit the transaction reference for administrator confirmation.")
            with st.form("deposit-usdt-manual"):
                amount = st.number_input("Amount (USD)", min_value=50.0, step=5.0, value=50.0, key="deposit-usdt-manual-amount")
                reference = st.text_input("Transaction hash / reference")
                sender = st.text_input("Sender name")
                notes = st.text_area("Notes", height=90)
                submit = st.form_submit_button("SUBMIT USDT CONFIRMATION", type="primary", use_container_width=True)
            if submit:
                if not reference.strip():
                    st.error("Transaction hash / reference is required.")
                else:
                    try:
                        _submit_manual(api, "usdt_manual", amount, reference, sender, notes)
                    except Exception as exc:
                        st.error(api_error(exc, "Could not submit USDT confirmation."))
        else:
            st.warning("USDT deposit is not configured yet.")

    with tabs[3]:
        st.subheader("Bank Transfer")
        details = config.get("bank_transfer_details") or {}
        if details:
            st.info("\n".join(f"{k.replace('_', ' ').title()}: {v}" for k, v in details.items() if v))
        else:
            st.warning("Bank transfer details are not configured yet.")
        with st.form("deposit-bank"):
            amount = st.number_input("Amount (USD)", min_value=50.0, step=5.0, value=50.0, key="deposit-bank-amount")
            reference = st.text_input("Bank payment reference")
            sender = st.text_input("Account holder / sender name")
            notes = st.text_area("Notes", height=90)
            submit = st.form_submit_button("SUBMIT BANK CONFIRMATION", type="primary", use_container_width=True)
        if submit:
            if not reference.strip():
                st.error("Bank payment reference is required.")
            else:
                try:
                    _submit_manual(api, "bank_transfer", amount, reference, sender, notes)
                except Exception as exc:
                    st.error(api_error(exc, "Could not submit bank confirmation."))
    st.divider()
    st.subheader("Deposit history")
    try:
        btcpay = api_json("GET", "/billing/deposits")
        manual = api_json("GET", "/billing/deposits/manual")
        rows = []
        for item in btcpay:
            rows.append({
                "Method": str(item.get("asset", "BTC")) + " / BTCPay",
                "Amount": _money(item["requested_cents"]),
                "Reference": item["invoice_id"],
                "Status": item["status"].title(),
                "Created": item["created_at"],
            })
        for item in manual:
            method = "USDT / Manual" if item["method"] == "usdt_manual" else "Bank Transfer"
            rows.append({
                "Method": method,
                "Amount": _money(item["amount_cents"]),
                "Reference": item["reference"],
                "Status": item["status"].title(),
                "Created": item["created_at"],
            })
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No deposits yet.")
    except Exception as exc:
        st.caption("Could not load deposit history: " + api_error(exc))
