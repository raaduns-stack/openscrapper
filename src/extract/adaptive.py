import os
from parsel import Selector
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider
from src.models.lead import Contact, Lead
from src.extract.metadata import MetadataExtractor
from src.extract.phone import normalize_phone


class PageLeads(BaseModel):
    leads: list[Lead] = Field(default_factory=list)


class AdaptiveLeadExtractor:
    """Deterministic-first extraction with bounded Groq self-correction."""

    def __init__(self, model: str = "openai/gpt-oss-20b"):
        self.model = model
        self.agent = None
        self.metadata = MetadataExtractor()

    def _get_agent(self):
        if self.agent is None:
            llm = GroqModel(self.model, provider=GroqProvider(api_key=os.environ.get('GROQ_API_KEY')))
            self.agent = Agent(
                llm,
                output_type=PageLeads,
                retries=2,
                system_prompt=(
                    "You are a business lead extraction engine. "
                    "Extract only businesses actually represented in the supplied HTML. "
                    "Never invent missing values. "
                    "Return one Lead per distinct business. "
                    "The source_url supplied by the application must be preserved exactly."
                ),
            )
        return self.agent

    def _extract_candidates(self, html: str, source_url: str) -> list[Lead]:
        selector = Selector(text=html)
        leads: list[Lead] = []

        containers = selector.css(
            '[itemtype*="LocalBusiness"], '
            '[itemtype*="Organization"], '
            '.business, .company, .business-card, .company-card, '
            '.directory-entry, [data-business], [data-company]'
        )

        for container in containers:
            name = (
                container.css('[itemprop="name"]::text').get()
                or container.css(
                    'h1::text, h2::text, h3::text, h4::text, strong::text, b::text'
                ).get()
                or container.attrib.get("data-business")
                or container.attrib.get("data-company")
            )

            if not name:
                continue

            city = (
                container.css('[itemprop="addressLocality"]::text').get()
                or container.css('.city::text, .location::text').get()
                or container.css('[data-city]::attr(data-city)').get()
            )

            state = (
                container.css('[itemprop="addressRegion"]::text').get()
                or container.css('.state::text').get()
                or container.css('[data-state]::attr(data-state)').get()
            )

            phone = (
                container.css('[itemprop="telephone"]::attr(content)').get()
                or container.css('[itemprop="telephone"]::text').get()
                or container.css('.phone::text').get()
                or container.css('a[href^="tel:"]::attr(href)').get()
            )

            website = (
                container.css('[itemprop="url"]::attr(href)').get()
                or container.css('a.website::attr(href)').get()
            )

            contacts = self._extract_contacts(container, source_url)

            try:
                leads.append(
                    Lead.model_validate(
                        {
                            "business_name": name.strip(),
                            "city": city.strip() if city else None,
                            "state": state.strip() if state else None,
                            "source_url": source_url,
                            "phone": phone.replace("tel:", "").strip() if phone else None,
                            "website": website,
                            "contacts": contacts,
                        }
                    )
                )
            except ValidationError:
                continue

        return leads

    @staticmethod
    def _extract_contacts(container, source_url: str) -> list[Contact]:
        contacts: list[Contact] = []

        nodes = container.css(
            '.contact, .person, .employee, .team-member, '
            '[class*="contact"], [class*="person"], [class*="employee"], '
            '[itemtype*="Person"]'
        )

        for node in nodes:
            name = (
                node.css('[itemprop="name"]::text').get()
                or node.css('.name::text, .person-name::text, '
                            '.contact-name::text, h3::text, h4::text').get()
            )

            if not name:
                continue

            title = (
                node.css('[itemprop="jobTitle"]::text').get()
                or node.css('.job-title::text, .jobtitle::text, '
                            '.title::text, .role::text').get()
            )

            email = node.css('a[href^="mailto:"]::attr(href)').get()
            if email:
                email = email.replace("mailto:", "").strip()

            phone = node.css('a[href^="tel:"]::attr(href)').get()
            if phone:
                phone = phone.replace("tel:", "").strip()

            try:
                contacts.append(
                    Contact(
                        person_name=name.strip(),
                        job_title=title.strip() if title else None,
                        email=email,
                        phone=phone,
                        source_url=source_url,
                    )
                )
            except ValidationError:
                continue

        return contacts

    @staticmethod
    def _compact_html(html: str, max_chars: int = 18000) -> str:
        soup = BeautifulSoup(html, "lxml")

        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()

        for tag in soup(["nav", "footer", "header"]):
            tag.decompose()

        compact = str(soup)

        if len(compact) <= max_chars:
            return compact

        body = soup.body or soup
        text = body.get_text(" ", strip=True)
        return text[:max_chars]

    async def _llm_extract(self, html: str, source_url: str) -> list[Lead]:
        compact_html = self._compact_html(html)

        prompt = (
            "Extract business leads from this HTML.\n\n"
            f"EXACT SOURCE URL: {source_url}\n\n"
            "Rules:\n"
            "1. Return one lead per distinct business or company.\n"
            "2. business_name is required.\n"
            "3. Use null when city, state, phone, or website is unavailable.\n"
            "4. Do not invent or infer values that are not represented in the HTML.\n"
            "5. Set source_url on every lead exactly to the supplied source URL.\n"
            "6. Ignore navigation, articles, advertisements, menus, and unrelated text.\n\n"
            "HTML:\n"
            f"{compact_html}"
        )

        result = await self._get_agent().run(prompt)
        leads: list[Lead] = []

        for raw in result.output.leads:
            try:
                data = raw.model_dump()
                data["source_url"] = source_url
                leads.append(Lead.model_validate(data))
            except ValidationError:
                continue

        return leads

    def _extract_metadata(self, html: str, source_url: str) -> list[Lead]:
        extracted = self.metadata.extract(html, source_url)
        leads: list[Lead] = []

        for item in extracted.get("json-ld", []):
            if not isinstance(item, dict):
                continue

            items = item.get("@graph", [item])
            if not isinstance(items, list):
                items = [items]

            for obj in items:
                if not isinstance(obj, dict):
                    continue

                obj_type = obj.get("@type", "")
                types = obj_type if isinstance(obj_type, list) else [obj_type]
                if not any(t in {"Organization", "LocalBusiness"} or str(t).endswith("Business") for t in types):
                    continue

                name = obj.get("name")
                if not name:
                    continue

                address = obj.get("address") or {}
                if not isinstance(address, dict):
                    address = {}

                website = obj.get("url")
                phone = obj.get("telephone")

                try:
                    leads.append(
                        Lead(
                            business_name=str(name).strip(),
                            city=address.get("addressLocality"),
                            state=address.get("addressRegion"),
                            phone=normalize_phone(str(phone).strip() if phone else None),
                            website=website,
                            source_url=source_url,
                        )
                    )
                except ValidationError:
                    continue

        return self._unique(leads)

    @staticmethod
    def _unique(leads: list[Lead]) -> list[Lead]:
        seen = set()
        result = []
        for lead in leads:
            key = (
                "".join(c.lower() for c in lead.business_name if c.isalnum()),
                (lead.city or "").lower(),
                (lead.state or "").lower(),
            )
            if key not in seen:
                seen.add(key)
                result.append(lead)
        return result

    async def extract(self, html: str, source_url: str) -> list[Lead]:
        metadata = self._extract_metadata(html, source_url)
        deterministic = self._extract_candidates(html, source_url)

        combined = self._unique(metadata + deterministic)
        if combined:
            return combined

        return await self._llm_extract(html, source_url)
