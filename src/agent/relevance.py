import re
from src.models.criteria import SearchCriteria
from src.search.models import SearchResult


class RelevanceScorer:
    POSITIVE_TERMS = {
        "dealer", "trader", "broker", "buyer", "seller",
        "supplier", "distributor", "merchant", "wholesaler",
        "retailer", "exporter", "importer", "company", "business",
        "contact", "directory", "members", "exhibitor", "association",
        "mining", "refinery",
    }

    NEGATIVE_TERMS = {
        "price", "calculator", "rate", "rates", "forecast",
        "news", "definition", "meaning", "history", "wiki",
        "investment guide", "how to invest",
    }

    def score(self, result: SearchResult, criteria: SearchCriteria) -> float:
        title = result.title.lower()
        snippet = result.snippet.lower()
        url = result.url.lower()
        text = " ".join([title, snippet, url])

        score = 0.0

        for term in self._criteria_terms(criteria):
            if term.lower() in text:
                score += 2.0

        for term in self.POSITIVE_TERMS:
            if re.search(r"\b" + re.escape(term) + r"\b", text):
                score += 1.0

        for term in self.NEGATIVE_TERMS:
            if term in text:
                score -= 2.0

        return score

    def is_relevant(
        self,
        result: SearchResult,
        criteria: SearchCriteria,
        minimum_score: float = 2.0,
    ) -> bool:
        return self.score(result, criteria) >= minimum_score

    @staticmethod
    def _criteria_terms(criteria: SearchCriteria) -> list[str]:
        terms = [
            criteria.industry,
            criteria.product,
            criteria.geography,
            *criteria.roles,
            *criteria.keywords,
        ]
        return [term.strip() for term in terms if term and term.strip()]
