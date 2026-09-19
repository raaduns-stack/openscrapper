from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
import psycopg
from src.policy import DEFAULT_GENERIC_MAILBOX_PREFIXES, normalize_mailbox_prefix
from psycopg.types.json import Jsonb

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://claw_scrapper:claw_scrapper_dev@127.0.0.1:5432/claw_scrapper")
RETENTION_DAYS = 31
SESSION_IDLE_MINUTES = int(os.getenv("SCRAPPEE_SESSION_IDLE_MINUTES", "20"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id UUID PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS wallets (
 user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, balance_cents BIGINT NOT NULL DEFAULT 0 CHECK(balance_cents >= 0), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS wallet_transactions (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, amount_cents BIGINT NOT NULL, balance_after_cents BIGINT NOT NULL, transaction_type TEXT NOT NULL, reference_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id, transaction_type, reference_id)
);
CREATE TABLE IF NOT EXISTS app_settings (
 key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS generic_mailbox_prefixes (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, prefix TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id, prefix)
);
CREATE TABLE IF NOT EXISTS domain_rules (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, domain TEXT NOT NULL, rule_type TEXT NOT NULL CHECK(rule_type IN ('blacklist','whitelist')), created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id, domain, rule_type)
);
CREATE TABLE IF NOT EXISTS sessions (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT UNIQUE NOT NULL, expires_at TIMESTAMPTZ NOT NULL, persistent BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS persistent BOOLEAN NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS scraps (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', criteria JSONB NOT NULL DEFAULT '{}', crawler_config JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS search_parameters (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, parameter_id TEXT NOT NULL, provider TEXT NOT NULL, query TEXT NOT NULL, url TEXT NOT NULL, family TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(scrap_id, parameter_id)
);
CREATE TABLE IF NOT EXISTS serp_sessions (
 token TEXT PRIMARY KEY, user_id UUID REFERENCES users(id) ON DELETE CASCADE, scrap_id UUID REFERENCES scraps(id) ON DELETE CASCADE, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL, urls JSONB NOT NULL DEFAULT '[]', results JSONB NOT NULL DEFAULT '[]', imports JSONB NOT NULL DEFAULT '[]', sources JSONB NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS premium_serp_extractions (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, idempotency_key TEXT NOT NULL, search_url TEXT NOT NULL, provider TEXT NOT NULL, status TEXT NOT NULL, charged_cents BIGINT NOT NULL DEFAULT 0, result JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(user_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS premium_provider_configs (
 provider TEXT PRIMARY KEY CHECK(provider IN ('serper','dataforseo','serpapi','brightdata')), enabled BOOLEAN NOT NULL DEFAULT false, is_default BOOLEAN NOT NULL DEFAULT false, credentials TEXT, settings JSONB NOT NULL DEFAULT '{}', updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS serp_sources (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, provider TEXT NOT NULL, query TEXT NOT NULL, url TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS serp_results (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, url TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', snippet TEXT NOT NULL DEFAULT '', provider TEXT, page_url TEXT, captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS url_occurrences (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, url TEXT NOT NULL, serp_result_id UUID REFERENCES serp_results(id) ON DELETE SET NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS jobs (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, status TEXT NOT NULL, stage TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}', result JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS crawl_pages (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, url TEXT NOT NULL, status TEXT, content TEXT, error TEXT, content_type TEXT, request_index INTEGER NOT NULL DEFAULT 0, depth INTEGER NOT NULL DEFAULT 0, occurrence_index INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS evidence (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, source_type TEXT NOT NULL, source_id UUID, data JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS leads (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lead_sources (
 lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE, evidence_id UUID REFERENCES evidence(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS exports (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, format TEXT NOT NULL, location TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_scraps_user_created ON scraps(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_generic_mailbox_user ON generic_mailbox_prefixes(user_id, prefix);
CREATE INDEX IF NOT EXISTS idx_domain_rules_user ON domain_rules(user_id, domain);
CREATE INDEX IF NOT EXISTS idx_search_parameters_scrap ON search_parameters(scrap_id, created_at);
CREATE INDEX IF NOT EXISTS idx_serp_results_scrap ON serp_results(scrap_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_premium_serp_user ON premium_serp_extractions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_serp_sessions_expiry ON serp_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_url_occurrences_scrap ON url_occurrences(scrap_id, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_scrap ON jobs(scrap_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_crawl_pages_scrap ON crawl_pages(scrap_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_scrap ON evidence(scrap_id, created_at);
CREATE INDEX IF NOT EXISTS idx_lead_sources_lead ON lead_sources(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_sources_evidence ON lead_sources(evidence_id);
CREATE INDEX IF NOT EXISTS idx_exports_scrap ON exports(scrap_id, created_at);
"""

@contextmanager
def db():
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


def init_db():
    with db() as conn:
        conn.execute(SCHEMA)
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS request_index INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS depth INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS occurrence_index INTEGER NOT NULL DEFAULT 0")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('scrap_creation_price_cents','200'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('serp_result_limit','1000'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('premium_serp_price_cents','100'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('research_default_max_leads','100'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('research_max_leads','10000'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('research_timeout_hours','48'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("ALTER TABLE premium_provider_configs DROP CONSTRAINT IF EXISTS premium_provider_configs_provider_check")
        conn.execute("ALTER TABLE premium_provider_configs ADD CONSTRAINT premium_provider_configs_provider_check CHECK(provider IN ('serper','dataforseo','serpapi','brightdata'))")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('serper',true,true,'{\"endpoint\":\"https://google.serper.dev/search\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('dataforseo',true,false,'{\"base_url\":\"https://api.dataforseo.com\",\"location_code\":2840,\"language_code\":\"en\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('serpapi',false,false,'{\"endpoint\":\"https://serpapi.com/search.json\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('brightdata',false,false,'{\"endpoint\":\"https://api.brightdata.com/request\",\"zone\":\"serp_api1\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO wallets(user_id) SELECT id FROM users ON CONFLICT(user_id) DO NOTHING")
        conn.execute("ALTER TABLE scraps ADD COLUMN IF NOT EXISTS crawler_config JSONB NOT NULL DEFAULT '{}'::jsonb")
        conn.execute("ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS error TEXT")
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS content_type TEXT")
        conn.execute("UPDATE sessions SET expires_at=LEAST(expires_at, now() + make_interval(mins => %s)) WHERE persistent=false",(SESSION_IDLE_MINUTES,))
        for prefix in DEFAULT_GENERIC_MAILBOX_PREFIXES:
            conn.execute("INSERT INTO generic_mailbox_prefixes(id,user_id,prefix) SELECT gen_random_uuid(),id,%s FROM users ON CONFLICT (user_id,prefix) DO NOTHING", (normalize_mailbox_prefix(prefix),))
        conn.commit()


def purge_expired_history():
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    with db() as conn:
        conn.execute("DELETE FROM scraps WHERE created_at < %s AND status NOT IN ('active','running')", (cutoff,))
        conn.execute("DELETE FROM sessions WHERE expires_at < now() AND persistent=false")
        conn.commit()


def get_client_policies(user_id):
    import uuid
    with db() as conn:
        prefixes = {r[0] for r in conn.execute("SELECT prefix FROM generic_mailbox_prefixes WHERE user_id=%s", (uuid.UUID(str(user_id)),)).fetchall()}
        rules = [(r[0], r[1]) for r in conn.execute("SELECT domain,rule_type FROM domain_rules WHERE user_id=%s", (uuid.UUID(str(user_id)),)).fetchall()]
    return prefixes, rules
