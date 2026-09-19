import inspect
import json
import os
import re

from bs4 import BeautifulSoup
from parsel import Selector
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider

from src.extract.evidence import EvidenceBuilder
from src.extract.candidates import CandidateBuilder
from src.extract.phone import normalize_phone
from src.extract.email import is_personal_email
from src.models.evidence import PageEvidence
from src.models.lead import Lead


class PageLeads(BaseModel):
    leads: list[dict] = Field(default_factory=list)


class AdaptiveLeadExtractor:
    """Individual-first deterministic extraction with bounded LLM fallback."""

    LLM_MAX_ATTEMPTS = 2

    def __init__(self, model: str = "openai/gpt-oss-20b", generic_prefixes: set[str] | None = None):
        self.model = model
        self.generic_prefixes = generic_prefixes
        self.agent = None
        self.evidence_builder = EvidenceBuilder()
        self.candidate_builder = CandidateBuilder()

    def _get_agent(self):
        if self.agent is None:
            if not os.environ.get("GROQ_API_KEY"):
                raise RuntimeError("LLM fallback unavailable: GROQ_API_KEY is not configured")
            llm = GroqModel(
                self.model,
                provider=GroqProvider(
                    api_key=os.environ.get("GROQ_API_KEY")
                ),
            )

            self.agent = Agent(
                llm,
                output_type=PageLeads,
                retries=2,
                system_prompt=(
                    "You extract individual business contacts. "
                    "Every accepted lead must contain a valid personal email. "
                    "A name is optional when no reliable name is available. "
                    "Never invent missing values. "
                    "Company, position, country, city, state, phone and "
                    "website are enrichment fields. "
                    "Preserve source_url exactly."
                ),
            )

        return self.agent

    @staticmethod
    def _split_name(value: str) -> tuple[str | None, str | None]:
        value = re.sub(r"\s+", " ", value or "").strip()

        if not value:
            return None, None

        parts = value.split(" ")

        if len(parts) == 1:
            return parts[0], None

        return parts[0], " ".join(parts[1:])

    @staticmethod
    def _clean_mailto(value: str | None) -> str | None:
        if not value:
            return None

        return (
            value.replace("mailto:", "", 1)
            .split("?", 1)[0]
            .strip()
            .lower()
        ) or None

    @staticmethod
    def _clean_tel(value: str | None) -> str | None:
        if not value:
            return None

        return value.replace("tel:", "", 1).strip() or None

    @staticmethod
    def _normalize_phone(value: str | None) -> str | None:
        normalized = normalize_phone(value)
        if normalized == value and value:
            digits = re.sub(r"\D", "", value)
            if len(digits) == 10 and digits[0] in "23456789":
                return "+1" + digits
        return normalized

    def _extract_candidates(
        self,
        html: str,
        source_url: str,
    ) -> list[Lead]:
        selector = Selector(text=html)
        leads: list[Lead] = []

        def add_lead(data: dict) -> None:
            try:
                candidate = self.candidate_builder.build(
                    source_url=source_url,
                    first_name=data.get("first_name"),
                    last_name=data.get("last_name"),
                    position=data.get("position"),
                    company_name=data.get("company_name") or data.get("name"),
                    country=data.get("country"),
                    city=data.get("city"),
                    state=data.get("state"),
                    email=self._clean_mailto(data.get("email")),
                    phone=self._normalize_phone(self._clean_tel(data.get("phone"))),
                    website=data.get("website"),
                )
                if self.candidate_builder.is_valid_lead(candidate, self.generic_prefixes):
                    leads.append(Lead.model_validate({k: v for k, v in candidate.__dict__.items() if k != "evidence" and v is not None}, context={"generic_prefixes": self.generic_prefixes}))
            except (ValidationError, TypeError, ValueError):
                return

        soup = BeautifulSoup(html, "lxml")
        for node in soup.select('script[type="application/ld+json"]'):
            raw_json = node.string or node.get_text()
            try:
                payload = json.loads(raw_json)
            except (TypeError, ValueError):
                continue
            items = payload if isinstance(payload, list) else [payload]
            expanded = []
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                    expanded.extend(item["@graph"])
                else:
                    expanded.append(item)
            for item in expanded:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type")
                types = item_type if isinstance(item_type, list) else [item_type]
                types = [str(value).rsplit("/", 1)[-1] for value in types if value]
                if not any(value.casefold() == "person" for value in types) or not item.get("email"):
                    continue
                address = item.get("address") if isinstance(item.get("address"), dict) else {}
                first_name, last_name = self._split_name(str(item.get("name") or ""))
                add_lead({
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": item.get("email"),
                    "phone": item.get("telephone"),
                    "website": item.get("url"),
                    "position": item.get("jobTitle"),
                    "company_name": (item.get("worksFor") or {}).get("name") if isinstance(item.get("worksFor"), dict) else None,
                    "city": address.get("addressLocality"),
                    "state": address.get("addressRegion"),
                    "country": address.get("addressCountry", {}).get("name") if isinstance(address.get("addressCountry"), dict) else address.get("addressCountry"),
                })

        company_containers = selector.css(
            '[itemtype*="LocalBusiness"], '
            '[itemtype*="Organization"], '
            '.business, .company, .business-card, .company-card, '
            '.directory-entry, [data-business], [data-company]'
        )

        # Scan person/contact blocks independently of company containers. A page can
        # legitimately contain both directory/company markup and standalone contacts.
        for person in selector.css('.contact, .person, .employee, .team-member, [itemtype*="Person"]'):
            full_name = (
                person.css('[itemprop="name"]::text').get()
                or person.css('.name::text, .person-name::text, .contact-name::text, h3::text, h4::text').get()
                or " ".join(filter(None, [person.css('[itemprop="givenName"]::text').get(), person.css('[itemprop="familyName"]::text').get()]))
            )
            email = self._clean_mailto(
                person.css('a[href^="mailto:"]::attr(href)').get()
                or person.css('[itemprop="email"]::attr(content)').get()
                or person.css('[itemprop="email"]::text').get()
            )
            if not full_name or not email:
                continue
            first_name, last_name = self._split_name(full_name)
            add_lead({
                "first_name": first_name,
                "last_name": last_name,
                "position": person.css('[itemprop="jobTitle"]::text, .job-title::text, .jobtitle::text, .title::text, .role::text').get(),
                "company_name": person.css('[itemprop="worksFor"] [itemprop="name"]::text, .company::text').get() or selector.css('article > h1::text, article > h2::text').get(),
                "city": person.css('[itemprop="addressLocality"]::text, .city::text').get(),
                "state": person.css('[itemprop="addressRegion"]::text, .state::text').get(),
                "country": person.css('[itemprop="addressCountry"]::text, .country::text').get(),
                "email": email,
                "phone": self._normalize_phone(self._clean_tel(person.css('a[href^="tel:"]::attr(href)').get() or person.css('[itemprop="telephone"]::text').get() or person.css('.phone::text').get())),
                "website": person.css('[itemprop="url"]::attr(href), a[href^="http"]::attr(href)').get(),
            })

        for company in company_containers:
            company_name = (
                company.css('[itemprop="name"]::text').get()
                or company.css(
                    ':scope > h1::text, :scope > h2::text, '
                    ':scope > h3::text, :scope > h4::text'
                ).get()
                or company.css('h1::text, h2::text, h3::text, h4::text').get()
                or company.attrib.get("data-business")
                or company.attrib.get("data-company")
            )

            city = (
                company.css('[itemprop="addressLocality"]::text').get()
                or company.css('.city::text, .location::text').get()
                or company.css('[data-city]::attr(data-city)').get()
            )

            state = (
                company.css('[itemprop="addressRegion"]::text').get()
                or company.css('.state::text').get()
                or company.css('[data-state]::attr(data-state)').get()
            )

            country = (
                company.css('[itemprop="addressCountry"]::text').get()
                or company.css('.country::text').get()
                or company.css('[data-country]::attr(data-country)').get()
            )

            website = (
                company.css('[itemprop="url"]::attr(href)').get()
                or company.css('a.website::attr(href)').get()
            )

            people = company.css(
                '.contact, .person, .employee, .team-member, '
                '[class*="contact"], [class*="person"], '
                '[class*="employee"], [itemtype*="Person"]'
            )
            if not people and company.css('a[href^="mailto:"]'):
                people = [company]

            for person in people:
                full_name = (
                    person.css('[itemprop="name"]::text').get()
                    or person.css(
                        '.name::text, .person-name::text, '
                        '.contact-name::text, h3::text, h4::text'
                    ).get()
                )
                if not full_name:
                    full_name = " ".join(filter(None, [
                        person.css('[itemprop="givenName"]::text').get(),
                        person.css('[itemprop="familyName"]::text').get(),
                    ])) or None

                email = self._clean_mailto(
                    person.css(
                        'a[href^="mailto:"]::attr(href)'
                    ).get()
                )

                if not full_name or not email:
                    continue

                first_name, last_name = self._split_name(full_name)

                position = (
                    person.css('[itemprop="jobTitle"]::text').get()
                    or person.css(
                        '.job-title::text, .jobtitle::text, '
                        '.title::text, .role::text'
                    ).get()
                )

                phone = self._clean_tel(
                    person.css(
                        'a[href^="tel:"]::attr(href)'
                    ).get()
                    or person.css(
                        '[itemprop="telephone"]::text'
                    ).get()
                )

                candidate = self.candidate_builder.build(
                    source_url=source_url,
                    first_name=first_name,
                    last_name=last_name,
                    position=position.strip() if position else None,
                    company_name=company_name.strip() if company_name else None,
                    country=country.strip() if country else None,
                    city=city.strip() if city else None,
                    state=state.strip() if state else None,
                    email=email,
                    phone=normalize_phone(phone),
                    website=website,
                )

                if not self.candidate_builder.is_valid_lead(candidate, self.generic_prefixes):
                    continue

                try:
                    leads.append(Lead.model_validate({
                        key: value for key, value in candidate.__dict__.items()
                        if key != "evidence" and value is not None
                    }, context={"generic_prefixes": self.generic_prefixes}))
                except ValidationError:
                    continue

        text_lines = [
            " ".join(line.split())
            for line in soup.get_text("\n").splitlines()
            if line.strip()
        ]
        for index, line in enumerate(text_lines):
            email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", line, re.I)
            if not email_match:
                continue
            email = email_match.group(0)
            window = text_lines[max(0, index - 4):index + 1]
            for context in reversed(window):
                match = re.match(r"(?:Managing Director|Deputy Managing Director|Director|Manager|Head|Chief Executive Officer|CEO|President|Chairman|Partner)\s*:\s*(.+)$", context, re.I)
                if not match:
                    continue
                first_name, last_name = self._split_name(match.group(1).strip())
                add_lead({
                    "first_name": first_name,
                    "last_name": last_name,
                    "position": context.split(":", 1)[0].strip(),
                    "email": email,
                })
                break

        return self._unique(leads)

    @staticmethod
    def _compact_html(
        html: str,
        max_chars: int = 18000,
    ) -> str:
        soup = BeautifulSoup(html, "lxml")

        for tag in soup(
            ["script", "style", "noscript", "svg", "iframe"]
        ):
            tag.decompose()

        for tag in soup(["nav", "footer", "header"]):
            tag.decompose()

        compact = str(soup)

        if len(compact) <= max_chars:
            return compact

        body = soup.body or soup
        return body.get_text(" ", strip=True)[:max_chars]

    async def _llm_extract(
        self,
        html: str,
        source_url: str,
        evidence: PageEvidence | None = None,
    ) -> list[Lead]:
        compact_html = self._compact_html(html)

        evidence_text = evidence.content if evidence else ""

        evidence_fields = "\n".join(
            f"{field.field}: {field.value}"
            for field in (
                evidence.fields if evidence else []
            )
        )

        prompt = (
            "Extract INDIVIDUAL business contacts from this page.\n\n"
            f"EXACT SOURCE URL: {source_url}\n\n"
            "Acceptance rules:\n"
            "1. Every returned lead MUST have a personal email.\n"
            "2. A name is optional; email-only leads are valid when no other reliable fields are available.\n"
            "3. Reject generic role mailboxes such as info@, contact@, sales@, support@, admin@ and similar.\n"
            "4. Prefer both first_name and last_name when explicitly present.\n"
            "5. Extract position, company_name, country, city, state, "
            "phone and website whenever represented.\n"
            "6. Use null for unavailable enrichment fields.\n"
            "7. Never invent or infer unsupported facts.\n"
            "8. Do not return company-only records without a personal email.\n"
            "9. Preserve source_url exactly.\n\n"
            f"OBSERVED FIELDS:\n{evidence_fields}\n\n"
            f"VISIBLE CONTENT:\n{evidence_text[:18000]}\n\n"
            f"HTML:\n{compact_html}"
        )

        agent = self._get_agent()
        result = None
        for attempt in range(self.LLM_MAX_ATTEMPTS):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += (
                    "\n\nCORRECTION REQUIRED:\n"
                    "The previous response failed structured-output or acceptance validation. "
                    "Return only leads with a valid personal email; a name is optional. "
                    "Do not invent values; use null for unavailable enrichment fields. "
                    "Preserve source_url exactly."
                )
            try:
                result = await agent.run(attempt_prompt)
                break
            except Exception:
                if attempt == self.LLM_MAX_ATTEMPTS - 1:
                    return []

        if result is None:
            return []

        leads: list[Lead] = []

        for raw in result.output.leads:
            try:
                data = raw if isinstance(raw, dict) else raw.model_dump()
                data["source_url"] = source_url
                leads.append(Lead.model_validate(data, context={"generic_prefixes": self.generic_prefixes}))
            except ValidationError:
                continue

        return self._unique(leads)

    @staticmethod
    def _unique(leads: list[Lead]) -> list[Lead]:
        seen: set[tuple[str, str, str]] = set()
        result: list[Lead] = []

        for lead in leads:
            key = (
                str(lead.email).casefold(),
                (lead.first_name or "").casefold(),
                (lead.last_name or "").casefold(),
            )

            if key in seen:
                continue

            seen.add(key)
            result.append(lead)

        return result

    async def extract(
        self,
        html: str,
        source_url: str,
        evidence: PageEvidence | None = None,
    ) -> list[Lead]:
        evidence = evidence or self.evidence_builder.build(
            url=source_url,
            html=html,
        )

        deterministic = self._extract_candidates(
            html,
            source_url,
        )

        # EvidenceBuilder already extracts verified email fields from visible page
        # content. A personal email alone is a valid Lead per the source of truth,
        # so do not discard those evidence-backed emails merely because the page
        # lacks structured person markup.
        if not deterministic and evidence:
            for field in evidence.fields:
                if field.field != "email" or not field.value:
                    continue
                email = self._clean_mailto(field.value)
                if not email or not is_personal_email(email, self.generic_prefixes):
                    continue
                try:
                    deterministic.append(
                        Lead.model_validate(
                            {"email": email, "source_url": source_url},
                            context={"generic_prefixes": self.generic_prefixes},
                        )
                    )
                except ValidationError:
                    continue
            deterministic = self._unique(deterministic)

        if deterministic:
            return deterministic

        if not inspect.ismethod(self._llm_extract):
            return await self._llm_extract(
                evidence.html,
                source_url,
                evidence=evidence,
            )

        if not os.environ.get("GROQ_API_KEY"):
            return []

        return await self._llm_extract(
            evidence.html,
            source_url,
            evidence=evidence,
        )
