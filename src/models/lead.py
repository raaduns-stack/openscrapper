from pydantic import BaseModel, EmailStr, Field, HttpUrl, ValidationInfo, model_validator

from src.extract.email import is_personal_email


class Lead(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    position: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=150)
    state: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    phone: str | None = None
    website: HttpUrl | None = None
    source_url: HttpUrl

    @model_validator(mode="after")
    def validate_contact_acceptance(self, info: ValidationInfo):
        prefixes = info.context.get("generic_prefixes") if isinstance(info.context, dict) else None
        if not self.email or not is_personal_email(str(self.email), prefixes):
            raise ValueError("accepted lead requires a personal email")
        return self
