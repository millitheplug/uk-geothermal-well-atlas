"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import admin, analyses, auth, dashboard, heat, projects, wells
from app.core.config import settings
from app.db.session import engine
from app.db.geo import spatial_dialect_label

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DESCRIPTION = """\
Screening platform for repurposing UK onshore oil, gas, exploration and other
wells to geothermal heat production and district heating.

**What this platform does not do.** It does not claim a well is commercially
viable from temperature or depth. Every figure it produces carries an explicit
provenance label - measured, derived, estimated, modelled, assumed or unknown -
and a well with no temperature record is reported as unknown rather than zero.

All engineering calculations are performed in Python by the deterministic
engine in `app.engineering`, with a full calculation trace attached to every
result. The eleven AI agents interpret, contextualise and explain those
results; they cannot compute them, alter them, or override the feasibility
score or the recommendation. Those are enforced in code, not by prompting.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown.

    The startup check reports which spatial backend is live rather than
    failing: a deployment that silently fell back to SQLite still runs, and the
    health endpoint is where that becomes visible.
    """
    try:
        with engine.connect() as connection:
            dialect = connection.dialect.name
        logger.info("database: %s", dialect)
        logger.info("spatial dialect: %s", spatial_dialect_label(engine))
        if dialect != "postgresql":
            logger.warning(
                "running on %s. PostGIS is the production target; distances will "
                "use the haversine fallback, which is accurate to about 1%% at "
                "UK well-to-building distances.",
                dialect,
            )
    except SQLAlchemyError as exc:
        logger.error("database unreachable at startup: %s", exc)

    if settings.llm_available:
        logger.info("llm: anthropic (%s)", settings.anthropic_model)
    elif settings.ai_enabled:
        logger.info("llm: mock provider (no ANTHROPIC_API_KEY configured)")
    else:
        logger.info("llm: disabled")

    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        max_age=3600,
    )

    # Map responses are large and compress extremely well. 1 kB minimum keeps
    # the middleware off small JSON responses, where it would only add latency.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        """Attach a request id to every log line and response."""
        import uuid as _uuid  # noqa: PLC0415

        request_id = request.headers.get("X-Request-ID") or _uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Return validation errors in a shape the frontend can render."""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "request validation failed",
                "errors": [
                    {
                        "field": ".".join(str(p) for p in err.get("loc", [])[1:]) or "body",
                        "message": err.get("msg"),
                        "type": err.get("type"),
                    }
                    for err in exc.errors()
                ],
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        """Log the detail, return something safe.

        The exception text can contain SQL or internal paths, so it goes to the
        log and the client gets a request id it can quote.
        """
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception("unhandled error [request_id=%s]", request_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "internal server error",
                "request_id": request_id,
            },
        )

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(wells.router, prefix=settings.api_prefix)
    app.include_router(analyses.router, prefix=settings.api_prefix)
    app.include_router(dashboard.router, prefix=settings.api_prefix)
    app.include_router(heat.router, prefix=settings.api_prefix)
    app.include_router(projects.router, prefix=settings.api_prefix)
    app.include_router(admin.router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/api/docs",
            "health": f"{settings.api_prefix}/admin/health",
            "notice": (
                "Screening platform. Every figure carries a provenance label. "
                "No output is a statement of commercial viability."
            ),
        }

    @app.get("/health", include_in_schema=False)
    def liveness() -> dict[str, Any]:
        """Liveness probe at the conventional path.

        Deliberately cheap: no database round trip. A liveness probe that queries
        the database reports the service dead when the database is briefly
        unavailable, and the orchestrator then restarts a process that was not the
        thing at fault. Readiness - which does depend on the database - lives at
        ``{api_prefix}/admin/health`` and should be wired to a different probe.
        """
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
