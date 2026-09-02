from dataclasses import dataclass
import re
from src.models.criteria import SearchCriteria
from src.models.lead import Lead

@dataclass(frozen=True)
class QualificationResult:
    relevant: bool
    score: float
    reasons: tuple[str, ...]

class LeadQualifier:
    def qualify(self, lead: Lead, criteria: SearchCriteria) -> QualificationResult:
        text = " ".join([
            lead.business_name,
            lead.city or "",
            lead.state or "",
            lead.phone or "",
            str(lead.website or ""),
            " ".join(
                f"{contact.person_name} {contact.job_title or ''}"
                for contact in lead.contacts
            ),
        ]).casefold()

        score = 0.0
        reasons: list[str] = []

        for term in self._terms(criteria):
            if re.search(r"\b" + re.escape(term.casefold()) + r"\b", text):
                score += 2.0
                reasons.append(f"matched:{term}")

        matched_term = any(
            re.search(r"\b" + re.escape(term.casefold()) + r"\b", text)
            for term in self._terms(criteria)
        )

        if criteria.geography and matched_term:
            geography = criteria.geography.casefold()
            if geography in text:
                score += 2.0
                reasons.append(f"geography:{criteria.geography}")

        if criteria.roles:
            for role in criteria.roles:
                if role.casefold() in text:
                    score += 2.0
                    reasons.append(f"role:{role}")

        if criteria.target_type in {"people", "both"} and lead.contacts:
            score += 1.0
            reasons.append("has_contact")

        if lead.website:
            score += 0.5
            reasons.append("has_website")

        return QualificationResult(
            relevant=score >= 2.0,
            score=score,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _terms(criteria: SearchCriteria) -> list[str]:
        values = [
            criteria.industry,
            criteria.product,
            *criteria.keywords,
        ]
        return list(dict.fromkeys(
            value.strip()
            for value in values
            if value and value.strip()
        ))
