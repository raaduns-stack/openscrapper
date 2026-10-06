# Scrappee UI Architecture — Source of Truth

**Status:** Approved architecture — React migration approved by CTO; implementation pending
**Scope:** Customer UI, shared shell, Senders UI, Admin UI, frontend technology migration

## 1. Purpose

This document defines the approved UI architecture for the next UI refactor. It is a structural/UI change only. Existing extraction, scraping, enrichment, qualification, deduplication, export, and browser-extension behavior must remain unchanged unless separately approved.

## 2. Frontend technology decision

**Decision: React frontend.** The CTO approved replacing Streamlit as the customer/admin frontend technology.

Rationale: the product now requires conventional SaaS application behavior—persistent application chrome, controlled routing, responsive layouts, complex navigation, account/billing surfaces, support, admin workflows, and browser-extension integration. The existing Streamlit implementation creates avoidable layout and DOM constraints for these requirements.

Migration boundary:

- Keep the existing API, scraping, extraction, enrichment, qualification, deduplication, persistence, billing, and browser-extension backend behavior unless separately approved.
- Replace the Streamlit presentation/routing layer with a React frontend.
- Reuse the existing API contracts where practical; API changes require separate approval.
- Do not begin a broad backend rewrite as part of the frontend migration.
- Streamlit remains temporarily available only until the React frontend reaches functional parity and is approved for cutover.

The React migration is an approved architecture decision, not authorization to publish or release. Implementation remains local until separately approved.

## 3. UI shell

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

## 4. Customer pages

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

## 5. Shared UI components

Reusable visual/interaction components belong under:

```text
src/ui/components/
├── metrics.py
├── tables.py
└── status.py
```

Components should contain presentation/reusable interaction logic, not business-domain workflows.

## 6. Senders UI

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

## 7. Admin UI

### 7.1 Separate Admin Application Surface

Admin is a **separate application interface** from the customer-facing Scrappee workspace.

- Admin is accessed at the dedicated `/admin` route/application surface.
- `/admin` must render a complete Admin interface with its own navigation, layout, information hierarchy, and operational workflows.
- The normal customer-facing interface must not be embedded inside the Admin interface, and customer navigation must not be reused as the Admin navigation.
- The Admin interface must not appear as a normal customer navigation item.
- Admin and customer surfaces may reuse shared frontend primitives/components where appropriate, but they remain separate application experiences.
- The Admin interface must provide a clear **switch-to-user-interface** control/icon allowing an authorized administrator to return to the normal customer-facing Scrappee workspace.
- The user-facing interface must provide a corresponding **switch-to-admin** control only when the authenticated server-side identity is authorized as an administrator.
- The switch controls are navigation conveniences only; they are never authorization mechanisms.
- Direct navigation to `/admin` and every Admin API request must continue to enforce server-side administrator authorization.
- A non-admin user must receive an authorization failure and must not gain Admin functionality by manually navigating to `/admin` or calling Admin APIs.

### 7.2 Admin Boundary

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

## 8. Application entry point

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

## 9. Authorization model

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

## 10. Refactor constraints

1. No intentional change to scraping/extraction/enrichment behavior.
2. No intentional change to database semantics unless separately approved.
3. No removal of existing working functionality merely to simplify the UI.
4. Refactor incrementally; validate after each surface.
5. Do not perform a broad rewrite of the 900+ line UI in one operation.
6. Existing unrelated working-tree changes must not be overwritten, reverted, or reformatted as part of this refactor.

## 11. Implementation order

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

## 12. Git release control

This document does not authorize a release.

All implementation commits remain local by default. No push or merge to stable/main is permitted without an explicit CTO command.

## 13. Engineering Agent Operating Model

1. **CTO** = final authority for architecture, approval, push, merge, and release.
2. **Lead Engineer** = architecture, implementation planning, source-of-truth compliance, review, validation, and regression analysis.
3. **Antigravity** = hands-on implementation agent responsible for filesystem edits, local commands, tests, validation, and local commits only when explicitly instructed.
4. Antigravity MUST NOT git push, merge, rebase stable/main, reset/clean the working tree, or modify unrelated existing changes without explicit CTO authorization.
5. All implementation remains local until the CTO explicitly authorizes publication/release.
6. Existing unrelated working-tree changes must be preserved.

