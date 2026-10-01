from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.errors import AppError


def _build_engine(url: str):
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # one shared in-memory DB (used by tests)
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = _build_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()  # rolls back anything that was not committed


def commit_or_conflict(db: Session, message: str, code: str = "conflict") -> None:
    """Commit, translating a DB uniqueness violation into a clean 409.

    Uniqueness is enforced by the database (not just by a pre-check) so it is
    race-safe when two requests arrive at the same time.
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, code, message) from exc
