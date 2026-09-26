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
        text = " ".join(filter(None, [
            lead.first_name,
            lead.last_name,
            lead.position,
            lead.company_name,
            lead.country,
            lead.city,
            lead.state,
            lead.email,
            lead.phone,
            str(lead.website or ""),
        ])).casefold()

        score = 0.0
        reasons: list[str] = []

        for term in self._terms(criteria):
            if re.search(r"\b" + re.escape(term.casefold()) + r"\b", text):
                score += 2.0
                reasons.append(f"matched:{term}")

        if criteria.geography and criteria.geography.casefold() in text:
            score += 2.0
            reasons.append(f"geography:{criteria.geography}")

        for role in criteria.roles:
            if role.casefold() in text:
                score += 2.0
                reasons.append(f"role:{role}")

        # Source of truth: any personal email qualifies alone; otherwise require
        # person identity plus at least one supporting person-specific field.
        from src.models.lead import is_accepted_lead

        if lead.email:
            score += 1.0
            reasons.append("personal_email")

        if is_accepted_lead(lead):
            reasons.append("person_specific_evidence")
            return QualificationResult(
                relevant=True,
                score=score,
                reasons=tuple(reasons),
            )

        return QualificationResult(
            relevant=False,
            score=score,
            reasons=tuple(reasons),
        )

    @staticmethod
    def _terms(criteria: SearchCriteria) -> list[str]:
        values = [criteria.industry, criteria.product, *criteria.keywords]
        return list(dict.fromkeys(
            value.strip()
            for value in values
            if value and value.strip()
        ))
