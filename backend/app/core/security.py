"""Security: authentication, authorisation, tenant isolation, audit logging.

The design decision worth stating: wells are national reference data, so a
tenant does not own a well and the same well must resolve identically for every
tenant. Isolation is therefore enforced on the tenant-scoped tables -
``Building``, ``HeatDemand``, ``HeatNetwork``, ``Project``, ``Analysis``,
``Evidence``, ``Claim`` - and a well is only reachable when it participates in
something the caller owns.

That distinction is enforced by :func:`scoped_well_query`, which is the only
supported way to load a well for a caller. Loading a well by id and then
filtering later is the mistake this module exists to prevent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.analysis import Analysis
from app.models.project import Project, ProjectWell
from app.models.user import ROLE_RANK, APIKey, AuditLog, Tenant, User
from app.models.well import Well

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------- passwords
# Password hashing uses PBKDF2-HMAC-SHA256 from the standard library rather than
# bcrypt through passlib. Two reasons: passlib's bcrypt backend is unmaintained
# and breaks against bcrypt 4.x, and PBKDF2 has no 72-byte input limit to trap
# users in - the limit is enforced here as policy rather than inherited as a
# library quirk.
#
# OWASP's 2023 guidance gives 600,000 iterations for PBKDF2-HMAC-SHA256.
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16
PBKDF2_DERIVED_BYTES = 32

#: Longest accepted password, in bytes. Applied to the hash and to validation.
MAX_PASSWORD_BYTES = 1024

#: Identifier of the password hashing scheme in use, not a password itself.
_PASSWORD_SCHEME = "pbkdf2_sha256"  # noqa: S105


def hash_password(password: str) -> str:
    """Hash a password with a fresh random salt.

    Format: ``pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>``. Self-describing
    so the iteration count can be raised later without invalidating existing
    hashes.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password must be at most {MAX_PASSWORD_BYTES} bytes when UTF-8 "
            f"encoded; got {len(encoded)}"
        )

    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", encoded, salt, PBKDF2_ITERATIONS, dklen=PBKDF2_DERIVED_BYTES
    )
    return (
        f"{_PASSWORD_SCHEME}${PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode()}$"
        f"{base64.b64encode(derived).decode()}"
    )


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a stored hash.

    Returns False rather than raising on any malformed input: a corrupt or
    truncated hash must never authenticate, and it must not turn a failed login
    into a 500.
    """
    try:
        scheme, iterations, salt_b64, hash_b64 = hashed.split("$")
        if scheme != _PASSWORD_SCHEME:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            plain.encode("utf-8"),
            salt,
            int(iterations),
            dklen=len(expected),
        )
    except (ValueError, TypeError, AttributeError):
        return False

    # Constant-time comparison, so a timing difference cannot reveal the hash.
    return hmac.compare_digest(candidate, expected)


def validate_password_strength(password: str) -> None:
    """Reject passwords that would make brute force trivial.

    NIST guidance favours length over composition rules, so only length and a
    small blocklist are enforced.
    """
    common = {"password", "password1", "12345678", "qwerty123", "letmein1"}
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password must be at most {MAX_PASSWORD_BYTES} bytes when UTF-8 "
            "encoded; use a passphrase or reduce non-ASCII characters"
        )
    if password.lower() in common:
        raise ValueError("password is too common")


# ------------------------------------------------------------ tokens
def create_access_token(
    *, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str, expires_minutes: int | None = None
) -> str:
    now = datetime.now(UTC)
    expires = now + timedelta(
        minutes=expires_minutes or settings.access_token_ttl_minutes
    )
    payload = {
        "sub": str(user_id),
        "tenant": str(tenant_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": "ukgeothermal",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer="ukgeothermal",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# --------------------------------------------------------- api keys
def generate_api_key() -> tuple[str, str]:
    """Return ``(full_key, hashed)``.

    The full key is shown once and never stored. The prefix is stored in the
    clear so a key can be identified in a log without exposing it.
    """
    prefix = f"ukg_{secrets.token_hex(4)}"
    secret = secrets.token_urlsafe(32)
    full = f"{prefix}_{secret}"
    return full, hash_api_key(full)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# --------------------------------------------------- caller identity
@dataclass(frozen=True)
class Caller:
    """The authenticated caller, used for scoping and audit."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    email: str
    scopes: frozenset[str] = frozenset()
    is_api_key: bool = False

    def has_role(self, minimum: str) -> bool:
        return ROLE_RANK.get(self.role, -1) >= ROLE_RANK.get(minimum, 99)

    def require_role(self, minimum: str) -> None:
        if not self.has_role(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{self.role}' is below the required '{minimum}'",
            )

    def require_scope(self, scope: str) -> None:
        if self.is_api_key and scope not in self.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"api key lacks the '{scope}' scope",
            )


