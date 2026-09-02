from src.search.base import SearchProvider
from src.search.models import SearchResult, SearchResults


class SearchAggregator:
    def __init__(self, providers: list[SearchProvider]):
        self.providers = providers

    async def search(self, query: str, limit_per_provider: int = 10) -> SearchResults:
        seen = set()
        results = []

        for provider in self.providers:
            try:
                if hasattr(provider, "search_async"):
                    response = await provider.search_async(
                        query,
                        limit=limit_per_provider,
                    )
                else:
                    response = provider.search(
                        query,
                        limit=limit_per_provider,
                    )
            except Exception as exc:
                print(f"search_skip={provider.name} error={exc}")
                continue

            for result in response.results:
                url = result.url.strip()

                if not url or url in seen:
                    continue

                seen.add(url)
                results.append(
                    SearchResult(
                        title=result.title,
                        url=url,
                        snippet=result.snippet,
                        provider=result.provider or provider.name,
                    )
                )

        return SearchResults(
            query=query,
            results=results,
        )
