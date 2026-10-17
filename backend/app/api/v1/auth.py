"""Authentication endpoints."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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


# ---------------------------------------------------------- registration
#: Sign-up creates a tenant, so it costs more than any other anonymous endpoint.
#: The general limiter allows 120 requests a minute; nobody registers at that
#: rate, and a script that could would fill the tenants table before anyone
#: noticed.
REGISTER_PER_MINUTE = 5


def _rate_limit_key(request: Request) -> str:
    """Identify the caller of a request that may have crossed a proxy.

    ``request.client.host`` is the proxy itself once a reverse proxy sits in
    front, so keying on it would put every visitor into a single shared bucket
    and lock real people out after five sign-ups between them. The forwarded
    chain is therefore read from the right, where the proxy appended the peer it
    actually saw: an entry a client supplies for itself sits on the left and
    cannot buy a fresh bucket.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()[:64] or "unknown"
    if request.client is not None:
        return request.client.host
    return "unknown"


def _tenant_slug(db: Session, seed: str) -> str:
    """A unique, readable slug for a new tenant.

    ``tenants.slug`` is unique and capped at 64 characters, and registration is
    the one path where a caller influences the value - so it is normalised and
    numbered on collision rather than taken verbatim.
    """
    stem = re.sub(r"[^a-z0-9]+", "-", seed.lower()).strip("-")
    stem = stem[:48].strip("-") or "org"

    for attempt in range(1, 100):
        candidate = stem if attempt == 1 else f"{stem}-{attempt}"
        if db.scalar(select(Tenant).where(Tenant.slug == candidate)) is None:
            return candidate

    # A hundred collisions on one stem means it is being scripted. A random
    # suffix cannot collide, and the hex after it is not a name anyone types.
    return f"{stem}-{uuid.uuid4().hex[:8]}"


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organisation and the account that administers it",
)
def register(
    payload: RegisterRequest,
    db: DbSession,
    request: Request,
) -> TokenResponse:
    """Open registration: one organisation, one owner, one token.

    This is the same work ``scripts.cli seed-user`` does, without the flags.
    Every account gets its own tenant, so a new sign-up starts with the national
    wells in view and none of anyone else's projects - adoption is what attaches
    a well to a tenant, and nothing has been attached yet.

    The account is recorded unverified because nothing verifies it. There is no
    mail service behind this platform, and asserting that an address has been
    checked when it has not is precisely the kind of claim this project refuses
    to make. Login does not gate on the flag.

    The email is checked across every tenant rather than within one: ``login``
    looks an account up by address alone with no tenant to disambiguate, so a
    duplicate would silently sign the second person into the first person's
    organisation.
    """
    allowed, _remaining = rate_limiter.check(
        _rate_limit_key(request), limit=REGISTER_PER_MINUTE
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many sign-up attempts from this address; try again in a minute",
            # Matches the header the general limiter sends, so a client that
            # backs off behaves the same way whichever one refused it.
            headers={"Retry-After": "60"},
        )

    email = payload.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="a valid email is required"
        )

    try:
        validate_password_strength(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account already exists for this email address",
        )

    local, _, domain = email.partition("@")
    tenant = Tenant(
        slug=_tenant_slug(db, payload.organisation.strip() or local),
        name=payload.organisation.strip() or domain,
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name.strip() or local,
        role=UserRole.OWNER.value,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.flush()

    record_audit(
        db,
        Caller(user_id=user.id, tenant_id=tenant.id, role=user.role, email=user.email),
        action="auth.register",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
        details={"tenant": tenant.slug},
    )
    db.commit()

    return TokenResponse(
        access_token=create_access_token(
            user_id=user.id, tenant_id=tenant.id, role=user.role
        ),
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


