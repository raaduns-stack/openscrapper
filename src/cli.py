import argparse
import asyncio
import json

from src.models.criteria import CrawlerConfig, SearchCriteria
from src.pipeline import LeadDiscoveryPipeline


def main():
    parser = argparse.ArgumentParser(prog="claw-scrapper")
    parser.add_argument("--criteria", required=True, help="JSON SearchCriteria")
    parser.add_argument("--output", default="output/leads.csv")
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--max-urls", type=int, default=100)
    parser.add_argument("--max-queries", type=int, default=20)
    parser.add_argument("--provider-failure-limit", type=int, default=2)
    parser.add_argument("--max-pagination-pages", type=int, default=10)
    parser.add_argument("--exhaustion-threshold", type=int, default=3)
    parser.add_argument("--disable-url-validity-checks", action="store_true")
    parser.add_argument("--disable-exhaustion-stop", action="store_true")
    parser.add_argument("--model", default="openai/gpt-oss-20b")
    args = parser.parse_args()

    criteria = SearchCriteria.model_validate(json.loads(args.criteria))

    crawler_config = CrawlerConfig(
        max_queries=args.max_queries,
        provider_failure_limit=args.provider_failure_limit,
        url_validity_checks=not args.disable_url_validity_checks,
        max_crawl_pages=args.max_pages,
        max_crawl_urls=args.max_urls,
        max_pagination_pages=args.max_pagination_pages,
        duplicate_exhaustion_enabled=not args.disable_exhaustion_stop,
        duplicate_exhaustion_threshold=args.exhaustion_threshold,
    )

    pipeline = LeadDiscoveryPipeline(
        model=args.model,
        crawler_config=crawler_config,
    )

    output = asyncio.run(
        pipeline.run_and_export(criteria, args.output)
    )

    print(f"Exported: {output}")


if __name__ == "__main__":
    main()