def _caller_from_token(db: Session, token: str) -> Caller:
    payload = decode_access_token(token)
    try:
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed token claims"
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user is inactive or no longer exists",
        )
    if str(user.tenant_id) != str(tenant_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token tenant no longer matches the user's tenant",
        )

    return Caller(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        email=user.email,
    )


def _caller_from_api_key(db: Session, raw_key: str) -> Caller:
    hashed = hash_api_key(raw_key)
    api_key = db.scalar(
        select(APIKey).where(APIKey.hashed_key == hashed, APIKey.is_revoked.is_(False))
    )
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown or revoked api key"
        )

    now = datetime.now(UTC)
    if api_key.expires_at and api_key.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="api key has expired"
        )
    if not raw_key.startswith(f"{api_key.prefix}_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="api key prefix mismatch"
        )

    api_key.last_used_at = now

    if api_key.tenant_id is None:
        # A key with no tenant is a platform-level key. It gets a synthetic
        # tenant so downstream scoping has something to compare against, and it
        # is granted owner rank because it must be able to do ingestion work.
        return Caller(
            user_id=uuid.UUID(int=0),
            tenant_id=uuid.UUID(int=0),
            role="owner",
            email=f"apikey:{api_key.name}",
            scopes=frozenset(api_key.scopes.split(",")),
            is_api_key=True,
        )

    tenant = db.get(Tenant, api_key.tenant_id)
    if tenant is None or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="tenant is inactive"
        )

    return Caller(
        user_id=uuid.UUID(int=0),
        tenant_id=tenant.id,
        role="owner",
        email=f"apikey:{api_key.name}",
        scopes=frozenset(api_key.scopes.split(",")),
        is_api_key=True,
    )


