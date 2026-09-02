from urllib.parse import urlparse
import re

from src.models.lead import Lead


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _normalize_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_website(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(str(value).strip().lower())
    host = parsed.netloc or parsed.path
    return host.removeprefix("www.").rstrip("/")


def dedupe(leads: list[Lead]) -> list[Lead]:
    seen_phones: set[str] = set()
    seen_websites: set[str] = set()
    seen_businesses: set[tuple[str, str, str]] = set()
    result: list[Lead] = []

    for lead in leads:
        phone = _normalize_phone(lead.phone)
        website = _normalize_website(lead.website)
        business = (
            _normalize_name(lead.business_name),
            (lead.city or "").strip().lower(),
            (lead.state or "").strip().lower(),
        )

        duplicate = (
            (phone and phone in seen_phones)
            or (website and website in seen_websites)
            or business in seen_businesses
        )

        if duplicate:
            continue

        result.append(lead)

        if phone:
            seen_phones.add(phone)
        if website:
            seen_websites.add(website)
        seen_businesses.add(business)

    return result
