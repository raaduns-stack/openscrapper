import re
import uuid
from urllib.parse import urlparse

from psycopg.types.json import Jsonb

from src.db import db
from src.models.lead import Lead


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def _normalize_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_website(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(str(value).strip().casefold())
    return (parsed.netloc or parsed.path).removeprefix("www.").rstrip("/")


def identity_keys(lead: Lead) -> set[tuple[str, ...]]:
    email = _normalize_email(str(lead.email) if lead.email else None)
    phone = _normalize_phone(lead.phone)
    first = _normalize(lead.first_name)
    last = _normalize(lead.last_name)
    company = _normalize(lead.company_name)
    source = _normalize_website(str(lead.source_url)) if lead.source_url else ""
    keys: set[tuple[str, ...]] = set()
    if email:
        keys.add(("email", email))
    if phone:
        keys.add(("phone", phone))
    if source and (first or last):
        keys.add(("source_person", source, first, last))
    if first and last and company:
        keys.add(("person_company", first, last, company))
    return keys


def merge_leads(existing: Lead, incoming: Lead) -> Lead:
    merged = existing.model_copy(update={
        field: getattr(incoming, field)
        if getattr(incoming, field) not in (None, "")
        else getattr(existing, field)
        for field in (
            "first_name", "last_name", "position", "company_name",
            "country", "city", "state", "email", "phone", "website",
            "source_url",
        )
    })
    if existing.capture_stage != incoming.capture_stage:
        merged = merged.model_copy(update={"capture_stage": "serp+scrapy"})
    return merged


def persist_lead(scrap_id, lead: Lead, evidence_id=None) -> bool:
    if not scrap_id:
        return True
    sid = uuid.UUID(str(scrap_id))
    data = lead.model_dump(mode="json")
    keys = identity_keys(lead)
    with db() as conn:
        existing = None
        if keys:
            for key in keys:
                if key[0] == "email":
                    existing = conn.execute(
                        "SELECT id,data FROM leads WHERE scrap_id=%s "
                        "AND lower(data->>'email')=lower(%s) LIMIT 1",
                        (sid, key[1]),
                    ).fetchone()
                elif key[0] == "phone":
                    existing = conn.execute(
                        "SELECT id,data FROM leads WHERE scrap_id=%s "
                        "AND regexp_replace(data->>'phone','\\D','','g')=%s LIMIT 1",
                        (sid, key[1]),
                    ).fetchone()
                elif key[0] == "source_person":
                    existing = conn.execute(
                        "SELECT id,data FROM leads WHERE scrap_id=%s "
                        "AND data->>'source_url'=%s "
                        "AND regexp_replace(lower(data->>'first_name'),'[^a-z0-9]','','g')=%s "
                        "AND regexp_replace(lower(data->>'last_name'),'[^a-z0-9]','','g')=%s LIMIT 1",
                        (sid, str(lead.source_url), key[2], key[3]),
                    ).fetchone()
                elif key[0] == "person_company":
                    existing = conn.execute(
                        "SELECT id,data FROM leads WHERE scrap_id=%s "
                        "AND regexp_replace(lower(data->>'first_name'),'[^a-z0-9]','','g')=%s "
                        "AND regexp_replace(lower(data->>'last_name'),'[^a-z0-9]','','g')=%s "
                        "AND regexp_replace(lower(data->>'company_name'),'[^a-z0-9]','','g')=%s LIMIT 1",
                        (sid, key[1], key[2], key[3]),
                    ).fetchone()
                if existing:
                    break
        if existing:
            existing_data = existing[1] or {}
            merged = dict(existing_data)
            for field in (
                "first_name", "last_name", "position", "company_name",
                "country", "city", "state", "email", "phone", "website",
                "source_url",
            ):
                value = getattr(lead, field)
                if value not in (None, ""):
                    merged[field] = value
            if existing_data.get("capture_stage", "scrapy") != lead.capture_stage:
                merged["capture_stage"] = "serp+scrapy"
            conn.execute(
                "UPDATE leads SET data=%s WHERE id=%s",
                (Jsonb(merged), existing[0]),
            )
            lead_id = existing[0]
            created = False
        else:
            lead_id = uuid.uuid4()
            conn.execute(
                "INSERT INTO leads(id,scrap_id,data) VALUES(%s,%s,%s)",
                (lead_id, sid, Jsonb(data)),
            )
            created = True

        if evidence_id:
            conn.execute(
                "INSERT INTO lead_sources(lead_id,evidence_id) "
                "VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (lead_id, evidence_id),
            )
        conn.commit()
    return created


def dedupe(leads: list[Lead]) -> list[Lead]:
    seen: dict[tuple[str, ...], int] = {}
    result: list[Lead] = []
    for lead in leads:
        keys = identity_keys(lead)
        match_index = next((seen[key] for key in keys if key in seen), None)
        if match_index is not None:
            result[match_index] = merge_leads(result[match_index], lead)
            for key in keys:
                seen[key] = match_index
            continue
        index = len(result)
        result.append(lead)
        for key in keys:
            seen[key] = index
    return result
