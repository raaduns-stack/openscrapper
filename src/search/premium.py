import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse, urlencode

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.fernet import Fernet


SUPPORTED_PROVIDERS = ("serper", "dataforseo", "serpapi", "brightdata")


@dataclass(frozen=True)
class PremiumSerpItem:
    url: str
    title: str = ""
    snippet: str = ""
    page_url: str | None = None


class PremiumSerpProvider(Protocol):
    def search(self, search_url: str, *, limit: int, page: int = 1) -> list[PremiumSerpItem]: ...


def parse_search_url(search_url: str) -> tuple[str, str]:
    parsed = urlparse(search_url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https":
        raise ValueError("Search URL must use HTTPS")
    if host == "google.com" or host.endswith(".google.com"):
        provider = "google"
    elif host == "bing.com" or host.endswith(".bing.com"):
        provider = "bing"
    else:
        raise ValueError("Only Google or Bing search URLs are supported")
    if parsed.path.rstrip("/") != "/search":
        raise ValueError("URL must be a Google or Bing /search URL")
    query = parse_qs(parsed.query).get("q", [""])[0].strip()
    if not query:
        raise ValueError("Search URL must contain a q query parameter")
    return provider, query


def _fernet() -> Fernet:
    key = os.getenv("PREMIUM_PROVIDER_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("Premium provider encryption key is not configured")
    return Fernet(key.encode())


def encrypt_credentials(credentials: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    return json.loads(_fernet().decrypt(value.encode()).decode())


def provider_statuses() -> list[dict[str, Any]]:
    from src.db import db
    with db() as conn:
        rows = conn.execute("SELECT provider,enabled,is_default,credentials,settings,updated_at FROM premium_provider_configs ORDER BY provider").fetchall()
    return [{"provider": r[0], "enabled": bool(r[1]), "is_default": bool(r[2]), "configured": bool(r[3]), "settings": r[4] or {}, "updated_at": r[5].isoformat()} for r in rows]


def _load_config(provider: str | None = None) -> tuple[str, dict[str, str], dict[str, Any]]:
    from src.db import db
    with db() as conn:
        if provider is None:
            row = conn.execute("SELECT provider,credentials,settings FROM premium_provider_configs WHERE enabled=true AND is_default=true LIMIT 1").fetchone()
        else:
            row = conn.execute("SELECT provider,credentials,settings FROM premium_provider_configs WHERE provider=%s AND enabled=true", (provider,)).fetchone()
    if not row:
        raise RuntimeError("No enabled default Premium SERP provider is configured") if provider is None else RuntimeError(f"Premium SERP provider '{provider}' is disabled or not configured")
    return row[0], decrypt_credentials(row[1]), row[2] or {}


def save_provider_config(provider: str, credentials: dict[str, str], settings: dict[str, Any], enabled: bool, make_default: bool) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported Premium SERP provider")
    from src.db import db
    with db() as conn:
        current = conn.execute("SELECT credentials FROM premium_provider_configs WHERE provider=%s", (provider,)).fetchone()
        merged = decrypt_credentials(current[0]) if current and current[0] else {}
        merged.update({k: v for k, v in credentials.items() if str(v).strip()})
        if make_default:
            if not enabled:
                raise ValueError("Default provider must be enabled")
            conn.execute("UPDATE premium_provider_configs SET is_default=false WHERE provider<>%s", (provider,))
        conn.execute("UPDATE premium_provider_configs SET enabled=%s,is_default=%s,credentials=%s,settings=%s,updated_at=now() WHERE provider=%s", (enabled, make_default, encrypt_credentials(merged) if merged else None, json.dumps(settings), provider))
        if not make_default:
            current = conn.execute("SELECT count(*) FROM premium_provider_configs WHERE is_default=true AND enabled=true").fetchone()[0]
            if current == 0:
                conn.execute("UPDATE premium_provider_configs SET is_default=true WHERE provider=%s AND enabled=true", (provider,))
        conn.commit()


class SerperPremiumSerpProvider:
    def __init__(self, credentials: dict[str, str], settings: dict[str, Any]) -> None:
        self.api_key = credentials.get("api_key", "").strip()
        self.endpoint = str(settings.get("endpoint", "https://google.serper.dev/search")).rstrip("/")
        self.timeout = min(float(settings.get("timeout", 30)), 20.0)
        self.gl = str(settings.get("gl", "")).strip()
        self.hl = str(settings.get("hl", "")).strip()

    def search(self, search_url: str, *, limit: int, page: int = 1) -> list[PremiumSerpItem]:
        if not self.api_key:
            raise RuntimeError("Serper credentials are not configured")
        engine, query = parse_search_url(search_url)
        if engine != "google":
            raise RuntimeError("Serper supports Google search URLs only")
        parsed = urlparse(search_url)
        params = parse_qs(parsed.query)
        page_size = min(max(int(limit), 1), 100)
        payload: dict[str, Any] = {"q": query, "num": page_size, "page": max(int(page), 1)}
        for source_key, target_key in (("gl", "gl"), ("hl", "hl")):
            if source_key in params and params[source_key]:
                payload[target_key] = params[source_key][0]
        if "page" in params and params["page"] and params["page"][0].isdigit():
            payload["page"] = max(int(params["page"][0]), 1) + max(int(page), 1) - 1
        if self.gl and "gl" not in payload:
            payload["gl"] = self.gl
        if self.hl and "hl" not in payload:
            payload["hl"] = self.hl
        response = requests.post(self.endpoint, json=payload, headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"Serper request failed: {data['error']}")
        rows = data.get("organic") or []
        return [PremiumSerpItem(str(r.get("link", "")).strip(), str(r.get("title", ""))[:1000], str(r.get("snippet", ""))[:5000], search_url) for r in rows if isinstance(r, dict) and str(r.get("link", "")).strip()][:limit]


class DataForSeoPremiumSerpProvider:
    def __init__(self, credentials: dict[str, str], settings: dict[str, Any]) -> None:
        self.login = credentials.get("login", "").strip()
        self.password = credentials.get("password", "").strip()
        self.base_url = str(settings.get("base_url", "https://api.dataforseo.com")).rstrip("/")
        self.location_code = int(settings.get("location_code", 2840))
        self.language_code = str(settings.get("language_code", "en"))
        self.timeout = float(settings.get("timeout", 30))

    def search(self, search_url: str, *, limit: int, page: int = 1) -> list[PremiumSerpItem]:
        if not self.login or not self.password:
            raise RuntimeError("DataForSEO credentials are not configured")
        provider, query = parse_search_url(search_url)
        engine = "google" if provider == "google" else "bing"
        depth = min(max(int(limit), 1), 200)
        pages = min(max((int(limit) + 9) // 10, 1), 100)
        endpoint = f"{self.base_url}/v3/serp/{engine}/organic/live/advanced"
        auth = base64.b64encode(f"{self.login}:{self.password}".encode()).decode()
        payload = [{"keyword": query, "location_code": self.location_code, "language_code": self.language_code, "depth": depth, "max_crawl_pages": pages, "device": "desktop"}]
        response = requests.post(endpoint, json=payload, headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"}, timeout=self.timeout)
        response.raise_for_status()
        data: Any = response.json()
        if not isinstance(data, dict) or data.get("status_code") != 20000:
            raise RuntimeError(f"DataForSEO request failed: {(data or {}).get('status_message', 'invalid response')}")
        tasks = data.get("tasks") or []
        task = tasks[0] if tasks and isinstance(tasks[0], dict) else {}
        if int(task.get("status_code", 0)) != 20000:
            raise RuntimeError(f"DataForSEO task failed: {task.get('status_message', 'unknown error')}")
        result = task.get("result") or []
        rows = result[0].get("items", []) if result and isinstance(result[0], dict) else []
        return [PremiumSerpItem(str(r["url"]).strip(), str(r.get("title", ""))[:1000], str(r.get("description", ""))[:5000], search_url) for r in rows if isinstance(r, dict) and r.get("type") == "organic" and str(r.get("url", "")).strip()][:limit]


class SerpApiPremiumSerpProvider:
    def __init__(self, credentials: dict[str, str], settings: dict[str, Any]) -> None:
        self.api_key = credentials.get("api_key", "").strip()
        self.endpoint = str(settings.get("endpoint", "https://serpapi.com/search")).rstrip("/")
        self.timeout = float(settings.get("timeout", 30))

    def search(self, search_url: str, *, limit: int, page: int = 1) -> list[PremiumSerpItem]:
        if not self.api_key:
            raise RuntimeError("SerpApi credentials are not configured")
        engine, query = parse_search_url(search_url)
        parsed = urlparse(search_url)
        source = parse_qs(parsed.query)
        params = {k: v[0] for k, v in source.items() if k not in {"q", "api_key", "engine", "start", "num", "page"}}
        page_size = min(max(int(limit), 1), 10)
        base_start = int(source.get("start", ["0"])[0]) if source.get("start", ["0"])[0].isdigit() else 0
        params.update({"engine": engine, "q": query, "api_key": self.api_key, "output": "json", "start": base_start + max(int(page) - 1, 0) * page_size, "num": page_size})
        response = requests.get(self.endpoint, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"SerpApi request failed: {data['error']}")
        rows = data.get("organic_results") or []
        return [PremiumSerpItem(str(r.get("link", "")).strip(), str(r.get("title", ""))[:1000], str(r.get("snippet", ""))[:5000], search_url) for r in rows if isinstance(r, dict) and str(r.get("link", "")).strip()][:limit]


class BrightDataPremiumSerpProvider:
    def __init__(self, credentials: dict[str, str], settings: dict[str, Any]) -> None:
        self.api_key = credentials.get("api_key", "").strip()
        self.endpoint = str(settings.get("endpoint", "https://api.brightdata.com/request"))
        self.zone = str(settings.get("zone", "serp_api1"))
        self.country = str(settings.get("country", ""))
        self.timeout = float(settings.get("timeout", 30))

    def search(self, search_url: str, *, limit: int, page: int = 1) -> list[PremiumSerpItem]:
        if not self.api_key:
            raise RuntimeError("Bright Data credentials are not configured")
        engine, _ = parse_search_url(search_url)
        parsed = urlparse(search_url)
        params = parse_qs(parsed.query)
        page_size = min(max(int(limit), 1), 100)
        if engine == "google":
            params["start"] = [str(max(int(page) - 1, 0) * page_size)]
        else:
            params["first"] = [str(max(int(page) - 1, 0) * page_size + 1)]
        paged_url = parsed._replace(query=urlencode(params, doseq=True)).geturl()
        body = {"zone": self.zone, "url": paged_url, "format": "json", "method": "GET"}
        if self.country:
            body["country"] = self.country
        response = requests.post(self.endpoint, json=body, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        rows = data.get("organic") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("Bright Data returned no structured organic results")
        return [PremiumSerpItem(str(r.get("link", "")).strip(), str(r.get("title", ""))[:1000], str(r.get("description", r.get("snippet", "")))[:5000], search_url) for r in rows if isinstance(r, dict) and str(r.get("link", "")).strip()][:limit]


class HttpPremiumSerpProvider:
    def _provider(self):
        provider, credentials, settings = _load_config()
        if provider == "serper":
            return provider, SerperPremiumSerpProvider(credentials, settings)
        if provider == "dataforseo":
            return provider, DataForSeoPremiumSerpProvider(credentials, settings)
        if provider == "serpapi":
            return provider, SerpApiPremiumSerpProvider(credentials, settings)
        if provider == "brightdata":
            return provider, BrightDataPremiumSerpProvider(credentials, settings)
        raise RuntimeError(f"Unsupported configured Premium SERP provider: {provider}")

    def search(self, search_url: str, *, limit: int) -> list[PremiumSerpItem]:
        _, provider = self._provider()
        return provider.search(search_url, limit=limit, page=1)

    def search_all(self, search_url: str, *, limit: int) -> list[PremiumSerpItem]:
        provider_name, provider = self._provider()
        if limit <= 0:
            return []
        if provider_name == "dataforseo":
            return provider.search(search_url, limit=limit, page=1)[:limit]

        page_size = 100 if provider_name in {"serper", "brightdata"} else 10
        max_pages = min((limit + page_size - 1) // page_size, 100)
        batch_width = min(max_pages, 5)

        def fetch(page: int) -> tuple[int, list[PremiumSerpItem]]:
            request_limit = min(page_size, limit - (page - 1) * page_size)
            return page, provider.search(search_url, limit=request_limit, page=page)

        collected: list[PremiumSerpItem] = []
        next_page = 1
        while next_page <= max_pages and len(collected) < limit:
            end_page = min(next_page + batch_width - 1, max_pages)
            with ThreadPoolExecutor(max_workers=end_page - next_page + 1, thread_name_prefix="premium-serp") as pool:
                futures = [pool.submit(fetch, page) for page in range(next_page, end_page + 1)]
                batches = dict(future.result() for future in as_completed(futures))
            stop_page = None
            for page in range(next_page, end_page + 1):
                batch = batches.get(page, [])
                collected.extend(item for item in batch if item.url)
                if not batch:
                    stop_page = page
                    break
                if len(collected) >= limit:
                    break
            if stop_page is not None:
                break
            next_page = end_page + 1
        return collected[:limit]
