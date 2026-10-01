import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings
from app.errors import AppError


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:  # e.g. password longer than bcrypt's 72-byte limit
        return False


# Verified against when the email is unknown, so login timing does not reveal which emails exist.
DUMMY_HASH = hash_password("timing-attack-dummy-password")


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    unauthorized = {"WWW-Authenticate": "Bearer"}
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
        return int(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise AppError(401, "token_expired", "Access token has expired", headers=unauthorized) from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AppError(401, "invalid_token", "Invalid access token", headers=unauthorized) from exc


def sign_payload(body: bytes) -> str:
    """HMAC-SHA256 hex digest used for webhook signatures."""
    return hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_payload(body), signature)
