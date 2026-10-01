from tests.conftest import future


def payload(catalogue, **over):
    return {"centre_id": catalogue["centre_id"], "test_id": catalogue["test_id"],
            "appointment_at": future(), **over}


def test_create_booking_snapshots_price_and_starts_pending(client, catalogue, user_h):
    r = client.post("/bookings/", json=payload(catalogue), headers=user_h)
    assert r.status_code == 201
    b = r.json()
    assert b["status"] == "PENDING" and b["amount"] == "500.00"
    assert b["centre"]["name"] == "EVE Noida" and b["test"]["name"] == "CBC"


def test_booking_requires_auth(client, catalogue):
    assert client.post("/bookings/", json=payload(catalogue)).status_code == 401
    assert client.get("/bookings/").status_code == 401


def test_invalid_booking_requests(client, catalogue, user_h):
    assert client.post("/bookings/", json=payload(catalogue, appointment_at=future(-5)), headers=user_h).status_code == 422
    assert client.post("/bookings/", json=payload(catalogue, appointment_at="2030-01-01T10:00:00"), headers=user_h).status_code == 422  # naive
    assert client.post("/bookings/", json=payload(catalogue, appointment_at="tomorrow"), headers=user_h).status_code == 422
    assert client.post("/bookings/", json=payload(catalogue, test_id=9999), headers=user_h).status_code == 404
    assert client.post("/bookings/", json=payload(catalogue, centre_id=9999), headers=user_h).status_code == 404
    assert client.post("/bookings/", json={}, headers=user_h).status_code == 422


def test_duplicate_active_booking_is_rejected(client, catalogue, user_h):
    body = payload(catalogue)
    assert client.post("/bookings/", json=body, headers=user_h).status_code == 201
    r = client.post("/bookings/", json=body, headers=user_h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_booking"


def test_cancelled_slot_can_be_rebooked(client, catalogue, user_h):
    body = payload(catalogue)
    first = client.post("/bookings/", json=body, headers=user_h).json()
    assert client.post(f"/bookings/{first['id']}/cancel", headers=user_h).status_code == 200
    assert client.post("/bookings/", json=body, headers=user_h).status_code == 201


def test_users_cannot_see_or_touch_each_others_bookings(client, user_h, other_h, make_booking):
    b = make_booking(user_h)
    assert client.get(f"/bookings/{b['id']}", headers=other_h).status_code == 404
    assert client.post(f"/bookings/{b['id']}/cancel", headers=other_h).status_code == 404
    assert client.get("/bookings/", headers=other_h).json()["total"] == 0
    assert client.get("/bookings/", headers=user_h).json()["total"] == 1
    assert client.get(f"/bookings/{b['id']}", headers=user_h).json()["status"] == "PENDING"  # untouched


def test_invalid_booking_ids(client, user_h):
    assert client.get("/bookings/99999", headers=user_h).status_code == 404
    assert client.get("/bookings/abc", headers=user_h).status_code == 422
    assert client.get("/bookings/0", headers=user_h).status_code == 422
    assert client.post("/bookings/99999/cancel", headers=user_h).status_code == 404


def test_cancel_twice_is_409(client, user_h, make_booking):
    b = make_booking(user_h)
    assert client.post(f"/bookings/{b['id']}/cancel", headers=user_h).json()["status"] == "CANCELLED"
    r = client.post(f"/bookings/{b['id']}/cancel", headers=user_h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_state_transition"


def test_list_filter_by_status(client, user_h, make_booking):
    a = make_booking(user_h, 48)
    make_booking(user_h, 72)
    client.post(f"/bookings/{a['id']}/cancel", headers=user_h)
    assert client.get("/bookings/", params={"status": "CANCELLED"}, headers=user_h).json()["total"] == 1
    assert client.get("/bookings/", params={"status": "PENDING"}, headers=user_h).json()["total"] == 1
    assert client.get("/bookings/", params={"status": "NOPE"}, headers=user_h).status_code == 422
