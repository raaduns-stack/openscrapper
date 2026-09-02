from src.extract.phone import normalize_phone


def test_normalize_international_phone():
    assert normalize_phone("+27 11 123 4567") == "+27111234567"


def test_normalize_invalid_phone_preserves_value():
    assert normalize_phone("not-a-phone") == "not-a-phone"


def test_empty_phone():
    assert normalize_phone(None) is None
