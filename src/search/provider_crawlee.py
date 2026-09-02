from urllib.parse import quote, urlparse, parse_qs, unquote
from bs4 import BeautifulSoup
from crawlee.crawlers import HttpCrawler
from crawlee import Request
from src.search.base import SearchProvider
from src.search.models import SearchResult, SearchResults


class CrawleeSearchProvider(SearchProvider):
    name = "crawlee"

    async def search_async(self, query: str, limit: int = 10) -> SearchResults:
        target = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        results = []

        async def handler(context):
            html = (await context.http_response.read()).decode(
                "utf-8", errors="ignore"
            )
            soup = BeautifulSoup(html, "html.parser")

            for link in soup.select("a.result__a, a.result-link, a[data-testid]"):
                href = link.get("href", "").strip()
                title = link.get_text(" ", strip=True)

                if not href or not title:
                    continue

                parsed = urlparse(href)

                if href.startswith("//duckduckgo.com/l/"):
                    resolved = parse_qs(parsed.query).get("uddg", [None])[0]
                    if not resolved:
                        continue
                    href = unquote(resolved).strip()
                    parsed = urlparse(href)

                if parsed.scheme not in {"http", "https"}:
                    continue

                if parsed.netloc.lower() in {
                    "google.com",
                    "www.google.com",
                    "duckduckgo.com",
                    "html.duckduckgo.com",
                }:
                    continue

                snippet = ""
                container = link.find_parent(
                    class_=lambda c: c and "result" in str(c)
                )
                if container:
                    node = container.select_one(
                        ".result__snippet, .result-snippet"
                    )
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

        crawler = HttpCrawler()
        crawler.router.default_handler(handler)

        await crawler.run([
            Request(uniqueKey=f"search:{query}", url=target)
        ])

        return SearchResults(
            query=query,
            results=results[:limit],
        )

    def search(self, query: str, limit: int = 10) -> SearchResults:
        raise RuntimeError(
            "CrawleeSearchProvider.search() is synchronous; "
            "use await search_async()"
        )
