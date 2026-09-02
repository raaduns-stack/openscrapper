import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pydantic import ValidationError
from src.models.lead import Lead

class LeadExtractor:
    def extract(self, html: str, source_url: str) -> list[Lead]:
        soup = BeautifulSoup(html, "lxml")
        raw_body = soup.body.get_text(strip=True) if soup.body else html

        try:
            data = json.loads(raw_body)
        except json.JSONDecodeError:
            data = None

        if isinstance(data, list):
            return self._extract_json(data, source_url)

        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        body = soup.get_text(" ", strip=True).lower()

        security_markers = (
            "cloudflare", "you have been blocked", "attention required",
            "performing security verification", "security service to protect against malicious bots",
            "unusual traffic from your computer network", "recaptcha", "i'm not a robot",
        )
        if any(marker in title.lower() or marker in body for marker in security_markers):
            raise RuntimeError(f"Target blocked by security layer: {source_url}")

        leads = []

        for item in soup.select("li.search_results_entry"):
            link = item.select_one("a[href]")
            if not link:
                continue
            name = link.get_text(" ", strip=True)
            if not self._valid_name(name):
                continue
            try:
                leads.append(Lead(
                    business_name=name,
                    city=None,
                    source_url=source_url,
                ))
            except ValidationError:
                continue

        for node in soup.select("article, .business, .company, [class*='business'], [class*='company']"):
            name_node = node.select_one("h1, h2, h3, h4, [class*='name'], [class*='title']")
            if not name_node:
                continue
            name = name_node.get_text(" ", strip=True)
            if not self._valid_name(name):
                continue
            city = self._field(node, "city")
            state = self._field(node, "state")
            phone = self._field(node, "phone")
            link = node.select_one("a[href]")
            website = urljoin(source_url, link["href"]) if link else None
            try:
                leads.append(Lead(
                    business_name=name, city=city, state=state, phone=phone,
                    website=website, source_url=source_url,
                ))
            except ValidationError:
                continue

        return self._unique(leads)

    @staticmethod
    def _field(node, field: str) -> str | None:
        element = node.select_one(f".{field}, [class*='{field}']")
        return element.get_text(" ", strip=True) if element else None

    @staticmethod
    def _extract_json(data: list, source_url: str) -> list[Lead]:
        leads = []
        for item in data:
            if not isinstance(item, dict):
                continue
            company = item.get("company") or {}
            address = item.get("address") or {}
            name = company.get("name")
            if not name:
                continue
            try:
                website = item.get("website")
                if website and not str(website).startswith(("http://", "https://")):
                    website = "https://" + str(website)
                leads.append(Lead(
                    business_name=str(name), city=address.get("city"),
                    phone=item.get("phone"), website=website, source_url=source_url,
                ))
            except ValidationError:
                continue
        return LeadExtractor._unique(leads)

    @staticmethod
    def _valid_name(name: str) -> bool:
        if len(name) < 2 or len(name) > 200:
            return False
        return not re.fullmatch(r"(home|menu|search|login|sign in|next|previous|example domain)", name, re.I)

    @staticmethod
    def _unique(leads: list[Lead]) -> list[Lead]:
        seen = set()
        result = []
        for lead in leads:
            key = (
                re.sub(r"[^a-z0-9]", "", lead.business_name.lower()),
                (lead.city or "").lower(),
                (lead.state or "").lower(),
            )
            if key not in seen:
                seen.add(key)
                result.append(lead)
        return result
