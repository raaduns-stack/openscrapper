from typing import Literal
from pydantic import BaseModel, Field, field_validator

class SearchCriteria(BaseModel):
    industry: str = Field(min_length=1)
    product: str | None = None
    geography: str | None = None
    target_type: Literal["people", "companies", "both"] = "people"
    roles: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    max_leads: int = Field(default=100, ge=1, le=10000)

    @field_validator("industry", "product", "geography", mode="before")
    @classmethod
    def clean_text(cls, value):
        if value is None:
            return value
        value = str(value).strip()
        return value or None

    @field_validator("roles", "keywords", mode="before")
    @classmethod
    def clean_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()]
