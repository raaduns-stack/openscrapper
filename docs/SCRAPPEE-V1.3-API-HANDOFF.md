# Scrappee V1.3 API Handoff

**Status:** Backend handoff specification generated from the implemented FastAPI service.
**Audience:** Frontend designer / frontend engineer.
**Backend:** FastAPI + PostgreSQL.
**Authentication:** Bearer token in `Authorization` header.

## 1. Integration rules

- The frontend is a presentation layer; PostgreSQL state is authoritative.
- All user-owned resources are scoped server-side to the authenticated user.
- Never store provider credentials, database credentials, or capability secrets in the frontend.
- Money values are returned as integer cents; display currency formatting in the UI.
- ISO-8601 timestamps are returned by the API.
- Do not infer lifecycle state from browser/session state.
- Job polling must use `GET /jobs/{job_id}`; status data is observational.
- Premium provider names are not search-engine provider names. Search-engine values are `google` or `bing`.

## 2. Authentication

### POST `/auth/register`
Request: `{ "email": string, "password": string }`.
Password length: 8–200 characters.
Response: `{ user_id, email, token, expires_at }`.

### POST `/auth/login`
Request: `{ "email": string, "password": string }`.
Response: `{ email, token, expires_at }`.

### GET `/auth/me`
Auth required.
Response: `{ "id": string, "email": string }`.

Frontend behavior: store the authenticated session securely and send `Authorization: Bearer <token>` on protected requests.

## 3. Billing and Scrap creation

### GET `/billing`
Auth required.
Response:
```json
{
  "balance_cents": 1000,
  "scrap_creation_price_cents": 200,
  "premium_serp_price_cents": 100
}
```

### POST `/scraps`
Auth required. Creates and charges one Scrap atomically.
Request:
```json
{
  "name": "Current Scrap",
  "criteria": {},
  "crawler": {}
}
```
Response includes `id`, `name`, `status`, `charged_cents`, `balance_cents`.
Possible UI errors: `402` insufficient wallet; `409` another active/running Scrap exists; `422` invalid request.

**UI rule:** show the configured Scrap price and wallet balance before creation. Do not hard-code `$2`.

### GET `/scraps/current`
Auth required.
Returns the user's active/running Scrap or `null`.

### GET `/scraps`
Auth required.
Returns persistent Scrap History: `id`, `name`, `status`, `created_at`, `completed_at`.

### GET `/scraps/{scrap_id}`
Auth required and ownership checked.
Returns Scrap metadata plus:
```json
{
  "counts": {
    "serp_results": 0,
    "url_occurrences": 0,
    "leads": 0,
    "crawl_pages": 0
  },
  "serp_limit": 1000
}
```

### POST `/scraps/{scrap_id}/complete-submission`
Auth + ownership required.
Transitions active/running Scrap to `submitted` and releases the Current Scrap creation lock.
Response: `{ "scrap_id": string, "status": "submitted" }`.
This is the explicit **URL SUBMISSION COMPLETED** action.

### POST `/scraps/{scrap_id}/reopen`
Auth + ownership required.
Reopens a submitted/failed/canceled Scrap as active when no other active/running Scrap exists.

### DELETE `/scraps/{scrap_id}`
Auth + ownership required.
Deletes the Scrap and cascaded persisted research data when no job is running.
`409` if a job is still queued/running.

## 4. Search strategy

### POST `/search/parameters`
Auth is required when `scrap_id` is supplied.
Request:
```json
{
  "scrap_id": "uuid-or-null",
  "criteria": {},
  "max_queries": 20
}
```
Response: `{ "parameters": [...] }`.
Each parameter contains `id`, `provider`, `query`, `url`, and `family`.

### GET `/scraps/{scrap_id}/search-parameters`
Auth + ownership required.
Returns persisted generated search parameters in position order.

## 5. Manual SERP discovery

Manual discovery is user-browser controlled. The backend does not operate Google/Bing.

The frontend/extension workflow is:
1. Request/generated search parameters are displayed.
2. User chooses **Open in Google** or **Open in Bing**.
3. User operates the normal browser and handles any challenge manually.
4. Browser extension captures rendered SERP results.
5. Captures are persisted to the user's Current Scrap.
6. UI refreshes persisted counts/results.
7. User clicks **URL SUBMISSION COMPLETED** when acquisition is finished.

### POST `/serp/sessions`
Creates a short-lived SERP import session. For a Scrap session, send `scrap_id` with authenticated request.
Request:
```json
{ "scrap_id": "uuid", "ttl_seconds": 1800 }
```
Response: `{ "token": string, "expires_in": number }`.

### GET `/scraps/{scrap_id}/serp-session`
Auth + ownership required. Returns the latest non-expired session token or `null`.

### GET `/serp/sessions/{token}`
Returns session URLs, results, imports, sources, and count. Ownership is enforced for authenticated sessions.

### POST `/serp/sources`
Adds a validated Google/Bing search source to a session and, when linked to a Scrap, persists provenance.
Request: `{ "token": string, "url": "https://www.google.com/search?q=..." }`.

