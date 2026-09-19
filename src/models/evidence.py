from pydantic import BaseModel, Field, HttpUrl


class FieldEvidence(BaseModel):
    field: str
    value: str
    source_url: HttpUrl
    excerpt: str = ""
    method: str = "deterministic"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PageEvidence(BaseModel):
    source_url: HttpUrl
    html: str = ""
    text: str = ""
    content: str = ""
    status: int = 200
    rendered: bool = False
    source: str = "scrapy"
    fields: list[FieldEvidence] = Field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.status < 400 and bool(
            self.html.strip() or self.text.strip() or self.content.strip()
        )
