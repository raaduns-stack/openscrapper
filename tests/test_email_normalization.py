from src.extract.email import is_personal_email, normalize_extracted_email


def test_removes_known_read_suffix_artifacts():
    assert normalize_extracted_email("goldbecho2020@gmail.com.read") == "goldbecho2020@gmail.com"
    assert normalize_extracted_email("goldtradeug@gmail.comread") == "goldtradeug@gmail.com"
    assert normalize_extracted_email("psrmetalseng@gmail.read") is None


def test_removes_email_label_prefix_only_with_context():
    context = "Contact Choker Set India. Email-chokersetindia@gmail.com"
    assert normalize_extracted_email("Email-chokersetindia@gmail.com", context) == "chokersetindia@gmail.com"
    assert normalize_extracted_email("Email-chokersetindia@gmail.com") == "Email-chokersetindia@gmail.com"


def test_does_not_invent_or_repair_unknown_values():
    assert normalize_extracted_email("john.smith @ gmail.com") == "john.smith@gmail.com"
    assert normalize_extracted_email("john.smith(at)gmail.com") is None


def test_normalized_personal_email_passes_validation():
    value = normalize_extracted_email("goldbecho2020@gmail.com.read")
    assert value == "goldbecho2020@gmail.com"
    assert is_personal_email(value)
