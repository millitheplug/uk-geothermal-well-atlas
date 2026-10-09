"""Engine and session management."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base

_connect_args: dict[str, object] = {}
_engine_kwargs: dict[str, object] = {"echo": settings.sql_echo, "future": True}

if settings.is_sqlite:
    _connect_args["check_same_thread"] = False
else:
    _engine_kwargs.update(
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )

engine = create_engine(settings.database_url, connect_args=_connect_args, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
    """Enable FK enforcement and a spatial-ish trig function set on SQLite.

    `acos`/`radians` exist in stock SQLite build 3.35+ with SQLITE_ENABLE_MATH
    on some platforms; the fallback in `db.geo` only needs `radians`, `sin`,
    `cos`, `asin`, `sqrt`, `pow`, `least`, all of which are available in the
    SQLite that ships with modern Python. Foreign keys are off by default and
    are enabled explicitly so behaviour matches PostgreSQL.
    """
    if not settings.is_sqlite:
        return
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts, workers and Alembic hooks."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all() -> None:
    """Create the schema directly. Used by tests and first-run dev bootstrap.

    Imports :mod:`app.models` first. Without that the metadata is empty at call
    time - the module is imported lazily by callers that only need the engine,
    so ``create_all`` would silently create nothing.

    Production and CI use Alembic; see alembic/versions.
    """
    import app.models  # noqa: F401  (populates Base.metadata)

    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    Base.metadata.drop_all(bind=engine)
