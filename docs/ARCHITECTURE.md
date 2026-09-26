# Claw Scrapper V1.2 Architecture

## Canonical architecture

```text
USER
  |
  v
SearchCriteria
  |
  v
Google / Bing SERP
  |
  v
Browser Extension Capture
  |
  v
SERP Candidates / Source URLs
  |
  v
SERP Qualification
  |
  v
Persistent Leads
  |
  v
Controlled Scrapy / HTTP Enrichment
  |-----------------------------|
  |                             |
  v                             v
normal HTML             scrapy-playwright
  |                             |
  |_____________________________|
                |
                v
        Evidence / Content
                |
                v
   First-level Extraction
 deterministic -> GLiNER-Relex
                |
                v
          Qualification
                |
                v
   Controlled Enrichment
 correction / completion
                |
                v
   Page Extraction / Validation
                |
                v
   OpenClaw if browser needed
                |
                v
          Qualification
                |
                v
     Pydantic + Self-Correction
                |
                v
             Dedupe
                |
                v
             Export
```

## Boundaries

The browser extension is the primary SERP discovery/capture mechanism for the
current V1.2 product workflow. It captures Google/Bing SERP candidates and source URLs.
Start Research submits all captured SERP URLs to the controlled enrichment engine.

Scrapy is the primary collection/enrichment engine after SERP capture. It does not perform
internet search discovery. It may discover additional qualifying people while processing
supplied URLs, but only within explicit crawl boundaries.

Controlled crawl boundaries include depth, page/URL limits, time, allowed domains, and
relevant-link policy. Default depth must be safe and must never result in unbounded
recursive crawling.

scrapy-playwright provides rendering when ordinary HTTP is insufficient.
OpenClaw is conditional browser interaction/research, not the primary crawler.

## Lead lifecycle

```text
SERP candidate -> qualification -> persistent lead
                         |
                         v
                 controlled enrichment
                    /            \
             update lead     new qualifying person
                    \            /
                     -> same qualification
                     -> same dedupe/persistence path
```

Personal email is optional. The exact qualification contract is:

```text
(first_name OR last_name)
AND
at least ONE of:
position, company_name, phone, city, state, country, website
```

The contract applies identically to SERP and Scrapy. If email is present, it must be
personal. One authoritative persistence/merge path is used for creation and updates.

Current dedupe identity signals are normalized email, phone, source URL plus person name,
and person name plus company. Website/domain, city, and state are not standalone identity
keys.

The Leads UI exposes per-lead **Enrich** actions. Manual enrichment and batch research use
the same enrichment engine.
