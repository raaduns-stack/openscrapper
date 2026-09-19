import re
from src.policy import DEFAULT_GENERIC_MAILBOX_PREFIXES, normalize_mailbox_prefix

_GENERIC_LOCAL_PARTS = set(DEFAULT_GENERIC_MAILBOX_PREFIXES)
_GENERIC_PREFIXES = tuple(f"{p}-" for p in DEFAULT_GENERIC_MAILBOX_PREFIXES) + tuple(f"{p}_" for p in DEFAULT_GENERIC_MAILBOX_PREFIXES)

def is_personal_email(email: str | None, generic_prefixes: set[str] | None = None) -> bool:
    if not email:
        return False
    value = email.strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return False
    local = value.split("@", 1)[0].strip("._-+")
    blocked = {normalize_mailbox_prefix(x) for x in (generic_prefixes if generic_prefixes is not None else DEFAULT_GENERIC_MAILBOX_PREFIXES)}
    return bool(local) and local not in blocked and not any(local.startswith(p + "-") or local.startswith(p + "_") for p in blocked)
