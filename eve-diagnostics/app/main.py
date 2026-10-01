import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import settings
from app.database import Base, engine
from app.errors import register_error_handlers
from app.logging_config import configure_logging
from app.routers import auth, bookings, catalogue, payments

logger = logging.getLogger("app.request")

DESCRIPTION = """
Backend for diagnostic test bookings and **simulated** payments.

* Auth: signup / login -> JWT. Click **Authorize** and paste the `access_token`.
* Admin-only: creating tests/centres and setting prices (create the admin with `python -m app.seed`).
* Payments are mocked. `POST /payments/webhook/` is idempotent and HMAC-signed.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fine for this assignment; a real deployment would run Alembic migrations instead.
    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version="1.0.0", description=DESCRIPTION, lifespan=lifespan)
    register_error_handlers(app)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        return response

    for r in (auth.router, catalogue.tests_router, catalogue.centres_router, bookings.router, payments.router):
        app.include_router(r)

    @app.get("/health", tags=["Meta"], summary="Liveness probe")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
