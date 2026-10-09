"""Authentication endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import (
    Caller,
    CurrentCaller,
    create_access_token,
    generate_api_key,
    record_audit,
    verify_password,
)
from app.models.user import APIKey, AuditLog, User
from app.schemas.well import LoginRequest, TokenResponse, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for a token")
def login(
    payload: LoginRequest,
    db: DbSession,
    request: Request,
) -> TokenResponse:
    """Authenticate and issue a bearer token.

    A failed login records an audit entry but returns the same 401 whether the
    account exists or the password was wrong, so the endpoint cannot be used to
    enumerate valid addresses.
    """
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    if user is None or not verify_password(payload.password, user.hashed_password):
        record_audit(
            db,
            None,
            action="auth.login_failed",
            resource_type="user",
            resource_id=payload.email[:64],
            request=request,
            details={"reason": "invalid_credentials"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="account is disabled"
        )

    token = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role
    )

    record_audit(
        db,
        Caller(user_id=user.id, tenant_id=user.tenant_id, role=user.role, email=user.email),
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    user.last_login_at = datetime.now(UTC)
    db.commit()

    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserRead.model_validate(user),
    )


@router.get("/me", response_model=UserRead, summary="Current user")
def me(db: DbSession, caller: CurrentCaller) -> UserRead:
    """The authenticated user's own record."""
    user = db.get(User, caller.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user record not found"
        )
    return UserRead.model_validate(user)


@router.get("/audit", summary="Audit entries for the caller's tenant")
def audit_log(
    db: DbSession,
    caller: CurrentCaller,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    action: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    """Recent audit entries.

    Owner-only: the audit log reveals what other people in the tenant have been
    looking at, which is useful to an administrator and nobody else.
    """
    caller.require_role("owner")

    stmt = select(AuditLog).where(AuditLog.tenant_id == caller.tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)

    rows = list(
        db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit))
    )
    return {
        "entries": [
            {
                "id": entry.id,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "user_id": str(entry.user_id) if entry.user_id else None,
                "ip_address": entry.ip_address,
                "details": entry.details,
                "note": entry.note,
                "created_at": entry.created_at.isoformat(),
            }
            for entry in rows
        ],
        "count": len(rows),
        "total_in_tenant": db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.tenant_id == caller.tenant_id
            )
        ),
    }


@router.post("/api-keys", status_code=status.HTTP_201_CREATED, summary="Issue an API key")
def create_api_key(
    db: DbSession,
    caller: CurrentCaller,
    name: Annotated[str, Query(min_length=1, max_length=128)],
    scopes: Annotated[str, Query(description="Comma-separated scopes")] = "read",
) -> dict[str, Any]:
    """Issue an API key for ingestion adapters or CI.

    The full key is returned exactly once. Only a hash is stored, so a lost key
    cannot be recovered and has to be replaced.
    """
    caller.require_role("owner")

    full_key, hashed = generate_api_key()
    prefix = full_key.split("_")[0] + "_" + full_key.split("_")[1]

    db.add(
        APIKey(
            tenant_id=caller.tenant_id,
            name=name,
            prefix=prefix,
            hashed_key=hashed,
            scopes=scopes,
        )
    )
    record_audit(
        db,
        caller,
        action="auth.api_key_created",
        resource_type="api_key",
        details={"name": name, "scopes": scopes},
    )
    db.commit()

    return {
        "api_key": full_key,
        "prefix": prefix,
        "scopes": scopes,
        "warning": (
            "This key is shown once and cannot be retrieved again. Store it now."
        ),
    }


