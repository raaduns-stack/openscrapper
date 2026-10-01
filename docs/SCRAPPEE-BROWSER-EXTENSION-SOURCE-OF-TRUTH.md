# Scrappee Browser Extension — Source of Truth

**Status:** APPROVED / CANONICAL
**Version:** 0.6.14
**Date:** 2026-10-01

## Purpose

This document is the canonical product specification for the Scrappee Browser Extension.
It records the agreed UX and behavior and must be consulted before changing the extension.

## Core workflow — LOCKED

The extension workflow is intentionally simple and must not be redesigned without explicit CTO approval:

1. User opens Google or Bing and performs a search.
2. User opens the Scrappee extension.
3. User logs in with Scrappee email and password if not already authenticated.
4. Extension identifies the user's current Scrappee Scrap automatically.
5. User clicks **CAPTURE CURRENT** to capture the visible SERP.
6. Captured results remain visible in the extension and persist locally between popup opens.
7. User can move to the next Google/Bing results page without logging in again.
8. User clicks **CAPTURE CURRENT** on each desired SERP page.
9. User clicks **SYNC TO CURRENT SCRAP** to send captured results to Scrappee.
10. User clicks **LOG OUT** only when they explicitly want to end the extension session.

## Authentication — LOCKED

- The extension has its own login form containing Email and Password.
- Successful extension login creates a persistent server-side extension session.
- The extension stores the authenticated session token in `chrome.storage.local`.
- The service worker is the persistent authentication coordinator; popup opens recover authentication from the stored extension session instead of treating popup/page lifecycle changes as logout.
- The popup must never block on authentication or display a user-facing “Checking authentication…” screen; local authentication state determines the initial UI immediately, while server validation runs in the background.
- Authentication is validated against `/auth/me`; only an actual `401` invalid/expired session clears local authentication.
- Popup startup must render from persisted `chrome.storage.local` authentication immediately; remote validation runs in the background and is bounded by a timeout so a slow/unreachable API cannot leave the popup stuck on **Checking authentication…**.
- Google/Bing navigation, pagination, tab changes, scrolling, and opening the extension popup must not log the user out.
- The normal Scrappee web application's short idle-session policy must not shorten an extension session.
- The extension session remains valid until the user explicitly logs out or the server invalidates/revokes it.
- **LOG OUT** must invalidate the server session and clear the extension's stored authentication state.
- The extension must never require the user to re-enter credentials merely because a SERP page changed.
- Extension-to-web authentication uses a separate persistent web session so reloading the Scrappee UI does not discard the web login state.
- Extension logout clears the extension authentication state; it does not directly clear the separate web-session cookie.

## Connection status — LOCKED

- An authenticated extension sends a heartbeat to Scrappee approximately once per minute.
- The API records the authenticated user's extension version and last-seen time.
- The Dashboard considers the extension connected when the last heartbeat is within 120 seconds.
- The Dashboard detects an outdated extension version and provides the current extension package directly.
- No browser-side connection state is inferred by the Dashboard; connection status is based on authenticated server-side heartbeat data.

## SERP capture — LOCKED

- Supported search providers are Google and Bing.
- Capture operates on the currently active SERP page.
- Results are captured as rendered result cards, including the result URL and available title/snippet data.
- Captured pages are accumulated rather than replacing previously captured pages.
- Duplicate results/pages must not be introduced solely because the popup was reopened.
- The extension displays the current captured count.
- The user can clear captured results explicitly with **CLEAR CAPTURED RESULTS**.

## Scrappee handoff — LOCKED

- The extension targets the authenticated user's **Current Scrap** automatically.
- The user must not manually copy a Scrap ID or authentication token.
- The extension sends captured SERP data to the Scrappee API using the authenticated extension session.
- Sync is an explicit user action: **SYNC TO CURRENT SCRAP**.
- Sync must not require the user to switch to the Scrappee web UI first.
- Sync must preserve the captured result data and associate it with the authenticated user's current Scrap.
- Sync is idempotent for already-synchronized captured occurrences; repeated Sync must not create duplicate SERP rows.

## UI — LOCKED

Authenticated popup must retain this functional structure:

- Scrappee branding/title.
- Authenticated account indicator.
- Current Scrap indicator.
- Captured result count.
- **CAPTURE CURRENT** button.
- **SYNC TO CURRENT SCRAP** button.
- **CLEAR CAPTURED RESULTS** button.
- Captured-result list.
- **LOG OUT** button.
- **REFRESH SCRAPS** remains available for refreshing the current Scrap state.

Unauthenticated popup must show:

- **Scrappee Login** heading.
- Email field.
- Password field.
- **LOGIN** button.
- Login error/status message when required.

## Explicit non-goals

- Do not add a second login mechanism.
- Do not require manual tokens.
- Do not require manual Scrap selection for the normal workflow.
- Do not introduce a page-to-page login flow.
- Do not redesign the popup workflow merely to solve implementation problems.
- Do not alter the core extraction/crawling pipeline when fixing extension authentication or handoff.

