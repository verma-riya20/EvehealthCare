from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Payment, WebhookEvent


def count(model) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def event(payment, status="SUCCESS", event_id="evt_1", **extra):
    return {"event_id": event_id, "provider_reference": payment["provider_reference"], "status": status, **extra}


def pending_payment(client, user_h, make_booking, pay):
    b = make_booking(user_h)
    p = pay(user_h, b["id"], "PENDING").json()
    return b, p


def booking_status(client, headers, booking_id):
    return client.get(f"/bookings/{booking_id}", headers=headers).json()["status"]


def test_webhook_settles_pending_payment(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    r = webhook(event(p))
    assert r.status_code == 200 and r.json() == {"event_id": "evt_1", "result": "applied"}
    assert client.get(f"/payments/{p['id']}", headers=user_h).json()["status"] == "SUCCESS"
    assert booking_status(client, user_h, b["id"]) == "CONFIRMED"


def test_webhook_failed_event_fails_booking(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    assert webhook(event(p, "FAILED")).json()["result"] == "applied"
    assert booking_status(client, user_h, b["id"]) == "FAILED"


def test_replayed_event_is_idempotent(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    results = [webhook(event(p)).json()["result"] for _ in range(5)]
    assert results == ["applied", "duplicate", "duplicate", "duplicate", "duplicate"]
    assert count(Payment) == 1 and count(WebhookEvent) == 1  # nothing duplicated
    assert booking_status(client, user_h, b["id"]) == "CONFIRMED"


def test_same_status_with_new_event_id_changes_nothing(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    webhook(event(p, event_id="evt_a"))
    assert webhook(event(p, event_id="evt_b")).json()["result"] == "no_change"
    assert count(Payment) == 1 and booking_status(client, user_h, b["id"]) == "CONFIRMED"


def test_late_conflicting_event_cannot_flip_a_final_payment(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    webhook(event(p, "SUCCESS", "evt_ok"))
    assert webhook(event(p, "FAILED", "evt_late")).json()["result"] == "ignored"
    assert client.get(f"/payments/{p['id']}", headers=user_h).json()["status"] == "SUCCESS"
    assert booking_status(client, user_h, b["id"]) == "CONFIRMED"


def test_webhook_confirming_an_already_settled_mock_payment_is_a_noop(client, user_h, make_booking, pay, webhook):
    b = make_booking(user_h)
    p = pay(user_h, b["id"], "SUCCESS").json()
    assert webhook(event(p)).json()["result"] == "no_change"
    assert booking_status(client, user_h, b["id"]) == "CONFIRMED"


def test_signature_is_required_and_checked(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    assert webhook(event(p), signature=None).status_code == 401
    assert webhook(event(p), signature="deadbeef").status_code == 401
    assert count(WebhookEvent) == 0
    assert booking_status(client, user_h, b["id"]) == "PENDING"


def test_invalid_payloads_are_422(client, webhook):
    assert webhook({}).status_code == 422
    assert webhook({"event_id": "e", "provider_reference": "x", "status": "MAYBE"}).status_code == 422
    assert webhook({"event_id": "", "provider_reference": "x", "status": "SUCCESS"}).status_code == 422


def test_unknown_provider_reference_is_404_and_can_be_retried(client, webhook):
    r = webhook({"event_id": "evt_x", "provider_reference": "mockpay_nope", "status": "SUCCESS"})
    assert r.status_code == 404
    assert count(WebhookEvent) == 0  # not recorded, so a retry is not mistaken for a duplicate


def test_amount_mismatch_is_rejected(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    r = webhook(event(p, amount="1.00"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "amount_mismatch"
    assert booking_status(client, user_h, b["id"]) == "PENDING"
    assert webhook(event(p, amount="500.00")).json()["result"] == "applied"


def test_success_for_cancelled_booking_does_not_resurrect_it(client, user_h, make_booking, pay, webhook):
    b, p = pending_payment(client, user_h, make_booking, pay)
    client.post(f"/bookings/{b['id']}/cancel", headers=user_h)
    assert webhook(event(p)).status_code == 200
    assert booking_status(client, user_h, b["id"]) == "CANCELLED"
