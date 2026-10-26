"""Administrative endpoints: health, datasets, adapters, prices, regulatory."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession, spatial_dialect
from app.core.config import settings
from app.core.security import CurrentCaller, record_audit
from app.data_import.registry import ADAPTERS, list_adapters, run_adapter, run_bootstrap
from app.db.geo import spatial_dialect_label
from app.models.analysis import RegulatoryRequirement
from app.models.evidence import Dataset
from app.models.heat import EnergyPrice
from app.models.well import Well
from app.schemas.well import HealthResponse, HeatDemandSummary
from app.services import query_service as qs

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health(db: DbSession) -> HealthResponse:
    """Liveness and configuration readout.

    Reports which spatial backend and which LLM provider are actually in use,
    because both are configured by environment variable and a deployment that
    silently fell back to SQLite or to the mock agent is a deployment nobody
    wants to discover during a review.
    """
    # Both queries sit inside the same guard. The mock-row count used to live
    # outside it, so an unreachable database raised straight out of the endpoint
    # and returned a bare 500: the graceful "degraded" readout below was never
    # built, and any platform health check wired to this path saw an empty error
    # instead of learning that the database was the thing at fault.
    try:
        db.execute(select(func.count()).select_from(Dataset))
        database = "postgresql" if db.get_bind().dialect.name == "postgresql" else "sqlite"
        # Report mock data from the wells themselves rather than from dataset
        # rows: a dataset can be registered without any of its rows having
        # landed, and a health check that says "mock data present" when none is
        # would send a reviewer looking in the wrong place.
        mock_rows = (
            db.scalar(
                select(func.count()).select_from(
                    select(Well.id).where(Well.source.like("mock_%")).subquery()
                )
            )
            or 0
        )
    except SQLAlchemyError:
        database = "unavailable"
        mock_rows = 0

    if not settings.ai_enabled:
        llm = "disabled"
    elif settings.ai_provider == "mock":
        llm = "mock"
    elif settings.mimo_api_key and settings.ai_provider in ("auto", "mimo"):
        llm = "mimo"
    elif settings.llm_available:
        llm = "anthropic"
    else:
        llm = "mock"

    return HealthResponse(
        status="ok" if database != "unavailable" else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        database=database,
        spatial_dialect=spatial_dialect_label(db.get_bind()),
        redis="configured" if settings.redis_url else "not configured",
        llm=llm,
        is_mock_data=mock_rows > 0,
    )


@router.get("/datasets", summary="Registered datasets and their provenance")
def list_datasets(db: DbSession, caller: CurrentCaller) -> dict[str, Any]:
    """Every ingested dataset with its provenance and quality score.

    This is the answer to "where did this number come from?" at dataset level.
    """
    rows = list(db.scalars(select(Dataset).order_by(Dataset.source, Dataset.version)))

    return {
        "datasets": [
            {
                "id": str(row.id),
                "source": row.source,
                "name": row.name,
                "description": row.description,
                "source_url": row.source_url,
                "download_date": str(row.download_date) if row.download_date else None,
                "published_date": str(row.published_date) if row.published_date else None,
                "licence": row.licence,
                "version": row.version,
                "reliability": row.reliability,
                "quality_score": row.quality_score,
                "row_count": row.row_count,
                "validation_summary": row.validation_summary,
                "is_mock": row.is_mock,
                "status": row.status,
                "last_ingested_at": (
                    row.last_ingested_at.isoformat() if row.last_ingested_at else None
                ),
            }
            for row in rows
        ],
        "counts": {
            "total": len(rows),
            "mock": sum(1 for r in rows if r.is_mock),
            "real": sum(1 for r in rows if not r.is_mock),
        },
        "note": (
            "Datasets marked is_mock contain synthetic development data and must "
            "never be presented as production well data."
            if any(r.is_mock for r in rows)
            else None
        ),
    }


@router.get("/adapters", summary="Available ingestion adapters")
def adapters(caller: CurrentCaller) -> dict[str, Any]:
    """Every registered adapter, so the ingestion surface is discoverable."""
    return {
        "adapters": list_adapters(),
        "count": len(ADAPTERS),
        "note": (
            "All currently registered adapters produce synthetic data. Real NSTA, "
            "BGS and heat-demand adapters are designed for but not yet configured; "
            "see docs/data-sources.md."
        ),
    }


@router.post("/ingest", summary="Run an ingestion adapter")
def ingest(
    db: DbSession,
    caller: CurrentCaller,
    adapter: Annotated[str, Query(description="Adapter name")] = "mock_wells",
    limit: Annotated[int | None, Query(ge=1, le=100_000)] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one adapter.

    Owner-only, because ingestion writes rows that every other user's results
    depend on. ``dry_run`` counts what would be read without writing anything.
    """
    caller.require_role("owner")

    if adapter not in ADAPTERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"unknown adapter '{adapter}'. Available: "
                f"{', '.join(sorted(ADAPTERS))}"
            ),
        )

    result = run_adapter(adapter, limit=limit, dry_run=dry_run)
    record_audit(
        db,
        caller,
        action="admin.ingest",
        resource_type="dataset",
        resource_id=result.source,
        details={"adapter": adapter, "limit": limit, "dry_run": dry_run},
    )
    db.commit()
    return result.to_dict()


