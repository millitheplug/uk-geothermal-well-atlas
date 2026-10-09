"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.geo import spatial_dialect_label
from app.db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]

MAX_PAGE_SIZE = 1000


def pagination(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Rows per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Rows to skip")] = 0,
) -> dict[str, int]:
    """Standard limit/offset, capped so a single request cannot pull the table."""
    return {"limit": limit, "offset": offset}


Pagination = Annotated[dict, Depends(pagination)]


class Ordering:
    """Whitelist-based ordering.

    Ordering is validated against an explicit allow-list rather than passed
    through to ``ORDER BY``: the column name reaches SQL from user input, and an
    allow-list is cheaper and clearer than trying to sanitise it.
    """

    def __init__(
        self,
        model: Any,
        allowed: dict[str, Any],
        default: str = "created_at",
        param_name: str = "order_by",
    ) -> None:
        self.model = model
        self.allowed = allowed
        self.default = default
        self.param_name = param_name

    def __call__(self, value: str | None = None, descending: bool = False):  # noqa: ANN201
        key = value or self.default
        if key not in self.allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"cannot order by '{key}'. Allowed: "
                    f"{', '.join(sorted(self.allowed))}"
                ),
            )
        column = self.allowed[key]
        return column.desc() if descending else column.asc()


def csv_param(
    value: Annotated[str | None, Query(description="Comma-separated values")] = None,
) -> list[str] | None:
    """Parse a comma-separated query parameter into a list.

    Empty entries are dropped so ``?status=producing,`` behaves as the user
    almost certainly intends rather than failing on an empty string.
    """
    if value is None:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


CsvParam = Annotated[list[str] | None, Depends(csv_param)]


def resolve_uuid(value: str, field: str = "id") -> uuid.UUID:
    """Parse a UUID, returning 422 rather than a 500 on bad input."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} must be a valid UUID",
        ) from exc


def get_optional_uuid(value: str | None, field: str = "id") -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return resolve_uuid(value, field)


def spatial_dialect(db: DbSession) -> str:
    """Which spatial backend this connection is using.

    Exposed on responses so a reader can tell whether distances came from PostGIS
    or from the development fallback.
    """
    return spatial_dialect_label(db.get_bind())


def count_of(db: Session, stmt) -> int:  # noqa: ANN001
    return int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def enforce_mock_disclosure(include_mock: bool, rows: list[Any]) -> bool:
    """Whether a response set contains synthetic rows, so the UI can watermark it."""
    if not include_mock:
        return False
    return any(
        getattr(row, "source", "") or getattr(row, "is_mock", False) is True
        for row in rows[: min(len(rows), 50)]
    )
