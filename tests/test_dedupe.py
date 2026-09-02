from src.dedupe.leads import dedupe
from src.models.lead import Lead


def lead(name, city=None, state=None, phone=None, website=None):
    return Lead(
        business_name=name,
        city=city,
        state=state,
        phone=phone,
        website=website,
        source_url="https://example.com/source",
    )


def test_dedupe_by_phone():
    leads = [
        lead("Acme Mining", "Accra", "GA", "+233201234567"),
        lead("Acme Mining Ltd", "Kumasi", "AH", "+233201234567"),
    ]
    assert len(dedupe(leads)) == 1


def test_dedupe_by_website():
    leads = [
        lead("Acme Mining", "Accra", "GA", website="https://acme.example"),
        lead("Acme Mining Ltd", "Kumasi", "AH", website="https://acme.example"),
    ]
    assert len(dedupe(leads)) == 1


def test_dedupe_by_business_location():
    leads = [
        lead("Acme Mining Ltd", "Accra", "Greater Accra"),
        lead("ACME-MINING LTD", "Accra", "Greater Accra"),
    ]
    assert len(dedupe(leads)) == 1


def test_distinct_businesses_are_preserved():
    leads = [
        lead("Acme Mining", "Accra", "Greater Accra"),
        lead("Beta Mining", "Accra", "Greater Accra"),
    ]
    assert len(dedupe(leads)) == 2
