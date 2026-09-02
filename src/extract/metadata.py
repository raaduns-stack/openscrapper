import extruct
from w3lib.html import get_base_url


class MetadataExtractor:
    def extract(self, html: str, source_url: str) -> dict[str, list]:
        return extruct.extract(
            html,
            base_url=get_base_url(html, source_url),
            syntaxes=["json-ld", "microdata", "opengraph", "rdfa", "microformat"],
            uniform=True,
        )
