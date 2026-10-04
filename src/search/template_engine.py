from dataclasses import dataclass
import re
from src.models.criteria import SearchCriteria
from src.agent.geography import GeographyResolver
from src.search.domain_resolver import ExternalDomainResolver

VARIABLES = {"industry", "product", "geography-1", "geography-2", "geography-3", "role", "keyword", "target_type", "domain"}
VAR_RE = re.compile(r"{([a-z0-9_-]+)}")

@dataclass(frozen=True)
class TemplateParameter:
    id: str
    provider: str
    query: str
    url: str
    family: str
    category: str
    template_id: str
    variables: dict

class SearchTemplateEngine:
    """Expand administrator-owned search templates; never invent search logic."""
    def __init__(self, conn, adapters, domain_resolver=None):
        self.conn = conn
        self.adapters = adapters
        self.geography = GeographyResolver()
        self.domain_resolver = domain_resolver if domain_resolver is not None else ExternalDomainResolver.from_env()
        self._domain_cache = {}

    def _geography_values(self, value):
        return self.geography.classify_values(value)

    def _expanded_roles(self, roles):
        out=[]
        for anchor in roles:
            anchor=str(anchor).strip()
            if not anchor:
                continue
            rows=self.conn.execute(
                "SELECT expanded_role FROM role_expansions WHERE lower(anchor_role)=lower(%s) AND active=true ORDER BY position,created_at",
                (anchor,)
            ).fetchall()
            values=[r[0] for r in rows] or [anchor]
            for value in [anchor, *values]:
                value=str(value).strip()
                if value and value.casefold() not in {x.casefold() for x in out}:
                    out.append(value)
        return out

    def _values(self, criteria):
        geography = self._geography_values(criteria.geography)
        return {
            "industry": [criteria.industry],
            "product": [criteria.product or criteria.industry],
            "geography-1": geography["geography-1"],
            "geography-2": geography["geography-2"],
            "geography-3": geography["geography-3"],
            "role": self._expanded_roles(criteria.roles),
            "keyword": criteria.keywords or [""],
            "target_type": [criteria.target_type],
        }

    def _domain_values(self, criteria, resolved):
        if not self.domain_resolver:
            return []
        geography = resolved.get("geography-3") or resolved.get("geography-2") or resolved.get("geography-1") or criteria.geography
        role = resolved.get("role", "")
        keyword = resolved.get("keyword", "")
        cache_key = (criteria.industry.casefold(), str(geography or "").casefold(), str(role or "").casefold(), str(keyword or "").casefold())
        if cache_key not in self._domain_cache:
            self._domain_cache[cache_key] = self.domain_resolver.resolve(
                industry=criteria.industry, geography=geography, role=role, keyword=keyword
            )
        return self._domain_cache[cache_key]

    def generate(self, criteria: SearchCriteria, max_queries: int|None = None):
        if max_queries is not None and max_queries < 0:
            return []
        rows = self.conn.execute(
            "SELECT t.id,t.category_id,t.provider,t.template,t.family,c.name "
            "FROM search_templates t JOIN search_template_categories c ON c.id=t.category_id "
            "WHERE t.active=true AND c.active=true ORDER BY c.position,t.position,t.created_at"
        ).fetchall()
        values = self._values(criteria)
        params=[]; seen=set()
        limit = None if max_queries in (None, 0) else max_queries
        for tid,cid,provider,template,family,category in rows:
            variables=VAR_RE.findall(template)
            if any(v not in VARIABLES for v in variables):
                continue
            combos=[{}]
            for var in dict.fromkeys(variables):
                if var == "domain":
                    continue
                nxt=[]
                for combo in combos:
                    for value in values[var]:
                        nxt.append({**combo,var:value})
                combos=nxt
            if "domain" in variables:
                nxt=[]
                for combo in combos:
                    for value in self._domain_values(criteria, combo):
                        nxt.append({**combo, "domain": value})
                combos=nxt
            for resolved in combos:
                if limit is not None and len(params) >= limit:
                    return params
                query=" ".join(template.format(**resolved).split()).strip()
                key=(provider,query.casefold())
                if not query or key in seen:
                    continue
                adapter=self.adapters.get(provider)
                if not adapter:
                    continue
                seen.add(key)
                ident=f"{provider}-{len(params)+1}"
                params.append(TemplateParameter(ident,provider,query,adapter.build_url(query),family,category,str(tid),resolved))
        return params
