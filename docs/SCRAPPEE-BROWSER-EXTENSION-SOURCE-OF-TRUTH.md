# Scrappee Browser Extension — Source of Truth

**Status:** APPROVED / CANONICAL
**Version:** 0.6.1
**Date:** 2026-09-17

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
- Google/Bing navigation, pagination, tab changes, scrolling, and opening the extension popup must not log the user out.
- The normal Scrappee web application's short idle-session policy must not shorten an extension session.
- The extension session remains valid until the user explicitly logs out or the server invalidates/revokes it.
- **LOG OUT** must invalidate the server session and clear the extension's stored authentication state.
- The extension must never require the user to re-enter credentials merely because a SERP page changed.

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
