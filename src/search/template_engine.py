from dataclasses import dataclass
import re
from src.models.criteria import SearchCriteria
from src.agent.geography import GeographyResolver

VARIABLES = {"industry", "product", "geography", "role", "keyword", "target_type"}
VAR_RE = re.compile(r"{([a-z_]+)}")

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
    def __init__(self, conn, adapters):
        self.conn = conn
        self.adapters = adapters
        self.geography = GeographyResolver()

    def _geography_values(self, value):
        raw = str(value or "").strip()
        if not raw:
            return [""]
        return self.geography.resolve_values(raw)

    def _values(self, criteria):
        return {
            "industry": [criteria.industry],
            "product": [criteria.product or criteria.industry],
            "geography": self._geography_values(criteria.geography),
            "role": criteria.roles or [""],
            "keyword": criteria.keywords or [""],
            "target_type": [criteria.target_type],
        }

    def generate(self, criteria: SearchCriteria, max_queries: int|None = None):
        if max_queries is not None and max_queries <= 0:
            return []
        rows = self.conn.execute(
            "SELECT t.id,t.category_id,t.provider,t.template,t.family,c.name "
            "FROM search_templates t JOIN search_template_categories c ON c.id=t.category_id "
            "WHERE t.active=true AND c.active=true ORDER BY c.position,t.position,t.created_at"
        ).fetchall()
        values = self._values(criteria)
        params=[]; seen=set()
        providers=[p for p in ("google","bing") if any(r[2]==p for r in rows)]
        if max_queries is not None and providers:
            provider_limits={p:max_queries//len(providers) for p in providers}
            for p in providers[:max_queries % len(providers)]: provider_limits[p]+=1
        else:
            provider_limits={p:max_queries for p in providers}
        provider_counts={p:0 for p in providers}
        for tid,cid,provider,template,family,category in rows:
            if max_queries is not None and provider_counts.get(provider,0) >= provider_limits.get(provider,0):
                continue
            variables=VAR_RE.findall(template)
            if any(v not in VARIABLES for v in variables):
                continue
            combos=[{}]
            for var in dict.fromkeys(variables):
                nxt=[]
                for combo in combos:
                    for value in values[var]:
                        nxt.append({**combo,var:value})
                combos=nxt
            for resolved in combos:
                if max_queries is not None and len(params) >= max_queries:
                    return params
                if max_queries is not None and provider_counts.get(provider,0) >= provider_limits.get(provider,0):
                    continue
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
                provider_counts[provider]=provider_counts.get(provider,0)+1
        return params
