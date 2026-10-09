"""Project and project-well models.

Kept in their own module because :mod:`app.core.security` imports them for
tenant scoping, and putting them in ``analysis.py`` would make that import
circular.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ProjectStage
from app.db.base import UUID, Base, UTCDateTime, created_at_col, updated_at_col

if TYPE_CHECKING:
    from app.models.analysis import Analysis


class Project(Base):
    """A named piece of work: one well, several wells, or a region."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectStage.SOURCING.value, index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    target_region: Mapped[str | None] = mapped_column(String(64), index=True)
    target_scenario: Mapped[str | None] = mapped_column(String(32))

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    due_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    wells: Mapped[list[ProjectWell]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    analyses: Mapped[list[Analysis]] = relationship(back_populates="project")

    def __repr__(self) -> str:
        return f"<Project {self.slug} stage={self.stage}>"


class ProjectWell(Base):
    """Join row carrying a well's role within a project."""

    __tablename__ = "project_wells"
    __table_args__ = (UniqueConstraint("project_id", "well_id", name="uq_project_wells_project_id_well_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    well_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("wells.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="candidate",
        doc="candidate | primary | backup",
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    added_at: Mapped[datetime] = created_at_col()

    project: Mapped[Project] = relationship(back_populates="wells")
