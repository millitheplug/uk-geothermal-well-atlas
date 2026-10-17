"""Authentication endpoints."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import (
    Caller,
    CurrentCaller,
    create_access_token,
    generate_api_key,
    hash_password,
    rate_limiter,
    record_audit,
    validate_password_strength,
    verify_password,
)
from app.models.user import APIKey, AuditLog, Tenant, User, UserRole
from app.schemas.well import LoginRequest, RegisterRequest, TokenResponse, UserRead

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


def _tenant_slug(name: str) -> str:
    """URL-safe slug from an organisation name, with a random suffix.

    The suffix keeps two organisations that share a name from colliding, and
    stops the slug leaking whether a given organisation is already registered.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "org"
    return f"{base}-{secrets.token_hex(3)}"


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its own organisation",
)
def register(
    payload: RegisterRequest,
    db: DbSession,
    request: Request,
) -> TokenResponse:
    """Self-service sign-up.

    Every registration creates a **new** organisation with the registrant as its
    owner, so a new account never lands inside someone else's workspace and
    cannot see their projects. Joining an existing organisation is an
    invitation, not a sign-up. The caller is signed in straight away.
    """
    if not settings.allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="self-service sign-up is disabled on this deployment",
        )

    ip = request.client.host if request.client else "unknown"
    allowed, _ = rate_limiter.check(f"register:{ip}", limit=5)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many sign-up attempts; try again in a minute",
            headers={"Retry-After": "60"},
        )

    if payload.password != payload.password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the two passwords do not match",
        )

    # Login looks accounts up by email alone, so an address has to be unique
    # across every organisation, not just within one.
    if db.scalar(select(User.id).where(func.lower(User.email) == payload.email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists; sign in instead",
        )

    try:
        # The platform's password policy (length, blocklist) applies to every
        # account created through the API, not only those made by the CLI.
        validate_password_strength(payload.password)
        hashed = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    tenant = Tenant(slug=_tenant_slug(payload.organisation), name=payload.organisation)
    user = User(
        tenant=tenant,
        email=payload.email,
        hashed_password=hashed,
        full_name=payload.full_name,
        role=UserRole.OWNER.value,
        last_login_at=datetime.now(UTC),
    )
    db.add_all([tenant, user])
    try:
        db.flush()
    except IntegrityError:
        # Two registrations for the same address raced past the check above.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists; sign in instead",
        ) from None

    caller = Caller(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role, email=user.email
    )
    record_audit(
        db,
        caller,
        action="auth.register",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
        details={"organisation": tenant.name},
    )
    db.commit()

    token = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, role=user.role
    )
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


