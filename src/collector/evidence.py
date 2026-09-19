from src.models.evidence import PageEvidence


class Evidence(PageEvidence):
    """Compatibility facade over the canonical V1.2 PageEvidence model."""

    def __init__(self, **data):
        if "source_url" not in data and "url" in data:
            data["source_url"] = data.pop("url")
        super().__init__(**data)

    @property
    def url(self) -> str:
        return str(self.source_url)

    @property
    def usable(self) -> bool:
        return self.status < 400 and bool(self.html.strip() or self.text.strip() or self.content.strip())
