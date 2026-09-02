import argparse
import asyncio
import json

from src.models.criteria import SearchCriteria
from src.pipeline import LeadDiscoveryPipeline


def main():
    parser = argparse.ArgumentParser(prog="claw-scrapper")
    parser.add_argument("--criteria", required=True, help="JSON SearchCriteria")
    parser.add_argument("--output", default="output/leads.csv")
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--model", default="openai/gpt-oss-20b")
    args = parser.parse_args()

    criteria = SearchCriteria.model_validate(json.loads(args.criteria))

    pipeline = LeadDiscoveryPipeline(
        model=args.model,
        max_pages=args.max_pages,
    )

    output = asyncio.run(
        pipeline.run_and_export(criteria, args.output)
    )

    print(f"Exported: {output}")


if __name__ == "__main__":
    main()