@router.post("/bootstrap", summary="Run every development adapter in order")
def bootstrap(
    db: DbSession,
    caller: CurrentCaller,
    limit: Annotated[int | None, Query(ge=1, le=100_000)] = None,
) -> dict[str, Any]:
    """Load the full development dataset.

    Idempotent: adapters upsert on their stable identifiers, so this can be run
    repeatedly without duplicating rows.
    """
    caller.require_role("owner")

    result = run_bootstrap(limit=limit)
    record_audit(db, caller, action="admin.bootstrap", resource_type="dataset")
    db.commit()
    return result


@router.get("/prices", summary="Energy price book")
def prices(
    db: DbSession,
    caller: CurrentCaller,
    fuel: Annotated[str | None, Query()] = None,
    on: Annotated[date | None, Query(description="Date in force")] = None,
) -> dict[str, Any]:
    """The tariff book, with the tax decomposition for each entry.

    The decomposition matters: a headline pence-per-kWh that bundles a third of
    its value in levies and network charges cannot be compared with an
    energy-only figure, and comparing them is how a financial model ends up
    wrong by a factor of two.
    """
    stmt = select(EnergyPrice)
    if fuel:
        stmt = stmt.where(EnergyPrice.fuel == fuel)
    if on:
        stmt = stmt.where(
            EnergyPrice.valid_from <= on,
            (EnergyPrice.valid_to.is_(None)) | (EnergyPrice.valid_to >= on),
        )

    rows = list(db.scalars(stmt.order_by(EnergyPrice.fuel, EnergyPrice.valid_from.desc())))

    return {
        "prices": [
            {
                "fuel": row.fuel,
                "price_p_per_kwh": row.price_p_per_kwh,
                "levies_p_per_kwh": row.levies_p_per_kwh,
                "valid_from": str(row.valid_from),
                "valid_to": str(row.valid_to) if row.valid_to else None,
                "customer_segment": row.customer_segment,
                "status": row.status,
                "price_basis": row.price_basis,
                "source": row.source,
                "is_mock": row.is_mock,
            }
            for row in rows
        ],
        "count": len(rows),
        "caveats": [
            "Rows with status ASSUMPTION are levels a scheme would need to achieve, "
            "not published tariffs. No market price for UK geothermal district heat "
            "exists."
        ],
    }


@router.get("/regulatory", summary="Consent requirements")
def regulatory(
    db: DbSession,
    caller: CurrentCaller,
    configuration: Annotated[
        str | None, Query(description="Filter to a geothermal configuration")
    ] = None,
    jurisdiction: str | None = None,
) -> dict[str, Any]:
    """Consents and obligations, filterable by configuration and jurisdiction."""
    stmt = select(RegulatoryRequirement)
    if jurisdiction:
        stmt = stmt.where(RegulatoryRequirement.jurisdiction == jurisdiction)
    if configuration:
        # A requirement applies if it is either configuration-agnostic or
        # explicitly for this configuration.
        stmt = stmt.where(
            (RegulatoryRequirement.applies_to_configuration.is_(None))
            | (RegulatoryRequirement.applies_to_configuration == configuration)
        )

    rows = list(db.scalars(stmt.order_by(RegulatoryRequirement.jurisdiction)))

    return {
        "requirements": [
            {
                "id": str(row.id),
                "jurisdiction": row.jurisdiction,
                "title": row.title,
                "description": row.description,
                "authority": row.authority,
                "applies_to_configuration": row.applies_to_configuration,
                "is_mandatory": row.is_mandatory,
                "typical_lead_time_months": row.typical_lead_time_months,
                "estimated_cost_gbp": row.estimated_cost_gbp,
                "status": row.status,
                "source": row.source,
                "source_url": row.source_url,
                "is_mock": row.is_mock,
            }
            for row in rows
        ],
        "count": len(rows),
        "max_lead_time_months": max(
            (row.typical_lead_time_months or 0 for row in rows), default=None
        ),
        "caveat": (
            "Lead times and costs are engineering estimates for programme planning, "
            "not quoted figures from an authority. Confirm with the relevant authority "
            "before committing to a programme."
        ),
    }


