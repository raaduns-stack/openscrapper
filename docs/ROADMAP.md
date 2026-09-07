# Claw Scrapper V1.2 Roadmap

## Completed foundation

- SearchCriteria
- QueryExpander
- Geography
- DiscoveryController / DiscoveryAgent
- Search aggregation and DuckDuckGo provider
- Relevance scoring
- OpenClaw adapter foundation
- Basic pagination
- Adaptive deterministic extraction
- JSON-LD and HTML extraction
- Individual Lead Pydantic contract
- Qualification
- Deduplication
- CSV and Excel export
- API/UI foundations

## V1.2 remaining work

### P0 — Collection architecture

1. Make Scrapy/HTTP the primary collection engine.
2. Integrate scrapy-playwright for JS-required pages.
3. Establish the evidence/content abstraction as the collection boundary.

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
criteria through discovery, collection, evidence, extraction/research, conditional
browser escalation, qualification, validation/self-correction, dedupe, and all target
exports, with automated tests covering the important decision boundaries.
