from dataclasses import dataclass
from src.models.criteria import SearchCriteria
from src.agent.query_expansion import QueryExpander

@dataclass(frozen=True)
class DiscoveryPlan:
    queries: list[str]
    budget: int

class DiscoveryController:
    def __init__(self, expander: QueryExpander | None = None):
        self.expander = expander or QueryExpander()

    def plan(self, criteria: SearchCriteria) -> DiscoveryPlan:
        budget = min(20, max(10, criteria.max_leads // 5))
        queries = self.expander.expand(criteria, max_queries=budget)
        return DiscoveryPlan(
            queries=queries[:budget],
            budget=budget,
        )
