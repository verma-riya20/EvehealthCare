import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


def _status_enum(enum_cls: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR (not a native PG enum) so adding a state never needs a risky migration.
    return Enum(enum_cls, native_enum=False, length=20)


# Partial-index predicates (supported by PostgreSQL and SQLite).
_ACTIVE_BOOKING = text("status IN ('PENDING', 'CONFIRMED')")
_ACTIVE_PAYMENT = text("status IN ('PENDING', 'SUCCESS')")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiagnosticTest(Base):
    """Catalogue entry, e.g. 'Complete Blood Count'. Price lives on CentreTest."""

    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Centre(Base):
    __tablename__ = "centres"
    __table_args__ = (UniqueConstraint("name", "location", name="uq_centre_name_location"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    location: Mapped[str] = mapped_column(String(120), index=True)
    address: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    offerings: Mapped[list["CentreTest"]] = relationship(
        back_populates="centre",
        cascade="all, delete-orphan",
        order_by="CentreTest.id",
        lazy="selectin",
    )

    @property
    def tests(self) -> list["CentreTest"]:
        return self.offerings


class CentreTest(Base):
    """A test offered by a centre, at that centre's price (many-to-many with payload)."""

    __tablename__ = "centre_tests"
    __table_args__ = (UniqueConstraint("centre_id", "test_id", name="uq_centre_test"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id", ondelete="CASCADE"), index=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id", ondelete="RESTRICT"))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    centre: Mapped[Centre] = relationship(back_populates="offerings")
    test: Mapped[DiagnosticTest] = relationship(lazy="joined")

    @property
    def name(self) -> str:
        return self.test.name

    @property
    def description(self) -> str | None:
        return self.test.description


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # A booking can only reference a test the centre actually offers.
        ForeignKeyConstraint(
            ["centre_id", "test_id"],
            ["centre_tests.centre_id", "centre_tests.test_id"],
            ondelete="RESTRICT",
            name="fk_booking_centre_offers_test",
        ),
        Index("ix_bookings_user_created", "user_id", "created_at"),
        # Same user cannot hold two live bookings for the same test/centre/time (double-click safe).
        Index(
            "uq_booking_active_slot",
            "user_id",
            "centre_id",
            "test_id",
            "appointment_at",
            unique=True,
            postgresql_where=_ACTIVE_BOOKING,
            sqlite_where=_ACTIVE_BOOKING,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    centre_id: Mapped[int] = mapped_column(ForeignKey("centres.id", ondelete="RESTRICT"))
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id", ondelete="RESTRICT"))
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Price snapshot: later price changes must not rewrite history.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[BookingStatus] = mapped_column(
        _status_enum(BookingStatus), default=BookingStatus.PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    centre: Mapped[Centre] = relationship(lazy="joined", innerjoin=True)
    test: Mapped[DiagnosticTest] = relationship(lazy="joined", innerjoin=True)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("booking_id", "idempotency_key", name="uq_payment_idempotency"),
        # DB-level guarantee: at most ONE pending-or-successful payment per booking.
        # Even if two requests race past the application checks, the second one fails.
        Index(
            "uq_payment_one_active_per_booking",
            "booking_id",
            unique=True,
            postgresql_where=_ACTIVE_PAYMENT,
            sqlite_where=_ACTIVE_PAYMENT,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[PaymentStatus] = mapped_column(
        _status_enum(PaymentStatus), default=PaymentStatus.PENDING, index=True
    )
    provider_reference: Mapped[str] = mapped_column(String(64), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    booking: Mapped[Booking] = relationship()

    @property
    def booking_status(self) -> BookingStatus:
        return self.booking.status


class WebhookEvent(Base):
    """Ledger of processed webhook events. UNIQUE(event_id) is what makes the webhook idempotent."""

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    provider_reference: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[str | None] = mapped_column(String(20))  # applied / no_change / ignored
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
