# Claw Scrapper

Claw Scrapper is an autonomous lead-research and web-extraction system.

## V1.2 source of truth

The canonical V1.2 specification is:

- `docs/V1.2-SOURCE-OF-TRUTH.md` — requirements and acceptance criteria.
- `docs/ARCHITECTURE.md` — canonical system architecture and boundaries.
- `docs/ADR-0001-v1.2-architecture.md` — architectural decisions and rationale.
- `docs/ROADMAP.md` — implementation status and remaining work.

These documents are versioned in Git and are the baseline for engineering audits.

## Runtime flow

The current V1.2 product workflow starts with browser-based SERP discovery. The browser extension captures Google/Bing SERP candidates and source URLs; Scrapy does not replace SERP discovery.

```text
GOOGLE / BING SERP
  -> BROWSER EXTENSION CAPTURE
  -> SERP CANDIDATE QUALIFICATION
  -> PERSISTENT LEAD
  -> ALL CAPTURED SERP URLs
  -> CONTROLLED SCRAPY ENRICHMENT
  -> EVIDENCE / CONTENT
  -> DETERMINISTIC EXTRACTION
  -> LLM RESEARCH IF NEEDED
  -> OPENCLAW IF BROWSER INTERACTION IS NEEDED
  -> SAME EVIDENCE-BASED QUALIFICATION
  -> PYDANTIC + SELF-CORRECTION
  -> SAME DEDUPE / PERSISTENCE PATH
  -> EXPORT
```

Scrapy is the collection/enrichment engine after SERP capture. It may discover additional qualifying people during controlled enrichment, but crawling is always bounded by explicit depth, page/URL, time, domain, and relevant-link controls. Personal email is optional; sufficient person-specific evidence is required. Manual Enrich actions in the Leads widget use the same enrichment engine as batch research.

### Lead qualification contract

An individual lead is accepted only when:

```text
(first_name OR last_name)
AND
at least ONE of:
position, company_name, phone, city, state, country, website
```

Email is optional. If present, it must be personal. Email-only, company-only, and name-only records are rejected.

## Scope

MVP scope is extraction, qualification, deduplication, and CSV/Excel/Google Sheets export.
CRM synchronization is out of scope for V1.2 MVP.

## Development

The CLI is a development/testing interface, not the final customer-facing product.

### Git stability rule

Development changes remain local until explicitly approved by the CTO. Do not push or
merge changes to `main` unless the CTO gives an explicit command to do so. Local feature
branches and local commits are permitted; `main` is the stable release branch.

Run tests with:

```bash
. .venv/bin/activate && pytest -q
```
