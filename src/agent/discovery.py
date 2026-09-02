from dataclasses import dataclass
from src.models.criteria import SearchCriteria
from src.agent.discovery_controller import DiscoveryController
from src.search.aggregator import SearchAggregator
from src.search.provider_crawlee import CrawleeSearchProvider
from src.agent.relevance import RelevanceScorer


@dataclass(frozen=True)
class CandidateSource:
    url: str
    query: str
    score: float


class DiscoveryAgent:
    def __init__(
        self,
        controller: DiscoveryController | None = None,
        search: SearchAggregator | None = None,
        relevance: RelevanceScorer | None = None,
    ):
        self.controller = controller or DiscoveryController()
        self.search = search or SearchAggregator(
            providers=[CrawleeSearchProvider()]
        )
        self.relevance = relevance or RelevanceScorer()

    async def discover(self, criteria: SearchCriteria) -> list[CandidateSource]:
        plan = self.controller.plan(criteria)

        sources: list[CandidateSource] = []
        seen: set[str] = set()

        for query in plan.queries:
            response = await self.search.search(query, limit_per_provider=10)

            for result in response.results:
                url = result.url.strip()

                if not url or url in seen:
                    continue

                score = self.relevance.score(result, criteria)

                if score < 2.0:
                    continue

                seen.add(url)
                sources.append(
                    CandidateSource(
                        url=url,
                        query=query,
                        score=score,
                    )
                )

        sources.sort(
            key=lambda source: source.score,
            reverse=True,
        )

        return sources[:criteria.max_leads]
