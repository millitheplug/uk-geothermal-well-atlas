"""Alembic environment.

The important behaviours here, in order of how much damage getting them wrong
would cause:

1. **The URL comes from application settings, not from alembic.ini.** Three
   different sources of truth for the database URL is how a migration ends up
   applied to the wrong database.
2. **`target_metadata` is populated by importing `app.models`.** Without the
   import the metadata is empty and autogenerate produces a migration that
   drops every table.
3. **PostGIS and pgvector are created outside Alembic**, in the first migration,
   with dialect guards. `CREATE EXTENSION` cannot run inside a transaction on
   every setup, and a SQLite test database must not try.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.core.config import settings
from app.db.base import Base

# Populates Base.metadata with every table. Do not remove.
import app.models  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def _is_postgres() -> bool:
    return settings.database_url.startswith("postgresql")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting. Used to review a migration."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live connection."""

    def _configure(connection) -> None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # SQLite cannot ALTER most things in place. Batch mode rewrites the
            # table instead, which is slower but keeps one migration valid on
            # both backends - a requirement for the test suite to be meaningful.
            render_as_batch=connection.dialect.name == "sqlite",
        )

        if _is_postgres():
            # Extensions live outside Alembic's transaction so a failure to
            # create one does not poison the migration that follows it.
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()