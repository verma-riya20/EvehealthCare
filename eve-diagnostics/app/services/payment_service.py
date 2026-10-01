import logging
import random
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import commit_or_conflict
from app.errors import AppError
from app.models import Booking, BookingStatus, Payment, PaymentStatus, User, WebhookEvent
from app.schemas import WebhookPayload
from app.services.booking_service import get_booking_for_user, transition

logger = logging.getLogger(__name__)


def _decide_outcome(simulate: str | None) -> PaymentStatus:
    if simulate:
        return PaymentStatus(simulate)
    ok = random.random() < settings.payment_success_rate
    return PaymentStatus.SUCCESS if ok else PaymentStatus.FAILED


def settle_payment(payment: Payment, booking: Booking, new_status: PaymentStatus) -> str:
    """Single place where a payment result is applied to the payment AND its booking.

    Used by both the mock payment endpoint and the webhook, so the rules cannot drift apart.
    Returns "applied", "no_change" or "ignored".
    """
    if payment.status == new_status:
        return "no_change"
    if payment.status != PaymentStatus.PENDING:
        # SUCCESS/FAILED are final: a late or out-of-order event must not flip them.
        logger.warning(
            "payment_event_ignored",
            extra={"payment_id": payment.id, "current": payment.status.value, "event": new_status.value},
        )
        return "ignored"

    payment.status = new_status
    if new_status == PaymentStatus.SUCCESS:
        if booking.status in (BookingStatus.PENDING, BookingStatus.FAILED):
            transition(booking, BookingStatus.CONFIRMED)
        else:
            # e.g. user cancelled while the payment was in flight -> needs a refund (out of scope)
            logger.warning(
                "payment_succeeded_for_unpayable_booking",
                extra={"payment_id": payment.id, "booking_id": booking.id, "booking_status": booking.status.value},
            )
    elif booking.status == BookingStatus.PENDING:
        transition(booking, BookingStatus.FAILED)

    logger.info(
        "payment_settled",
        extra={"payment_id": payment.id, "booking_id": booking.id, "status": new_status.value},
    )
    return "applied"


def create_payment(
    db: Session, user: User, booking_id: int, simulate: str | None, idempotency_key: str | None
) -> tuple[Payment, bool]:
    """Simulate a payment. Returns (payment, created); created=False means an idempotent replay."""
    booking = get_booking_for_user(db, booking_id, user, for_update=True)  # row lock

    if idempotency_key:
        existing = db.scalar(
            select(Payment).where(
                Payment.booking_id == booking.id, Payment.idempotency_key == idempotency_key
            )
        )
        if existing:
            return existing, False

    if booking.status == BookingStatus.CONFIRMED:
        raise AppError(409, "booking_already_paid", "This booking is already paid and confirmed")
    if booking.status == BookingStatus.CANCELLED:
        raise AppError(409, "booking_cancelled", "Cancelled bookings cannot be paid")
    if db.scalar(
        select(Payment.id).where(
            Payment.booking_id == booking.id, Payment.status == PaymentStatus.PENDING
        )
    ):
        raise AppError(409, "payment_in_progress", "A payment for this booking is already in progress")

    payment = Payment(
        booking_id=booking.id,
        amount=booking.amount,
        status=PaymentStatus.PENDING,
        provider_reference=f"mockpay_{uuid.uuid4().hex}",
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    try:
        db.flush()
    except IntegrityError as exc:  # lost a race against another payment attempt
        db.rollback()
        raise AppError(409, "payment_conflict", "A payment for this booking already exists") from exc

    outcome = _decide_outcome(simulate)
    if outcome != PaymentStatus.PENDING:
        settle_payment(payment, booking, outcome)
    commit_or_conflict(db, "Could not record payment", "payment_conflict")
    return payment, True


def get_payment_for_user(db: Session, payment_id: int, user: User) -> Payment:
    payment = db.scalar(
        select(Payment).join(Booking).where(Payment.id == payment_id, Booking.user_id == user.id)
    )
    if payment is None:
        raise AppError(404, "payment_not_found", f"Payment {payment_id} not found")
    return payment


def process_webhook(db: Session, event: WebhookPayload, raw_payload: dict) -> str:
    """Idempotent webhook handling.

    1. Insert the event into the ledger first. UNIQUE(event_id) means a replay (even a concurrent
       one) fails here and is answered with "duplicate" - nothing else is touched.
    2. Only then look at the payment, under row locks, and apply the result once.
    Ledger insert + state change share ONE transaction: either both happen or neither does.
    """
    record = WebhookEvent(
        event_id=event.event_id,
        provider_reference=event.provider_reference,
        status=event.status,
        payload=raw_payload,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("webhook_duplicate", extra={"event_id": event.event_id})
        return "duplicate"

    payment = db.scalar(select(Payment).where(Payment.provider_reference == event.provider_reference))
    if payment is None:
        db.rollback()  # drop the ledger row so the provider can retry once the payment exists
        raise AppError(404, "payment_not_found", "Unknown provider_reference")
    if event.amount is not None and event.amount != payment.amount:
        db.rollback()
        raise AppError(409, "amount_mismatch", "Event amount does not match the payment amount")

    # Lock order is always booking -> payment (same as create_payment) to avoid deadlocks.
    booking = db.scalars(
        select(Booking).where(Booking.id == payment.booking_id).with_for_update(of=Booking)
    ).unique().one()
    db.refresh(payment, with_for_update=True)

    result = settle_payment(payment, booking, PaymentStatus(event.status))
    record.result = result
    db.commit()
    logger.info("webhook_processed", extra={"event_id": event.event_id, "result": result})
    return result
