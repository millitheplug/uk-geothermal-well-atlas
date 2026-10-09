"""Application settings.

All configuration is environment driven. Defaults are chosen so that the
application runs end-to-end on a developer laptop with no external services.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The checked-in development secret. Named so the production guard can
#: compare against it by identity rather than by re-typing the string. It is a
#: published constant, not a credential: startup refuses to run with it set.
_DEVELOPMENT_SECRET_KEY = "dev-only-change-me-in-production-please-32b"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Application ----------------------------------------------------
    app_name: str = "UK Geothermal Well Atlas"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"

    # ---- Database -------------------------------------------------------
    # PostgreSQL+PostGIS is the production target. The SQLite fallback exists so
    # that the geospatial layer can be exercised without a PostGIS server; the
    # geometry expressions are swapped at the SQLAlchemy dialect level.
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/ukgeothermal",
    )
    sql_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---- Redis ----------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120

    # ---- Security -------------------------------------------------------
    secret_key: str = _DEVELOPMENT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 12
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # ---- AI -------------------------------------------------------------
    # When no API key is present the agent layer falls back to a deterministic
    # mock provider that returns schema-valid structured output.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    ai_enabled: bool = True
    ai_max_tokens: int = 4096
    ai_temperature: float = 0.0

    # ---- Object storage -------------------------------------------------
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "ukgeothermal"
    object_storage_access_key: str = "minioadmin"
    # MinIO's published local default. Set OBJECT_STORAGE_SECRET_KEY in any
    # environment that is not a throwaway local stack.
    object_storage_secret_key: str = "minioadmin"  # noqa: S105

    # ---- Domain defaults ------------------------------------------------
    # Default assumption set applied when a user does not override. These are
    # *assumptions*, never facts, and are always reported as such.
    default_project_lifetime_years: int = 20
    default_electricity_price_p_per_kwh: float = 15.0
    default_heat_price_p_per_kwh: float = 8.5
    default_discount_rate: float = 0.08

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _reject_development_secrets_in_production(self) -> Settings:
        """Refuse to start a production deployment with a checked-in secret.

        The default ``secret_key`` signs every access token. If it reaches a
        production deployment, anyone holding the repository can mint a valid
        token for any tenant. Failing at import time is the only place this is
        caught early enough to matter - by the time a deployment is serving
        traffic it is expensive.

        Deliberately not a warning. A warning in a startup log is exactly the
        thing that gets filtered out during a deploy.
        """
        if self.environment == "production":
            if self.secret_key == _DEVELOPMENT_SECRET_KEY:
                raise ValueError(
                    "SECRET_KEY is still the development default. Set a unique "
                    "random value before running in production; anyone with the "
                    "repository could otherwise mint valid tokens."
                )
            if self.debug:
                raise ValueError(
                    "DEBUG must be false in production. Debug responses expose "
                    "internals that should not leave the process."
                )
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_available(self) -> bool:
        return bool(self.ai_enabled and self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
