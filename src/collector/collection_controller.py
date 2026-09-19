"""Application-facing adapter over the V1.3 Scrapy crawl engine."""
from __future__ import annotations

from typing import Iterable

from src.collector.scrapy_runner import CollectedPage, ScrapyCollector
from src.models.criteria import CrawlerConfig


class EscalationPolicy:
    """Compatibility policy; escalation is now owned by CollectionSpider."""

    def needs_rendering(self, page: CollectedPage) -> bool:
        if page.content_type and not page.content_type.startswith("text/html"):
            return False
        if page.error or page.status >= 400:
            return True
        return len(page.text.strip()) < 120 and len(page.html.strip()) < 1200


class CollectionController:
    """Thin application boundary; Scrapy owns crawl state, navigation and escalation."""

    def __init__(self, max_pages: int | None = None, collector: ScrapyCollector | None = None,
                 policy: EscalationPolicy | None = None, browser=None,
                 config: CrawlerConfig | None = None):
        self.config = config or CrawlerConfig(
            max_crawl_pages=max_pages, max_crawl_urls=None
        )
        self.collector = collector or ScrapyCollector(
            max_pages=self.config.max_crawl_pages,
            max_urls=self.config.max_crawl_urls,
            max_depth=self.config.max_crawl_depth,
        )
        self.policy = policy or EscalationPolicy()

    def collect_sync(self, urls: Iterable[str], progress_callback=None) -> list[CollectedPage]:
        """Synchronous application boundary for callers that do not use asyncio."""
        return self.collector.collect(urls, progress_callback=progress_callback)

    async def collect(self, urls: Iterable[str], progress_callback=None) -> list[CollectedPage]:
        """Delegate the complete bounded crawl to Scrapy."""
        if progress_callback is None:
            return await self.collector.collect_async(urls)
        return await self.collector.collect_async(urls, progress_callback=progress_callback)
