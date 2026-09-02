from urllib.parse import quote, urlparse
import requests
from bs4 import BeautifulSoup
from src.search.base import SearchProvider
from src.search.models import SearchResult, SearchResults

class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    def search(self, query: str, limit: int = 10) -> SearchResults:
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results = []

        for link in soup.select("a.result__a[href]"):
            href = link.get("href", "").strip()
            title = link.get_text(" ", strip=True)

            if not href or not title:
                continue

            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"}:
                continue

            container = link.find_parent("div", class_="result")
            snippet = ""
            if container:
                node = container.select_one(".result__snippet")
                if node:
                    snippet = node.get_text(" ", strip=True)

            results.append(
                SearchResult(
                    title=title,
                    url=href,
                    snippet=snippet,
                    provider=self.name,
                )
            )

            if len(results) >= limit:
                break

        return SearchResults(query=query, results=results)
