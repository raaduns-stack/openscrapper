# Crawler Configuration

All search and crawl safety controls are centralized in `CrawlerConfig`.

## Configurable limits

- `max_queries`: maximum search queries per discovery plan.
- `provider_failure_limit`: consecutive failures allowed for a provider.
- `url_deduplication`: enable URL duplicate suppression.
- `url_validity_checks`: reject malformed/non-HTTP(S) URLs.
- `max_crawl_pages`: maximum collected pages.
- `max_crawl_urls`: independent URL queue/visit budget.
- `max_pagination_pages`: maximum dynamic pagination pages requested.
- `duplicate_exhaustion_enabled`: stop when discovery/collection stops producing progress.
- `duplicate_exhaustion_threshold`: number of no-progress rounds before stopping.

`max_crawl_pages` and `max_crawl_urls` are intentionally independent. Increasing the
page limit does not automatically increase the URL budget, and vice versa.

The Streamlit UI exposes these under **Optional refinements → Search & crawl limits**.
The API accepts them under the `crawler` object in a job request. The CLI exposes
corresponding flags.
