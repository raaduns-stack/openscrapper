import json
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from src.browser.openclaw import OpenClawBrowser

class Paginator:
    def __init__(self, browser: OpenClawBrowser, max_pages: int = 25):
        self.browser = browser
        self.max_pages = max_pages

    def collect(self, url: str) -> list[tuple[str, str]]:
        pages = []
        seen_result_keys = set()
        current_url = url
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        page_key = next((k for k in ("_page", "page") if k in query), None)

        for index in range(self.max_pages):
            if index == 0:
                self.browser.navigate(current_url)

            actual_url = self.browser.current_url()
            html = self.browser.html()
            if not html.strip():
                break

            result_keys = self._result_keys(html)
            if result_keys:
                new_keys = result_keys - seen_result_keys
                if not new_keys:
                    break
                seen_result_keys.update(result_keys)
            elif not pages:
                result_keys = {hash(html)}
                seen_result_keys.update(result_keys)
            else:
                break

            seen_result_keys.update(result_keys)
            pages.append((actual_url, html))

            pagination_snapshot = self.browser.snapshot()
            next_ref = self._find_next_ref(pagination_snapshot)

            if next_ref and index + 1 < self.max_pages:
                self.browser.click(next_ref)
                time.sleep(1)
                continue

            if not page_key:
                break

            current_page = int(query[page_key][0])
            query[page_key] = [str(current_page + 1)]
            next_query = urlencode(query, doseq=True)
            current_url = urlunparse(parsed._replace(query=next_query))

        return pages

    @staticmethod
    def _result_keys(html: str) -> set[str]:
        soup = BeautifulSoup(html, "lxml")
        raw = soup.body.get_text(strip=True) if soup.body else html

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None

        if isinstance(data, list):
            return {
                str(
                    item.get("place_id")
                    or item.get("osm_type", "") + ":" + str(item.get("osm_id", ""))
                    or item
                )
                for item in data
                if isinstance(item, dict)
            }

        return {
            re.sub(r"\\s+", " ", link.get_text(" ", strip=True)).strip().lower()
            for link in soup.select("li.search_results_entry a[href]")
            if link.get_text(" ", strip=True)
        }

    @staticmethod
    def _find_next_ref(snapshot: str) -> str | None:
        for line in snapshot.splitlines():
            if re.search(r"\b(?:next(?:\s+page)?|more\s+results)\b", line, re.I):
                match = re.search(r"\[ref=([A-Za-z0-9_-]+)\]", line)
                if match:
                    return match.group(1)
        return None
