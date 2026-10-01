from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.deps import CurrentUser, DbSession
from app.models import BookingStatus
from app.pagination import PageParams
from app.schemas import BookingCreate, BookingOut, Page
from app.services import booking_service as svc

router = APIRouter(prefix="/bookings", tags=["Bookings"])

BookingId = Annotated[int, Path(gt=0)]


@router.post("/", response_model=BookingOut, status_code=201, summary="Book a diagnostic test (starts as PENDING)")
def create_booking(body: BookingCreate, db: DbSession, user: CurrentUser):
    return svc.create_booking(db, user, body)


@router.get("/", response_model=Page[BookingOut], summary="List my bookings")
def list_bookings(
    db: DbSession,
    user: CurrentUser,
    page: Annotated[PageParams, Depends()],
    status: Annotated[BookingStatus | None, Query()] = None,
):
    return svc.list_bookings(db, user, status, page)


@router.get("/{booking_id}", response_model=BookingOut, summary="Get one of my bookings")
def get_booking(booking_id: BookingId, db: DbSession, user: CurrentUser):
    return svc.get_booking_for_user(db, booking_id, user)


@router.post("/{booking_id}/cancel", response_model=BookingOut, summary="Cancel one of my bookings")
def cancel_booking(booking_id: BookingId, db: DbSession, user: CurrentUser):
    return svc.cancel_booking(db, user, booking_id)
