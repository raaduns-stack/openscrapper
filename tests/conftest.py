import os
from urllib.parse import urlparse, urlunparse

import pytest
from cryptography.fernet import Fernet
from psycopg.types.json import Jsonb


# Never run the suite against the live application database.
if "CLAW_SCRAPPER_TEST_DATABASE_URL" in os.environ:
    os.environ["DATABASE_URL"] = os.environ["CLAW_SCRAPPER_TEST_DATABASE_URL"]
else:
    base_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://claw_scrapper:claw_scrapper_dev@127.0.0.1:5432/claw_scrapper",
    )
    parsed = urlparse(base_url)
    os.environ["DATABASE_URL"] = urlunparse(parsed._replace(path="/claw_scrapper_test"))

os.environ.setdefault("PREMIUM_PROVIDER_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture(scope="session", autouse=True)
def initialize_test_database():
    from src.db import init_db, db

    init_db()
    with db() as conn:
        conn.execute("UPDATE app_settings SET value='200'::jsonb WHERE key='scrap_creation_price_cents'")
        conn.execute("UPDATE app_settings SET value='100'::jsonb WHERE key='premium_serp_price_cents'")
        conn.execute("UPDATE app_settings SET value='1000'::jsonb WHERE key='serp_result_limit'")
        conn.commit()
    yield


@pytest.fixture(autouse=True)
def isolate_mutable_app_settings():
    from src.db import db

    with db() as conn:
        baseline = dict(conn.execute(
            "SELECT key,value FROM app_settings WHERE key IN "
            "('scrap_creation_price_cents','premium_serp_price_cents','serp_result_limit')"
        ).fetchall())
    old_admin_emails = os.environ.get("ADMIN_EMAILS")
    yield
    with db() as conn:
        for key, value in baseline.items():
            conn.execute("UPDATE app_settings SET value=%s WHERE key=%s", (Jsonb(value), key))
        conn.commit()
    if old_admin_emails is None:
        os.environ.pop("ADMIN_EMAILS", None)
    else:
        os.environ["ADMIN_EMAILS"] = old_admin_emails
