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

    CONTACT_TERMS = [
        "contact", "contact us", "email", "phone",
        "staff", "team", "procurement", "purchasing",
        "sales", "directory", "members", "exhibitors",
    ]

    EMAIL_SEARCH_PATTERNS = [
        '"@"',
        'email',
        '"email address"',
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

        location = criteria.geography or ""
        relevance_terms = [*custom_terms, *intent_terms]
        contact_anchors = list(criteria.roles) or (
            self.PEOPLE_TERMS[:6] if criteria.target_type in ("people", "both") else self.COMPANY_TERMS[:6]
        )
        # Interleave topical and contact-bearing intent so crawl-page limits do not
        # consume the budget before contact-oriented results are reached.
        relevance_index = 0
        contact_index = 0
        while len(queries) < max_queries and (
            relevance_index < len(relevance_terms) or contact_index < len(self.CONTACT_TERMS)
        ):
            if relevance_index < len(relevance_terms):
                term = relevance_terms[relevance_index]
                relevance_index += 1
                add(industry, product if product != industry else "", term, location)
                if len(queries) >= max_queries:
                    return queries

            if contact_index < len(self.CONTACT_TERMS):
                contact_term = self.CONTACT_TERMS[contact_index]
                contact_anchor = contact_anchors[contact_index % len(contact_anchors)]
                contact_index += 1
                add(
                    industry,
                    product if product != industry else "",
                    contact_anchor,
                    contact_term,
                    location,
                )

                # Search-engine queries must actively surface contact-bearing sources.
                # "@" is an evidence marker, not a provider/domain allowlist: this
                # intentionally covers personal mailboxes on public and company domains.
                if len(queries) < max_queries:
                    email_pattern = self.EMAIL_SEARCH_PATTERNS[(contact_index - 1) % len(self.EMAIL_SEARCH_PATTERNS)]
                    add(
                        industry,
                        product if product != industry else "",
                        contact_anchor,
                        email_pattern,
                        location,
                    )

                if len(queries) < max_queries and criteria.target_type in ("people", "both"):
                    add(
                        "site:linkedin.com",
                        contact_anchor,
                        '"@"',
                        location,
                    )

        # Stage 3: broad fallback queries if the budget still has room.
        add(industry, location)
        if product != industry:
            add(product, location)

        # Stage 4: geographic expansion only after relevance + contact intent.
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
