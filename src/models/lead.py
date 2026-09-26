from typing import Literal
from pydantic import BaseModel, EmailStr, Field, HttpUrl, ValidationInfo, model_validator

from src.extract.email import is_personal_email


PERSON_IDENTITY_FIELDS = ("first_name", "last_name")
PERSON_SUPPORT_FIELDS = ("position", "company_name", "phone", "city", "state", "country", "website")

# CTO-controlled automation gate. Fields listed here are rendered with `*` in the
# workstation and MUST NOT be populated or corrected by scraping/enrichment.
# Manual workstation editing remains allowed.
PROTECTED_LEAD_FIELDS = frozenset({"email", "phone"})


def is_protected_lead_field(field: str) -> bool:
    return field in PROTECTED_LEAD_FIELDS


def strip_protected_lead_fields(data: dict) -> dict:
    return {field: value for field, value in data.items() if not is_protected_lead_field(field)}


_BAD_NAME_TOKENS = {"email", "phone", "number", "list", "database", "contacts", "verified", "gmail", "yahoo", "outlook", "hotmail"}
_BAD_SUPPORT_PHRASES = ("email list", "email database", "verified contacts", "contact database", "mailing list", "phone number list")


def _is_plausible_person_name(value: object) -> bool:
    text = str(value or "").strip()
    if not text or "@" in text or "http://" in text.casefold() or "https://" in text.casefold():
        return False
    tokens = {token.casefold() for token in text.replace("-", " ").split()}
    return not tokens.intersection(_BAD_NAME_TOKENS)


def _is_valid_support(field: str, value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    folded = text.casefold()
    if field in {"position", "company_name"}:
        if "@" in text or "http://" in folded or "https://" in folded:
            return False
        if any(phrase in folded for phrase in _BAD_SUPPORT_PHRASES):
            return False
    return True


def has_person_specific_evidence(data: object) -> bool:
    """Return True when a record identifies a person and has valid supporting evidence."""
    values = data if isinstance(data, dict) else data.__dict__
    has_name = any(_is_plausible_person_name(values.get(field)) for field in PERSON_IDENTITY_FIELDS)
    has_support = any(_is_valid_support(field, values.get(field)) for field in PERSON_SUPPORT_FIELDS)
    return bool(has_name and has_support)


def is_accepted_lead(data: object, generic_prefixes: set[str] | None = None) -> bool:
    """Return True for any of the three authoritative Lead acceptance paths."""
    values = data if isinstance(data, dict) else data.__dict__
    email = str(values.get("email") or "").strip()
    if email and is_personal_email(email, generic_prefixes):
        return True
    return has_person_specific_evidence(data)


class Lead(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    position: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=150)
    state: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    phone: str | None = None
    website: HttpUrl | None = None
    source_url: HttpUrl
    capture_stage: Literal["serp", "scrapy", "serp+scrapy"] = "scrapy"

    @model_validator(mode="after")
    def validate_contact_acceptance(self, info: ValidationInfo):
        prefixes = info.context.get("generic_prefixes") if isinstance(info.context, dict) else None
        if not is_accepted_lead(self, prefixes):
            raise ValueError(
                "accepted lead requires a person name and supporting person-specific evidence"
            )
        if self.email and not is_personal_email(str(self.email), prefixes):
            raise ValueError("accepted lead email must be personal when provided")
        return self
