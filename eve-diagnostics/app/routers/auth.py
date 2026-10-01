from fastapi import APIRouter

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.security import create_access_token
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/signup", response_model=UserOut, status_code=201, summary="Create an account")
def signup(body: SignupRequest, db: DbSession):
    return auth_service.signup(db, body)


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for a JWT")
def login(body: LoginRequest, db: DbSession):
    user = auth_service.authenticate(db, body.email, body.password)
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user: CurrentUser):
    return user