### POST `/serp/import`
Imports captured URL occurrences/results.
Request:
```json
{
  "token": "...",
  "urls": ["https://example.com/a"],
  "results": [
    {"url":"https://example.com/a","title":"Example","snippet":"...","provider":"google","page_url":"..."}
  ],
  "page_url": "https://www.google.com/search?q=..."
}
```
Server enforces the configured per-Scrap SERP capacity. Exact duplicate destination URLs are deduplicated within a Scrap before crawl submission; distinct destination paths remain independent.

### POST `/serp/sync`
Compatibility synchronization endpoint for authenticated extension flow. Uses `X-Scrap-Id` when supplied; otherwise resolves Current Scrap. Server enforces SERP capacity.

## 6. Premium SERP Extraction

Premium is a separate paid acquisition path. Pasting a Google/Bing search URL here is **not** manual discovery.

### GET `/billing`
Use `premium_serp_price_cents` for the displayed Premium price.

### POST `/serp/premium`
Auth required.
Request:
```json
{
  "scrap_id": "uuid",
  "search_url": "https://www.google.com/search?q=buyer+india",
  "idempotency_key": "client-generated-unique-key"
}
```
`search_url` must be HTTPS Google/Bing `/search` and contain `q`.

Response includes:
```json
{
  "extraction_id": "uuid",
  "scrap_id": "uuid",
  "provider": "google",
  "query": "buyer india",
  "search_url": "...",
  "results": 25,
  "charged_cents": 100,
  "balance_cents": 900
}
```

The `provider` response field identifies the search engine (`google`/`bing`), not the paid vendor.

UI requirements:
- Display the current Premium price from `/billing`.
- Generate a fresh idempotency key for a new user action.
- Disable duplicate submission while a request is active.
- Treat `402` as insufficient funds.
- Treat `409` as capacity/idempotency conflict.
- Treat `502` as provider failure.
- Never expose provider API credentials.

## 7. SERP result and URL occurrence views

### GET `/scraps/{scrap_id}/serp-results`
Returns persisted SERP result occurrences with `id`, `url`, `title`, `snippet`, `provider`, `page_url`, `created_at`.

### GET `/scraps/{scrap_id}/url-occurrences`
Returns persisted URL occurrences. Duplicate URLs are valid and must remain visible as separate occurrences/provenance.

## 8. Research jobs

### POST `/jobs`
Creates a general research job against the Scrap.
Request:
```json
{
  "scrap_id": "uuid",
  "criteria": {},
  "crawler": {},
  "export_format": "csv",
  "google_spreadsheet_id": null,
  "google_worksheet": "Leads"
}
```
Response HTTP `202` with `job_id`, status `queued`, stage `Queued`.

### POST `/jobs/from-urls`
Creates a research job from harvested URL inputs/results.
Request uses the same export fields and includes:
```json
{
  "scrap_id": "uuid",
  "criteria": {},
  "urls": ["https://example.com"],
  "results": [],
  "crawler": {},
  "export_format": "csv"
}
```

### GET `/jobs/{job_id}`
Auth + ownership required.
Response:
```json
{
  "job_id":"...",
  "status":"running",
  "stage":"Extraction",
  "message":"...",
  "counts": {},
  "events": [],
  "lead_count": 10,
  "export_format":"csv",
  "output":null,
  "error":null,
  "created_at":"...",
  "updated_at":"..."
}
```
Poll this endpoint while a job is non-terminal. Do not use frontend-local counters as authoritative.

### POST `/jobs/{job_id}/cancel`
Auth + ownership required.
Response gives `job_id` and `status: canceled`.

### GET `/jobs/{job_id}/download`
Auth + ownership required. Only completed CSV/XLSX jobs have file downloads. Google Sheets jobs return `409`.

## 9. Results, evidence, crawl and exports

### GET `/scraps/{scrap_id}/results`
Returns persisted Leads: `id`, `data`, `created_at`.

### GET `/scraps/{scrap_id}/crawl-pages`
Returns persisted crawl pages: `id`, `url`, `status`, `content`, `created_at`.

### GET `/scraps/{scrap_id}/evidence`
Returns persisted evidence: `id`, `source_type`, `source_id`, `data`, `created_at`.

### GET `/scraps/{scrap_id}/exports`
Returns export history: `id`, `format`, `location`, `created_at`.

### GET `/scraps/{scrap_id}/exports/{export_id}/download`
Downloads CSV/XLSX exports. Google Sheets exports are not downloadable files.

Supported export formats: `csv`, `xlsx`, `google_sheets`.

## 10. Client settings

### GET/POST/DELETE `/settings/generic-mailbox-prefixes`
Authenticated, per-user settings.
- GET lists prefixes.
- POST `{ "prefix": "..." }` adds/normalizes a prefix.
- DELETE `/settings/generic-mailbox-prefixes/{prefix_id}` removes one.

### GET/POST/DELETE `/settings/domain-rules`
Authenticated, per-user settings.
- GET lists rules.
- POST `{ "domain": "example.com", "rule_type": "blacklist"|"whitelist" }`.
- DELETE `/settings/domain-rules/{rule_id}` removes one.

