"""Scrapy-native bounded crawl engine for V1.3."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Iterable

from scrapy import Item, Field, Request, Spider, signals
from scrapy.exceptions import IgnoreRequest
from scrapy.linkextractors import LinkExtractor

try:
    from scrapy_playwright.page import PageMethod
except ImportError:
    PageMethod = None


@dataclass(frozen=True)
class CollectedPage:
    url: str
    html: str
    text: str
    status: int
    source: str = "scrapy"
    error: str | None = None
    request_index: int = 0
    content_type: str = "text/html"
    body: bytes = b""
    depth: int = 0


def _candidate_urls(urls: Iterable[str], max_urls: int | None) -> list[str]:
    """Keep every valid URL occurrence in original order; never deduplicate."""
    result: list[str] = []
    for url in urls:
        if not isinstance(url, str):
            continue
        value = url.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        result.append(value)
        if max_urls is not None and len(result) >= max_urls:
            break
    return result


def _is_html_response(response) -> bool:
    content_type = response.headers.get(b"Content-Type", b"").decode(errors="ignore").lower()
    return not content_type or content_type.startswith("text/html")


CONTACT_PATH_RE = r"(?:contact|team|staff|people|management|directory|procurement|purchasing|sales|buyer|buyers|leadership|about-us|about_people)"
CONTACT_TEXT_RE = r"(?:contact|team|staff|people|management|directory|procurement|purchasing|sales|buyer|buyers|leadership)"


class CrawlPageItem(Item):
    url = Field()
    html = Field()
    text = Field()
    status = Field()
    source = Field()
    error = Field()
    request_index = Field()
    content_type = Field()
    body = Field()
    depth = Field()


class CrawlItemPipeline:
    """Persist normalized crawl items and hand them to the worker result boundary."""
    def process_item(self, item, spider):
        if getattr(spider, "scrap_id", None):
            import uuid as _uuid
            from src.db import db as _db
            with _db() as conn:
                conn.execute("INSERT INTO crawl_pages(id,scrap_id,url,status,content,error,content_type,request_index,depth,occurrence_index) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (_uuid.uuid4(), _uuid.UUID(str(spider.scrap_id)), item["url"], str(item.get("status", 0)), item.get("html", "") or item.get("text", ""), item.get("error"), item.get("content_type", ""), int(item.get("request_index", 0)), int(item.get("depth", 0)), int(item.get("request_index", 0))))
                conn.commit()
        page = CollectedPage(
            url=item["url"], html=item.get("html", ""), text=item.get("text", ""),
            status=int(item.get("status", 0)), source=item.get("source", "scrapy"),
            error=item.get("error"), request_index=int(item.get("request_index", 0)),
            content_type=item.get("content_type", ""), body=item.get("body", b""),
            depth=int(item.get("depth", 0)),
        )
        spider.output.append(page)
        if spider.page_callback:
            spider.page_callback(page)
        spider.crawler.stats.inc_value("claw/items_collected")
        return item


class CrawlDiagnosticsMiddleware:
    """Scrapy downloader middleware for response/exception diagnostics."""
    def process_response(self, request, response, spider):
        stats = spider.crawler.stats
        stats.inc_value("claw/responses")
        stats.inc_value(f"claw/http/status/{response.status}")
        if response.status >= 400:
            stats.inc_value("claw/http/failures")
            stats.inc_value(f"claw/http/failures/{response.status}")
            stats.inc_value("claw/responses_failed")
            outcome = "http_error"
        else:
            stats.inc_value("claw/responses_success")
            outcome = "success"
        if request.meta.get("playwright"):
            stats.inc_value("claw/browser_escalations_executed")
        if request.meta.get("redirect_times", 0):
            stats.inc_value("claw/redirects")
            stats.set_value("claw/last_redirects", request.meta["redirect_times"])
        spider.record_url_outcome(request, outcome, status=response.status)
        return response

    def process_exception(self, request, exception, spider):
        stats = spider.crawler.stats
        reason = str(exception)
        lowered = reason.casefold()
        if isinstance(exception, IgnoreRequest) and "robots.txt" in lowered:
            stats.inc_value("claw/failures/robots_denied")
            stats.inc_value("claw/responses_failed")
            outcome = "robots_denied"
        elif "timeout" in lowered:
            stats.inc_value("claw/failures/timeout")
            outcome = "timeout"
        elif any(token in lowered for token in ("dns", "connect", "connection", "tls", "ssl")):
            stats.inc_value("claw/failures/network")
            outcome = "network_error"
        else:
            stats.inc_value("claw/failures/other")
            outcome = "request_error"
        if request.meta.get("playwright"):
            stats.inc_value("claw/browser_escalations_failed")
        spider.record_url_outcome(request, outcome, error=reason)
        return None


class CrawlTelemetryExtension:
    """Scrapy signal extension; Scrapy stats are the crawl telemetry source of truth."""
    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls()
        crawler.signals.connect(ext.spider_opened, signals.spider_opened)
        crawler.signals.connect(ext.response_received, signals.response_received)
        crawler.signals.connect(ext.request_dropped, signals.request_dropped)
        crawler.signals.connect(ext.spider_idle, signals.spider_idle)
        crawler.signals.connect(ext.spider_closed, signals.spider_closed)
        return ext

    def _emit(self, spider, state, message):
        if not spider.progress_callback:
            return
        stats = spider.crawler.stats.get_stats()
        spider.progress_callback({
            "state": state,
            "urls_submitted": len(spider.urls),
            "urls_scheduled": int(stats.get("scheduler/enqueued", 0)),
            "responses_downloaded": int(stats.get("downloader/response_count", 0)),
            "pages_collected": int(stats.get("claw/items_collected", 0)),
            "pages_failed": int(stats.get("claw/responses_failed", 0)),
            "retries": int(stats.get("retry/count", 0)),
            "robots_denied": int(stats.get("claw/failures/robots_denied", stats.get("robotstxt/forbidden", 0))),
            "browser_escalations": int(stats.get("claw/browser_escalations_executed", 0)),
            "url_outcomes": list(spider.url_outcomes[-25:]),
            "max_depth_reached": int(spider._max_depth_seen),
            "exhausted": bool(stats.get("claw/exhaustion/no_progress", 0)),
            "stats": stats,
            "message": message,
        })

    def spider_opened(self, spider):
        self._emit(spider, "started", "Scrapy spider opened")

    def response_received(self, response, request, spider):
        self._emit(spider, "running", f"Scrapy received {response.url}")

    def request_dropped(self, request, spider):
        spider.crawler.stats.inc_value("claw/request_dropped")
        self._emit(spider, "running", f"Scrapy dropped request: {request.url}")

    def spider_idle(self, spider):
        if not spider._page_limit_reached:
            spider.crawler.stats.inc_value("claw/exhaustion/no_progress")
            self._emit(spider, "running", "Scrapy crawl exhausted")

    def spider_closed(self, spider, reason):
        self._emit(spider, "completed", f"Scrapy spider closed: {reason}")


class CollectionSpider(Spider):
    name = "claw_collection"
    custom_settings = {
        "LOG_ENABLED": False,
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
        "DOWNLOAD_TIMEOUT": 15,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 1,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.25,
        "AUTOTHROTTLE_MAX_DELAY": 5.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 4.0,
        "DOWNLOAD_HANDLERS": {"http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler", "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler"},
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
        "DOWNLOADER_STATS": True,
        "ITEM_PIPELINES": {"src.collector.scrapy_runner.CrawlItemPipeline": 100},
        "DOWNLOADER_MIDDLEWARES": {"src.collector.scrapy_runner.CrawlDiagnosticsMiddleware": 900},
        "EXTENSIONS": {"src.collector.scrapy_runner.CrawlTelemetryExtension": 500},
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        max_depth = kwargs.get("max_depth")
        crawler.settings.set("DEPTH_LIMIT", 0 if max_depth is None else int(max_depth), priority="spider")
        return spider

    def __init__(self, urls, output, max_pages=None, max_urls=None, progress_callback=None, telemetry=None, max_depth=None, scrap_id=None, page_callback=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls = list(urls)
        self.max_pages = int(max_pages) if max_pages is not None else None
        self.max_urls = int(max_urls) if max_urls is not None else None
        self.max_depth = int(max_depth) if max_depth is not None else None
        self.allowed_domains = sorted({urlparse(url).hostname for url in self.urls if urlparse(url).hostname})
        self.output = output
        self.scrap_id = scrap_id
        self.progress_callback = progress_callback
        self.page_callback = page_callback
        self.telemetry = telemetry if telemetry is not None else {}
        self._url_occurrences_submitted = 0
        self._pages_collected = 0
        self._pages_failed = 0
        self._scheduled_occurrences = 0
        self._processed_pages = 0
        self._page_limit_reached = False
        self._link_extractor = LinkExtractor(deny_extensions=(), unique=True)
        self.url_outcomes = []
        self._max_depth_seen = 0

    def _progress(self, event: dict) -> None:
        if self.progress_callback:
            self.progress_callback(event)

    def record_url_outcome(self, request, outcome: str, status: int | None = None, error: str | None = None) -> None:
        self._max_depth_seen = max(self._max_depth_seen, int(request.meta.get("depth", 0)))
        self.url_outcomes.append({
            "url": request.url,
            "request_index": int(request.meta.get("request_index", 0)),
            "depth": int(request.meta.get("depth", 0)),
            "outcome": outcome,
            "status": status,
            "error": error,
            "browser_escalated": bool(request.meta.get("playwright")),
            "url_occurrence_index": int(request.meta.get("url_occurrence_index", request.meta.get("request_index", 0))),
        })

    def _relevant_links(self, response):
        links = list(self._link_extractor.extract_links(response))
        extracted_urls = {link.url for link in links}
        for anchor in response.css("a[href]"):
            text = " ".join(anchor.css("::text").getall()).strip().casefold()
            href = anchor.attrib.get("href", "")
            if text and re.search(CONTACT_TEXT_RE, text):
                absolute = response.urljoin(href)
                if absolute.startswith(("http://", "https://")) and absolute not in extracted_urls:
                    links.append(type("LinkLike", (), {"url": absolute})())
        return links

    def _needs_rendering(self, response) -> bool:
        if not _is_html_response(response) or PageMethod is None:
            return False
        if response.status >= 400:
            return True
        text = " ".join(part.strip() for part in response.css("body ::text").getall() if part.strip())
        return len(text) < 120 and len(response.text.strip()) < 1200

    def _request(self, url: str, request_index: int, callback=None, rendered=False, depth=0):
        callback = callback or self.parse
        meta = {
            "handle_httpstatus_all": True,
            "request_index": request_index,
            "url_occurrence_index": request_index,
            "depth": depth,
            "browser_escalation_attempted": rendered,
        }
        if rendered:
            if PageMethod is None:
                raise RuntimeError("scrapy-playwright is not installed")
            meta.update({
                "playwright": True,
                "playwright_include_page": False,
                "playwright_page_methods": [PageMethod("wait_for_load_state", "networkidle", timeout=10000)],
                "playwright_page_goto_kwargs": {"wait_until": "domcontentloaded", "timeout": 30000},
            })
            callback = self.parse_rendered
        return Request(url, callback=callback, errback=self.collect_error, dont_filter=rendered, meta=meta)

    def _requests(self):
        for request_index, url in enumerate(self.urls):
            if self.max_urls is not None and request_index >= self.max_urls:
                break
            self._url_occurrences_submitted += 1
            self._scheduled_occurrences += 1
            yield self._request(url, request_index, depth=0)

    def start_requests(self):
        yield from self._requests()

    async def start(self):
        for request in self._requests():
            yield request

    def _item(self, response, source="scrapy", error=None):
        html = response.text if _is_html_response(response) else ""
        text = " ".join(part.strip() for part in response.css("body ::text").getall() if part.strip()) if _is_html_response(response) else ""
        content_type = response.headers.get(b"Content-Type", b"").decode(errors="ignore").split(";", 1)[0].lower()
        return CrawlPageItem(
            url=response.url, html=html, text=text, status=response.status,
            source=source, error=error, request_index=response.meta.get("request_index", 0),
            content_type=content_type, body=response.body if not _is_html_response(response) else b"",
            depth=int(response.meta.get("depth", 0)),
        )

    def _queue_internal_links(self, response):
        if self._page_limit_reached:
            return []
        if not _is_html_response(response):
            return []
        if response.status >= 400 or (self.max_urls is not None and self._scheduled_occurrences >= self.max_urls):
            return []
        depth = int(response.meta.get("depth", 0))
        if self.max_depth is not None and depth >= self.max_depth:
            return []
        requests = []
        for link in self._relevant_links(response):
            if self.max_urls is not None and self._scheduled_occurrences >= self.max_urls:
                break
            parsed = urlparse(link.url)
            if parsed.hostname not in self.allowed_domains:
                continue
            index = self._scheduled_occurrences
            self._scheduled_occurrences += 1
            req = self._request(link.url, index, depth=depth + 1)
            requests.append(req)
        return requests

    def parse(self, response):
        if self.max_pages is not None and self._processed_pages >= self.max_pages:
            self._page_limit_reached = True
            return
        if self._needs_rendering(response) and not response.meta.get("browser_escalation_attempted"):
            if getattr(self, "crawler", None) is not None:
                self.crawler.stats.inc_value("claw/browser_escalations_requested")
            yield self._request(
                response.url,
                response.meta.get("request_index", 0),
                rendered=True,
                depth=int(response.meta.get("depth", 0)),
            )
            return
        self._processed_pages += 1
        if self.max_pages is not None and self._processed_pages >= self.max_pages:
            self._page_limit_reached = True
        error = f"HTTP {response.status}" if response.status >= 400 else None
        if error:
            self._pages_failed += 1
        else:
            self._pages_collected += 1
        yield self._item(response, error=error)
        for request in self._queue_internal_links(response):
            yield request

    def parse_rendered(self, response):
        if self.max_pages is not None and self._processed_pages >= self.max_pages:
            self._page_limit_reached = True
            return
        self._processed_pages += 1
        if self.max_pages is not None and self._processed_pages >= self.max_pages:
            self._page_limit_reached = True
        error = f"HTTP {response.status}" if response.status >= 400 else None
        if error:
            self._pages_failed += 1
        else:
            self._pages_collected += 1
        yield self._item(response, source="scrapy-playwright", error=error)
        for request in self._queue_internal_links(response):
            yield request

    def closed(self, reason):
        stats = self.crawler.stats.get_stats()
        self.telemetry["stats"] = stats
        self.telemetry["finish_reason"] = reason
        self._progress({
            "state": "completed",
            "urls_submitted": len(self.urls),
            "urls_scheduled": int(stats.get("scheduler/enqueued", 0)),
            "responses_downloaded": int(stats.get("downloader/response_count", 0)),
            "pages_collected": int(stats.get("claw/items_collected", 0)),
            "pages_failed": int(stats.get("claw/responses_failed", 0)),
            "retries": int(stats.get("retry/count", 0)),
            "robots_denied": int(stats.get("robotstxt/forbidden", 0)),
            "browser_escalations": int(stats.get("claw/browser_escalations_executed", 0)),
            "url_outcomes": list(spider.url_outcomes),
            "stats": stats,
            "message": f"Scrapy spider closed: {reason}",
        })

    def collect_error(self, failure):
        request = failure.request
        response = getattr(failure.value, "response", None)
        reason = str(failure.value)
        self._pages_failed += 1
        self.crawler.stats.inc_value("claw/responses_failed")
        yield CrawlPageItem(
            url=request.url,
            html=response.text if response is not None and _is_html_response(response) else "",
            text="",
            status=response.status if response is not None else 0,
            error=reason,
            request_index=request.meta.get("request_index", 0),
            content_type=response.headers.get(b"Content-Type", b"").decode(errors="ignore").split(";", 1)[0].lower() if response is not None else "",
            body=response.body if response is not None and not _is_html_response(response) else b"",
            depth=int(request.meta.get("depth", 0)),
        )


class ScrapyCollector:
    WORKER_TIMEOUT_SECONDS = 600

    def __init__(self, max_pages=None, max_urls=None, max_depth=None):
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if max_urls is not None and max_urls < 1:
            raise ValueError("max_urls must be at least 1")
        if max_depth is not None and max_depth < 0:
            raise ValueError("max_depth must be at least 0")
        self.max_pages = max_pages
        self.max_urls = max_urls
        self.max_depth = max_depth

    def collect(self, urls, progress_callback=None, scrap_id=None, page_callback=None, cancel_check=None, stop_check=None):
        candidates = _candidate_urls([str(url) for url in urls], self.max_urls)
        if not candidates:
            return []
        payload = {"urls": candidates, "max_pages": self.max_pages, "max_urls": self.max_urls, "max_depth": self.max_depth}
        if scrap_id:
            payload["scrap_id"] = str(scrap_id)
        payload_input = json.dumps(payload)
        stdout_lines = []
        latest_progress = {"pages_collected": 0, "pages_failed": 0}
        stream_offsets = {}
        if progress_callback is None and page_callback is None:
            result = subprocess.run([sys.executable, "-m", "src.collector.worker"], input=payload_input, capture_output=True, text=True, check=False, cwd=Path(__file__).resolve().parents[2], timeout=self.WORKER_TIMEOUT_SECONDS)
            stdout_lines = result.stdout.splitlines()
            returncode = result.returncode
        else:
            result = subprocess.Popen([sys.executable, "-m", "src.collector.worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=Path(__file__).resolve().parents[2], start_new_session=True)
            assert result.stdin is not None and result.stdout is not None
            result.stdin.write(payload_input)
            result.stdin.close()
            for line in result.stdout:
                if cancel_check and cancel_check():
                    try:
                        os.killpg(result.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    result.wait(timeout=10)
                    if progress_callback:
                        progress_callback({"state": "canceled", "urls_submitted": len(candidates), "pages_collected": int(latest_progress.get("pages_collected", 0)), "pages_failed": int(latest_progress.get("pages_failed", 0)), "message": "Scrapy collection worker terminated by cancellation"})
                    raise RuntimeError("Scrapy collection canceled")
                if stop_check and stop_check():
                    try:
                        os.killpg(result.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    result.wait(timeout=10)
                    if progress_callback:
                        progress_callback({"state": "completed", "urls_submitted": len(candidates), "pages_collected": int(latest_progress.get("pages_collected", 0)), "pages_failed": int(latest_progress.get("pages_failed", 0)), "message": "Scrapy collection stopped by research limit"})
                    return []
                line = line.rstrip("\n")
                if line.startswith("CLAW_PROGRESS="):
                    try:
                        event = json.loads(line.split("=", 1)[1])
                        latest_progress = event
                        if progress_callback:
                            progress_callback(event)
                    except (json.JSONDecodeError, ValueError):
                        pass
                elif line.startswith("CLAW_PAGE_FILE="):
                    if page_callback:
                        path = line.split("=", 1)[1]
                        offset = stream_offsets.get(path, 0)
                        try:
                            with open(path, "r", encoding="utf-8") as stream:
                                stream.seek(offset)
                                for record in stream:
                                    item = json.loads(record)
                                    page_callback(CollectedPage(
                                        url=item["url"], html=item.get("html", ""), text=item.get("text", ""),
                                        status=int(item.get("status", 0)), source=item.get("source", "scrapy"),
                                        error=item.get("error"), request_index=int(item.get("request_index", 0)),
                                        content_type=item.get("content_type", "text/html"),
                                        body=base64.b64decode(item.get("body", "")) if item.get("body") else b"",
                                        depth=int(item.get("depth", 0)),
                                    ))
                                stream_offsets[path] = stream.tell()
                        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                            pass
                else:
                    stdout_lines.append(line)
            try:
                returncode = result.wait(timeout=self.WORKER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                result.kill()
                result.wait()
                if progress_callback:
                    progress_callback({"state": "failed", "urls_submitted": len(candidates), "pages_collected": int(latest_progress.get("pages_collected", 0)), "pages_failed": int(latest_progress.get("pages_failed", 0)), "message": "Scrapy collection worker timed out after 600 seconds"})
                raise RuntimeError("Scrapy collection worker timed out after 600 seconds")
        if returncode:
            detail = " ".join(stdout_lines).strip()
            if progress_callback:
                progress_callback({"state": "failed", "urls_submitted": len(candidates), "pages_collected": int(latest_progress.get("pages_collected", 0)), "pages_failed": int(latest_progress.get("pages_failed", 0)), "message": detail[-500:] or "Scrapy worker failed"})
            raise RuntimeError(f"Scrapy collection worker failed: {detail}")
        if progress_callback:
            progress_callback({"state": "completed", "urls_submitted": len(candidates), "pages_collected": int(latest_progress.get("pages_collected", 0)), "pages_failed": int(latest_progress.get("pages_failed", 0)), "stats": latest_progress.get("stats", {}), "message": "Scrapy worker completed"})
        marker = "CLAW_RESULT="
        payload = next((line[len(marker):] for line in reversed(stdout_lines) if line.startswith(marker)), None)
        if payload is None:
            raise RuntimeError("Scrapy collection worker returned no result")
        pages = [CollectedPage(
            url=item["url"], html=item.get("html", ""), text=item.get("text", ""), status=int(item.get("status", 0)),
            source=item.get("source", "scrapy"), error=item.get("error"), request_index=int(item.get("request_index", 0)),
            content_type=item.get("content_type", "text/html"), body=base64.b64decode(item.get("body", "")) if item.get("body") else b"",
            depth=int(item.get("depth", 0)),
        ) for item in json.loads(payload)]
        for path in stream_offsets:
            try:
                os.unlink(path)
            except OSError:
                pass
        return sorted(pages, key=lambda page: page.request_index)

    async def collect_async(self, urls, progress_callback=None, scrap_id=None, page_callback=None, cancel_check=None, stop_check=None):
        return await asyncio.to_thread(self.collect, urls, progress_callback, scrap_id, page_callback, cancel_check, stop_check)
