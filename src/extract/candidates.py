from __future__ import annotations

from dataclasses import dataclass, field

from src.models.lead import has_person_specific_evidence


@dataclass
class Candidate:
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    company_name: str | None = None
    country: str | None = None
    city: str | None = None
    state: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    source_url: str | None = None
    evidence: dict[str, str] = field(default_factory=dict)


class CandidateBuilder:
    """Builds non-qualified extraction candidates from page evidence."""

    def build(self, evidence: object | None = None, *, source_url: str | None = None,
        company_name: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        position: str | None = None,
        country: str | None = None,
        city: str | None = None,
        state: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        website: str | None = None,
        evidence_map: dict[str, str] | None = None,
    ) -> Candidate:
        return Candidate(
            first_name=first_name,
            last_name=last_name,
            position=position,
            company_name=company_name,
            country=country,
            city=city,
            state=state,
            email=email,
            phone=phone,
            website=website,
            source_url=source_url or getattr(evidence, "source_url", None),
            evidence=evidence_map or {},
        )

    @staticmethod
    def is_valid_lead(candidate: Candidate, generic_prefixes: set[str] | None = None) -> bool:
        if not has_person_specific_evidence(candidate):
            return False
        if candidate.email:
            from src.extract.email import is_personal_email
            if not is_personal_email(candidate.email, generic_prefixes):
                return False
        return True