## 11. Admin API

Admin access is determined server-side by configured administrator identity. Frontend must never assume admin access solely from local state.

### GET `/admin/settings`
Returns commercial settings: Scrap creation price, Premium price, SERP limit.

### POST `/admin/scrap-price`
Sets Scrap creation price in cents.

### POST `/admin/premium-serp-price`
Request `{ "amount_cents": number }`.

### POST `/admin/serp-limit`
Request `{ "limit": number }`, range 1–1,000,000.

### GET `/admin/users`
Lists users and wallet balances.

### DELETE `/admin/users/{user_id}`
Deletes a user except the logged-in admin.

### GET `/admin/users/paged`
Admin-only paginated user list. Query parameters: `page` (1+), `page_size` (1–200), and optional `search` (email substring).
Response includes `users`, `total`, `page`, `page_size`, and `total_pages`.
The UI should use this endpoint rather than loading the entire user table.

### POST `/admin/users/bulk-delete`
Admin-only bulk deletion. Request: `{ "user_ids": ["uuid", "..."] }`.
Maximum 200 unique user IDs per request. The logged-in admin cannot be deleted.
Deletion is performed as one database transaction and returns `deleted`, `emails`, and `requested`.

### GET `/admin/wallets`
Lists wallet balances.

### POST `/admin/wallet-adjust`
Request `{ "user_email": string, "amount_cents": number }`.

### GET `/admin/premium-providers`
Returns exactly four provider configurations with non-secret status/settings:
- `serper`
- `dataforseo`
- `serpapi`
- `brightdata`

Response exposes `enabled`, `is_default`, `configured`, non-secret `settings`, and `updated_at`. **Credentials are never returned.**

### POST `/admin/premium-providers/{provider}`
Request:
```json
{
  "credentials": {},
  "settings": {},
  "enabled": true,
  "make_default": false
}
```
Credentials are submitted only by an authenticated administrator and stored encrypted by the backend.

The frontend must provide provider-specific configuration forms but must never display previously stored secret values.

## 12. Provider configuration UI

Exactly four paid Premium adapters exist:

| Provider | Typical credential fields | Typical non-secret settings |
|---|---|---|
| Serper | `api_key` | endpoint, `gl`, `hl` |
| DataForSEO | `login`, `password` | base URL, location code, language code |
| SerpApi | `api_key` | endpoint |
| Bright Data | `api_key` | endpoint, SERP zone, country |

The admin UI must clearly show which provider is the current default and permit switching the default without code changes.

## 13. Global UI state model

```text
No Current Scrap
    ↓
Create Scrap (wallet charge)
    ↓
Collecting / Current Scrap
    ├── Manual SERP Discovery (Free)
    └── Premium SERP Extraction (Paid)
    ↓
SERP occurrences persisted
    ↓
User clicks URL SUBMISSION COMPLETED
    ↓
Submitted / Current Scrap lock released
    ↓
Research Job
    ├── Queued
    ├── Running
    ├── Completed
    ├── Failed
    └── Canceled
    ↓
Results / Exports / Scrap History
```

The frontend should present the workflow clearly while allowing persistent history and results to be revisited.

## 14. Error handling contract

Recommended generic frontend handling:
- `401`: session invalid/expired → authenticate again.
- `403`: authenticated but unauthorized → show permission error.
- `404`: resource does not exist or is not owned by the user.
- `409`: lifecycle, capacity, duplicate/idempotency, or state conflict.
- `402`: wallet balance insufficient for a billable action.
- `422`: request validation failure → show field/action error.
- `502`: external Premium provider failure → show provider-unavailable message; no retry storm.
- `500`: backend failure → show generic failure and preserve user-entered state.

## 15. Frontend acceptance checklist

1. Never hard-code Scrap or Premium prices.
2. Current Scrap survives reload/logout/re-login because backend state is authoritative.
3. Only **URL SUBMISSION COMPLETED** ends SERP collection and releases the Current Scrap creation lock.
4. Manual and Premium SERP acquisition are visibly separate paths.
5. Pasted Google/Bing search URLs go only through Premium extraction.
6. Duplicate destination URLs are displayed as separate occurrences when applicable.
7. SERP usage is shown as `used / limit` from persisted backend counts.
8. Job progress comes from `GET /jobs/{job_id}`.
9. Terminal job state is persisted and visible after reload.
10. Provider secrets are never returned or displayed.
11. Admin-only controls are hidden or access-denied based on server authorization.
12. CSV, XLSX, and Google Sheets export states are distinct.
13. Google Sheets requires spreadsheet ID and worksheet.
14. All user-owned API requests include authentication.
15. The UI must not implement search-engine CAPTCHA solving or bypassing.

## 16. Backend implementation notes

The API contract intentionally exposes normalized business objects rather than internal crawler/provider implementation details. Frontend code must not depend on Python module names, database tables, process-local dictionaries, or provider-specific HTTP APIs.

**Source of truth:** `docs/V1.3-SOURCE-OF-TRUTH.md` remains authoritative for product behavior; this document is the frontend integration contract derived from the implemented API.