## 7.3 Approved Admin Console Functional Scope

**CTO approval:** Approved on 2026-09-29. This section is the source-of-truth baseline for the React Admin Console. It defines the intended administration scope; implementation of capabilities not already backed by the API requires separate engineering validation and must not invent backend behavior.

### Admin navigation

```text
ADMIN

OPERATIONS
  Overview
  Activity
  System health

CUSTOMERS
  Users
  Customer activity

BILLING
  Wallets
  Deposits
  Transactions

RESEARCH
  Scraps
  SERP providers
  Search templates

OUTBOUND
  Campaigns
  Senders

SUPPORT
  Tickets

PLATFORM
  Pricing
  Research settings
  Client policies
  Platform settings

SECURITY
  Audit log
  Administrators
```

Bottom navigation must retain:

- Switch to User Interface
- Log out

### 7.3.1 Overview

The Admin overview is an operational dashboard, not a duplicate customer dashboard.

Platform health:

- API status
- Database status
- scraping/pipeline status
- queue/job status
- browser-extension/service status
- email delivery status
- payment processor status
- premium SERP provider status

Customer metrics:

- total users
- active users
- suspended users
- new users by time period
- users currently scraping
- users with active campaigns
- users with outstanding support tickets

Financial metrics:

- total wallet balance
- pending deposits
- deposits by period
- revenue
- admin credits/debits
- failed payments

Research metrics:

- Scraps by period
- SERP usage
- URLs crawled
- leads discovered
- leads approved
- paid enrichment jobs
- premium SERP usage
- page-indexer usage

### 7.3.2 Users

Users is a customer-administration workstation, not a delete-only table.

User list must support:

- search by email and supported customer identifiers
- filtering by account status
- filtering by admin/non-admin role
- filtering by activity and billing state
- pagination
- selection and bulk operations where server support exists

List information should include, where available from the API:

- status
- email
- name/company if supported
- created date
- last login/activity
- wallet balance
- deposits
- Scraps
- leads
- campaigns
- support tickets

Supported administrative operations must be exposed only when backed by server-side endpoints. Existing functionality includes user deletion/bulk deletion and wallet adjustment.

### 7.3.3 User Detail

Selecting a customer opens a dedicated user administration workspace.

```text
Customer
email
STATUS
Created
Last login

[ Suspend ] [ Adjust wallet ] [ Force logout ]

Overview | Activity | Wallet | Deposits | Scraps | Leads | Campaigns | Support | Security
```

The detail workspace must centralize customer context rather than requiring the administrator to infer state from separate lists.

### 7.3.4 User Activity

The approved target is a chronological customer activity timeline covering, where data is retained:

Authentication:

- login
- logout
- failed login
- password reset
- session creation/expiration
- forced logout

Research:

- Scrap creation/submission/completion
- SERP activity
- URL submission
- crawl activity
- lead discovery/approval/deletion
- enrichment requests/completion

Billing:

- deposit creation/approval/rejection
- wallet charges
- wallet credits/debits
- admin adjustments
- refunds/corrections

Campaigns:

- campaign creation/change
- launch/pause/resume where supported
- test sends
- successful/failed sends
- replies

Support:

- ticket creation
- replies
- assignment
- status changes
- resolution/reopening
- ratings

This requires an auditable event model. Existing support audit events must not be assumed to cover system-wide customer activity.

### 7.3.5 Account Lifecycle

Target account states:

```text
Active
Suspended
Pending
Deleted
```

Suspension is an approved target capability but is **not currently assumed to exist** merely because the UI exposes it. Before implementation, the backend/database must be audited and a server-side lifecycle model added if required.

Suspension requirements:

- reason
- optional internal note
- optional customer-facing message
- indefinite or scheduled duration
- session invalidation
- login enforcement
- research/campaign enforcement as applicable
- immutable audit event

Deletion must protect the current administrator and must not permit removing the last administrator.

### 7.3.6 Wallets and Transactions

