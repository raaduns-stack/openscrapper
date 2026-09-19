from typing import Literal
from pydantic import BaseModel, Field, field_validator


class CrawlerConfig(BaseModel):
    """User-configurable search and crawling safety limits."""

    max_queries: int = Field(default=20, ge=1, le=500)
    provider_failure_limit: int = Field(default=2, ge=1, le=20)
    url_validity_checks: bool = True
    max_crawl_pages: int | None = Field(default=None, ge=1, le=10000)
    max_crawl_urls: int | None = Field(default=None, ge=1, le=100000)
    max_crawl_depth: int | None = Field(default=None, ge=0, le=100)
    max_pagination_pages: int | None = Field(default=None, ge=1, le=1000)
    max_duration_hours: int = Field(default=48, ge=1, le=720)
    duplicate_exhaustion_enabled: bool = True
    duplicate_exhaustion_threshold: int = Field(default=3, ge=1, le=100)


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
