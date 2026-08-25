from datetime import datetime

from pydantic import ConfigDict, BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


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
