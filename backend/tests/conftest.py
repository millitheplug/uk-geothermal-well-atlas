"""Shared test fixtures.

Every test runs against a temporary SQLite database with the schema created
directly, so the suite needs no external services. The spatial layer runs through
its haversine fallback in this configuration, which is the point: the same
queries have to work on both backends.

A seeded tenant and user exist on every test session so the auth and
tenant-scoping paths can be exercised for real rather than stubbed.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

# Must be set before app modules import, since the engine is built at import time.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from sqlalchemy.orm import Session  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.user import Tenant, User  # noqa: E402

DEV_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
OTHER_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000ee")

TEST_EMAIL = "analyst@example.com"
# 43 characters, comfortably inside bcrypt's 72-byte limit.
TEST_PASSWORD = "correct-horse-battery-staple-2026"


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    """Create the schema once for the session."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture(scope="session")
def tenants() -> tuple[uuid.UUID, uuid.UUID]:
    """Two tenants, so cross-tenant leakage can be tested."""
    with SessionLocal() as session:
        for tenant_id, slug, name in (
            (DEV_TENANT_ID, "development", "Development"),
            (OTHER_TENANT_ID, "other-org", "Other Organisation"),
        ):
            if session.get(Tenant, tenant_id) is None:
                session.add(Tenant(id=tenant_id, slug=slug, name=name))
        session.commit()
    return DEV_TENANT_ID, OTHER_TENANT_ID


@pytest.fixture(scope="session")
def user(tenants: tuple[uuid.UUID, uuid.UUID]) -> dict:
    """A development-tenant user plus a ready-made access token."""
    dev_tenant_id, _ = tenants
    with SessionLocal() as session:
        existing = session.query(User).filter(User.email == TEST_EMAIL).first()
        if existing is None:
            existing = User(
                id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
                tenant_id=dev_tenant_id,
                email=TEST_EMAIL,
                hashed_password=hash_password(TEST_PASSWORD),
                full_name="Development Analyst",
                role="analyst",
                is_active=True,
            )
            session.add(existing)
            session.commit()
        token = create_access_token(
            user_id=existing.id,
            tenant_id=existing.tenant_id,
            role=existing.role,
            expires_minutes=60,
        )
        return {
            "id": existing.id,
            "tenant_id": existing.tenant_id,
            "role": existing.role,
            "email": existing.email,
            "token": token,
        }


@pytest.fixture
def auth_header(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


@pytest.fixture(scope="session")
def loaded_data() -> dict:
    """Run the development adapters once per session and report what landed.

    Session-scoped so a dozen tests do not each re-import the synthetic
    datasets. The guard lives in the session fixture rather than a module global
    so a ``--lf`` or re-ordered run cannot leave the flag set against an empty
    database.
    """
    from app.data_import.registry import run_bootstrap
    from app.db.session import SessionLocal
    from app.models.heat import Building
    from app.models.well import Well

    if not _LOADED_RESULT:
        result = run_bootstrap()
        if result["summary"]["adapters_failed"]:
            # A silent partial import would make later assertions pass or fail
            # for the wrong reason, so surface it immediately.
            failures = [
                a for a in result["adapters"] if not a["ok"]
            ]
            raise RuntimeError(
                f"development data import failed for: "
                f"{[a['source'] for a in failures]}"
            )
        with SessionLocal() as session:
            _LOADED_RESULT.update(
                {
                    "loaded": True,
                    "well_count": session.query(Well).count(),
                    "building_count": session.query(Building).count(),
                    "summary": result["summary"],
                }
            )

    return dict(_LOADED_RESULT)


_LOADED_RESULT: dict = {}


@pytest.fixture
def sample_well(db: Session, loaded_data: dict):
    """One representative well, fully characterised."""
    from app.models.well import Well

    well = db.query(Well).filter(Well.well_id == "UK-MOCK-WLN-002").one_or_none()
    if well is None:
        pytest.skip("development dataset not loaded")
    return well


@pytest.fixture
def unknown_well(db: Session, loaded_data: dict):
    """A well with no temperature and no integrity assessment."""
    from app.models.well import Well

    well = db.query(Well).filter(Well.well_id == "UK-MOCK-HAM-010").one_or_none()
    if well is None:
        pytest.skip("development dataset not loaded")
    return well


@pytest.fixture
def spatial_dialect(db: Session) -> str:
    from app.services.query_service import spatial_dialect

    return spatial_dialect(db)
