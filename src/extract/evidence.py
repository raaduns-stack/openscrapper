import re
from bs4 import BeautifulSoup
import trafilatura
from src.models.evidence import FieldEvidence, PageEvidence
from src.extract.email import normalize_extracted_email


EMAIL_RE = re.compile(
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
    re.I,
)


class EvidenceBuilder:
    """Normalize collected pages into evidence without inventing facts."""

    def build(
        self,
        *,
        url: str,
        html: str,
        text: str = "",
        content: str = "",
        status: int = 200,
        rendered: bool = False,
        source: str = "scrapy",
    ) -> PageEvidence:
        soup = BeautifulSoup(html or "", "lxml")

        extracted_content = trafilatura.extract(
            html or "",
            include_links=True,
            include_tables=True,
            include_comments=False,
            favor_precision=True,
        ) or ""

        visible = (
            text.strip()
            or content.strip()
            or soup.get_text(" ", strip=True)
        )

        if extracted_content.strip() and extracted_content.strip() not in visible:
            visible = f"{visible}\n\n{extracted_content.strip()}".strip()

        fields: list[FieldEvidence] = []

        for match in EMAIL_RE.finditer(visible):
            value = normalize_extracted_email(match.group(0), visible)
            if not value:
                continue
            value = value.lower()
            start = max(0, match.start() - 120)
            end = min(len(visible), match.end() + 120)

            fields.append(
                FieldEvidence(
                    field="email",
                    value=value,
                    source_url=url,
                    excerpt=visible[start:end],
                    method="regex",
                    confidence=1.0,
                )
            )

        seen_emails = {field.value for field in fields}

        for node in soup.select("a[href^='mailto:']"):
            value = (
                node.get("href", "")
                .replace("mailto:", "", 1)
                .split("?", 1)[0]
                .strip()
                .lower()
            )

            if value and EMAIL_RE.fullmatch(value) and value not in seen_emails:
                fields.append(
                    FieldEvidence(
                        field="email",
                        value=value,
                        source_url=url,
                        excerpt=node.parent.get_text(
                            " ", strip=True
                        )[:300],
                        method="mailto",
                        confidence=1.0,
                    )
                )
                seen_emails.add(value)

        return PageEvidence(
            source_url=url,
            html=html or "",
            text=text or "",
            content=visible,
            status=status,
            rendered=rendered,
            source=source,
            fields=fields,
        )