Wallet administration must provide:

- current balance
- available credits
- total deposited
- total spent
- total admin adjustments
- transaction ledger

Transaction records should expose, where supported:

- timestamp
- type
- amount
- balance after
- reference
- source
- administrator for administrative adjustments

Target transaction categories include deposits, product charges, admin credit/debit, refunds, and corrections.

Existing server capability includes `/admin/wallet-adjust`; the React UI must require a reason for administrative adjustments once the backend contract supports it and must record the action in the audit trail.

### 7.3.7 Deposits

Admin deposit management must support:

- pending/approved/rejected/expired filtering
- customer
- payment method
- amount
- reference
- created/reviewed timestamps
- reviewer
- deposit detail
- approve/reject actions where server-authorized
- internal notes where supported

Existing server functionality includes deposit listing and review.

### 7.3.8 Support

Admin Support must expose the existing server-backed workflow:

- queue by status
- priority/category filters
- customer search
- assignee filtering
- ticket detail
- conversation
- attachments
- internal notes
- assignment/reassignment
- priority/status changes
- resolve/reopen/close
- customer rating

Existing server endpoints include support metrics, ticket listing/detail, messages, internal notes, status, assignment, assignees, and attachment download.

### 7.3.9 Research Administration

Admin research visibility should cover customer Scraps and their operational state:

- Scrap status
- created/completed times
- SERP results
- URLs/pages crawled
- leads
- job status/final stage
- pipeline events/errors
- usage/cost where available

Administrative retry/cancel operations must only be exposed after confirming safe server-side contracts.

### 7.3.10 Campaign and Sender Administration

Admin should provide operational visibility into customer campaigns and sender identities:

- customer
- campaign status
- sender
- letter/audience
- sent/failed/replied counts
- sender provider/health
- enabled state

Pause/resume/cancel/disable operations require explicit server-side support and auditability.

Secrets such as SMTP passwords or OAuth credentials must never be displayed.

### 7.3.11 SERP, Search Templates and Research Controls

### 7.3.12 Search Templates Administrator Completion — 2026-10-02

The Search Templates page exposes category and template configuration as a persistent administrator workflow. Categories and templates support priority ordering through move-up/move-down controls; category active state is editable; every category is deletable through a confirmation-gated control; template variable validation follows the deterministic template engine grammar; and the UI shows active-template capacity. Existing CRUD, rename, provider filtering, geography variables, and database persistence remain unchanged.

The Create Template editor also exposes `{domain}` as an approved derived variable. `{domain}` is resolved from the external client database during deterministic search generation; it is not a manually managed domain list.


Existing admin-backed controls include:

- premium SERP providers
- provider enablement/configuration
- search-template categories
- search templates
- search-template ordering
- global SERP limit
- research settings

React Admin must expose the existing server contracts without changing their semantics.

### 7.3.12 Pricing and Platform Configuration

Existing administrative pricing/configuration includes:

- Scrap price
- paid enrichment price
- premium SERP price
- page-indexer price
- SERP limit
- deposit configuration
- research settings
- platform settings

Configuration changes must show current value, proposed value, administrator, timestamp, and audit event where the backend supports auditability.

### 7.3.13 Client Policies

Admin must distinguish global policies from customer-specific policies.

Global:

- domain blacklist
- policies applying to all customers/crawlers

Customer-specific:

- mailbox-prefix exclusions
- supported customer-specific collection rules

Existing server-backed domain blacklist and client-policy functionality must remain intact during React migration.

### 7.3.14 Audit Log

A system-wide Admin Audit Log is an approved target capability.

Each auditable event should record:

- timestamp
- actor
- action
- target
- module
- result
- metadata/reason where appropriate

High-risk actions requiring auditability include:

- user lifecycle changes
- wallet adjustments
- deposit decisions
- pricing/configuration changes
- support administration
- provider/configuration changes
- destructive operations

Existing support audit events are not considered a substitute for a system-wide audit log.

### 7.3.15 Administrator Roles and Permissions

The approved target model supports future role separation:

```text
Super Admin
Support Admin
Billing Admin
Operations Admin
Read Only
```

