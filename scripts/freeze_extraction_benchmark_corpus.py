#!/usr/bin/env python3
"""Freeze a read-only 150-record extraction benchmark corpus outside the repo."""
import json
import os
from pathlib import Path
import psycopg
from src.pipeline import LeadDiscoveryPipeline

OUT = Path("/tmp/claw-extraction-benchmark-corpus.json")
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    rows = conn.execute("""
        SELECT id, url, title, snippet, raw_text
        FROM serp_results
        ORDER BY captured_at DESC, id
        LIMIT 150
    """).fetchall()

records = []
for rid, url, title, snippet, raw_text in rows:
    payload = LeadDiscoveryPipeline._serp_payload(
        {"title": title, "snippet": snippet, "raw_text": raw_text}, url
    )
    records.append({
        "id": str(rid), "url": url, "title": title,
        "snippet": snippet, "raw_text": raw_text, "current": payload,
    })
OUT.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
print(f"FROZEN {len(records)} RECORDS -> {OUT}")
