"""Google Sheets export boundary for V1.2."""

from __future__ import annotations

import os
from typing import Iterable

from src.models.lead import Lead

HEADERS = [
    "first_name", "last_name", "position", "company_name", "country",
    "city", "state", "email", "phone", "website", "source_url",
]


def _rows(leads: Iterable[Lead]) -> list[list[str]]:
    rows = [HEADERS]
    for lead in leads:
        data = lead.model_dump(mode="json")
        rows.append([str(data.get(field) or "") for field in HEADERS])
    return rows


def export_google_sheets(
    leads: Iterable[Lead],
    spreadsheet_id: str,
    *,
    worksheet: str = "Leads",
    credentials_file: str | None = None,
) -> str:
    """Write leads to an existing Google Sheet and return its spreadsheet ID."""
    if not spreadsheet_id.strip():
        raise ValueError("spreadsheet_id is required")
    if not worksheet.strip():
        raise ValueError("worksheet is required")

    try:
        import gspread
    except ImportError as exc:
        raise RuntimeError("gspread is required for Google Sheets export") from exc

    credentials = credentials_file or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials:
        client = gspread.service_account(filename=credentials)
    else:
        client = gspread.service_account()

    sheet = client.open_by_key(spreadsheet_id)
    try:
        tab = sheet.worksheet(worksheet)
    except gspread.WorksheetNotFound:
        tab = sheet.add_worksheet(title=worksheet, rows=1000, cols=len(HEADERS))

    tab.clear()
    tab.update(_rows(leads), "A1", raw=False)
    return spreadsheet_id
