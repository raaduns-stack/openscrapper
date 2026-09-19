from src.dedupe.leads import dedupe
from src.models.lead import Lead


def lead(first="John", last="Doe", company="Acme Mining", email="john@example.com", phone=None, website=None, city="Accra", state="Greater Accra"):
    return Lead(first_name=first,last_name=last,company_name=company,email=email,phone=phone,website=website,city=city,state=state,source_url="https://example.com/source")

def test_dedupe_by_phone():
    leads=[lead(email="john@example.com",phone="+233201234567"),lead(first="Jane",last="Smith",company="Acme Mining Ltd",email="jane@example.com",phone="+233201234567",city="Kumasi",state="Ashanti")]
    assert len(dedupe(leads)) == 1

def test_dedupe_by_website():
    leads=[lead(email="john@example.com",website="https://acme.example"),lead(first="Jane",last="Smith",company="Acme Mining Ltd",email="jane@example.com",website="https://acme.example",city="Kumasi",state="Ashanti")]
    assert len(dedupe(leads)) == 1

def test_dedupe_by_business_location():
    leads=[lead(email="john@example.com",company="Acme Mining Ltd"),lead(first="Jane",last="Smith",company="ACME-MINING LTD",email="jane@example.com")]
    assert len(dedupe(leads)) == 1

def test_distinct_businesses_are_preserved():
    leads=[lead(email="john@example.com",company="Acme Mining"),lead(first="Jane",last="Smith",company="Beta Mining",email="jane@example.com")]
    assert len(dedupe(leads)) == 2
