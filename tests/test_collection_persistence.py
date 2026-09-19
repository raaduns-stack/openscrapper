import uuid

import pytest
from scrapy.http import Request

from src.collector.scrapy_runner import CrawlItemPipeline, CollectionSpider


class _Conn:
    def __init__(self):
        self.calls = []
        self.committed = False

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def commit(self):
        self.committed = True


class _DB:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *args):
        return False


def _spider(scrap_id):
    spider = CollectionSpider(urls=["https://example.com"], output=[], scrap_id=scrap_id)
    spider.crawler = type("Crawler", (), {"stats": type("Stats", (), {"inc_value": lambda self, key: None})()})()
    return spider


def test_item_pipeline_persists_failed_occurrence(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr("src.db.db", lambda: _DB(conn))
    scrap_id = uuid.uuid4()
    spider = _spider(scrap_id)
    item = {"url": "https://bad.example", "status": 503, "error": "HTTP 503", "request_index": 4, "depth": 0, "content_type": "text/html", "html": ""}
    CrawlItemPipeline().process_item(item, spider)
    assert conn.committed
    assert conn.calls[0][1][1] == scrap_id
    assert conn.calls[0][1][3] == "503"
    assert conn.calls[0][1][5] == "HTTP 503"


def test_item_pipeline_preserves_repeated_occurrence_indexes(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr("src.db.db", lambda: _DB(conn))
    spider = _spider(uuid.uuid4())
    pipeline = CrawlItemPipeline()
    for index in (0, 1):
        pipeline.process_item({"url": "https://same.example", "status": 200, "request_index": index, "depth": 0, "content_type": "text/html", "html": "ok"}, spider)
    assert [call[1][7] for call in conn.calls] == [0, 1]
    assert [call[1][9] for call in conn.calls] == [0, 1]


def test_item_pipeline_persistence_failure_propagates(monkeypatch):
    class BrokenDB:
        def __enter__(self):
            raise RuntimeError("database unavailable")
        def __exit__(self, *args):
            return False
    monkeypatch.setattr("src.db.db", lambda: BrokenDB())
    with pytest.raises(RuntimeError, match="database unavailable"):
        CrawlItemPipeline().process_item({"url": "https://example.com", "status": 200, "request_index": 0}, _spider(uuid.uuid4()))
