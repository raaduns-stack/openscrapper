import re
from urllib.parse import urlparse
from src.models.lead import Lead

def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())

def _normalize_email(value: str | None) -> str:
    return (value or "").strip().casefold()

def _normalize_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")

def _normalize_website(value: str | None) -> str:
    if not value: return ""
    parsed = urlparse(str(value).strip().casefold())
    return (parsed.netloc or parsed.path).removeprefix("www.").rstrip("/")

def dedupe(leads: list[Lead]) -> list[Lead]:
    seen: set[tuple[str, ...]] = set()
    result: list[Lead] = []
    for lead in leads:
        email = _normalize_email(str(lead.email) if lead.email else None)
        phone = _normalize_phone(lead.phone)
        first = _normalize(lead.first_name)
        last = _normalize(lead.last_name)
        company = _normalize(lead.company_name)
        city = _normalize(lead.city)
        state = _normalize(lead.state)
        website = _normalize_website(str(lead.website) if lead.website else None)
        keys = {
            ("email", email) if email else None,
            ("phone", phone) if phone else None,
            ("website", website) if website else None,
            ("person", first, last, company) if (first or last) and company else None,
            ("company_location", company, city, state) if company and city and state else None,
        }
        keys.discard(None)
        if any(key in seen for key in keys): continue
        result.append(lead)
        seen.update(keys)
    return result
