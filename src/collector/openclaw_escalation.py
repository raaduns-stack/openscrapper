import hashlib
import time

from src.browser.openclaw import OpenClawBrowser
from src.collector.evidence import Evidence


class OpenClawEscalation:
    """Bounded browser escalation for pages requiring real interaction."""

    def __init__(self, browser: OpenClawBrowser | None = None):
        self.browser = browser or OpenClawBrowser()

    def collect(self, url: str) -> Evidence:
        self.browser.navigate(url)
        return Evidence(
            source_url=self.browser.current_url(),
            html=self.browser.html(),
            text=self.browser.text(),
            status=200,
            rendered=True,
            source="openclaw",
        )

    def paginate(self, url: str, max_pages: int = 3) -> list[Evidence]:
        """Interact with a dynamic Next/Load More control with a hard bound."""
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        self.browser.navigate(url)
        pages: list[Evidence] = []
        seen: set[str] = set()
        for _ in range(max_pages):
            current_url = self.browser.current_url()
            html = self.browser.html()
            text = self.browser.text()
            fingerprint = hashlib.sha256(
                (current_url + "\0" + html + "\0" + text).encode("utf-8", "ignore")
            ).hexdigest()
            if fingerprint in seen:
                break
            seen.add(fingerprint)
            pages.append(Evidence(
                source_url=current_url, html=html, text=text,
                status=200, rendered=True, source="openclaw"
            ))
            clicked = self.browser.evaluate("""() => {
                const nodes = [...document.querySelectorAll('button,a')];
                const node = nodes.find(n => /load more|show more|next page|next results/i.test(
                    `${n.innerText || ''} ${n.getAttribute('aria-label') || ''}`));
                if (!node || node.hasAttribute('disabled')) return false;
                node.click(); return true;
            }""")
            if clicked is not True:
                break
            time.sleep(1)
        return pages
