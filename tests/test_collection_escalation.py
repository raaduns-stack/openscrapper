import pytest

from src.collector.scrapy_runner import CollectionSpider


def test_scrapy_spider_owns_conditional_rendering_policy():
    spider = CollectionSpider(urls=["https://example.com"], output=[])
    assert callable(spider._needs_rendering)


def test_scrapy_spider_can_build_rendered_request():
    spider = CollectionSpider(urls=["https://example.com"], output=[])
    request = spider._request("https://example.com", 0, rendered=True)
    assert request.meta["playwright"] is True
    assert request.meta["browser_escalation_attempted"] is True


def test_diagnostics_classifies_http_failure_and_browser_execution():
    class Stats:
        def __init__(self): self.data = {}
        def inc_value(self, key, count=1): self.data[key] = self.data.get(key, 0) + count
        def set_value(self, key, value): self.data[key] = value
    class Crawler: pass
    class Spider: pass
    from scrapy.http import Request, Response
    from src.collector.scrapy_runner import CrawlDiagnosticsMiddleware
    stats = Stats(); spider = Spider(); spider.crawler = Crawler(); spider.crawler.stats = stats; spider.url_outcomes = []
    spider.record_url_outcome = lambda request, outcome, status=None, error=None: spider.url_outcomes.append((request.url, outcome, status, error))
    request = Request("https://example.com", meta={"playwright": True, "request_index": 7, "depth": 1})
    response = Response(request=request, status=503, url=request.url)
    CrawlDiagnosticsMiddleware().process_response(request, response, spider)
    assert stats.data["claw/http/failures/503"] == 1
    assert stats.data["claw/browser_escalations_executed"] == 1
    assert spider.url_outcomes[-1][1] == "http_error"


def test_diagnostics_classifies_timeout_failure():
    from src.collector.scrapy_runner import CrawlDiagnosticsMiddleware
    from scrapy.http import Request
    class Stats:
        def __init__(self): self.data = {}
        def inc_value(self, key, count=1): self.data[key] = self.data.get(key, 0) + count
    class Crawler: pass
    class Spider: pass
    stats = Stats(); spider = Spider(); spider.crawler = Crawler(); spider.crawler.stats = stats; spider.url_outcomes = []
    spider.record_url_outcome = lambda request, outcome, status=None, error=None: spider.url_outcomes.append(outcome)
    request = Request("https://example.com", meta={"request_index": 1})
    CrawlDiagnosticsMiddleware().process_exception(request, TimeoutError("download timeout"), spider)
    assert stats.data["claw/failures/timeout"] == 1
    assert spider.url_outcomes == ["timeout"]


def test_diagnostics_classifies_network_failure():
    from src.collector.scrapy_runner import CrawlDiagnosticsMiddleware
    from scrapy.http import Request
    class Stats:
        def __init__(self): self.data = {}
        def inc_value(self, key, count=1): self.data[key] = self.data.get(key, 0) + count
    class Crawler: pass
    class Spider: pass
    stats = Stats(); spider = Spider(); spider.crawler = Crawler(); spider.crawler.stats = stats; spider.url_outcomes = []
    spider.record_url_outcome = lambda request, outcome, status=None, error=None: spider.url_outcomes.append(outcome)
    request = Request("https://missing.example", meta={"request_index": 2})
    CrawlDiagnosticsMiddleware().process_exception(request, OSError("DNS lookup failed"), spider)
    assert stats.data["claw/failures/network"] == 1
    assert spider.url_outcomes == ["network_error"]


def test_diagnostics_classifies_robots_denial_without_bypass():
    from src.collector.scrapy_runner import CrawlDiagnosticsMiddleware
    from scrapy.http import Request
    from scrapy.exceptions import IgnoreRequest
    class Stats:
        def __init__(self): self.data = {}
        def inc_value(self, key, count=1): self.data[key] = self.data.get(key, 0) + count
    class Crawler: pass
    class Spider: pass
    stats = Stats(); spider = Spider(); spider.crawler = Crawler(); spider.crawler.stats = stats; spider.url_outcomes = []
    spider.record_url_outcome = lambda request, outcome, status=None, error=None: spider.url_outcomes.append(outcome)
    request = Request("https://example.com/private", meta={"request_index": 3})
    CrawlDiagnosticsMiddleware().process_exception(request, IgnoreRequest("robots.txt disallowed"), spider)
    assert stats.data["claw/failures/robots_denied"] == 1
    assert spider.url_outcomes == ["robots_denied"]


def test_collector_propagates_worker_failure(monkeypatch):
    import subprocess
    from src.collector.scrapy_runner import ScrapyCollector
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 17, "", "worker crashed")
    monkeypatch.setattr("src.collector.scrapy_runner.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="worker failed"):
        ScrapyCollector(max_pages=1).collect(["https://example.com"])
