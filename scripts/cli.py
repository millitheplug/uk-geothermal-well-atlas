"""Operational command line interface.

Commands are grouped by what they change:

* ``init``       - create the schema
* ``seed-user``  - create a tenant and an account
* ``ingest``     - run one adapter
* ``bootstrap``  - run every adapter in dependency order
* ``assess``     - run the deterministic pipeline over wells from the CLI
* ``check``      - verify the environment and report what is loaded
* ``parameters`` - print the engine's documented parameters

Every command prints a warning when the data it touches is synthetic. That is
not decoration: the CLI writes to the same database the API serves, so an
operator who ingests development data and then forgets will produce results
that look real and are not.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# `app` lives under backend/. This repo keeps operational scripts at the root so
# the surface that can mutate a database is visible without reading application
# code, which means the package is not importable until the backend is on the
# path. Rather than require every operator to export PYTHONPATH, resolve it here.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings  # noqa: E402

logger = logging.getLogger("scripts.cli")

MOCK_WARNING = (
    "SYNTHETIC DATA: this operation uses development datasets. Nothing it "
    "produces corresponds to a real UK well, building or price, and no result "
    "may be presented as production data."
)


# ----------------------------------------------------------------- utilities
def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _emit(payload: Any, *, as_json: bool) -> None:
    """Print a result.

    Structured payloads are always rendered as JSON even without ``--json``,
    because a Python ``repr`` of a dict with UUID keys is not something anyone
    should have to read or grep.
    """
    structured = isinstance(payload, (dict, list))
    if as_json or structured:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(payload)


def _warn_if_mock(is_mock: bool) -> None:
    if is_mock:
        print(MOCK_WARNING, file=sys.stderr)


# ------------------------------------------------------------------ commands
def cmd_init(args: argparse.Namespace) -> int:
    """Create the schema.

    Uses Alembic when ``--migrate`` is given, otherwise ``create_all``. Alembic
    is the right answer for anything that will be shared; ``create_all`` is for
    a throwaway local database where a migration history is noise.
    """
    if args.migrate:
        from alembic import command
        from alembic.config import Config

        ini = Path(args.alembic_ini)
        if not ini.is_absolute():
            ini = _BACKEND / ini
        if not ini.exists():
            print(f"alembic.ini not found at {ini}", file=sys.stderr)
            return 1

        config = Config(str(ini))
        config.set_main_option("script_location", str(ini.parent / "alembic"))
        # alembic runs from its own working directory, so `backend/` has to be on
        # the path for the env module to import `app`.
        if str(_BACKEND) not in sys.path:
            sys.path.insert(0, str(_BACKEND))
        command.upgrade(config, args.revision)
        _emit(f"migrated to {args.revision}", as_json=args.json)
        return 0

    from app.db.session import create_all

    create_all()
    _emit("schema created", as_json=args.json)
    return 0


def cmd_seed_user(args: argparse.Namespace) -> int:
    """Create a tenant and a user, or attach a user to an existing tenant."""
    from sqlalchemy import select

    from app.core.security import hash_password, validate_password_strength
    from app.db.session import session_scope
    from app.models.user import Tenant, User, UserRole

    validate_password_strength(args.password)

    with session_scope() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == args.tenant))
        if tenant is None:
            tenant = Tenant(
                slug=args.tenant,
                name=args.tenant_name or args.tenant.replace("-", " ").title(),
                max_wells_per_month=args.max_wells_per_month,
                max_analyses_per_day=args.max_analyses_per_day,
            )
            db.add(tenant)
            db.flush()
            logger.info("created tenant %s (%s)", tenant.slug, tenant.id)

        existing = db.scalar(
            select(User).where(
                User.tenant_id == tenant.id, User.email == args.email
            )
        )
        if existing is not None:
            if not args.force:
                print(
                    f"user {args.email} already exists in tenant {tenant.slug}. "
                    "Pass --force to reset the password.",
                    file=sys.stderr,
                )
                return 1
            existing.hashed_password = hash_password(args.password)
            existing.role = args.role
            existing.is_active = True
            db.flush()
            _emit(
                {
                    "tenant": tenant.slug,
                    "tenant_id": str(tenant.id),
                    "email": existing.email,
                    "user_id": str(existing.id),
                    "action": "password_reset",
                },
                as_json=args.json,
            )
            return 0

        user = User(
            tenant_id=tenant.id,
            email=args.email,
            hashed_password=hash_password(args.password),
            full_name=args.full_name or args.email.split("@")[0],
            role=args.role,
            is_active=True,
            is_verified=not args.unverified,
        )
        db.add(user)
        db.flush()

        _emit(
            {
                "tenant": tenant.slug,
                "tenant_id": str(tenant.id),
                "email": user.email,
                "user_id": str(user.id),
                "role": user.role,
                "action": "created",
            },
            as_json=args.json,
        )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Run one adapter."""
    from app.data_import.registry import get_adapter, list_adapters, run_adapter

    if args.list:
        _emit(list_adapters(), as_json=True)
        return 0

    result = run_adapter(args.adapter, limit=args.limit, dry_run=args.dry_run)
    _warn_if_mock(get_adapter(args.adapter).is_mock)

    if args.json:
        _emit(result.to_dict(), as_json=True)
    else:
        print(
            f"{result.source}: read={result.records_read} "
            f"wells_created={result.wells_created} "
            f"wells_updated={result.wells_updated} "
            f"wells_skipped={result.wells_skipped} "
            f"buildings_created={result.buildings_created} "
            f"temperatures_created={result.temperatures_created} "
            f"rejected={result.records_rejected} ok={result.ok}"
        )
        for error in result.errors[:20]:
            print(f"  error: {error}", file=sys.stderr)

    return 0 if result.ok else 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Run every adapter in dependency order."""
    from app.data_import.registry import run_bootstrap

    report = run_bootstrap(limit=args.limit, dry_run=args.dry_run)
    _warn_if_mock(bool(report.get("is_mock_data")))

    if args.json:
        _emit(report, as_json=True)
    else:
        summary = report["summary"]
        for key, value in summary.items():
            print(f"{key:>26}: {value}")
        failed = summary["adapters_failed"]
        if failed:
            print(f"\n{failed} adapter(s) failed", file=sys.stderr)
        else:
            print("\nAll adapters completed.")

    return 1 if report["summary"]["adapters_failed"] else 0


def cmd_assess(args: argparse.Namespace) -> int:
    """Run the deterministic engineering pipeline over selected wells.

    Nothing here involves a language model: the score, the recommendation and
    every figure come from the Python engine. ``--with-agents`` adds the agent
    interpretation, which can only narrate what the engine already decided.

    This command selects wells directly rather than through the tenant-scoped
    query the API uses. That is deliberate: the CLI is an operator tool with
    database access, and requiring a project to exist before a well can be
    screened would make it useless for its purpose. Assessments are still
    written under the tenant that owns the supplied account, so the results are
    visible in the API exactly as if they had been requested through it.
    """
    from sqlalchemy import select

    from app.core.security import Caller
    from app.db.session import session_scope
    from app.models import Well
    from app.models.user import Tenant, User
    from app.services import analysis_service

    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == args.email))
        if user is None:
            print(
                f"no user with email {args.email}; create one with "
                "`python -m scripts.cli seed-user`",
                file=sys.stderr,
            )
            return 1
        tenant = db.get(Tenant, user.tenant_id)
        if tenant is None:
            print(f"tenant missing for {args.email}", file=sys.stderr)
            return 1

        caller = Caller(
            user_id=user.id,
            tenant_id=tenant.id,
            role=user.role,
            email=user.email,
        )

        stmt = select(Well)
        if args.exclude_mock:
            stmt = stmt.where(Well.source.not_like("mock%"))
        if args.min_score is not None:
            stmt = stmt.where(Well.feasibility_score >= args.min_score)
        if args.min_temperature is not None:
            stmt = stmt.where(Well.temperature_c >= args.min_temperature)
        stmt = stmt.order_by(
            Well.feasibility_score.is_(None), Well.feasibility_score.desc()
        ).limit(args.limit)

        wells = list(db.scalars(stmt))
        total = len(wells)

        print(f"assessing {total} wells as {caller.email}", flush=True)

        results: list[dict[str, Any]] = []
        for index, well in enumerate(wells, start=1):
            analysis, assessment, _ = analysis_service.run_assessment(
                db,
                well,
                caller=caller,
                include_ai=args.with_agents,
                tenant_id=tenant.id,
            )
            db.commit()

            row: dict[str, Any] = {
                "well_id": well.well_id,
                "name": well.well_name,
                "score": round(float(assessment.feasibility_score), 1),
                "confidence": round(float(assessment.confidence_score), 3),
                "recommendation": str(assessment.recommendation),
                "analysis_id": str(analysis.id) if analysis else None,
                "data_gaps": len(assessment.data_gaps),
            }
            results.append(row)
            print(f"[{index}/{total}] {json.dumps(row, default=str)}", flush=True)

    if args.json:
        _emit(results, as_json=True)

    _warn_if_mock(not args.exclude_mock)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Verify the environment and report what is loaded."""
    from sqlalchemy import func, select

    from app.db.geo import spatial_dialect_label
    from app.db.session import engine, session_scope
    from app.models import Dataset, Well
    from app.models.user import Tenant, User

    counts: dict[str, int] = {}
    with session_scope() as db:
        counts["wells"] = db.scalar(select(func.count()).select_from(Well)) or 0
        counts["tenants"] = db.scalar(select(func.count()).select_from(Tenant)) or 0
        counts["users"] = db.scalar(select(func.count()).select_from(User)) or 0
        try:
            datasets = list(db.scalars(select(Dataset)))
            counts["datasets"] = len(datasets)
            counts["mock_datasets"] = sum(1 for d in datasets if d.is_mock)
        except Exception:  # noqa: BLE001 - the table may not exist yet
            counts["datasets"] = 0
            counts["mock_datasets"] = 0

    payload = {
        "app_version": settings.app_version,
        "environment": settings.environment,
        "database": engine.dialect.name,
        "spatial_dialect": spatial_dialect_label(engine),
        "llm_available": settings.llm_available,
        "llm_model": settings.anthropic_model if settings.llm_available else "mock",
        "counts": counts,
        "is_mock_data": counts.get("mock_datasets", 0) > 0,
        "warnings": ([MOCK_WARNING] if counts.get("mock_datasets", 0) > 0 else []),
    }

    if args.json:
        _emit(payload, as_json=True)
    else:
        for key, value in payload.items():
            if key == "warnings":
                continue
            print(f"{key:>18}: {value}")
        for warning in payload["warnings"]:
            print(f"\n{warning}")

    return 0


