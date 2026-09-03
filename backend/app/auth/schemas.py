from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.config import get_settings


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _reject_undeliverable_domains(cls, value: str) -> str:
        """EmailStr above only checks *format* -- "aaa@totally-fake-domain-
        that-does-not-exist.example" sails straight through it untouched,
        confirmed live: any syntactically-shaped address is accepted
        regardless of whether its domain could ever receive mail. A real
        MX-record lookup (email-validator's own deliverability check --
        already a transitive dependency of pydantic's EmailStr, no new
        package needed) catches that class of junk address synchronously,
        in well under a second, with no confirmation-email round trip.

        Deliberately gated to production only: the lookup is a real DNS
        call, which would make every local/CI signup test dependent on
        live network access and a real-world domain's MX records staying
        exactly as they are today. Tests already register against the
        reserved, deliberately mail-less "@example.com" domain (see
        tests/conftest.py's fake_user and test_auth.py's _unique_email) --
        production is the only place a fake signup actually costs
        anything, so it's the only place this runs.
        """
        settings = get_settings()
        if settings.environment != "production":
            return value
        try:
            validate_email(value, check_deliverability=True)
        except EmailNotValidError as exc:
            raise ValueError("This email address doesn't look reachable -- double-check it and try again.") from exc
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    currency: str
    decimal_places: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


SUPPORTED_CURRENCIES = {"NGN", "USD", "EUR", "GBP", "JPY", "INR", "CAD", "AUD"}


class UserSettingsUpdate(BaseModel):
    currency: str | None = Field(default=None)
    decimal_places: int | None = Field(default=None, ge=0, le=4)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
