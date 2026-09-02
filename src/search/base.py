from abc import ABC, abstractmethod
from src.search.models import SearchResults

class SearchProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> SearchResults:
        raise NotImplementedError
