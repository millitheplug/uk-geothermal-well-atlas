"""Shared mixins for tenant isolation and provenance."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import UTCDateTime


class TenantMixin:
    """Every tenant-scoped row carries the owning organisation.

    Tenant isolation is enforced in two layers: a SQLAlchemy event listener
    injects the current tenant into INSERTs, and query helpers filter by it on
    read. Row-level security is additionally enabled by the Alembic migration
    when running on PostgreSQL.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class ProvenanceMixin:
    """Which ingestion adapter wrote this row, and from which dataset.

    Nothing enters the platform without these four fields, which is what makes
    "swap the mock adapter for the real NSTA download" a configuration change
    rather than a code change.
    """

    source: Mapped[str] = mapped_column(
        String(64), nullable=False, doc="Adapter id, e.g. 'nsta' or 'mock_nsta'"
    )
    source_url: Mapped[str | None] = mapped_column(String(1024))
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    dataset_version: Mapped[str | None] = mapped_column(String(64))