Permission enforcement must be server-side. The React UI may hide unavailable actions for usability but must never be the authorization layer.

This role model is a target capability and is not considered implemented until the backend authorization model explicitly supports it.

### 7.3.16 Security Requirements

Admin must enforce:

- server-side authorization on every Admin endpoint
- safe session handling
- audit logging for sensitive actions
- confirmation for destructive/financial/account actions
- protection against deleting the current administrator
- protection against removing the last administrator
- no secret exposure
- appropriate rate limiting and request protection

The switch-to-admin and switch-to-user controls are navigation only and never confer authorization.

### 7.3.17 Implementation Rule

The Admin React implementation must distinguish three states:

1. **Existing backend capability** — expose it in React using the existing contract.
2. **Existing legacy UI behavior without complete React/API parity** — preserve behavior and audit the contract before implementing.
3. **Approved target capability not currently backed by the server** — document and engineer the backend contract first; do not fabricate client-side state or authorization.

No Admin feature may be represented as operationally complete until its server-side authorization, persistence semantics, and failure paths are validated.

### 7.3.14 Search Template builder visual polish — 2026-10-03

The Search Templates Create Template surface uses a builder-style visual hierarchy: editor header, horizontally scrollable variable library, structured provider/family/template/state controls, validation, example preview, and capacity status. Category deletion is always visible and confirmation-gated for every category. This does not alter backend persistence semantics.

### 7.3.13 Create Template editor improvements — 2026-10-03

The Search Templates Create Template editor provides click-to-insert approved variables, inline variable validation, an illustrative example preview, existing-family suggestions, explicit state selection, and responsive form layout. `{domain}` is presented as externally derived. These are UX improvements only; the database model and deterministic search-template expansion contract remain unchanged.

### 7.3.15 Search Template builder structural editor + family selector fix — 2026-10-03
- Create/Edit Template uses a three-zone builder layout: variable library, pattern editor, and live-check/save rail.
- Existing CRUD, ordering, state, validation, cursor insertion, capacity display, and category controls are preserved.
- Family is a native select populated from the active category's families, with a Custom family option that exposes the free-text field for new family names.
- Category delete remains visible for every category.


### 7.3.16 Search Template library table redesign — 2026-10-03
The Search Templates library uses a configuration-oriented table hierarchy: Search Pattern, Provider, Family, Status, and Actions. Edit and ordering remain visible; Enable/Disable and Delete are grouped under an overflow menu to reduce row clutter. Provider badges, status dots, hover treatment, controlled monospace pattern display, and responsive layouts are visual-only. Existing category/template CRUD, ordering, state changes, filtering, persistence, validation, and builder behavior are preserved.


### 7.3.17 Category deletion policy correction — 2026-10-03
CTO clarified that every Search Template category must expose a delete icon, including categories carrying a stable/built-in key. Deletion remains confirmation-gated and uses the existing category DELETE endpoint; database cascade removes templates belonging to the deleted category. The stable_key field remains for identity/seed compatibility and no longer controls UI/API deletion permission.


### 7.3.18 Published family selector correction — 2026-10-03
The Create/Edit Template editor exposes exactly one Family control: a native dropdown populated dynamically from active/published Template Family names in the database's category records, ordered by published position. The frontend contains no hardcoded family list, category-scoped suggestion logic, or Custom family free-text path.

### 7.3.19 Published family persistence normalization — 2026-10-06
Persisted template family is the current published category name. Legacy family values must not survive category rename/administration. Category rename synchronizes all templates in that category, startup reconciliation repairs legacy mismatches, and create/update APIs accept only the current published category name.

## Lead Workstation — Working / Completed Tabs (2026-10-05)

The Lead Workstation MUST present exactly two lead-status tabs: **Working Leads** first/default and **Completed Leads** second. Working Leads remain the editable operational surface. Completed Leads are approved/locked records and are the only records eligible for workstation CSV/XLSX download. Existing sender/mobile access to completed Leads remains unchanged. This is a focused navigation/export change; it MUST NOT redesign the existing workstation visual system or alter Lead persistence, approval, extraction, enrichment, qualification, or sender semantics.
