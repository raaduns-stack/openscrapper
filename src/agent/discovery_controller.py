from dataclasses import dataclass
from src.models.criteria import SearchCriteria
from src.agent.query_expansion import QueryExpander
from src.models.criteria import CrawlerConfig


@dataclass(frozen=True)
class DiscoveryPlan:
    queries: list[str]
    query_budget: int

    @property
    def budget(self) -> int:
        """Backward-compatible alias for the query budget."""
        return self.query_budget


class DiscoveryController:
    def __init__(self, expander: QueryExpander | None = None, config: CrawlerConfig | None = None):
        self.expander = expander or QueryExpander()
        self.config = config or CrawlerConfig()

    def plan(self, criteria: SearchCriteria) -> DiscoveryPlan:
        query_budget = min(self.config.max_queries, max(10, criteria.max_leads // 5))
        queries = self.expander.expand(
            criteria,
            max_queries=query_budget,
        )

        return DiscoveryPlan(
            queries=queries[:query_budget],
            query_budget=query_budget,
        )
