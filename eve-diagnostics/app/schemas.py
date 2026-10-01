from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from app.models import BookingStatus, PaymentStatus

T = TypeVar("T")

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Money = Annotated[
    Decimal,
    Field(gt=0, max_digits=10, decimal_places=2),
    AfterValidator(lambda v: v.quantize(Decimal("0.01"))),  # always store/return 2 dp
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------- auth ----------
class SignupRequest(BaseModel):
    email: EmailStr
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def strong_enough(cls, v: str) -> str:
        if len(v.encode()) > 72:  # bcrypt only uses the first 72 bytes
            raise ValueError("password must be at most 72 bytes")
        if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError("password must contain at least one letter and one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the token expires")


class UserOut(ORMModel):
    id: int
    email: EmailStr
    full_name: str
    is_admin: bool
    created_at: datetime


# ---------- catalogue ----------
class DiagnosticTestCreate(BaseModel):
    name: Name
    description: str | None = Field(default=None, max_length=1000)


class DiagnosticTestOut(ORMModel):
    id: int
    name: str
    description: str | None


class CentreCreate(BaseModel):
    name: Name
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    address: str | None = Field(default=None, max_length=255)


class CentreOut(ORMModel):
    id: int
    name: str
    location: str
    address: str | None


class CentreTestAttach(BaseModel):
    test_id: int = Field(gt=0)
    price: Money


class CentreTestUpdate(BaseModel):
    price: Money


class CentreTestOut(ORMModel):
    test_id: int
    name: str
    description: str | None
    price: Decimal


class CentreDetail(CentreOut):
    tests: list[CentreTestOut]


# ---------- bookings ----------
class BookingCreate(BaseModel):
    centre_id: int = Field(gt=0)
    test_id: int = Field(gt=0)
    appointment_at: AwareDatetime = Field(description="ISO-8601 with timezone, must be in the future")

    @field_validator("appointment_at")
    @classmethod
    def to_utc(cls, v: datetime) -> datetime:
        return v.astimezone(timezone.utc)


class BookingOut(ORMModel):
    id: int
    user_id: int
    centre: CentreOut
    test: DiagnosticTestOut
    appointment_at: datetime
    amount: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime


# ---------- payments ----------
class PaymentCreate(BaseModel):
    booking_id: int = Field(gt=0)
    simulate: Literal["SUCCESS", "FAILED", "PENDING"] | None = Field(
        default=None,
        description=(
            "Mock-only switch to force an outcome. Omit for a random result "
            "(PAYMENT_SUCCESS_RATE). PENDING leaves the payment open so it can be settled "
            "via POST /payments/webhook/."
        ),
    )


class PaymentOut(ORMModel):
    id: int
    booking_id: int
    amount: Decimal
    status: PaymentStatus
    provider_reference: str
    booking_status: BookingStatus
    created_at: datetime


class WebhookPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=128, description="Unique per provider event")
    provider_reference: str = Field(min_length=1, max_length=64)
    status: Literal["SUCCESS", "FAILED"]
    amount: Money | None = None


class WebhookResponse(BaseModel):
    event_id: str
    result: Literal["applied", "no_change", "ignored", "duplicate"]
