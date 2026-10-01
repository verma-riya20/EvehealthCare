from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import commit_or_conflict
from app.errors import AppError
from app.models import User
from app.schemas import SignupRequest
from app.security import DUMMY_HASH, hash_password, verify_password


def signup(db: Session, data: SignupRequest) -> User:
    if db.scalar(select(User.id).where(User.email == data.email)):
        raise AppError(409, "email_taken", "An account with this email already exists")
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        is_admin=False,  # admins are never created through the public API
    )
    db.add(user)
    commit_or_conflict(db, "An account with this email already exists", "email_taken")
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(password, user.hashed_password if user else DUMMY_HASH)
    if user is None or not password_ok:
        # Same message for "unknown email" and "wrong password" -> no account enumeration.
        raise AppError(
            401, "invalid_credentials", "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
