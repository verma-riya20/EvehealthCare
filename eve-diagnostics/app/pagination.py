from typing import Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.schemas import Page


class PageParams:
    """Query params shared by every list endpoint: ?limit=20&offset=0"""

    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100, description="Page size"),
        offset: int = Query(0, ge=0, description="Rows to skip"),
    ):
        self.limit = limit
        self.offset = offset


def paginate(db: Session, stmt: Select, schema: type[BaseModel], page: PageParams) -> Page[Any]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(page.limit).offset(page.offset)).unique().all()
    return Page[schema](  # type: ignore[valid-type]
        items=[schema.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
