# Engineering Goal: SERP URLs as Scrapy Crawl Seeds

## Status
Authoritative engineering instruction established by CTO on 2026-09-18.

## Core instruction
Each submitted SERP URL represents a crawling seed for Scrapy.

Scrapy is responsible for crawling from those seeds and providing the crawling capabilities required by the Claw Scrapper pipeline.

## Required Scrapy capabilities
| Feature | What it does | Relevance to Claw Scrapper |
|---|---|---|
| Spider framework | Defines what to crawl and how to extract data | Core |
| Crawler engine | Coordinates requests, responses, spiders and scheduling | Core |
| Request scheduling | Queues and prioritizes URLs to crawl | Core |
| Concurrency | Processes many requests efficiently in parallel | Core |
| Asynchronous networking | Non-blocking crawling using Twisted | Core |
| Downloader | Handles HTTP requests/responses | Core |
| Selectors | XPath/CSS selectors for extracting data | Core |
| Item pipelines | Cleans, validates and processes extracted records | Core |
| Feed exports | Exports scraped data to JSON, CSV, XML, etc. | Core |
| Middleware | Modify requests/responses and crawler behavior | Core |
| Downloader middleware | Proxy, headers, retries, authentication, etc. | Core |
| Spider middleware | Controls spider input/output processing | Core |
| AutoThrottle | Dynamically adjusts crawling speed | Core |
| Retry handling | Automatically retries failed requests | Core |
| Redirect handling | Handles HTTP redirects | Core |
| Cookies/session handling | Maintains cookies across requests | Core |
| HTTP caching | Caches responses to reduce repeated requests | Useful |
| Robots.txt support | Can respect robots.txt rules | Useful |
| Depth control | Limits how deep crawling goes | Core |
| Allowed domains | Prevents spiders from leaving specified domains | Core |
| Duplicate request filtering | Prevents crawling the same URL repeatedly | Core |
| Link extraction | Finds links from pages for further crawling | Core |
| Pagination | Can follow next-page links and pagination patterns | Core |
| Signals | Hooks into crawler lifecycle events | Useful |
| Telnet console | Runtime debugging/control | Development |
| Stats collection | Tracks requests, responses, errors, items, etc. | Core |
| Logging | Detailed crawler diagnostics | Core |
| Proxy support | Supports proxies through middleware/configuration | Useful |
| User-agent control | Customize crawler identity | Useful |
| Request headers | Customize HTTP headers | Useful |
| Authentication | Supports authenticated HTTP requests | Depends on target |
| Extensions | Pluggable crawler functionality | Useful |
| Custom pipelines | Build custom processing/export logic | Core |
| Custom middleware | Build custom crawling behavior | Core |

## Engineering constraints
- Do not invent crawl limits, page counts, URL caps, depth values, or stopping rules that are not defined by authoritative project documentation or explicitly approved by the CTO.
- Do not treat a SERP seed as a single page-only crawl target.
- Do not silently truncate submitted SERP seeds.
- Scrapy crawling, discovery, pagination, scheduling, retries, deduplication and telemetry must be auditable from runtime metrics.
- This document defines the engineering goal; implementation details must be reconciled against the project's source-of-truth documentation before coding.
