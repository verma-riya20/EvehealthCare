# EVE Diagnostics Booking API

Backend service for **diagnostic test bookings** with **simulated payments** and an **idempotent payment webhook**.
Built for the EVE Healthcare SDE Intern assignment.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 · PostgreSQL · JWT (PyJWT) · bcrypt · pytest · Docker

**Bonus items included:** Docker + docker-compose · Swagger/OpenAPI (`/docs`) · 39 tests + GitHub Actions CI · structured JSON logging · pagination · HMAC-signed webhook · idempotency keys on payments.

---

## 1. Run it

### Option A - Docker (recommended)

```bash
docker compose up --build
docker compose exec api python -m app.seed    # creates admin + demo centres/tests
```

API: http://localhost:8000 · Swagger UI: http://localhost:8000/docs

### Option B - locally

```bash
# Windows PowerShell, terminal 1
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:DATABASE_URL = "sqlite:///./eve.db"
$env:JWT_SECRET = "local-development-secret-minimum-32-chars"
$env:WEBHOOK_SECRET = "local-webhook-secret"
python -m uvicorn app.main:app --reload

# Windows PowerShell, terminal 2 (same directory)
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "sqlite:///./eve.db"
python -m app.seed
```

API: http://localhost:8000 · Swagger UI: http://localhost:8000/docs

Keep `DATABASE_URL` identical in both terminals. Restart the API after
changing `config.py` or environment values. The seed command creates
`admin@example.com` with password `Admin@12345`.

Call `/auth/login` first and copy its `access_token` into Swagger's
**Authorize** dialog, or send it on every protected request:

```powershell
$login = Invoke-RestMethod -Method Post http://localhost:8000/auth/login `
  -ContentType 'application/json' `
  -Body (@{email='admin@example.com';password='Admin@12345'} | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod http://localhost:8000/auth/me -Headers $headers
```

Use the same sequence for a normal user: sign up, log in, retain the returned
token, then send that token to `/bookings/` and `/payments/`. Admin-only
catalogue endpoints require the seeded admin token. Missing tokens receive
`401`; normal user tokens receive `403` for admin-only endpoints.

### Run the tests

```bash
pytest -q          # uses in-memory SQLite, no Postgres needed
```

### Configuration (env vars, see `.env.example`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | e.g. `postgresql+psycopg://eve:eve@localhost:5432/eve` |
| `JWT_SECRET` | signs access tokens (min 32 chars) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | token lifetime (default 60) |
| `WEBHOOK_SECRET` | HMAC key shared with the payment provider |
| `PAYMENT_SUCCESS_RATE` | chance a mock payment succeeds when no outcome is forced (default 0.8) |

---

## 2. API overview

Every error has the same shape: `{"error": {"code": "...", "message": "...", "details": [...]}}`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/signup` | - | Create account |
| POST | `/auth/login` | - | Get JWT |
| GET | `/auth/me` | user | Current user |
| POST | `/tests/` | admin | Add test to catalogue |
| GET | `/tests/` | - | List catalogue tests |
| POST | `/centres/` | admin | Create centre |
| GET | `/centres/` | - | List centres + their tests/prices (`?location=`, `?test=`, `?limit=`, `?offset=`) |
| GET | `/centres/{id}` | - | Centre details |
| POST | `/centres/{id}/tests` | admin | Offer a test at a price |
| PATCH | `/centres/{id}/tests/{test_id}` | admin | Change price |
| POST | `/bookings/` | user | Book a test (starts `PENDING`) |
| GET | `/bookings/` | user | My bookings (`?status=`, pagination) |
| GET | `/bookings/{id}` | owner | One booking |
| POST | `/bookings/{id}/cancel` | owner | Cancel |
| POST | `/payments/` | owner | **Simulated payment** |
| GET | `/payments/{id}` | owner | One payment |
| POST | `/payments/webhook/` | HMAC signature | **Idempotent provider webhook** |
| GET | `/health` | - | Liveness |

### Example flow

```bash
B=http://localhost:8000

