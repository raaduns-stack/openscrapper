import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from scrapy.http import HtmlResponse

from src.collector import CollectionController as PublicCollectionController
from src.collector import ScrapyCollector as PublicScrapyCollector
from src.collector import worker
from src.collector.collection_controller import CollectionController
from src.collector.evidence import Evidence
from src.collector.scrapy_runner import CollectionSpider, CollectedPage, ScrapyCollector


def test_collector_interfaces_are_available_from_the_package():
    assert PublicCollectionController is CollectionController
    assert PublicScrapyCollector is ScrapyCollector


@pytest.mark.asyncio
async def test_spider_requests_only_supplied_candidate_urls():
    spider = CollectionSpider(
        urls=["https://one.example", "https://two.example"], output=[]
    )
    requests = [request async for request in spider.start()]

    assert [request.url for request in requests] == [
        "https://one.example", "https://two.example"
    ]
    assert all(request.callback == spider.parse for request in requests)
    assert all(request.errback == spider.collect_error for request in requests)


def test_spider_uses_scrapy_http_with_conditional_playwright():
    assert CollectionSpider.custom_settings["DOWNLOAD_HANDLERS"]["http"].endswith("ScrapyPlaywrightDownloadHandler")
    assert CollectionSpider.custom_settings["DOWNLOAD_HANDLERS"]["https"].endswith("ScrapyPlaywrightDownloadHandler")
    assert CollectionSpider.custom_settings["ITEM_PIPELINES"]
    assert CollectionSpider.custom_settings["DOWNLOADER_MIDDLEWARES"]
    assert CollectionSpider.custom_settings["EXTENSIONS"]


def test_spider_submits_all_seed_occurrences_independent_of_page_limit():
    urls = [f"https://example{i}.com" for i in range(36)]
    spider = CollectionSpider(urls=urls, output=[], max_pages=25, max_urls=100)
    requests = list(spider.start_requests())
    assert len(requests) == 36
    assert [request.url for request in requests] == urls
    assert all(not request.dont_filter for request in requests)


def test_spider_collects_content_and_follows_relevant_internal_links():
    output = []
    spider = CollectionSpider(urls=["https://one.example"], output=output, max_pages=5, max_urls=5)
    request = next(spider.start_requests())
    response = HtmlResponse(
        url="https://one.example/about",
        request=request,
        body=b"<html><body><a href='/next'>Next</a><a href='/contact'>Contact</a><h1>Acme</h1><p>" + (b"useful contact information " * 10) + b"</p></body></html>",
        encoding="utf-8",
        status=200,
    )

    results = list(spider.parse(response))
    requests = [result for result in results if hasattr(result, "url") and hasattr(result, "dont_filter")]
    items = [result for result in results if not (hasattr(result, "dont_filter") and hasattr(result, "url"))]
    assert [item.url for item in requests] == ["https://one.example/contact"]
    assert items[0]["text"].startswith("Next Contact Acme")
    assert items[0]["status"] == 200


def test_collector_preserves_duplicate_url_occurrences_and_bounds_candidate_urls(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, "CLAW_RESULT=[]\n", "")

    monkeypatch.setattr("src.collector.scrapy_runner.subprocess.run", fake_run)

    pages = ScrapyCollector(max_pages=2).collect([
        "https://one.example",
        "ftp://ignored.example",
        "https://one.example",
        "https://two.example",
        "https://three.example",
    ])

    assert pages == []
    assert captured["command"][-1] == "src.collector.worker"
    assert captured["payload"] == {
        "urls": ["https://one.example", "https://one.example", "https://two.example", "https://three.example"],
        "max_pages": 2,
        "max_urls": None,
        "max_depth": None,
    }


def test_collector_returns_worker_pages_in_discovery_order(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            "CLAW_RESULT=" + json.dumps([
                {"url": "https://second.example", "html": "two", "text": "two", "status": 200, "request_index": 1},
                {"url": "https://first.example", "html": "one", "text": "one", "status": 200, "request_index": 0},
            ]) + "\n",
            "",
        )

    monkeypatch.setattr("src.collector.scrapy_runner.subprocess.run", fake_run)
    pages = ScrapyCollector().collect([
        "https://first.example", "https://second.example"
    ])

    assert [page.url for page in pages] == [
        "https://first.example", "https://second.example"
    ]
    assert all(page.source == "scrapy" for page in pages)


def test_collector_fetches_candidate_url_with_scrapy():
    requested_paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested_paths.append(self.path)
            if self.path == "/robots.txt":
                body = b"User-agent: *\nAllow: /\n"
            elif self.path == "/candidate":
                body = b"<html><body><a href='/contact'>Contact</a><h1>Acme</h1></body></html>"
            elif self.path == "/contact":
                body = b"<html><body><h1>Contact</h1><p>sales@example.test</p></body></html>"
            else:
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except PermissionError:
        pytest.skip("the execution sandbox does not permit local TCP listeners")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    events = []
    try:
        page = ScrapyCollector().collect([
            f"http://127.0.0.1:{server.server_port}/candidate"
        ], progress_callback=events.append)[0]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert page.status == 200
    assert page.text == "Contact Acme"
    assert "<h1>Acme</h1>" in page.html
    assert requested_paths == ["/robots.txt", "/candidate", "/candidate", "/contact"]
    completed = [event for event in events if event.get("state") == "completed"][-1]
    assert completed["stats"].get("downloader/request_count", 0) >= 2
    assert completed["stats"]["claw/responses_success"] >= 2
    assert completed["stats"].get("retry/count", 0) == 0


def test_worker_serializes_raw_scrapy_evidence_without_a_network_listener(monkeypatch, capsys):
    captured = {}

    class FakeProcess:
        def __init__(self, settings):
            captured["settings"] = settings

        def crawl(self, spider_class, **kwargs):
            captured["spider_class"] = spider_class
            captured["urls"] = kwargs["urls"]
            kwargs["output"].append(CollectedPage(
                url="https://one.example",
                html="<html><body>Acme</body></html>",
                text="Acme",
                status=200,
            ))

        def start(self, *, install_signal_handlers):
            captured["started"] = install_signal_handlers

    monkeypatch.setattr(worker, "CrawlerProcess", FakeProcess)
    monkeypatch.setattr(worker.sys, "stdin", __import__("io").StringIO(
        '{"urls": ["https://one.example"]}'
    ))

    worker.main()

    result = capsys.readouterr().out.removeprefix("CLAW_RESULT=")
    assert captured["spider_class"] is CollectionSpider
    assert captured["urls"] == ["https://one.example"]
    assert captured["started"] is False
    assert json.loads(result)[0]["text"] == "Acme"


@pytest.mark.asyncio
async def test_controller_forwards_discovery_url_stream_to_scrapy():
    class FakeCollector:
        async def collect_async(self, urls):
            return [CollectedPage(url=url, html="<html></html>", text="", status=200) for url in urls]

    result = await CollectionController(collector=FakeCollector()).collect(
        url for url in ["https://one.example", "https://two.example"]
    )

    assert [page.url for page in result] == [
        "https://one.example", "https://two.example"
    ]
