from __future__ import annotations

import os
import re
import threading
from urllib.parse import urlparse


_SHARED_MODEL = None
_MODEL_LOCK = threading.Lock()
_INFERENCE_LOCK = threading.Lock()

from src.extract.email import is_personal_email, normalize_extracted_email
from src.models.lead import Lead


class ContextualLeadExtractor:
    """Optional GLiNER-Relex fallback for SERP records missed by deterministic extraction."""

    MODEL = os.getenv("CLAW_CONTEXTUAL_MODEL", "knowledgator/gliner-relex-base-v1.0")
    RELATION_THRESHOLD = float(os.getenv("CLAW_CONTEXTUAL_RELATION_THRESHOLD", "0.80"))

    LABELS = ["person", "job_role", "company", "location", "email", "phone"]
    RELATIONS = ["has_position", "works_at", "located_in", "has_email", "has_phone"]

    _ORG_NAME_MARKERS = {
        "university", "hospital", "medical", "center", "centre", "health",
        "association", "institute", "college", "school", "services",
        "foundation", "network", "clinic", "system", "council",
    }
    _BAD_SUPPORT = {
        "phone number", "views", "gmail", "email address", "website",
    }

    def __init__(self, generic_prefixes: set[str] | None = None):
        self.generic_prefixes = generic_prefixes

    def _get_model(self):
        global _SHARED_MODEL
        if _SHARED_MODEL is None:
            with _MODEL_LOCK:
                if _SHARED_MODEL is None:
                    from gliner import GLiNER
                    _SHARED_MODEL = GLiNER.from_pretrained(self.MODEL)
        return _SHARED_MODEL

    @staticmethod
    def _text(record: dict) -> str:
        return "\n".join(
            str(record.get(key) or "").replace("\xa0", " ").strip()
            for key in ("title", "snippet", "raw_text")
            if str(record.get(key) or "").strip()
        ).strip()

    @staticmethod
    def _split_name(value: str) -> tuple[str | None, str | None]:
        words = re.sub(r"\s+", " ", value or "").strip().split()
        if not words:
            return None, None
        return words[0], " ".join(words[1:]) or None

    @classmethod
    def _plausible_person(cls, value: str) -> bool:
        first, last = cls._split_name(value)
        if not first or not last:
            return False
        words = value.casefold().split()
        if len(words) > 5:
            return False
        return not any(word.strip(".,:;()") in cls._ORG_NAME_MARKERS for word in words)

    @staticmethod
    def _clean_relation_value(value: str) -> str | None:
        value = re.sub(r"\s+", " ", value or "").strip(" .,:;|")
        return value or None

    @classmethod
    def _valid_phone(cls, value: str | None) -> bool:
        return bool(value and len(re.sub(r"\D", "", value)) >= 7)

    @classmethod
    def _relation_context_valid(cls, text: str, relation: dict, serp: bool = False) -> bool:
        head = relation.get("head", {})
        tail = relation.get("tail", {})
        start = min(int(head.get("start", 0)), int(tail.get("start", 0)))
        end = max(int(head.get("end", 0)), int(tail.get("end", 0)))
        context = text[max(0, start - 90):min(len(text), end + 90)].casefold()
        relation_type = relation.get("relation")
        cues = {
            "has_position": ("currently", "is a", "is an", "works as", "job title", "position", "role", "crna", "rn"),
            "works_at": ("works at", "works for", "employed by", "with", "at"),
            "located_in": ("based in", "located in", "in "),
        }
        required = cues.get(relation_type)
        if required and any(cue in context for cue in required):
            return True
        if not serp:
            return not required
        if relation_type == "has_position":
            value = cls._clean_relation_value(tail.get("text", "")) or ""
            distance = abs(int(tail.get("start", 0)) - int(head.get("end", 0)))
            return distance <= 100 and 1 <= len(value.split()) <= 5
        return False

    @classmethod
    def _valid_support(cls, relation: str, value: str) -> bool:
        value_cf = value.casefold()
        if value_cf in cls._BAD_SUPPORT:
            return False
        if relation == "has_email":
            return bool(re.fullmatch(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I))
        if relation == "has_phone":
            return cls._valid_phone(value)
        if relation == "has_position":
            return not any(marker in value_cf for marker in cls._ORG_NAME_MARKERS)
        if relation == "works_at":
            return not value_cf.endswith((" for", " of", " and", " the", " at", " in"))
        return True

    @staticmethod
    def _is_source_platform_company(value: str, source_url: str) -> bool:
        host = (urlparse(source_url).hostname or "").casefold()
        company = re.sub(r"[^a-z0-9]", "", value.casefold())
        host_parts = [re.sub(r"[^a-z0-9]", "", part) for part in host.split(".") if part]
        return bool(company and company in host_parts)

    @staticmethod
    def _location_parts(value: str) -> tuple[str | None, str | None, str | None]:
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not parts:
            return None, None, None
        city = parts[0]
        state = parts[1] if len(parts) >= 2 and len(parts[1]) <= 3 else None
        country = parts[2] if len(parts) >= 3 else None
        if country:
            country = {"US": "United States", "USA": "United States"}.get(country.upper(), country)
        return city, state, country

    def extract(self, record: dict, source_url: str) -> Lead | None:
        text = self._text(record)
        if not text:
            return None

        result = self._get_model().inference(
            text,
            labels=self.LABELS,
            relations=self.RELATIONS,
            threshold=0.35,
            relation_threshold=self.RELATION_THRESHOLD,
            return_relations=True,
            flat_ner=False,
        )
        if isinstance(result, tuple):
            entity_groups, relation_groups = result
        else:
            entity_groups = result.get("entities") or []
            relation_groups = result.get("relations") or []
        entities = entity_groups[0] if entity_groups else []
        relations = relation_groups[0] if relation_groups else []

        people = [
            entity for entity in entities
            if entity.get("label") == "person"
            and self._plausible_person(entity.get("text", ""))
        ]
        if not people:
            return None

        candidates = []
        for person in people:
            name = person["text"]
            fields = {}
            for relation in relations:
                if relation.get("head", {}).get("text") != name:
                    continue
                score = float(relation.get("score") or 0)
                if score < self.RELATION_THRESHOLD:
                    continue
                relation_type = relation.get("relation")
                value = self._clean_relation_value(relation.get("tail", {}).get("text", ""))
                if not value or not self._valid_support(relation_type, value):
                    continue
                if relation_type in {"has_position", "works_at", "located_in"} and not self._relation_context_valid(text, relation, serp=True):
                    continue
                if relation_type == "has_position":
                    fields.setdefault("position", value)
                elif relation_type == "works_at":
                    if not self._is_source_platform_company(value, source_url):
                        fields.setdefault("company_name", value)
                elif relation_type == "located_in":
                    city, state, country = self._location_parts(value)
                    fields.setdefault("city", city)
                    if state:
                        fields.setdefault("state", state)
                    if country:
                        fields.setdefault("country", country)
                elif relation_type == "has_email":
                    value = normalize_extracted_email(value, text)
                    if value and is_personal_email(value, self.generic_prefixes):
                        fields.setdefault("email", value)
                elif relation_type == "has_phone":
                    fields.setdefault("phone", value)

            first_name, last_name = self._split_name(name)
            payload = {
                "first_name": first_name,
                "last_name": last_name,
                "source_url": source_url,
                "capture_stage": "serp",
                **fields,
            }
            try:
                lead = Lead.model_validate(payload, context={"generic_prefixes": self.generic_prefixes})
            except Exception:
                continue
            candidates.append(lead)

        if not candidates:
            return None
        return candidates[0]