# 1. sign up + log in
curl -X POST $B/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"riya@example.com","full_name":"Riya Verma","password":"Passw0rd123"}'
TOKEN=$(curl -s -X POST $B/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"riya@example.com","password":"Passw0rd123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 2. browse centres (public)
curl "$B/centres/?location=noida"

# 3. book
curl -X POST $B/bookings/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2026-12-01T10:30:00+05:30"}'

# 4. pay (mock). Optional "simulate": "SUCCESS" | "FAILED" | "PENDING"; omit for random.
curl -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: order-123' -d '{"booking_id":1}'
```

### Webhook example

The provider signs the **raw body** with HMAC-SHA256 using `WEBHOOK_SECRET` and sends it in `X-Signature`.

```bash
# create a payment that stays PENDING, then settle it through the webhook
curl -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id":1,"simulate":"PENDING"}'          # note provider_reference in the response

BODY='{"event_id":"evt_001","provider_reference":"mockpay_xxx","status":"SUCCESS"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')
curl -X POST $B/payments/webhook/ -H "X-Signature: $SIG" -H 'Content-Type: application/json' -d "$BODY"
# -> {"event_id":"evt_001","result":"applied"}
# send it again -> {"event_id":"evt_001","result":"duplicate"}   (nothing changes)
```

Admin: `python -m app.seed` creates `admin@example.com` (password from `ADMIN_PASSWORD`). Signup never creates admins.

---

## 3. Database design

```mermaid
erDiagram
    users ||--o{ bookings : makes
    centres ||--o{ centre_tests : offers
    diagnostic_tests ||--o{ centre_tests : "offered as"
    centres ||--o{ bookings : hosts
    diagnostic_tests ||--o{ bookings : for
    bookings ||--o{ payments : "paid by"
    payments ||..o{ webhook_events : "updated by"
    users { int id PK  string email UK  string hashed_password  bool is_admin }
    diagnostic_tests { int id PK  string name UK }
    centres { int id PK  string name  string location }
    centre_tests { int id PK  int centre_id FK  int test_id FK  numeric price }
    bookings { int id PK  int user_id FK  int centre_id FK  int test_id FK  timestamptz appointment_at  numeric amount  string status }
    payments { int id PK  int booking_id FK  numeric amount  string status  string provider_reference UK  string idempotency_key }
    webhook_events { int id PK  string event_id UK  string provider_reference  string result }
```

Key decisions:

* **Test catalogue is separate from price.** `centre_tests` is a many-to-many link that carries the centre's own price; `UNIQUE(centre_id, test_id)`.
* **Bookings snapshot the price** (`amount`), so later price changes never rewrite history.
* **Composite FK** `bookings(centre_id, test_id) -> centre_tests(centre_id, test_id)`: the database itself refuses a booking for a test the centre does not offer.
* **Money is `NUMERIC(10,2)`**, never float.
* **Statuses are `VARCHAR`**, not native PG enums, so adding a state is not a risky migration.
* **Constraints do the concurrency work** (partial unique indexes, supported by Postgres and SQLite):
  * `uq_payment_one_active_per_booking`: at most one `PENDING`/`SUCCESS` payment per booking, so no double charge even under races.
  * `uq_booking_active_slot`: the same user cannot hold two live bookings for the same test/centre/time.
  * `webhook_events.event_id UNIQUE`: the heart of webhook idempotency.
* Indexes on `users.email`, `centres.location`, `bookings(user_id, created_at)`, `bookings.status`, `payments.booking_id`.

### State machines

```
Booking:  PENDING --pay ok--> CONFIRMED --cancel--> CANCELLED
          PENDING --pay fail--> FAILED --retry pay ok--> CONFIRMED
          PENDING / FAILED --cancel--> CANCELLED         (CANCELLED is terminal)
Payment:  PENDING --> SUCCESS | FAILED                    (both terminal)
```

Transitions are enforced in one table (`ALLOWED_TRANSITIONS`); anything else returns `409`.

---

## 4. How the webhook is idempotent

1. Verify `X-Signature` (HMAC-SHA256 over the raw body, constant-time compare), otherwise `401`.
2. Validate the payload, otherwise `422`.
3. **Insert the event into `webhook_events` first.** `UNIQUE(event_id)` means a replay, even two concurrent identical requests, fails on that insert and returns `200 {"result":"duplicate"}` without touching anything else.
4. Look up the payment (`404` if unknown; the ledger row is rolled back so the provider can retry later), check the optional `amount`, then lock booking and payment rows and apply the result through `settle_payment()`, the same function the mock payment endpoint uses.
5. Ledger insert and state change are **one transaction**: both happen or neither does.

Extra protections: final payment states (`SUCCESS`/`FAILED`) cannot be flipped by a late or out-of-order event (`ignored`); the same status arriving under a new `event_id` is a harmless `no_change`; a success for an already-cancelled booking does not resurrect it (logged for refund follow-up). The provider always gets `200` for events it should not retry.

---

## 5. Edge cases handled

| Case | Behaviour |
|---|---|
| Invalid body / types / bad enum / naive datetime | `422` with field-level details |
| Appointment in the past | `422` |
| Non-numeric or non-positive IDs | `422` |
| Booking/payment/centre does not exist | `404` |
| Someone else's booking or payment | `404` (not 403, so IDs cannot be probed) |
| Non-admin creating centres/tests/prices | `403`; no token or bad/expired token gives `401` |
| Test not offered by centre | `404` |
| Same booking submitted twice | `409` |
| Paying a confirmed or cancelled booking | `409` |
| Second payment while one is pending | `409` (also enforced by DB index) |
| Failed payment | Booking becomes `FAILED`, user can retry payment |
| Repeated `Idempotency-Key` on `POST /payments/` | Returns the original payment (`200`), no second charge |
| Cancelling twice / illegal transition | `409` |
| Login with unknown email vs wrong password | identical response and timing (no account enumeration) |
| Bad/missing webhook signature | `401`, nothing recorded |
| Webhook replay / duplicate | `200 duplicate`, no state change |
| Webhook for unknown payment | `404`, retry-safe |
| Webhook amount differs from payment | `409` |

---

## 6. Project layout

```
app/
  main.py            app factory, request-logging middleware, routers
  config.py          env-based settings
  database.py        engine/session, commit_or_conflict helper
  models.py          SQLAlchemy models, constraints, indexes
  schemas.py         Pydantic request/response models + validation
  security.py        bcrypt, JWT, webhook HMAC
  deps.py            auth dependencies (current user, admin)
  errors.py          AppError + uniform error responses
  pagination.py      limit/offset helper
  routers/           thin HTTP layer (auth, catalogue, bookings, payments)
  services/          business rules (booking state machine, payment + webhook logic)
  seed.py            admin + demo data
tests/               39 tests: auth, catalogue, bookings, payments, webhook
```

Routers stay thin; all rules live in `services/`, so they are easy to test and to change.

---

## 7. Assumptions

* A "location" is a free-text city/area; no geo-search.
* One booking = one test at one centre. Multi-test bookings are out of scope.
* `POST /payments/` accepts an optional `simulate` field. This is **mock-only** and would be removed with a real gateway.
* Payment is synchronous by default; `simulate: PENDING` models an async provider that settles via webhook.
* Cancelling a `CONFIRMED` booking is allowed, but refunds are not simulated.
* Appointments must simply be in the future; opening hours and slot capacity are not modelled.
* Only admins manage the catalogue. Admins are created via the seed script, never via public signup.
* Tables are created on startup (`create_all`) to keep the project easy to run.

## 8. What I would improve with more time

* **Alembic migrations** instead of `create_all`.
* **Background retries**: a Celery/RQ worker for webhook processing with exponential backoff and a dead-letter table.
* **Slot capacity and opening hours** per centre, so a slot cannot be overbooked.
* **Refunds** and a reconciliation job for "paid but cancelled" bookings (currently only logged).
* **Redis** for caching centre listings and for rate limiting login/signup/webhook.
* **Refresh tokens**, email verification, password reset.
* **Signed-timestamp replay window** on webhooks, on top of `event_id` dedupe.
* **Postgres-backed integration tests** in CI, including a real concurrency test. Today the tests run on SQLite, and the Postgres DDL is only verified by compiling it.
* Metrics (Prometheus) and tracing (OpenTelemetry).
