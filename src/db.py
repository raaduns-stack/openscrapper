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
CREATE TABLE IF NOT EXISTS wallet_deposits (
 id UUID PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 btcpay_invoice_id TEXT UNIQUE NOT NULL,
 requested_cents BIGINT NOT NULL CHECK(requested_cents > 0),
 paid_btc NUMERIC(24,12),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','settled','expired','invalid')),
 settled_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_wallet_deposits_user ON wallet_deposits(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_deposits_status ON wallet_deposits(status,updated_at);
CREATE TABLE IF NOT EXISTS manual_deposits (
 id UUID PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 method TEXT NOT NULL CHECK(method IN ('usdt_manual','bank_transfer')),
 amount_cents BIGINT NOT NULL CHECK(amount_cents > 0),
 reference TEXT NOT NULL,
 sender_name TEXT,
 notes TEXT,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
 reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
 reviewed_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(method,reference)
);
CREATE INDEX IF NOT EXISTS idx_manual_deposits_user ON manual_deposits(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_manual_deposits_status ON manual_deposits(status,created_at DESC);
CREATE TABLE IF NOT EXISTS app_settings (
 key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_tickets (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, subject TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'normal', status TEXT NOT NULL DEFAULT 'new', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), resolved_at TIMESTAMPTZ, closed_at TIMESTAMPTZ, assigned_to UUID REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON support_tickets(user_id,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status,updated_at DESC);
CREATE TABLE IF NOT EXISTS support_ticket_messages (
 id UUID PRIMARY KEY, ticket_id UUID NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE, author_id UUID REFERENCES users(id) ON DELETE SET NULL, body TEXT NOT NULL, is_internal BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_support_ticket_messages_ticket ON support_ticket_messages(ticket_id,created_at);
CREATE TABLE IF NOT EXISTS support_ticket_attachments (
 id UUID PRIMARY KEY, ticket_id UUID NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE, message_id UUID REFERENCES support_ticket_messages(id) ON DELETE SET NULL, user_id UUID REFERENCES users(id) ON DELETE SET NULL, filename TEXT NOT NULL, content_type TEXT, size_bytes BIGINT NOT NULL DEFAULT 0, storage_path TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_ticket_ratings (
 ticket_id UUID PRIMARY KEY REFERENCES support_tickets(id) ON DELETE CASCADE, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5), comment TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS support_audit_events (
 id UUID PRIMARY KEY, ticket_id UUID REFERENCES support_tickets(id) ON DELETE CASCADE, actor_id UUID REFERENCES users(id) ON DELETE SET NULL, action TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_support_audit_ticket ON support_audit_events(ticket_id,created_at);
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
CREATE TABLE IF NOT EXISTS extension_connections (
 user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, version TEXT NOT NULL, last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_extension_connections_last_seen ON extension_connections(last_seen_at);
CREATE TABLE IF NOT EXISTS scraps (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', criteria JSONB NOT NULL DEFAULT '{}', crawler_config JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS scraps (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', criteria JSONB NOT NULL DEFAULT '{}', crawler_config JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ
);
ALTER TABLE scraps ADD COLUMN IF NOT EXISTS llm_calls BIGINT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS page_indexer_jobs (
 id UUID PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE,
 url TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'processing' CHECK(status IN ('processing','completed','failed','refunded')),
 charged_cents BIGINT NOT NULL DEFAULT 0,
 leads_count INTEGER NOT NULL DEFAULT 0,
 result JSONB NOT NULL DEFAULT '{}',
 error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(user_id,scrap_id,fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_page_indexer_user_created ON page_indexer_jobs(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_indexer_scrap_created ON page_indexer_jobs(scrap_id,created_at DESC);
ALTER TABLE page_indexer_jobs DROP CONSTRAINT IF EXISTS page_indexer_jobs_user_id_fingerprint_key;
ALTER TABLE page_indexer_jobs DROP CONSTRAINT IF EXISTS page_indexer_jobs_user_id_scrap_id_fingerprint_key;
ALTER TABLE page_indexer_jobs DROP CONSTRAINT IF EXISTS page_indexer_jobs_user_scrap_fingerprint_key;
ALTER TABLE page_indexer_jobs ADD CONSTRAINT page_indexer_jobs_user_scrap_fingerprint_key UNIQUE(user_id,scrap_id,fingerprint);
ALTER TABLE page_indexer_jobs ADD COLUMN IF NOT EXISTS leads_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE page_indexer_jobs ADD COLUMN IF NOT EXISTS result JSONB NOT NULL DEFAULT '{}';
ALTER TABLE page_indexer_jobs ADD COLUMN IF NOT EXISTS error TEXT;
ALTER TABLE serp_results ADD COLUMN IF NOT EXISTS raw_text TEXT;
CREATE TABLE IF NOT EXISTS search_template_categories (
 id UUID PRIMARY KEY, name TEXT NOT NULL UNIQUE, active BOOLEAN NOT NULL DEFAULT true, position INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS search_templates (
 id UUID PRIMARY KEY, category_id UUID NOT NULL REFERENCES search_template_categories(id) ON DELETE CASCADE, provider TEXT NOT NULL CHECK(provider IN ('google','bing')), family TEXT NOT NULL, template TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT true, position INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS search_parameters (
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, parameter_id TEXT NOT NULL, provider TEXT NOT NULL, query TEXT NOT NULL, url TEXT NOT NULL, family TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, category TEXT NOT NULL DEFAULT '', template_id UUID, variables JSONB NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending', completed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(scrap_id, parameter_id)
);
ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '';
ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS template_id UUID;
ALTER TABLE search_parameters ADD COLUMN IF NOT EXISTS variables JSONB NOT NULL DEFAULT '{}';
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
 id UUID PRIMARY KEY, scrap_id UUID NOT NULL REFERENCES scraps(id) ON DELETE CASCADE, data JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'working' CHECK(status IN ('working','completed')), approved_at TIMESTAMPTZ, approved_by UUID REFERENCES users(id) ON DELETE SET NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'working';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_leads_scrap_status ON leads(scrap_id,status,created_at);
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
CREATE INDEX IF NOT EXISTS idx_search_parameters_queue ON search_parameters(scrap_id, category, status, position);
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
CREATE TABLE IF NOT EXISTS sender_accounts (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 display_name TEXT NOT NULL, email TEXT NOT NULL, provider TEXT NOT NULL CHECK(provider IN ('smtp','gmail_oauth','microsoft_oauth')),
 enabled BOOLEAN NOT NULL DEFAULT true, health TEXT NOT NULL DEFAULT 'unknown',
 config JSONB NOT NULL DEFAULT '{}', secret_encrypted TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(user_id,email)
);
CREATE TABLE IF NOT EXISTS sender_letters (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, subject TEXT NOT NULL, body_text TEXT NOT NULL, body_html TEXT,
 variables JSONB NOT NULL DEFAULT '[]', active BOOLEAN NOT NULL DEFAULT true,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sender_campaigns (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name TEXT NOT NULL, sender_id UUID NOT NULL REFERENCES sender_accounts(id) ON DELETE RESTRICT,
 letter_id UUID NOT NULL REFERENCES sender_letters(id) ON DELETE RESTRICT,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','paused','completed')),
 config JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sender_campaign_leads (
 campaign_id UUID NOT NULL REFERENCES sender_campaigns(id) ON DELETE CASCADE,
 lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(campaign_id,lead_id)
);
CREATE INDEX IF NOT EXISTS idx_sender_campaign_leads_user ON sender_campaign_leads(user_id,campaign_id);
ALTER TABLE sender_accounts ALTER COLUMN email DROP NOT NULL;
CREATE TABLE IF NOT EXISTS sender_messages (
 id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 campaign_id UUID REFERENCES sender_campaigns(id) ON DELETE SET NULL,
 lead_id UUID REFERENCES leads(id) ON DELETE SET NULL, sender_id UUID REFERENCES sender_accounts(id) ON DELETE SET NULL,
 recipient_email TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','sent','failed','replied')),
 idempotency_key TEXT NOT NULL, reply_to TEXT, provider_message_id TEXT, error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(user_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS sender_oauth_states (
 state TEXT PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 sender_id UUID REFERENCES sender_accounts(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, display_name TEXT, expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sender_oauth_states_expiry ON sender_oauth_states(expires_at);
CREATE INDEX IF NOT EXISTS idx_sender_accounts_user ON sender_accounts(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sender_letters_user ON sender_letters(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sender_campaigns_user ON sender_campaigns(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sender_messages_user ON sender_messages(user_id,created_at DESC);
"""

@contextmanager
def db():
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn


def init_db():
    with db() as conn:
        conn.execute(SCHEMA)
        conn.execute("ALTER TABLE sender_oauth_states ALTER COLUMN sender_id DROP NOT NULL")
        conn.execute("ALTER TABLE wallet_deposits ADD COLUMN IF NOT EXISTS asset TEXT NOT NULL DEFAULT 'BTC'")
        conn.execute("ALTER TABLE sender_oauth_states ADD COLUMN IF NOT EXISTS display_name TEXT")
        conn.execute("DELETE FROM sender_accounts WHERE provider='gmail_oauth' AND email IS NULL AND NOT (config ? 'oauth_email')")
        conn.execute("UPDATE sender_accounts SET config=config || '{\"throttle_seconds\":60}'::jsonb WHERE provider='smtp' AND NOT (config ? 'throttle_seconds')")
        conn.execute("ALTER TABLE sender_messages DROP CONSTRAINT IF EXISTS sender_messages_status_check")
        conn.execute("ALTER TABLE sender_messages ADD CONSTRAINT sender_messages_status_check CHECK(status IN ('queued','sending','sent','failed','replied'))")
        conn.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_status_check")
        conn.execute("ALTER TABLE leads ADD CONSTRAINT leads_status_check CHECK(status IN ('working','completed'))")
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS request_index INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS depth INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS occurrence_index INTEGER NOT NULL DEFAULT 0")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('scrap_creation_price_cents','200'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('serp_result_limit','1000'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('premium_serp_price_cents','100'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('page_indexer_price_cents','1'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('paid_enrichment_unit_micros_usd','1000'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('research_default_max_leads','100'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('research_max_leads','10000'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('research_timeout_hours','48'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('usdt_manual_wallet','null'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('usdt_manual_enabled','false'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("INSERT INTO app_settings(key,value) VALUES('bank_transfer_details','{}'::jsonb) ON CONFLICT(key) DO NOTHING")
        conn.execute("ALTER TABLE premium_provider_configs DROP CONSTRAINT IF EXISTS premium_provider_configs_provider_check")
        conn.execute("ALTER TABLE premium_provider_configs ADD CONSTRAINT premium_provider_configs_provider_check CHECK(provider IN ('serper','dataforseo','serpapi','brightdata'))")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('serper',true,true,'{\"endpoint\":\"https://google.serper.dev/search\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('dataforseo',true,false,'{\"base_url\":\"https://api.dataforseo.com\",\"location_code\":2840,\"language_code\":\"en\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('serpapi',false,false,'{\"endpoint\":\"https://serpapi.com/search.json\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO premium_provider_configs(provider,enabled,is_default,settings) VALUES('brightdata',false,false,'{\"endpoint\":\"https://api.brightdata.com/request\",\"zone\":\"serp_api1\",\"timeout\":30}'::jsonb) ON CONFLICT(provider) DO NOTHING")
        conn.execute("INSERT INTO wallets(user_id) SELECT id FROM users ON CONFLICT(user_id) DO NOTHING")
        conn.execute("INSERT INTO search_template_categories(id,name,position) VALUES(gen_random_uuid(),'People',1),(gen_random_uuid(),'Contact',2),(gen_random_uuid(),'Company',3),(gen_random_uuid(),'Keyword',4),(gen_random_uuid(),'Broad',5) ON CONFLICT(name) DO NOTHING")
        conn.execute("INSERT INTO search_templates(id,category_id,provider,family,template,position) SELECT gen_random_uuid(),c.id,'google',x.family,x.template,x.position FROM (VALUES ('People','people','{product} {role} {geography} contact',1),('Contact','contact','{product} {geography} email',2),('Company','company','{product} {geography} company contact',3),('Keyword','keyword-contact','{product} {keyword} {geography} contact',4),('Broad','broad','{product} {geography}',5)) AS x(category,family,template,position) JOIN search_template_categories c ON c.name=x.category WHERE NOT EXISTS (SELECT 1 FROM search_templates t WHERE t.category_id=c.id AND t.provider='google')")
        conn.execute("INSERT INTO search_templates(id,category_id,provider,family,template,position) SELECT gen_random_uuid(),c.id,'bing',x.family,x.template,x.position FROM (VALUES ('People','people','{product} {role} {geography} contact',1),('Contact','contact','{product} {geography} email',2),('Company','company','{product} {geography} company contact',3),('Keyword','keyword-email','{product} {keyword} {geography} email',4),('Broad','broad','{product} {geography}',5)) AS x(category,family,template,position) JOIN search_template_categories c ON c.name=x.category WHERE NOT EXISTS (SELECT 1 FROM search_templates t WHERE t.category_id=c.id AND t.provider='bing')")
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
