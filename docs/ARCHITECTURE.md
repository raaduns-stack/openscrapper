# Claw Scrapper V1.2 Architecture

## Canonical architecture

```text
USER
  |
  v
SearchCriteria
  |
  v
QueryExpander
  |
  v
Discovery / Search Layer
  |
  v
Candidate URLs
  |
  v
Relevance / Discovery Controller
  |
  v
Scrapy / HTTP Collection
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
     Deterministic Extraction
                |
                v
       LLM Research if needed
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

Discovery finds candidate URLs; it does not crawl them at scale.
Scrapy is the primary collector; it does not perform internet search discovery.
scrapy-playwright provides rendering when ordinary HTTP is insufficient.
OpenClaw is conditional browser interaction/research, not the primary crawler.
