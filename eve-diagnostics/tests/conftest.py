import json
import os
from datetime import datetime, timedelta, timezone

# Must be set before the app is imported.
os.environ.update(
    DATABASE_URL="sqlite://",
    JWT_SECRET="test-secret-test-secret-test-secret-1234",
    WEBHOOK_SECRET="test-webhook-secret",
    BCRYPT_ROUNDS="4",
    PAYMENT_SUCCESS_RATE="1.0",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password, sign_payload  # noqa: E402

PASSWORD = "Passw0rd123"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def register(client, email: str) -> dict:
    r = client.post("/auth/signup", json={"email": email, "full_name": "Test User", "password": PASSWORD})
    assert r.status_code == 201, r.text
    return login(client, email)


def login(client, email: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def user_h(client):
    return register(client, "alice@example.com")


@pytest.fixture
def other_h(client):
    return register(client, "bob@example.com")


@pytest.fixture
def admin_h(client):
    with SessionLocal() as db:
        db.add(User(email="admin@example.com", full_name="Admin",
                    hashed_password=hash_password(PASSWORD), is_admin=True))
        db.commit()
    return login(client, "admin@example.com")


@pytest.fixture
def catalogue(client, admin_h):
    """One centre offering one test at 500.00."""
    test = client.post("/tests/", json={"name": "CBC"}, headers=admin_h).json()
    centre = client.post("/centres/", json={"name": "EVE Noida", "location": "Noida"}, headers=admin_h).json()
    r = client.post(f"/centres/{centre['id']}/tests", json={"test_id": test["id"], "price": "500.00"}, headers=admin_h)
    assert r.status_code == 201, r.text
    return {"centre_id": centre["id"], "test_id": test["id"], "price": "500.00"}


def future(hours: int = 48) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.fixture
def make_booking(client, catalogue):
    def _make(headers, hours: int = 48):
        r = client.post("/bookings/", headers=headers, json={
            "centre_id": catalogue["centre_id"], "test_id": catalogue["test_id"], "appointment_at": future(hours)})
        assert r.status_code == 201, r.text
        return r.json()
    return _make


@pytest.fixture
def pay(client):
    def _pay(headers, booking_id, simulate=None, key=None):
        h = dict(headers)
        if key:
            h["Idempotency-Key"] = key
        body = {"booking_id": booking_id}
        if simulate:
            body["simulate"] = simulate
        return client.post("/payments/", json=body, headers=h)
    return _pay


@pytest.fixture
def webhook(client):
    def _send(payload: dict, signature: str | None = "auto"):
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if signature == "auto":
            headers["X-Signature"] = sign_payload(body)
        elif signature:
            headers["X-Signature"] = signature
        return client.post("/payments/webhook/", content=body, headers=headers)
    return _send
