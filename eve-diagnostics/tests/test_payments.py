def booking_status(client, headers, booking_id):
    return client.get(f"/bookings/{booking_id}", headers=headers).json()["status"]


def test_successful_payment_confirms_booking(client, user_h, make_booking, pay):
    b = make_booking(user_h)
    r = pay(user_h, b["id"], "SUCCESS")
    assert r.status_code == 201
    assert r.json()["status"] == "SUCCESS" and r.json()["booking_status"] == "CONFIRMED"
    assert r.json()["amount"] == "500.00"
    assert booking_status(client, user_h, b["id"]) == "CONFIRMED"


def test_failed_payment_marks_booking_failed_then_retry_succeeds(client, user_h, make_booking, pay):
    b = make_booking(user_h)
    r = pay(user_h, b["id"], "FAILED")
    assert r.status_code == 201 and r.json()["status"] == "FAILED"
    assert booking_status(client, user_h, b["id"]) == "FAILED"

    r = pay(user_h, b["id"], "SUCCESS")  # retry allowed after a failure
    assert r.status_code == 201
    assert booking_status(client, user_h, b["id"]) == "CONFIRMED"


def test_default_outcome_is_success_or_failed(client, user_h, make_booking, pay):
    b = make_booking(user_h)
    assert pay(user_h, b["id"]).json()["status"] in ("SUCCESS", "FAILED")


def test_cannot_pay_twice_or_after_cancel(client, user_h, make_booking, pay):
    b = make_booking(user_h)
    pay(user_h, b["id"], "SUCCESS")
    r = pay(user_h, b["id"], "SUCCESS")
    assert r.status_code == 409 and r.json()["error"]["code"] == "booking_already_paid"

    c = make_booking(user_h, 96)
    client.post(f"/bookings/{c['id']}/cancel", headers=user_h)
    r = pay(user_h, c["id"], "SUCCESS")
    assert r.status_code == 409 and r.json()["error"]["code"] == "booking_cancelled"


def test_cannot_pay_someone_elses_booking(client, user_h, other_h, make_booking, pay):
    b = make_booking(user_h)
    assert pay(other_h, b["id"], "SUCCESS").status_code == 404
    assert booking_status(client, user_h, b["id"]) == "PENDING"


def test_payment_validation_and_auth(client, user_h, pay):
    assert pay(user_h, 99999).status_code == 404
    assert client.post("/payments/", json={"booking_id": "abc"}, headers=user_h).status_code == 422
    assert client.post("/payments/", json={"booking_id": 1, "simulate": "MAYBE"}, headers=user_h).status_code == 422
    assert client.post("/payments/", json={"booking_id": 1}).status_code == 401


def test_pending_payment_blocks_a_second_attempt(client, user_h, make_booking, pay):
    b = make_booking(user_h)
    assert pay(user_h, b["id"], "PENDING").json()["status"] == "PENDING"
    r = pay(user_h, b["id"], "SUCCESS")
    assert r.status_code == 409 and r.json()["error"]["code"] == "payment_in_progress"


def test_idempotency_key_replays_same_payment(client, user_h, make_booking, pay):
    b = make_booking(user_h)
    first = pay(user_h, b["id"], "SUCCESS", key="abc-123")
    again = pay(user_h, b["id"], "SUCCESS", key="abc-123")
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"]


def test_get_payment_is_owner_only(client, user_h, other_h, make_booking, pay):
    b = make_booking(user_h)
    p = pay(user_h, b["id"], "SUCCESS").json()
    assert client.get(f"/payments/{p['id']}", headers=user_h).status_code == 200
    assert client.get(f"/payments/{p['id']}", headers=other_h).status_code == 404
