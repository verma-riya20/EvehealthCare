from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.deps import AdminUser, DbSession
from app.pagination import PageParams
from app.schemas import (
    CentreCreate,
    CentreDetail,
    CentreTestAttach,
    CentreTestOut,
    CentreTestUpdate,
    DiagnosticTestCreate,
    DiagnosticTestOut,
    Page,
)
from app.services import catalogue_service as svc

tests_router = APIRouter(prefix="/tests", tags=["Diagnostic tests"])
centres_router = APIRouter(prefix="/centres", tags=["Diagnostic centres"])

Pagination = Annotated[PageParams, Depends()]
CentreId = Annotated[int, Path(gt=0)]
TestId = Annotated[int, Path(gt=0)]


@tests_router.post("/", response_model=DiagnosticTestOut, status_code=201, summary="Add a test to the catalogue (admin)")
def create_test(body: DiagnosticTestCreate, db: DbSession, _: AdminUser):
    return svc.create_test(db, body)


@tests_router.get("/", response_model=Page[DiagnosticTestOut], summary="List catalogue tests")
def list_tests(db: DbSession, page: Pagination):
    return svc.list_tests(db, page)


@centres_router.post("/", response_model=CentreDetail, status_code=201, summary="Create a centre (admin)")
def create_centre(body: CentreCreate, db: DbSession, _: AdminUser):
    return svc.create_centre(db, body)


@centres_router.get("/", response_model=Page[CentreDetail], summary="List centres with the tests they offer")
def list_centres(
    db: DbSession,
    page: Pagination,
    location: Annotated[str | None, Query(max_length=120, description="Case-insensitive contains")] = None,
    test: Annotated[str | None, Query(max_length=120, description="Only centres offering a test whose name contains this")] = None,
):
    return svc.list_centres(db, page, location, test)


@centres_router.get("/{centre_id}", response_model=CentreDetail, summary="Centre details")
def get_centre(centre_id: CentreId, db: DbSession):
    return svc.get_centre_or_404(db, centre_id)


@centres_router.post(
    "/{centre_id}/tests", response_model=CentreTestOut, status_code=201,
    summary="Offer a test at this centre with a price (admin)",
)
def attach_test(centre_id: CentreId, body: CentreTestAttach, db: DbSession, _: AdminUser):
    return svc.attach_test(db, centre_id, body)


@centres_router.patch(
    "/{centre_id}/tests/{test_id}", response_model=CentreTestOut,
    summary="Change the price of a test at this centre (admin)",
)
def update_price(centre_id: CentreId, test_id: TestId, body: CentreTestUpdate, db: DbSession, _: AdminUser):
    return svc.update_price(db, centre_id, test_id, body.price)
