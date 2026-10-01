from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import User
from app.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from /auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    if credentials is None:
        raise AppError(
            401, "not_authenticated", "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        )
    user = db.get(User, decode_access_token(credentials.credentials))
    if user is None:
        raise AppError(
            401, "invalid_token", "Invalid access token", headers={"WWW-Authenticate": "Bearer"}
        )
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise AppError(403, "forbidden", "Admin privileges required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
