from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import commit_or_conflict
from app.errors import AppError
from app.models import Centre, CentreTest, DiagnosticTest
from app.pagination import PageParams, paginate
from app.schemas import (
    CentreCreate,
    CentreDetail,
    CentreTestAttach,
    DiagnosticTestCreate,
    DiagnosticTestOut,
)


def create_test(db: Session, data: DiagnosticTestCreate) -> DiagnosticTest:
    test = DiagnosticTest(name=data.name, description=data.description)
    db.add(test)
    commit_or_conflict(db, f"A test named '{data.name}' already exists", "test_exists")
    return test


def list_tests(db: Session, page: PageParams):
    return paginate(db, select(DiagnosticTest).order_by(DiagnosticTest.id), DiagnosticTestOut, page)


def create_centre(db: Session, data: CentreCreate) -> Centre:
    centre = Centre(name=data.name, location=data.location, address=data.address)
    db.add(centre)
    commit_or_conflict(db, "A centre with this name already exists at this location", "centre_exists")
    return centre


def get_centre_or_404(db: Session, centre_id: int) -> Centre:
    centre = db.get(Centre, centre_id)
    if centre is None:
        raise AppError(404, "centre_not_found", f"Centre {centre_id} not found")
    return centre


def list_centres(db: Session, page: PageParams, location: str | None, test_name: str | None):
    stmt = select(Centre).order_by(Centre.id)
    if location:
        stmt = stmt.where(func.lower(Centre.location).contains(location.lower(), autoescape=True))
    if test_name:
        stmt = stmt.where(
            Centre.offerings.any(
                CentreTest.test.has(
                    func.lower(DiagnosticTest.name).contains(test_name.lower(), autoescape=True)
                )
            )
        )
    return paginate(db, stmt, CentreDetail, page)


def attach_test(db: Session, centre_id: int, data: CentreTestAttach) -> CentreTest:
    get_centre_or_404(db, centre_id)
    if db.get(DiagnosticTest, data.test_id) is None:
        raise AppError(404, "test_not_found", f"Test {data.test_id} not found")
    offering = CentreTest(centre_id=centre_id, test_id=data.test_id, price=data.price)
    db.add(offering)
    commit_or_conflict(db, "This centre already offers that test", "offering_exists")
    return offering


def update_price(db: Session, centre_id: int, test_id: int, price) -> CentreTest:
    offering = db.scalar(
        select(CentreTest).where(CentreTest.centre_id == centre_id, CentreTest.test_id == test_id)
    )
    if offering is None:
        raise AppError(404, "offering_not_found", "This centre does not offer that test")
    offering.price = price  # existing bookings keep their own price snapshot
    db.commit()
    return offering
