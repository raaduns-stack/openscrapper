"""Legacy compatibility entry point for the V1.2 individual lead extractor.

The old company-first extraction implementation has been removed. New code
must use ``AdaptiveLeadExtractor`` directly; this synchronous adapter exists
only for legacy CLI/tests that still import ``LeadExtractor``.
"""

from __future__ import annotations

import asyncio
import re

from src.extract.adaptive import AdaptiveLeadExtractor
from src.models.lead import Lead


class LeadExtractor:
    """Compatibility wrapper around the canonical V1.2 extractor."""

    def __init__(self, model: str = "openai/gpt-oss-20b"):
        self._extractor = AdaptiveLeadExtractor(model=model)

    def extract(self, html: str, source_url: str) -> list[Lead]:
        self._raise_if_blocked(html, source_url)
        return asyncio.run(self._extractor.extract(html, source_url))

    @staticmethod
    def _raise_if_blocked(html: str, source_url: str) -> None:
        markers = (
            "cloudflare", "you have been blocked", "attention required",
            "performing security verification", "security service to protect against malicious bots",
            "unusual traffic from your computer network", "recaptcha", "i'm not a robot",
        )
        value = re.sub(r"\s+", " ", html or "").lower()
        if any(marker in value for marker in markers):
            raise RuntimeError(f"Target blocked by security layer: {source_url}")
