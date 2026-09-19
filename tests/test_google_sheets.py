import pytest

from src.exports.google_sheets import HEADERS, _rows, export_google_sheets
from src.models.lead import Lead


def lead():
    return Lead(first_name="Jane", last_name="Doe", email="jane@example.com", company_name="Example Mining", source_url="https://example.com/contact")


def test_google_sheet_rows_match_lead_schema():
    rows = _rows([lead()])
    assert rows[0] == HEADERS
    assert rows[1][0:4] == ["Jane", "Doe", "", "Example Mining"]
    assert rows[1][7] == "jane@example.com"
    assert rows[1][-1] == "https://example.com/contact"


def test_google_sheet_export_uses_existing_worksheet(monkeypatch):
    calls = {}

    class Tab:
        def clear(self):
            calls["clear"] = True

        def update(self, values, range_name, raw=False):
            calls["update"] = (values, range_name, raw)

    class Sheet:
        def worksheet(self, name):
            calls["worksheet"] = name
            return Tab()

    class Client:
        def open_by_key(self, key):
            calls["key"] = key
            return Sheet()

    import gspread
    monkeypatch.setattr(gspread, "service_account", lambda: Client())
    assert export_google_sheets([lead()], "sheet123", worksheet="Leads") == "sheet123"
    assert calls["key"] == "sheet123"
    assert calls["worksheet"] == "Leads"
    assert calls["clear"] is True
    assert calls["update"][1:] == ("A1", False)


def test_google_sheet_export_rejects_missing_id():
    with pytest.raises(ValueError, match="spreadsheet_id"):
        export_google_sheets([lead()], "")