def get_caller(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> Caller:
    """Resolve the caller from a bearer token or an API key.

    Authentication is deliberately not optional even in development: a build that
    runs with auth disabled locally and enabled in production is a build where
    nobody has tested the auth path. Development credentials are created by the
    seed script instead.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    if token.startswith("ukg_"):
        return _caller_from_api_key(db, token)
    return _caller_from_token(db, token)


CurrentCaller = Annotated[Caller, Depends(get_caller)]


def require_role(minimum: str):  # noqa: ANN201
    """Dependency factory enforcing a minimum role."""

    def _dependency(caller: CurrentCaller) -> Caller:
        caller.require_role(minimum)
        return caller

    return _dependency


# ----------------------------------------------------- tenant scoping
def scoped_well_query(
    stmt: Select, caller: Caller, *, tenant_id: uuid.UUID | None = None
) -> Select:
    """Restrict a well query to wells the caller can legitimately see.

    A well is visible when it is referenced by something the caller owns: a
    project they are a member of, or an analysis in their tenant. This is the
    only supported way to load wells for a caller, and it exists so that
    "national reference data" cannot quietly become "everyone's data with a
    tenant column that nobody filters on".
    """
    tid = tenant_id or caller.tenant_id
    return stmt.where(Well.id.in_(visible_well_ids(tid)))


def visible_well_ids(tenant_id: uuid.UUID) -> Select:
    """Subquery of the well ids a tenant may read."""
    return select(Analysis.well_id).where(Analysis.tenant_id == tenant_id).union(
        select(ProjectWell.well_id).where(
            ProjectWell.project_id.in_(
                select(Project.id).where(Project.tenant_id == tenant_id)
            )
        )
    )


def claimable_well_ids() -> Select:
    """Subquery of the well ids nobody has adopted yet.

    A well is claimable when **no** project, in any tenant, references it. Those
    are the wells nobody has looked at, and they are what a new organisation
    starts from.

    Without this the tenancy model is a dead end: wells become visible only by
    being attached to one of your own projects, and you cannot find a well to
    attach because you cannot see any. The split is deliberately narrow:

    * claimable - in no project at all, so adopting one takes nothing away from
      anyone;
    * invisible - already inside somebody's project. Readable by them, not by
      you.

    Visibility is deliberately **not** folded in here. A well a tenant already
    holds is readable but no longer claimable, and conflating the two would make
    the platform keep offering a well back to the organisation that adopted it.

    Adoption is a one-way door in practice: the API never deletes a
    ``project_wells`` row, so a claimed well stays visible to its adopter, and a
    well two organisations both care about ends up visible to both rather than
    being silently reassigned. Two organisations investigating the same borehole
    is a realistic outcome and a far less harmful one than a quiet transfer.
    """
    return select(Well.id).where(Well.id.notin_(select(ProjectWell.well_id)))


def scoped_or_claimable_well_query(
    stmt: Select, caller: Caller, *, tenant_id: uuid.UUID | None = None
) -> Select:
    """Wells the caller can read, plus wells nobody has adopted.

    Used only by the discovery endpoints. Reads of a specific well still go
    through :func:`scoped_well_query`, so this never widens what a well's detail
    response contains - only which wells a search is willing to offer as
    candidates for adoption.
    """
    tid = tenant_id or caller.tenant_id
    return stmt.where(
        Well.id.in_(visible_well_ids(tid))
        | Well.id.in_(claimable_well_ids())
    )


def tenant_filter(model: Any, caller: Caller):
    """Standard tenant predicate for a model that has ``tenant_id``."""
    return model.tenant_id == caller.tenant_id


# -------------------------------------------------------------- audit
def record_audit(
    db: Session,
    caller: Caller | None,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    request: Request | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    note: str | None = None,
) -> AuditLog:
    """Append an audit entry.

    Written inside the caller's transaction so the audit and the change commit or
    roll back together. There is deliberately no update or delete path.
    """
    entry = AuditLog(
        tenant_id=caller.tenant_id if caller else None,
        user_id=caller.user_id if caller else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
        before=before,
        after=after,
        details=details,
        note=note,
    )
    db.add(entry)
    return entry


def audit_scope(request: Request) -> dict[str, Any]:
    """Extract audit-safe request context.

    Query parameters are included because "who searched for what" is part of the
    access record for a data platform, but the body is not: it may contain
    credentials or well report contents.
    """
    return {
        "method": request.method,
        "path": request.url.path,
        "query": dict(request.query_params),
    }


# ----------------------------------------------------- rate limiting
class RateLimiter:
    """Sliding-window limiter with an in-process fallback.

    Redis is used when configured, because a multi-worker deployment would
    otherwise enforce a per-worker limit that multiplies the real one. The
    in-process fallback is explicitly not suitable for production and says so in
    its docstring, so nobody deploys it believing it is distributed.
    """

    def __init__(self) -> None:
        self._counts: dict[str, list[float]] = {}
        self._redis = None

    def _client(self):  # noqa: ANN202
        if self._redis is None and settings.redis_url:
            try:
                import redis  # noqa: PLC0415

                self._redis = redis.Redis.from_url(
                    settings.redis_url, decode_responses=True, socket_timeout=1
                )
                self._redis.ping()
            except Exception as exc:  # noqa: BLE001
                logger.warning("redis unavailable, using in-process rate limit: %s", exc)
                self._redis = None
        return self._redis

    def check(self, key: str, limit: int | None = None) -> tuple[bool, int]:
        """Return ``(allowed, remaining)``."""
        if not settings.rate_limit_enabled:
            return True, -1

        limit = limit or settings.rate_limit_per_minute
        window = 60.0

        client = self._client()
        if client is not None:
            try:
                import time  # noqa: PLC0415

                now = time.time()
                key_ = f"ratelimit:{key}"
                entries = client.zrange(key_, 0, -1, withscores=True)
                for member, score in entries:
                    if now - float(score) > window:
                        client.zrem(key_, member)
                count = client.zcard(key_)
                if count >= limit:
                    return False, 0
                client.zadd(key_, {str(now): now})
                client.expire(key_, int(window) + 1)
                return True, limit - int(count) - 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("redis rate limit failed, falling back: %s", exc)

        import time  # noqa: PLC0415

        now = time.time()
        entries = [t for t in self._counts.get(key, []) if now - t < window]
        if len(entries) >= limit:
            self._counts[key] = entries
            return False, 0
        entries.append(now)
        self._counts[key] = entries
        return True, limit - len(entries)


rate_limiter = RateLimiter()


async def enforce_rate_limit(
    request: Request,
    caller: CurrentCaller,
) -> None:
    """Rate limit dependency.

    Keyed by tenant rather than by user so that one noisy user cannot exhaust a
    shared tenant quota, and by IP for unauthenticated routes.
    """
    tenant_key = (
        str(caller.tenant_id)
        if str(caller.tenant_id) != str(uuid.UUID(int=0))
        else f"ip:{request.client.host if request.client else 'unknown'}"
    )
    allowed, remaining = rate_limiter.check(tenant_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": "60"},
        )


RateLimited = Annotated[None, Depends(enforce_rate_limit)]


# ------------------------------------------------- tenant bootstrap
def get_tenant(db: Session, caller: Caller) -> Tenant:
    tenant = db.get(Tenant, caller.tenant_id)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="tenant not found"
        )
    return tenant


def require_quota(tenant: Tenant, *, analyses_today: int = 0) -> None:
    if analyses_today >= tenant.max_analyses_per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"daily analysis quota of {tenant.max_analyses_per_day} reached for "
                f"tenant {tenant.slug}"
            ),
        )


def current_tenant_id(
    caller: CurrentCaller,
) -> uuid.UUID:
    """Dependency returning the caller's tenant id."""
    return caller.tenant_id


TenantId = Annotated[uuid.UUID, Depends(current_tenant_id)]
