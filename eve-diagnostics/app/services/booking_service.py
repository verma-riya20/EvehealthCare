import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import commit_or_conflict
from app.errors import AppError
from app.models import Booking, BookingStatus, CentreTest, User
from app.pagination import PageParams, paginate
from app.schemas import BookingCreate, BookingOut

logger = logging.getLogger(__name__)

# Booking state machine. Anything not listed here is rejected with 409.
ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING: {BookingStatus.CONFIRMED, BookingStatus.FAILED, BookingStatus.CANCELLED},
    BookingStatus.FAILED: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},  # FAILED -> retry payment
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
}


def transition(booking: Booking, new_status: BookingStatus) -> None:
    if new_status not in ALLOWED_TRANSITIONS[booking.status]:
        raise AppError(
            409,
            "invalid_state_transition",
            f"Booking is {booking.status.value}; cannot move to {new_status.value}",
        )
    logger.info(
        "booking_transition",
        extra={"booking_id": booking.id, "from": booking.status.value, "to": new_status.value},
    )
    booking.status = new_status


def create_booking(db: Session, user: User, data: BookingCreate) -> Booking:
    if data.appointment_at <= datetime.now(timezone.utc):
        raise AppError(422, "appointment_in_past", "Appointment time must be in the future")

    offering = db.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == data.centre_id, CentreTest.test_id == data.test_id
        )
    )
    if offering is None:
        raise AppError(404, "test_not_offered", "Centre not found or it does not offer this test")

    booking = Booking(
        user_id=user.id,
        centre_id=data.centre_id,
        test_id=data.test_id,
        appointment_at=data.appointment_at,
        amount=offering.price,  # snapshot the price at booking time
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    commit_or_conflict(
        db,
        "You already have an active booking for this test, centre and time",
        "duplicate_booking",
    )
    logger.info("booking_created", extra={"booking_id": booking.id, "user_id": user.id})
    return booking


def get_booking_for_user(
    db: Session, booking_id: int, user: User, *, for_update: bool = False
) -> Booking:
    """Fetch a booking owned by `user`.

    Someone else's booking returns 404 (not 403) so IDs cannot be probed.
    `for_update` takes a row lock so concurrent payment/cancel calls are serialised.
    """
    stmt = select(Booking).where(Booking.id == booking_id, Booking.user_id == user.id)
    if for_update:
        stmt = stmt.with_for_update(of=Booking)
    booking = db.scalars(stmt).unique().first()
    if booking is None:
        raise AppError(404, "booking_not_found", f"Booking {booking_id} not found")
    return booking


def list_bookings(db: Session, user: User, status: BookingStatus | None, page: PageParams):
    stmt = select(Booking).where(Booking.user_id == user.id)
    if status:
        stmt = stmt.where(Booking.status == status)
    stmt = stmt.order_by(Booking.created_at.desc(), Booking.id.desc())
    return paginate(db, stmt, BookingOut, page)


def cancel_booking(db: Session, user: User, booking_id: int) -> Booking:
    booking = get_booking_for_user(db, booking_id, user, for_update=True)
    transition(booking, BookingStatus.CANCELLED)
    db.commit()
    return booking
