#!/usr/bin/env python3
"""Read-only extraction-engine spike benchmark.

This script never writes to PostgreSQL and never invokes the production pipeline.
It compares the current deterministic SERP parser with spaCy and GLiNER2 on a
frozen sample of persisted SERP evidence.
"""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import spacy
from gliner2 import AutoExtractor

from src.models.lead import Lead

CORPUS_PATH = "/tmp/claw-extraction-benchmark-corpus.json"
GLINER_MODEL = "fastino/gliner2.5-small-v1"


def load_corpus():
    return json.loads(Path(CORPUS_PATH).read_text(encoding="utf-8"))


def text_for(row):
    return "\n".join(
        x for x in (row.get("title"), row.get("snippet"), row.get("raw_text")) if x
    ).strip()


def accepted(payload):
    if not payload:
        return False
    try:
        Lead.model_validate(payload, context={"generic_prefixes": set()})
        return True
    except Exception:
        return False


def split_person(value):
    words = value.strip().split()
    if len(words) == 1:
        return words[0], None
    return words[0], " ".join(words[1:])

def gliner_result(model, text):
    started = time.perf_counter()
    result = model.extract_entities(
        text,
        {
            "person": "a human person's name",
            "job_role": "a person's occupation, job title, professional role, or position",
            "company": "an employer, company, hospital, university, organization, or institution",
            "location": "a city, state, region, country, or geographic place",
            "email": "an email address",
            "phone": "a telephone or mobile phone number",
        },
    )
    return result, time.perf_counter() - started


def gliner_payload(result, url):
    entities = result.get("entities", {})
    people = entities.get("person", [])
    if not people:
        return None
    person = people[0]
    first, last = split_person(person)
    roles = entities.get("job_role", [])
    companies = entities.get("company", [])
    locations = entities.get("location", [])
    emails = entities.get("email", [])
    phones = entities.get("phone", [])
    return {
        "first_name": first,
        "last_name": last,
        "position": roles[0] if roles else None,
        "company_name": companies[0] if companies else None,
        "city": locations[0] if locations else None,
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "source_url": url,
        "capture_stage": "serp",
    }


def spacy_payload(doc, url):
    people = [e.text for e in doc.ents if e.label_ == "PERSON"]
    if not people:
        return None
    first, last = split_person(people[0])
    organizations = [e.text for e in doc.ents if e.label_ == "ORG"]
    locations = [e.text for e in doc.ents if e.label_ in {"GPE", "LOC", "FAC"}]
    return {
        "first_name": first,
        "last_name": last,
        "company_name": organizations[0] if organizations else None,
        "city": locations[0] if locations else None,
        "source_url": url,
        "capture_stage": "serp",
    }


def summarize(name, rows):
    total = len(rows)
    accepted_count = sum(x["accepted"] for x in rows)
    person_count = sum(bool(x["payload"] and x["payload"].get("first_name")) for x in rows)
    support_count = sum(
        bool(x["payload"] and any(x["payload"].get(k) for k in
            ("position", "company_name", "phone", "city", "state", "country", "website")))
        for x in rows
    )
    elapsed = sum(x.get("seconds", 0.0) for x in rows)
    print(json.dumps({
        "engine": name,
        "records": total,
        "person_records": person_count,
        "supporting_evidence_records": support_count,
        "contract_accepted_records": accepted_count,
        "seconds": round(elapsed, 3),
        "avg_seconds": round(elapsed / total, 4) if total else 0,
    }))

def main():
    rows = load_corpus()
    print(json.dumps({"corpus_size": len(rows), "requested": 150}))

    current = [
        {"accepted": accepted(row.get("current")), "payload": row.get("current"), "seconds": 0.0}
        for row in rows
    ]
    summarize("current_deterministic", current)

    nlp = spacy.load("en_core_web_sm")
    spacy_rows = []
    for row in rows:
        started = time.perf_counter()
        payload = spacy_payload(nlp(text_for(row)), row["url"])
        spacy_rows.append({"payload": payload, "accepted": accepted(payload), "seconds": time.perf_counter() - started})
    summarize("spacy_en_core_web_sm", spacy_rows)

    model = AutoExtractor.from_pretrained(GLINER_MODEL)
    gliner_rows = []
    for row in rows:
        result, seconds = gliner_result(model, text_for(row))
        payload = gliner_payload(result, row["url"])
        gliner_rows.append({"payload": payload, "accepted": accepted(payload), "seconds": seconds})
    summarize(GLINER_MODEL, gliner_rows)

    recovered = []
    for i, row in enumerate(rows):
        if not current[i]["accepted"] and gliner_rows[i]["accepted"]:
            recovered.append({"id": str(row["id"]), "title": row["title"], "payload": gliner_rows[i]["payload"]})
    report_path = Path("/root/claw-scrapper/benchmark_results/extraction_engine_comparison.csv")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "id", "url", "title", "current_accepted", "current_payload",
            "spacy_accepted", "spacy_payload",
            "gliner_accepted", "gliner_payload",
            "raw_text",
        ])
        writer.writeheader()
        for i, row in enumerate(rows):
            writer.writerow({
                "id": row["id"],
                "url": row["url"],
                "title": row["title"],
                "current_accepted": current[i]["accepted"],
                "current_payload": json.dumps(current[i]["payload"], ensure_ascii=False),
                "spacy_accepted": spacy_rows[i]["accepted"],
                "spacy_payload": json.dumps(spacy_rows[i]["payload"], ensure_ascii=False),
                "gliner_accepted": gliner_rows[i]["accepted"],
                "gliner_payload": json.dumps(gliner_rows[i]["payload"], ensure_ascii=False),
                "raw_text": row.get("raw_text") or "",
            })
    print(json.dumps({"detail_report": str(report_path), "records": len(rows)}))
    print(json.dumps({"gliner_recovered_over_current": len(recovered), "examples": recovered[:20]}, default=str))


if __name__ == "__main__":
    main()
