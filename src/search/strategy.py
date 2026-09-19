from dataclasses import dataclass
from src.models.criteria import SearchCriteria
from src.search.provider_google import GoogleQueryAdapter
from src.search.provider_bing import BingQueryAdapter


@dataclass(frozen=True)
class SearchParameter:
    id: str
    provider: str
    query: str
    url: str
    family: str


class SearchStrategyEngine:
    """Generate diverse provider-specific search parameters; never executes search."""

    ROLE_SYNONYMS = {
        "buyer": ["buyer", "buyers", "purchasing", "procurement", "sourcing", "purchaser"],
        "trader": ["trader", "traders", "dealer", "dealers", "merchant"],
        "supplier": ["supplier", "suppliers", "distributor", "distributors", "wholesaler"],
        "broker": ["broker", "brokers", "agent", "agents", "intermediary"],
        "seller": ["seller", "sellers", "sales", "sales manager", "account manager"],
        "exporter": ["exporter", "exporters", "export manager", "international sales"],
        "importer": ["importer", "importers", "import manager", "purchasing manager"],
    }
    CONTACT_VARIANTS = ["email", '"@"', '"email address"', "contact", "phone", "tel", "mailto", '"get in touch"']
    NEGATIVE_TERMS = '-intitle:"profiles" -inurl:"dir/"'

    def _roles(self, criteria: SearchCriteria) -> list[str]:
        source = criteria.roles or [criteria.industry]
        out=[]
        for role in source:
            out.extend(self.ROLE_SYNONYMS.get(role.casefold(), [role]))
        return list(dict.fromkeys(out))

    @staticmethod
    def _location(criteria: SearchCriteria) -> str:
        return criteria.geography.strip() if criteria.geography else ""

    @staticmethod
    def _object(criteria: SearchCriteria) -> str:
        return (criteria.product or criteria.industry).strip()

    def generate(self, criteria: SearchCriteria, max_queries: int = 20) -> list[SearchParameter]:
        if max_queries <= 0:
            return []
        location=self._location(criteria)
        obj=self._object(criteria)
        roles=criteria.roles or [criteria.industry]
        params=[]; seen=set()
        adapters={"google":GoogleQueryAdapter(), "bing":BingQueryAdapter()}

        def add(provider: str, query: str, family: str) -> None:
            if len(params) >= max_queries: return
            query=" ".join(query.split()).strip()
            key=(provider, query.casefold())
            if not query or key in seen: return
            seen.add(key)
            ident=f"{provider}-{len(params)+1}"
            params.append(SearchParameter(ident, provider, query, adapters[provider].build_url(query), family))

        geo=f'"{location}"' if location else ""
        for role in roles:
            variants=self._roles(SearchCriteria(industry=role, roles=[role]))
            ors=" OR ".join(f'"{obj} {variant}"' for variant in variants)
            add("google", f'({ors}) {geo} +site:linkedin.com/in/', "linkedin-google")
            add("google", f'({ors}) {geo} +"contact"', "contact-google")
            add("bing", f'({ors}) {geo} {self.NEGATIVE_TERMS} site:linkedin.com/in/', "linkedin-bing")
            add("bing", f'({ors}) {geo} "email" {self.NEGATIVE_TERMS}', "contact-bing")

        for contact in self.CONTACT_VARIANTS[:5]:
            term=contact.strip(chr(34))
            add("google", f'"{obj}" {geo} +"{term}"', "contact-evidence-google")
            add("bing", f'"{obj}" {geo} "{term}" {self.NEGATIVE_TERMS}', "contact-evidence-bing")

        for keyword in criteria.keywords:
            add("google", f'"{obj}" "{keyword}" {geo} +"contact"', "keyword-contact")
            add("bing", f'"{obj}" "{keyword}" {geo} "email" {self.NEGATIVE_TERMS}', "keyword-email")

        if criteria.target_type in ("companies", "both"):
            for term in ("company", "business", "supplier", "distributor", "manufacturer", "refinery"):
                add("google", f'"{obj}" "{term}" {geo} +"contact"', "company-contact")
                add("bing", f'"{obj}" "{term}" {geo} "email" {self.NEGATIVE_TERMS}', "company-email")

        add("google", f'"{obj}" {geo}', "broad")
        add("bing", f'"{obj}" {geo} {self.NEGATIVE_TERMS}', "broad")
        return params
