# Claw Scrapper V1.2 Roadmap

## Completed foundation

- SearchCriteria
- QueryExpander
- Geography
- DiscoveryController / DiscoveryAgent foundation (legacy/internal discovery path)
- Search aggregation and DuckDuckGo provider foundation
- Relevance scoring foundation
- OpenClaw adapter foundation
- Basic pagination
- Adaptive deterministic extraction
- JSON-LD and HTML extraction
- Individual Lead Pydantic contract
- Evidence-based qualification with optional personal email
- Authoritative lead dedupe/persistence path
- CSV and Excel export
- API/UI foundations
- Browser extension SERP capture integration for the current product workflow
- Controlled Scrapy enrichment path with crawl/time/lead bounds

## Current architecture commitments

- SERP capture is the primary research discovery input.
- All captured SERP URLs are submitted when Start Research is clicked.
- Lead qualification is evidence-based and does not require a personal email.
- SERP and Scrapy share the same qualification contract.
- Scrapy may discover additional qualifying people during controlled enrichment.
- Scrapy crawling is bounded by depth, page/URL, time, domain, and relevant-link policy.
- One authoritative dedupe/persistence path handles lead creation and updates.
- The Leads widget exposes per-lead Enrich actions using the same enrichment engine as batch research.
- CRM synchronization remains outside MVP scope.

## V1.2 remaining work

### P0 — Collection architecture

1. Keep the browser extension as the primary Google/Bing SERP discovery/capture path.
2. Complete Scrapy/HTTP as the primary post-capture collection/enrichment engine.
3. Integrate scrapy-playwright for JS-required pages.
4. Establish the evidence/content abstraction as the collection boundary.

### P1 — Extraction and research

4. Integrate Trafilatura and strengthen metadata extraction.
5. Harden email validation and phone normalization.
6. Build the LLM research/interpretation layer with ambiguity-based invocation.
7. Implement conditional OpenClaw escalation through the adapter.

### P1 — Autonomous reliability

8. Strengthen the ReAct crawl controller with bounded pages/URLs, duplicate/result-state
detection, stopping conditions, and failure handling.
9. Implement bounded LLM/Pydantic self-correction.
10. Add production-scale crawl orchestration and observability.

### P2 — Product surface

11. Add Google Sheets export.
12. Complete the customer-facing search interface and connect it to SearchCriteria.
13. Document deployment, configuration, operations, and failure recovery.

## Definition of V1.2 complete

V1.2 is complete only when the canonical pipeline is executable end-to-end from customer
criteria through browser-based Google/Bing SERP discovery/capture, controlled collection,
evidence, extraction/research, conditional browser escalation, qualification, validation/
self-correction, dedupe, and all target exports, with automated tests covering the important
decision boundaries.
