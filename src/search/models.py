from dataclasses import dataclass, field

@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""

@dataclass
class SearchResults:
    query: str
    results: list[SearchResult] = field(default_factory=list)

    def urls(self) -> list[str]:
        return [r.url for r in self.results]
