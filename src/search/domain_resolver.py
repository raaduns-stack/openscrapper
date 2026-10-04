from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pymysql


class ExternalDomainResolver:
    """Read-only resolver for domains derived from the external clients database."""

    def __init__(self, *, host, port, database, user, password, limit=25, connect_timeout=5, read_timeout=10):
        self.config = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "connect_timeout": connect_timeout,
            "read_timeout": read_timeout,
            "write_timeout": read_timeout,
            "autocommit": True,
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.Cursor,
        }
        self.limit = max(1, int(limit))
        self._conn = None

    @classmethod
    def from_env(cls):
        password = os.getenv("SCRAPPEE_DOMAIN_DB_PASSWORD", "")
        if not password:
            return None
        return cls(
            host=os.getenv("SCRAPPEE_DOMAIN_DB_HOST", "85.202.160.143"),
            port=int(os.getenv("SCRAPPEE_DOMAIN_DB_PORT", "3306")),
            database=os.getenv("SCRAPPEE_DOMAIN_DB_NAME", "trustedg_alpha-marketing-saas"),
            user=os.getenv("SCRAPPEE_DOMAIN_DB_USER", "trustedg_clawscrapper"),
            password=password,
            limit=int(os.getenv("SCRAPPEE_DOMAIN_DB_LIMIT", "25")),
        )

    def _connection(self):
        if self._conn is None or not self._conn.open:
            self._conn = pymysql.connect(**self.config)
        return self._conn

    @staticmethod
    def _clean_domain(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I) else f"http://{raw}")
        host = (parsed.hostname or "").strip().lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        return host

    def resolve(self, *, industry, geography, role, keyword):
        where = ["website IS NOT NULL", "TRIM(website) <> ''"]
        args = []

        if industry:
            where.append("LOWER(TRIM(industry)) = LOWER(TRIM(%s))")
            args.append(industry)

        if geography:
            geo = str(geography).strip()
            where.append("((LOWER(TRIM(company_country)) = LOWER(TRIM(%s))) OR (LOWER(TRIM(country)) = LOWER(TRIM(%s))))")
            args.extend([geo, geo])

        if role:
            where.append("LOWER(COALESCE(title, '')) LIKE LOWER(%s)")
            args.append(f"%{role}%")

        if keyword:
            where.append("LOWER(COALESCE(keywords, '')) LIKE LOWER(%s)")
            args.append(f"%{keyword}%")

        sql = "SELECT website FROM clients WHERE " + " AND ".join(where) + " ORDER BY id DESC LIMIT %s"
        args.append(self.limit)

        try:
            with self._connection().cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
        except Exception:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            raise

        domains = []
        seen = set()
        for (website,) in rows:
            domain = self._clean_domain(website)
            if domain and domain not in seen:
                seen.add(domain)
                domains.append(domain)
        return domains
