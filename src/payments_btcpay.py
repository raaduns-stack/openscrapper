import hashlib, hmac, os
from decimal import Decimal, InvalidOperation
import requests

BTCPAY_URL = os.getenv('BTCPAY_URL', '').rstrip('/')
BTCPAY_STORE_ID = os.getenv('BTCPAY_STORE_ID', '').strip()
BTCPAY_API_KEY = os.getenv('BTCPAY_API_KEY', '').strip()
BTCPAY_WEBHOOK_SECRET = os.getenv('BTCPAY_WEBHOOK_SECRET', '').strip()


def configured() -> bool:
    return bool(BTCPAY_URL and BTCPAY_STORE_ID and BTCPAY_API_KEY and BTCPAY_WEBHOOK_SECRET)


def _headers():
    return {'Authorization': f'token {BTCPAY_API_KEY}', 'Content-Type': 'application/json'}


def create_invoice(amount_usd: str, order_id: str, store_id: str | None = None):
    if not configured():
        raise RuntimeError('BTCPay is not configured')
    target_store = (store_id or BTCPAY_STORE_ID).strip()
    if not target_store:
        raise RuntimeError('BTCPay store is not configured')
    response = requests.post(
        f'{BTCPAY_URL}/api/v1/stores/{target_store}/invoices',
        headers=_headers(), json={'amount': amount_usd, 'currency': 'USD', 'orderId': order_id}, timeout=20,
    )
    if not response.ok:
        import logging
        logging.error("BTCPay API %s: %s", response.status_code, response.text[:1000])
        if response.status_code == 403:
            stores_response = requests.get(f'{BTCPAY_URL}/api/v1/stores', headers=_headers(), timeout=20)
            logging.error("BTCPay accessible stores %s: %s", stores_response.status_code, stores_response.text[:2000])
    response.raise_for_status()
    return response.json()


def verify_webhook(raw_body: bytes, signature: str) -> bool:
    if not BTCPAY_WEBHOOK_SECRET or not signature.startswith('sha256='):
        return False
    expected = hmac.new(BTCPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


def payment_btc(payload: dict):
    values = []
    for payment in payload.get('payments') or []:
        try:
            values.append(Decimal(str(payment.get('value'))))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return sum(values, Decimal('0')) if values else None
