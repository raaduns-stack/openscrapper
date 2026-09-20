import phonenumbers


def extract_phone(value: str | None, default_region: str | None = None) -> str | None:
    if not value:
        return None
    for match in phonenumbers.PhoneNumberMatcher(value, default_region):
        candidate = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        if phonenumbers.is_possible_number(match.number) and phonenumbers.is_valid_number(match.number):
            return candidate
    return None


def normalize_phone(value: str | None, default_region: str | None = None) -> str | None:
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        parsed = phonenumbers.parse(value, default_region)
    except phonenumbers.NumberParseException:
        return value

    if not phonenumbers.is_possible_number(parsed):
        return value

    if not phonenumbers.is_valid_number(parsed):
        return value

    return phonenumbers.format_number(
        parsed,
        phonenumbers.PhoneNumberFormat.E164,
    )
