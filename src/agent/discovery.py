from dataclasses import dataclass
from typing import Any
from src.observability.job_events import emit_event
from src.models.criteria import SearchCriteria, CrawlerConfig
from src.agent.discovery_controller import DiscoveryController

@dataclass(frozen=True)
class CandidateSource:
    url: str
    query: str

class DiscoveryAgent:
    """V1.3 discovery generates parameters; it does not scrape search engines."""
    def __init__(self, controller=None, search=None, config=None):
        self.config=config or CrawlerConfig(); self.controller=controller or DiscoveryController(config=self.config); self.search=search

    async def discover(self, criteria: SearchCriteria, event_sink: Any = None):
        plan=self.controller.plan(criteria)
        emit_event(event_sink, "Discovery", "Search parameters generated; awaiting human SERP selection", state="complete", queries_generated=len(plan.queries))
        return []
