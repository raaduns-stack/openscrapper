import pytest

from src.collector.collection_controller import CollectionController
from src.collector.scrapy_runner import CollectedPage


class FakeCollector:
    async def collect_async(self, urls, progress_callback=None):
        return [CollectedPage(url=u, html="<html></html>", text="ok", status=200) for u in urls]


@pytest.mark.asyncio
async def test_controller_delegates_collection_to_scrapy_adapter():
    controller = CollectionController(collector=FakeCollector())
    pages = await controller.collect(["https://example.com/a", "https://example.com/b"])
    assert [page.url for page in pages] == ["https://example.com/a", "https://example.com/b"]


def test_controller_uses_scrapy_limits():
    controller = CollectionController(max_pages=7)
    assert controller.collector.max_pages == 7
    assert controller.collector.max_urls == 28
