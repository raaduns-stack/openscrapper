from urllib.parse import urlparse

DEFAULT_GENERIC_MAILBOX_PREFIXES = {
    "info", "contact", "sales", "support", "admin", "administrator",
    "accounts", "billing", "careers", "enquiries", "enquiry", "general",
    "hello", "hr", "inquiry", "jobs", "marketing", "media", "office",
    "orders", "press", "recruitment", "service", "team", "webmaster",
    "noreply", "no-reply", "donotreply", "do-not-reply",
}

def normalize_mailbox_prefix(value: str) -> str:
    return value.strip().casefold().strip("._-+")

def normalize_domain(value: str) -> str:
    raw = value.strip().casefold()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else "//" + raw)
    host = (parsed.hostname or "").strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host

def domain_matches(host: str, rule: str) -> bool:
    host, rule = normalize_domain(host), normalize_domain(rule)
    return bool(host and rule and (host == rule or host.endswith("." + rule)))