@router.get("/heat-networks", summary="Known heat networks")
def heat_networks(
    db: DbSession,
    caller: CurrentCaller,
    centre_lat: Annotated[float | None, Query(ge=49, le=62)] = None,
    centre_lon: Annotated[float | None, Query(ge=-9, le=3)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=500_000)] = None,
    existing_only: bool = False,
) -> dict[str, Any]:
    """Existing and planned heat networks."""
    networks = qs.heat_networks(
        db,
        centre_lat=centre_lat,
        centre_lon=centre_lon,
        radius_m=radius_m,
        existing_only=existing_only,
    )

    return {
        "networks": [
            {
                "id": str(n.id),
                "name": n.name,
                "operator": n.operator,
                "centre_latitude": n.centre_latitude,
                "centre_longitude": n.centre_longitude,
                "existing": n.existing,
                "operational": n.operational,
                "network_type": n.network_type,
                "current_heat_source": n.current_heat_source,
                "flow_temperature_c": n.flow_temperature_c,
                "return_temperature_c": n.return_temperature_c,
                "network_length_m": n.network_length_m,
                "connected_buildings": n.connected_buildings,
                "annual_delivered_heat_gwh": n.annual_delivered_heat_gwh,
                "spare_capacity_mw": n.spare_capacity_mw,
                "reinforcement_required": n.reinforcement_required,
                "status": n.status,
                "is_mock": n.is_mock,
            }
            for n in networks
        ],
        "count": len(networks),
        "spatial_dialect": spatial_dialect(db),
    }


@router.get("/demand-areas", summary="Settlement-level heat demand")
def demand_areas(
    db: DbSession,
    caller: CurrentCaller,
    centre_lat: Annotated[float | None, Query(ge=49, le=62)] = None,
    centre_lon: Annotated[float | None, Query(ge=-9, le=3)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=500_000)] = None,
    min_demand_kwh: Annotated[float | None, Query(ge=0)] = None,
) -> dict[str, Any]:
    """Aggregate demand by settlement, as published zoning datasets provide."""
    areas = qs.heat_demand_areas(
        db,
        centre_lat=centre_lat,
        centre_lon=centre_lon,
        radius_m=radius_m,
        min_demand_kwh=min_demand_kwh,
    )

    return {
        "areas": [
            HeatDemandSummary(
                area_code=a.area_code,
                area_name=a.area_name,
                area_type=a.area_type,
                latitude=a.latitude,
                longitude=a.longitude,
                total_annual_demand_kwh=a.total_annual_demand_kwh,
                household_count=a.household_count,
                average_supply_temperature_c=a.average_supply_temperature_c,
                source=a.source,
                is_mock=a.is_mock,
            ).model_dump()
            for a in areas
        ],
        "count": len(areas),
        "total_demand_gwh": sum(a.total_annual_demand_kwh for a in areas) / 1e6,
    }


@router.get("/parameters", summary="Documented default parameters")
def engineering_parameters(caller: CurrentCaller) -> dict[str, Any]:
    """Every engineering default with its rationale, source and range.

    Exposed so a reviewer can see the full assumption set without reading the
    source, and so the what-if endpoint can show which values it is about to
    override.
    """
    from app.engineering.parameters import DEFAULTS  # noqa: PLC0415

    return {
        "parameters": [spec.to_dict() for spec in DEFAULTS],
        "count": len(DEFAULTS),
        "note": (
            "Every value here is an ASSUMPTION, not a measurement. Values with a "
            "null value are computed from well data at run time and are never "
            "defaulted independently."
        ),
    }
