import re
from src.policy import DEFAULT_GENERIC_MAILBOX_PREFIXES, normalize_mailbox_prefix

_GENERIC_LOCAL_PARTS = set(DEFAULT_GENERIC_MAILBOX_PREFIXES)
_GENERIC_PREFIXES = tuple(f"{p}-" for p in DEFAULT_GENERIC_MAILBOX_PREFIXES) + tuple(f"{p}_" for p in DEFAULT_GENERIC_MAILBOX_PREFIXES)
_KNOWN_READ_SUFFIXES = (".com.read", ".net.read", ".org.read", ".co.read", ".in.read", ".read", ".comread", ".netread", ".orgread", ".coread", ".inread")

def normalize_extracted_email(email: str | None, context: str | None = None) -> str | None:
    """Conservatively remove common SERP/UI extraction artifacts; never invent a mailbox."""
    if not email:
        return None
    value = email.strip().strip(" .,:;|\\\"'")
    if not value:
        return None
    value = re.sub(r"\s+", "", value)
    lower = value.casefold()
    for suffix in _KNOWN_READ_SUFFIXES:
        if lower.endswith(suffix):
            value = value[:-len("read")].rstrip(".")
            break
    if context and value.casefold().startswith("email-"):
        candidate = value[len("email-"):]
        if re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Z]{2,}", candidate, re.I) and re.search(r"\bemail\b", context, re.I):
            value = candidate
    return value if re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Z]{2,}", value, re.I) else None

def is_personal_email(email: str | None, generic_prefixes: set[str] | None = None) -> bool:
    if not email:
        return False
    value = email.strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return False
    local = value.split("@", 1)[0].strip("._-+")
    blocked = {normalize_mailbox_prefix(x) for x in (generic_prefixes if generic_prefixes is not None else DEFAULT_GENERIC_MAILBOX_PREFIXES)}
    return bool(local) and local not in blocked and not any(local.startswith(p + "-") or local.startswith(p + "_") for p in blocked)
