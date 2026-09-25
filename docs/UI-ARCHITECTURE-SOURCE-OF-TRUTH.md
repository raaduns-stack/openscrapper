# Scrappee UI Architecture — Source of Truth

**Status:** Approved design — implementation not yet started  
**Scope:** Customer UI, shared shell, Senders UI, Admin UI

## 1. Purpose

This document defines the approved UI architecture for the next UI refactor. It is a structural/UI change only. Existing extraction, scraping, enrichment, qualification, deduplication, export, and browser-extension behavior must remain unchanged unless separately approved.

## 2. UI shell

The application shell has exactly one implementation for each global surface:

```text
src/ui/components/
├── sidebar.py
├── header.py
└── footer.py
```

### Sidebar

Single source for application navigation, current Scrap state, user identity, and role-aware navigation visibility.

### Header

Single source for page title/context, global status/notifications, and global page actions.

### Footer

Single source for application/version information and global footer content.

No page may create its own independent sidebar, header, or footer implementation.

## 3. Customer pages

```text
src/ui/pages/
├── dashboard.py
├── new_scrap.py
├── current_scrap.py
├── lead_workstation.py
├── scrap_history.py
└── exports.py
```

The customer UI must prioritize the operational workflow and avoid exposing implementation-level telemetry unless it is useful to the user.

### Current Scrap

Current Scrap is organized around the lifecycle:

```text
COLLECT → REVIEW → SUBMIT → PROCESS
```

SERP results, URLs, and captured leads should be presented as related views rather than one excessively long mixed page.

Primary metrics should remain concise. Detailed technical telemetry belongs in secondary/detail views.

The Cancel Scrap action must remain available during an active Scrap and terminate the active Scrap without deleting its historical data.

## 4. Shared UI components

Reusable visual/interaction components belong under:

```text
src/ui/components/
├── metrics.py
├── tables.py
└── status.py
```

Components should contain presentation/reusable interaction logic, not business-domain workflows.

## 5. Senders UI

Senders is a dedicated product surface, not a single monolithic page.

```text
src/ui/senders/
├── summary.py
├── configuration.py
├── campaigns.py
├── letters.py
└── reply_to.py
```

Navigation and information hierarchy must keep sender configuration, campaign details, letters, and reply-to configuration distinct.

## 6. Admin UI

Admin is a separate application surface and must not be mixed into normal customer navigation/content.

```text
src/ui/admin/
├── dashboard.py
├── billing.py
├── wallets.py
├── users.py
├── serp_providers.py
├── client_policies.py
└── browser_extension.py
```

Admin pages are visible **only to users whose authenticated server-side role is admin**.

Hiding the Admin navigation item in the frontend is not an authorization mechanism. Every Admin API endpoint must independently enforce server-side admin authorization.

A non-admin user must not be able to access Admin functionality by manually constructing a URL or API request.

## 7. Application entry point

`src/ui/app.py` remains the application entry/router. It should be responsible for:

- authentication/session bootstrap
- role detection
- page routing
- shared shell composition
- global error handling

It should not contain the implementation of every page.

Target structure:

```text
src/ui/
├── app.py
├── components/
├── pages/
├── senders/
└── admin/
```

## 8. Authorization model

```text
Authenticated user
│
├── regular user
│   └── Customer UI
│
└── admin
    ├── Customer UI
    └── Admin UI
```

Authorization is enforced server-side. UI visibility is an additional usability layer only.

## 9. Refactor constraints

1. No intentional change to scraping/extraction/enrichment behavior.
2. No intentional change to database semantics unless separately approved.
3. No removal of existing working functionality merely to simplify the UI.
4. Refactor incrementally; validate after each surface.
5. Do not perform a broad rewrite of the 900+ line UI in one operation.
6. Existing unrelated working-tree changes must not be overwritten, reverted, or reformatted as part of this refactor.

## 10. Implementation order

```text
1. Shared shell: sidebar / header / footer
2. Current Scrap
3. Lead Workstation
4. Scrap History
5. Dashboard
6. Senders
7. Admin
8. Final UI module decomposition/cleanup
```

## 11. Git release control

This document does not authorize a release.

All implementation commits remain local by default. No push or merge to stable/main is permitted without an explicit CTO command.

## 12. Engineering Agent Operating Model

1. **CTO** = final authority for architecture, approval, push, merge, and release.
2. **Lead Engineer** = architecture, implementation planning, source-of-truth compliance, review, validation, and regression analysis.
3. **Antigravity** = hands-on implementation agent responsible for filesystem edits, local commands, tests, validation, and local commits only when explicitly instructed.
4. Antigravity MUST NOT git push, merge, rebase stable/main, reset/clean the working tree, or modify unrelated existing changes without explicit CTO authorization.
5. All implementation remains local until the CTO explicitly authorizes publication/release.
6. Existing unrelated working-tree changes must be preserved.
