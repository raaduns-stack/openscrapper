from pydantic import BaseModel, EmailStr, Field, HttpUrl

class Contact(BaseModel):
    person_name: str
    job_title: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    source_url: HttpUrl

class Lead(BaseModel):
    business_name: str
    city: str | None = None
    state: str | None = None
    source_url: HttpUrl
    phone: str | None = None
    website: HttpUrl | None = None
    contacts: list[Contact] = Field(default_factory=list)
