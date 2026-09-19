"""Process entry point for the Scrapy collector."""

from __future__ import annotations

import base64
import json
import sys
import tempfile

from scrapy.crawler import CrawlerProcess

from src.collector.scrapy_runner import CollectionSpider


def _progress(event: dict) -> None:
    print("CLAW_PROGRESS=" + json.dumps(event, separators=(",", ":"), default=str), flush=True)


def _page(page, stream_file) -> None:
    stream_file.write(json.dumps({
        "url": page.url, "html": page.html, "text": page.text, "status": page.status,
        "source": page.source, "error": page.error, "request_index": page.request_index,
        "content_type": page.content_type,
        "body": base64.b64encode(page.body).decode("ascii") if page.body else "",
        "depth": page.depth,
    }, separators=(",", ":"), ensure_ascii=True, default=str) + "\n")
    stream_file.flush()
    print("CLAW_PAGE_FILE=" + stream_file.name, flush=True)


def main() -> None:
    payload = json.loads(sys.stdin.read())
    output = []
    telemetry = {}
    stream_file = tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", prefix="claw-pages-", suffix=".jsonl", delete=False)
    process = CrawlerProcess(settings=CollectionSpider.custom_settings)
    spider_urls = payload["urls"]
    process.crawl(CollectionSpider, urls=spider_urls, output=output, progress_callback=_progress, page_callback=lambda page: _page(page, stream_file), max_pages=payload.get("max_pages"), max_urls=payload.get("max_urls"), max_depth=payload.get("max_depth"), telemetry=telemetry, scrap_id=payload.get("scrap_id"))
    process.start(install_signal_handlers=False)
    stream_file.close()
    stats = telemetry.get("stats", {})
    if stats:
        _progress({"state": "completed", "urls_submitted": len(spider_urls), "urls_scheduled": int(stats.get("scheduler/enqueued", 0)), "responses_downloaded": int(stats.get("downloader/response_count", 0)), "pages_collected": int(stats.get("claw/items_collected", 0)), "pages_failed": int(stats.get("claw/responses_failed", 0)), "retries": int(stats.get("retry/count", 0)), "robots_denied": int(stats.get("claw/failures/robots_denied", stats.get("robotstxt/forbidden", 0))), "browser_escalations": int(stats.get("claw/browser_escalations_executed", 0)), "stats": stats, "message": "Scrapy worker completed"})
    print("CLAW_RESULT=" + json.dumps([
        {
            "url": page.url,
            "html": page.html,
            "text": page.text,
            "status": page.status,
            "source": page.source,
            "error": page.error,
            "request_index": page.request_index,
            "content_type": page.content_type,
            "body": base64.b64encode(page.body).decode("ascii") if page.body else "",
            "depth": page.depth,
        }
        for page in output
    ]))


if __name__ == "__main__":
    main()
