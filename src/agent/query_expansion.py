from src.models.criteria import SearchCriteria
from src.agent.geography import GeographyResolver


class QueryExpander:
    PEOPLE_TERMS = [
        "dealer", "trader", "broker", "buyer", "seller",
        "exporter", "importer", "supplier", "distributor",
        "merchant", "wholesaler", "retailer", "agent",
    ]

    COMPANY_TERMS = [
        "company", "business", "supplier", "dealer",
        "trader", "exporter", "importer", "distributor",
        "wholesaler", "refinery", "mining company",
    ]

    INTENT_TERMS = [
        "directory", "companies", "businesses",
        "suppliers", "dealers", "traders",
        "buyers", "exporters", "importers",
        "associations", "members", "exhibitors",
    ]

    def __init__(self, geography: GeographyResolver | None = None):
        self.geography = geography or GeographyResolver()

    def expand(
        self,
        criteria: SearchCriteria,
        max_queries: int = 20,
    ) -> list[str]:
        if max_queries <= 0:
            return []

        industry = criteria.industry
        product = criteria.product or industry
        queries: list[str] = []
        seen: set[str] = set()

        def add(*parts: str) -> bool:
            if len(queries) >= max_queries:
                return False

            q = " ".join(
                p.strip() for p in parts
                if p and p.strip()
            )

            key = q.casefold()

            if not q or key in seen:
                return False

            seen.add(key)
            queries.append(q)
            return True

        custom_terms = [
            *criteria.keywords,
            *criteria.roles,
        ]

        if criteria.target_type in ("people", "both"):
            intent_terms = self.PEOPLE_TERMS + self.INTENT_TERMS
        else:
            intent_terms = self.COMPANY_TERMS + self.INTENT_TERMS

        # Stage 1: commercial discovery intent first.
        for term in [*custom_terms, *intent_terms]:
            if criteria.geography:
                add(industry, term, criteria.geography)
            else:
                add(industry, term)

            if len(queries) >= max_queries:
                return queries

        # Stage 2: broad fallback queries.
        add(industry)
        if product != industry:
            add(product)

        if criteria.geography:
            add(industry, criteria.geography)
            if product != industry:
                add(product, criteria.geography)

        # Stage 3: geographic expansion only after broad queries.
        if criteria.geography and len(queries) < max_queries:
            geo = self.geography.resolve(criteria.geography)

            for state in geo.states:
                add(industry, state.name)

                if len(queries) >= max_queries:
                    return queries

            # Only use cities if the query budget still has room.
            for state in geo.states:
                for city in state.cities:
                    add(industry, city)

                    if len(queries) >= max_queries:
                        return queries

        return queries
