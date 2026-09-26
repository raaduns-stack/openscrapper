import os
import requests
from urllib.parse import urlparse
from src.models.lead import Lead

class FirecrawlEnricher:
    def __init__(self, search_limit=5, max_queries=3, max_pages=3):
        self.api_key = os.getenv("FIRECRAWL_API_KEY", "").strip()
        if not self.api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is not configured")
        self.search_limit = max(1, min(search_limit, 10))
        self.max_queries = max(1, min(max_queries, 3))
        self.max_pages = max(1, min(max_pages, 8))
        self.usage = {"search_requests": 0, "scrape_requests": 0, "search_results": 0, "search_results_returned": 0, "estimated_search_credits": 0, "estimated_scrape_credits": 0, "pages_collected": 0, "estimated_credits": 0, "scrape_errors": []}
        self.base_url = "https://api.firecrawl.dev/v2"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})

    def query_plan(self, lead):
        email = str(lead.email or "").strip()
        name = " ".join(x for x in (lead.first_name, lead.last_name) if x).strip()
        company = str(lead.company_name or "").strip()
        position = str(lead.position or "").strip()
        location = " ".join(x for x in (lead.city, lead.state, lead.country) if x).strip()
        plan = []
        if name:
            identity = f'"{name}"'
            if company:
                identity += f' "{company}"'
            if location:
                identity += f' "{location}"'
            plan.append({"intent": "identity_confirmation", "query": identity, "allow_linkedin": True})
        if name and (company or position):
            professional = f'"{name}"'
            if position:
                professional += f' "{position}"'
            if company:
                professional += f' "{company}"'
            if location:
                professional += f' "{location}"'
            plan.append({"intent": "professional_company", "query": professional, "allow_linkedin": True})
        if name:
            contact = f'"{name}"'
            if company:
                contact += f' "{company}"'
            if location:
                contact += f' {location}'
            plan.append({"intent": "contact_source_discovery", "query": contact, "allow_linkedin": bool(email)})
        elif company:
            plan.append({"intent": "contact_source_discovery", "query": f'"{company}" {location}'.strip(), "allow_linkedin": bool(email)})
        if email and name:
            plan.insert(0, {"intent": "email_identity", "query": f'"{name}" "{email}"', "allow_linkedin": True})
        return plan[:self.max_queries]

    def _queries(self, lead):
        return [item["query"] for item in self.query_plan(lead)]

    @staticmethod
    def _items(payload):
        data = payload.get("data") or {}
        return data.get("web") or data.get("results") or []

    def search(self, lead):
        items, seen = [], set()
        for step in self.query_plan(lead):
            query = step["query"]
            response = self.session.post(f"{self.base_url}/search", json={"query": query, "limit": self.search_limit, "sources": ["web"]}, timeout=60)
            self.usage["search_requests"] += 1
            response.raise_for_status()
            response_items = self._items(response.json())
            self.usage["search_results_returned"] += len(response_items)
            self.usage["estimated_search_credits"] += ((len(response_items) + 9) // 10) * 2
            for item in response_items:
                url = str(item.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                items.append({"url": url, "title": str(item.get("title") or ""), "snippet": str(item.get("description") or item.get("snippet") or ""), "query": query, "intent": step["intent"], "allow_linkedin": step["allow_linkedin"]})
                self.usage["search_results"] += 1
                if len(items) >= self.search_limit * self.max_queries:
                    return items
        return items

    def scrape(self, url):
        self.usage["scrape_requests"] += 1
        self.usage["estimated_scrape_credits"] = self.usage["scrape_requests"]
        response = self.session.post(f"{self.base_url}/scrape", json={"url": url, "formats": ["markdown"]}, timeout=120)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or payload
        metadata = data.get("metadata") or {}
        return {"url": str(metadata.get("sourceURL") or data.get("url") or url), "title": str(metadata.get("title") or data.get("title") or ""), "markdown": str(data.get("markdown") or ""), "status": int(metadata.get("statusCode") or 200)}

    @staticmethod
    def relevance_score(item, lead):
        query = str(item.get("query") or "").casefold()
        text = " ".join(str(item.get(k) or "") for k in ("title", "snippet", "url")).casefold()
        score = 0
        email = str(lead.email or "").casefold()
        name = " ".join(x for x in (lead.first_name, lead.last_name) if x).strip().casefold()
        company = str(lead.company_name or "").casefold()
        if email and email in text: score += 100
        if name and name in text: score += 40
        if company and company in text: score += 20
        if email and email in query: score += 10
        if name and name in query: score += 5
        if company and company in query: score += 3
        return score

    @classmethod
    def relevant(cls, item, lead):
        return cls.relevance_score(item, lead) > 0

    def collect(self, lead):
        search_items = self.search(lead)
        pages = []
        source_host = urlparse(str(lead.source_url or "")).netloc.casefold().removeprefix("www.")
        external_items = [
            item for item in search_items
            if urlparse(str(item.get("url") or "")).netloc.casefold().removeprefix("www.") != source_host
        ]
        def is_linkedin(item):
            host = (urlparse(str(item.get("url") or "")).hostname or "").casefold().removeprefix("www.")
            return host == "linkedin.com"

        if not lead.email:
            ranked_items = sorted(external_items, key=lambda item: (is_linkedin(item), -self.relevance_score(item, lead)))
        else:
            ranked_items = sorted(external_items, key=lambda item: self.relevance_score(item, lead), reverse=True)
        for item in ranked_items[:self.max_pages]:
            try:
                page = self.scrape(item["url"])
            except requests.RequestException as exc:
                self.usage["scrape_errors"].append({"url": item["url"], "error": f"{type(exc).__name__}: {exc}"[:500]})
                continue
            if page["markdown"].strip():
                page["intent"] = item.get("intent", "")
                page["allow_linkedin"] = item.get("allow_linkedin", bool(lead.email))
                page["linkedin_source"] = is_linkedin(item)
                pages.append(page)
                self.usage["pages_collected"] += 1
        self.usage["estimated_credits"] = (self.usage.get("estimated_search_credits", 0) + self.usage.get("estimated_scrape_credits", 0))
        return external_items, pages
