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

```text
USER CRITERIA
  -> QUERY EXPANSION
  -> DISCOVERY / SEARCH
  -> CANDIDATE URLs
  -> RELEVANCE
  -> SCRAPY / HTTP
  -> SCRAPY-PLAYWRIGHT IF NEEDED
  -> EVIDENCE / CONTENT
  -> DETERMINISTIC EXTRACTION
  -> LLM RESEARCH IF NEEDED
  -> OPENCLAW IF BROWSER INTERACTION IS NEEDED
  -> QUALIFICATION
  -> PYDANTIC + SELF-CORRECTION
  -> DEDUPE
  -> EXPORT
```

## Scope

MVP scope is extraction, qualification, deduplication, and CSV/Excel/Google Sheets export.
CRM synchronization is out of scope for V1.2 MVP.

## Development

The CLI is a development/testing interface, not the final customer-facing product.

Run tests with:

```bash
. .venv/bin/activate && pytest -q
```
