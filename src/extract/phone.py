import phonenumbers


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