## Change-control rule

This document is the source of truth for extension behavior.
Code, UI, API changes, tests, and future agent instructions must conform to it.
If a proposed change conflicts with this document, stop and obtain explicit CTO approval before implementation.
Approved changes must update this document and the extension version together.

## Current implementation references

- Extension source: `browser-extension/`
- Extension manifest: `browser-extension/manifest.json`
- Extension popup: `browser-extension/popup.html`, `browser-extension/popup.js`
- Extension service worker: `browser-extension/service-worker.js`
- Authentication backend: `src/auth.py`, `src/api/app.py`, `src/db.py`
- API handoff contract: `docs/SCRAPPEE-V1.3-API-HANDOFF.md`

## Page Lead Indexer — APPROVED

The extension includes a **Page Lead Indexer** alongside the locked SERP workflow.

### Controls

- **Auto Indexing:** OFF by default. The user can turn it OFF and the preference persists in extension storage.
- **INDEX THIS PAGE:** explicitly indexes the currently active HTTP(S) page.
- Current Scrap is the persistence target; without an active Current Scrap, indexing is not submitted.

### Auto behavior

When Auto Indexing is ON, completed navigation is inspected locally for a lead-bearing signal. Pages without relevant contact/lead signals are discarded locally and are never sent to Scrappee. Search engines, Scrappee domains, browser-internal pages, and extension pages are excluded.

For eligible pages the extension submits the rendered page HTML and URL to the authenticated `/page-indexer/process` API. The extension does not solve CAPTCHA, automate authentication, or operate a server-side browser.

### Billing UX

The backend controls the price. The default commercial price is **$0.01 per eligible indexed page**. The extension displays processing/usage state but does not become the billing authority.

### Safety

- Page content is size-bounded before submission.
- Identical user/page content fingerprints are idempotent and are not charged repeatedly.
- Backend validation remains authoritative even when the extension eligibility gate passes.
- Failed backend/provider processing is refunded by the backend.




## Extension Popup — Approved Navigation Contract

The popup MUST separate the two acquisition workflows while keeping the shared research metrics visible at the top.

### Fixed top section
- Extension identity/version.
- Authentication state.
- Current Scrap and status.
- A single three-metric strip immediately below Current Scrap:
  - **SERP Captured** — Google/Bing search results captured for the Current Scrap.
  - **Page Leads** — leads produced by the most recent Page Lead Indexer operation.
  - **Page Indexer** — charge for the most recent indexed page.
- The three metrics MUST appear together at the top and MUST NOT be duplicated lower in the popup.

### Tabs
The popup then exposes exactly two primary workflow tabs:

1. **Google / Bing Searches**
   - Email only control.
   - SERP collection controls.
   - Start/stop/resume SERP collection.
   - CAPTCHA/challenge status.
   - Local SERP preview/clear controls.

2. **Page Leads Capture**
   - Email only control.
   - Auto Indexing control; default **OFF** for new installations.
   - **INDEX THIS PAGE**.
   - Last indexed page status and charge.
   - **VIEW LAST INDEXED LEADS**.
   - Indexed lead results.

The tabs are presentation-only. They MUST NOT create separate backend pipelines, alter authentication, alter billing, or alter Current Scrap semantics.

The shared top metrics remain visible regardless of the selected tab.

## Page Lead Indexer — Approved UI Contract

**Email-only integration:** When Email only is ON, Page Lead Indexer MUST submit only extracted leads containing a valid personal email. Leads without email or with generic mailbox prefixes are discarded before qualification/persistence. When Email only is OFF, the normal accepted-lead paths remain available.

The Page Lead Indexer UI is a separate presentation layer from the SERP capture counter. It MUST clearly distinguish **SERP Captured** from **Page Leads**.

Approved interaction and display:
- **Auto Indexing:** OFF by default and persistent when changed.
- **INDEX THIS PAGE:** explicit page-index action.
- After successful indexing, show a success card with the indexed URL, lead count, and charge.
- Show separate counters for SERP results and Page Leads.
- Show the configured per-page charge for the most recent indexed page.
- **VIEW LAST INDEXED LEADS** retrieves the existing server-side indexed result and MUST NOT trigger a new charge.
- Lead preview cards show available name, position/company, email/phone, geography, and source URL.
- Existing SERP controls remain unchanged.
- No UI action may bypass backend billing, validation, qualification, deduplication, or persistence rules.


### Popup visual contract — clean header and connection status

The popup header is intentionally compact: Scrappee identity/version, a live connection-status badge, and the Current Scrap name/status. The three shared metrics remain immediately below. Backend implementation details MUST NOT be presented as explanatory prose in the user-facing popup.

The footer uses concise product chrome only: copyright, connection/security wording, Refresh, and Log out.

The popup navigation uses two tabs. Tab switching is client-side presentation only and MUST remain functional independently of backend state.
