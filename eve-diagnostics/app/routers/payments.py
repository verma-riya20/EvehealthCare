import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from pydantic import ValidationError

from app.deps import CurrentUser, DbSession
from app.errors import AppError, simplify_validation_errors
from app.schemas import PaymentCreate, PaymentOut, WebhookPayload, WebhookResponse
from app.security import verify_signature
from app.services import payment_service as svc

router = APIRouter(prefix="/payments", tags=["Payments"])


async def raw_body(request: Request) -> bytes:
    """The signature is computed over the exact bytes received, so read them untouched."""
    return await request.body()


@router.post(
    "/", response_model=PaymentOut, status_code=201,
    summary="Simulate a payment for a booking (mock gateway)",
    responses={200: {"description": "Idempotent replay of an earlier request with the same Idempotency-Key"}},
)
def create_payment(
    body: PaymentCreate,
    response: Response,
    db: DbSession,
    user: CurrentUser,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
):
    payment, created = svc.create_payment(db, user, body.booking_id, body.simulate, idempotency_key)
    if not created:
        response.status_code = 200
    return payment


@router.post(
    "/webhook/", response_model=WebhookResponse,
    summary="Payment-status webhook from the (simulated) provider - idempotent",
    description="Send header `X-Signature`: hex HMAC-SHA256 of the raw request body using WEBHOOK_SECRET. "
    "Replays of the same `event_id` are acknowledged with `duplicate` and change nothing.",
)
def payment_webhook(
    raw: Annotated[bytes, Depends(raw_body)],
    db: DbSession,
    x_signature: Annotated[str | None, Header()] = None,
):
    if not x_signature or not verify_signature(raw, x_signature):
        raise AppError(401, "invalid_signature", "Missing or invalid X-Signature header")
    try:
        event = WebhookPayload.model_validate_json(raw)
    except ValidationError as exc:
        raise AppError(422, "invalid_payload", "Invalid webhook payload",
                       details=simplify_validation_errors(exc.errors())) from exc

    result = svc.process_webhook(db, event, json.loads(raw))
    return WebhookResponse(event_id=event.event_id, result=result)


@router.get("/{payment_id}", response_model=PaymentOut, summary="Get one of my payments")
def get_payment(payment_id: Annotated[int, Path(gt=0)], db: DbSession, user: CurrentUser):
    return svc.get_payment_for_user(db, payment_id, user)
