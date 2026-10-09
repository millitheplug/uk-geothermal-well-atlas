"""Project endpoints: the pipeline view."""

from __future__ import annotations

import re
import uuid
from datetime import UTC
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, Pagination
from app.core.enums import ProjectStage
from app.core.security import Caller, CurrentCaller, record_audit
from app.models.analysis import Analysis
from app.models.project import Project, ProjectWell
from app.models.well import Well
from app.schemas.well import AnalysisSummary, ProjectCreate, ProjectDetail, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


def _slugify(name: str) -> str:
    """URL-safe slug with a random suffix.

    The suffix keeps slugs unique without a uniqueness-retry loop, and the slug
    is a convenience identifier rather than a primary key, so the randomness
    costs nothing.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return f"{base}-{uuid.uuid4().hex[:6]}" if base else uuid.uuid4().hex[:12]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: DbSession,
    caller: CurrentCaller,
) -> ProjectRead:
    """Create a project and optionally attach candidate wells.

    Adding a well to a project is what makes it visible to the tenant: wells are
    national data, so a project is the entry point through which an organisation
    claims one for its own work.
    """
    caller.require_role("analyst")

    project = Project(
        tenant_id=caller.tenant_id,
        name=payload.name,
        slug=_slugify(payload.name),
        description=payload.description,
        target_region=payload.target_region,
        owner_id=caller.user_id,
        stage=ProjectStage.SOURCING.value,
    )
    db.add(project)
    db.flush()

    added = 0
    for well_id in payload.well_ids:
        stmt = select(Well).where(Well.id == well_id)
        well = db.scalar(stmt)
        if well is None:
            continue
        already = db.scalar(
            select(ProjectWell).where(
                ProjectWell.project_id == project.id, ProjectWell.well_id == well_id
            )
        )
        if already is None:
            db.add(
                ProjectWell(
                    project_id=project.id,
                    well_id=well_id,
                    role="candidate",
                    added_by=caller.user_id,
                )
            )
            added += 1

    record_audit(
        db,
        caller,
        action="project.created",
        resource_type="project",
        resource_id=str(project.id),
        after={"name": project.name, "wells_added": added},
    )
    db.commit()
    db.refresh(project)
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectRead])
def list_projects(
    db: DbSession,
    caller: CurrentCaller,
    page: Pagination,
    stage: Annotated[list[str] | None, Query()] = None,
    include_archived: bool = False,
) -> list[ProjectRead]:
    """The caller's own projects."""
    stmt = select(Project).where(Project.tenant_id == caller.tenant_id)
    if not include_archived:
        stmt = stmt.where(Project.is_archived.is_(False))
    if stage:
        stmt = stmt.where(Project.stage.in_(stage))

    rows = list(
        db.scalars(
            stmt.order_by(Project.updated_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    )
    return [ProjectRead.model_validate(r) for r in rows]


@router.get("/{project_uuid}", response_model=ProjectDetail)
def get_project(
    project_uuid: uuid.UUID, db: DbSession, caller: CurrentCaller
) -> ProjectDetail:
    """One project with its well count and recent analyses."""
    project = _scoped(db, caller, project_uuid)
    well_count = db.scalar(
        select(func.count()).select_from(ProjectWell).where(ProjectWell.project_id == project.id)
    ) or 0

    analyses = list(
        db.scalars(
            select(Analysis)
            .where(Analysis.project_id == project.id)
            .order_by(Analysis.created_at.desc())
            .limit(25)
        )
    )

    detail = ProjectDetail.model_validate(project)
    detail.well_count = well_count
    detail.analyses = [
        AnalysisSummary(
            id=a.id,
            well_id=a.well_id,
            status=a.status,
            feasibility_score=a.feasibility_score,
            confidence_score=a.confidence_score,
            recommendation=a.recommendation,
            progress_stage=a.progress_stage,
            created_at=a.created_at,
            completed_at=a.completed_at,
        )
        for a in analyses
    ]
    return detail


@router.post("/{project_uuid}/wells/{well_uuid}", status_code=status.HTTP_204_NO_CONTENT)
def add_well_to_project(
    project_uuid: uuid.UUID,
    well_uuid: uuid.UUID,
    db: DbSession,
    caller: CurrentCaller,
    role: Annotated[str, Query(pattern="^(candidate|primary|backup)$")] = "candidate",
) -> None:
    """Attach a well to a project, which makes it visible to the tenant."""
    project = _scoped(db, caller, project_uuid)

    well = db.get(Well, well_uuid)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    existing = db.scalar(
        select(ProjectWell).where(
            ProjectWell.project_id == project.id, ProjectWell.well_id == well_uuid
        )
    )
    if existing is not None:
        return

    db.add(
        ProjectWell(
            project_id=project.id,
            well_id=well_uuid,
            role=role,
            added_by=caller.user_id,
        )
    )
    record_audit(
        db,
        caller,
        action="project.well_added",
        resource_type="project",
        resource_id=str(project.id),
        details={"well_id": str(well_uuid), "role": role},
    )
    db.commit()


@router.patch("/{project_uuid}/stage")
def update_stage(
    project_uuid: uuid.UUID,
    db: DbSession,
    caller: CurrentCaller,
    stage: Annotated[
        str,
        Query(
            pattern="^(sourcing|screening|due_diligence|validation|feed_study|"
            "investment_decision|delivery|operating|closed|rejected)$"
        ),
    ],
) -> dict[str, Any]:
    """Move a project through the pipeline stages."""
    project = _scoped(db, caller, project_uuid)

    before = project.stage
    project.stage = stage
    record_audit(
        db,
        caller,
        action="project.stage_changed",
        resource_type="project",
        resource_id=str(project.id),
        before={"stage": before},
        after={"stage": stage},
    )
    db.commit()

    return {
        "id": str(project.id),
        "stage": project.stage,
        "previous_stage": before,
        "available_stages": [s.value for s in ProjectStage],
    }


@router.post("/{project_uuid}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_project(
    project_uuid: uuid.UUID, db: DbSession, caller: CurrentCaller
) -> None:
    """Archive a project. Analysis results are retained."""
    from datetime import datetime  # noqa: PLC0415

    project = _scoped(db, caller, project_uuid)
    project.is_archived = True
    project.archived_at = datetime.now(UTC)
    record_audit(
        db, caller, action="project.archived", resource_type="project",
        resource_id=str(project.id),
    )
    db.commit()


def _scoped(db: Session, caller: Caller, project_uuid: uuid.UUID) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_uuid, Project.tenant_id == caller.tenant_id
        )
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found for this tenant",
        )
    return project