def cmd_parameters(args: argparse.Namespace) -> int:
    """Print the engine's documented parameters."""
    from app.engineering.parameters import DEFAULTS

    payload = [spec.to_dict() for spec in DEFAULTS]

    if args.json:
        _emit(payload, as_json=True)
    else:
        for spec in payload:
            source = spec.get("source") or "ASSUMPTION"
            print(f"{spec['key']:<38} = {spec['value']} {spec['unit'] or ''}")
            print(f"{'':<38}   source:    {source}")
            print(f"{'':<38}   rationale: {spec['rationale']}\n")

    return 0


# -------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create the schema")
    p_init.add_argument(
        "--migrate", action="store_true", help="use Alembic instead of create_all"
    )
    p_init.add_argument("--revision", default="head")
    p_init.add_argument("--alembic-ini", default="alembic.ini")
    p_init.set_defaults(func=cmd_init)

    p_user = sub.add_parser("seed-user", help="create or reset a user")
    p_user.add_argument("--email", required=True)
    p_user.add_argument("--password", required=True)
    p_user.add_argument("--full-name", default=None)
    p_user.add_argument("--tenant", default="dev-org")
    p_user.add_argument("--tenant-name", default=None)
    p_user.add_argument(
        "--role",
        default="analyst",
        choices=["owner", "engineer", "analyst", "viewer"],
    )
    p_user.add_argument("--force", action="store_true", help="reset an existing user")
    p_user.add_argument("--unverified", action="store_true")
    p_user.add_argument("--max-wells-per-month", type=int, default=50_000)
    p_user.add_argument("--max-analyses-per-day", type=int, default=500)
    p_user.set_defaults(func=cmd_seed_user)

    p_ingest = sub.add_parser("ingest", help="run one ingestion adapter")
    p_ingest.add_argument("adapter", nargs="?", default=None)
    p_ingest.add_argument("--list", action="store_true", help="list adapters and exit")
    p_ingest.add_argument("--limit", type=int, default=None)
    p_ingest.add_argument("--dry-run", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

    p_boot = sub.add_parser("bootstrap", help="run every adapter in order")
    p_boot.add_argument("--limit", type=int, default=None)
    p_boot.add_argument("--dry-run", action="store_true")
    p_boot.set_defaults(func=cmd_bootstrap)

    p_assess = sub.add_parser("assess", help="run the pipeline over wells")
    p_assess.add_argument("--email", default="analyst@example.com")
    p_assess.add_argument("--limit", type=int, default=10)
    p_assess.add_argument("--min-score", type=float, default=None)
    p_assess.add_argument("--min-temperature", type=float, default=None)
    p_assess.add_argument("--exclude-mock", action="store_true")
    p_assess.add_argument("--with-agents", action="store_true")
    p_assess.set_defaults(func=cmd_assess)

    p_check = sub.add_parser("check", help="verify the environment")
    p_check.set_defaults(func=cmd_check)

    p_params = sub.add_parser("parameters", help="print engine parameters")
    p_params.set_defaults(func=cmd_parameters)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())