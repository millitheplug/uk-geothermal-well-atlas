"""Well endpoints: search, detail, explorer filters and the map layer."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, Pagination, spatial_dialect
from app.core.security import CurrentCaller, scoped_well_query
from app.models.well import Well
from app.schemas.well import (
    MapFeature,
    MapFeatureCollection,
    WellDetail,
    WellSearchResponse,
    WellSummary,
)
from app.services import query_service as qs

router = APIRouter(prefix="/wells", tags=["wells"])


@router.get("", response_model=WellSearchResponse, summary="Search and filter wells")
def search_wells(
    db: DbSession,
    caller: CurrentCaller,
    page: Pagination,
    search: Annotated[str | None, Query(max_length=120)] = None,
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    purpose: Annotated[list[str] | None, Query()] = None,
    operator: Annotated[str | None, Query(max_length=255)] = None,
    licence: Annotated[str | None, Query(max_length=64)] = None,
    region: Annotated[list[str] | None, Query()] = None,
    county: Annotated[str | None, Query(max_length=120)] = None,
    formation: Annotated[str | None, Query(max_length=120)] = None,
    min_temperature_c: Annotated[float | None, Query(ge=0, le=400)] = None,
    max_temperature_c: Annotated[float | None, Query(ge=0, le=400)] = None,
    min_depth_m: Annotated[float | None, Query(ge=0)] = None,
    max_depth_m: Annotated[float | None, Query(ge=0)] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    min_confidence_score: Annotated[float | None, Query(ge=0, le=1)] = None,
    min_data_confidence: Annotated[list[str] | None, Query()] = None,
    drilling_year_from: Annotated[int | None, Query(ge=1800, le=2100)] = None,
    drilling_year_to: Annotated[int | None, Query(ge=1800, le=2100)] = None,
    has_temperature: Annotated[bool | None, Query()] = None,
    has_integrity: Annotated[bool | None, Query()] = None,
    recommendation: Annotated[list[str] | None, Query()] = None,
    min_nearest_demand_m: Annotated[float | None, Query(ge=0)] = None,
    max_nearest_demand_m: Annotated[float | None, Query(ge=0)] = None,
    min_annual_demand_kwh: Annotated[float | None, Query(ge=0)] = None,
    centre_lat: Annotated[float | None, Query(ge=49, le=62)] = None,
    centre_lon: Annotated[float | None, Query(ge=-9, le=3)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=500_000)] = None,
    include_mock: Annotated[bool, Query(description="Include synthetic development data")] = True,
    include_claimable: Annotated[
        bool,
        Query(
            description=(
                "Also return wells that belong to no project, so they can be "
                "adopted into one. Off by default: a plain search should show "
                "what you hold, not the whole national inventory."
            )
        ),
    ] = False,
    order_by: Annotated[str, Query()] = "feasibility_score",
    descending: Annotated[bool, Query()] = True,
) -> WellSearchResponse:
    """Filtered well search.

    Every filter in the map's filter panel maps to a parameter here, so the UI
    and the API cannot drift apart. Wells are visible only when the caller
    references them through a project or analysis of their own, unless
    ``include_claimable`` is set.
    """
    filters = qs.WellFilters(
        search=search,
        status=status_filter,
        original_purpose=purpose,
        operator=operator,
        licence=licence,
        region=region,
        county=county,
        formation=formation,
        min_temperature_c=min_temperature_c,
        max_temperature_c=max_temperature_c,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        min_score=min_score,
        max_score=max_score,
        min_confidence_score=min_confidence_score,
        min_data_confidence=min_data_confidence,
        drilling_year_from=drilling_year_from,
        drilling_year_to=drilling_year_to,
        has_temperature=has_temperature,
        has_integrity=has_integrity,
        recommendation=recommendation,
        min_nearest_demand_m=min_nearest_demand_m,
        max_nearest_demand_m=max_nearest_demand_m,
        min_annual_demand_kwh=min_annual_demand_kwh,
        centre_lat=centre_lat,
        centre_lon=centre_lon,
        radius_m=radius_m,
        include_mock=include_mock,
        include_claimable=include_claimable,
    )

    allowed_order = {
        "feasibility_score": Well.feasibility_score,
        "confidence_score": Well.confidence_score,
        "temperature_c": Well.temperature_c,
        "total_depth_m": Well.total_depth_m,
        "drilling_year": Well.drilling_year,
        "well_name": Well.well_name,
        "recommendation": Well.recommendation,
        "data_confidence": Well.data_confidence,
        "analysed_at": Well.analysed_at,
    }
    if order_by not in allowed_order:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"cannot order by '{order_by}'. Allowed: "
                f"{', '.join(sorted(allowed_order))}"
            ),
        )

    rows, total = qs.search_wells(
        db,
        caller,
        filters,
        limit=page["limit"],
        offset=page["offset"],
        order_by=order_by,
        descending=descending,
    )

    return WellSearchResponse(
        items=[WellSummary.model_validate(row) for row in rows],
        total=total,
        limit=page["limit"],
        offset=page["offset"],
        spatial_dialect=spatial_dialect(db),
    )


@router.get("/map", response_model=MapFeatureCollection, summary="Well points for the map")
def well_map_features(
    db: DbSession,
    caller: CurrentCaller,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    min_temperature_c: Annotated[float | None, Query(ge=0, le=400)] = None,
    max_temperature_c: Annotated[float | None, Query(ge=0, le=400)] = None,
    min_depth_m: Annotated[float | None, Query(ge=0)] = None,
    max_depth_m: Annotated[float | None, Query(ge=0)] = None,
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    region: Annotated[list[str] | None, Query()] = None,
    min_data_confidence: Annotated[list[str] | None, Query()] = None,
    max_nearest_demand_m: Annotated[float | None, Query(ge=0)] = None,
    centre_lat: Annotated[float | None, Query(ge=49, le=62)] = None,
    centre_lon: Annotated[float | None, Query(ge=-9, le=3)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=500_000)] = None,
    include_mock: bool = True,
    include_claimable: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=20_000)] = 5000,
) -> MapFeatureCollection:
    """GeoJSON feature collection for the national map.

    Property names are terse because this payload is the heaviest thing the
    frontend loads, and every field here is rendered in the map popup. Coloured
    by ``score``; ``confidence`` is included separately so the UI can distinguish
    a strong well from a well merely measured well.

    ``include_claimable`` adds wells that belong to no project. The map is the
    platform's discovery surface, so a brand new organisation needs it to have
    anything to look at; every detail read still goes through the strict
    visibility check.
    """
    filters = qs.WellFilters(
        min_score=min_score,
        max_score=max_score,
        min_temperature_c=min_temperature_c,
        max_temperature_c=max_temperature_c,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        status=status_filter,
        region=region,
        min_data_confidence=min_data_confidence,
        max_nearest_demand_m=max_nearest_demand_m,
        centre_lat=centre_lat,
        centre_lon=centre_lon,
        radius_m=radius_m,
        include_mock=include_mock,
        include_claimable=include_claimable,
    )

    rows, _ = qs.search_wells(
        db, caller, filters, limit=limit, offset=0,
        order_by="feasibility_score", descending=True,
    )

    # Which of the returned wells are still unadopted? The map needs to say so,
    # because clicking an unadopted well cannot open its record - the caller has
    # no claim on it yet - and the honest response is to offer the adoption step
    # rather than a 404 with no way forward.
    #
    # Scoped to the returned ids so the extra query is a handful of primary keys
    # rather than a scan of the whole inventory.
    row_ids = [row.id for row in rows]
    unadopted: set[uuid.UUID] = set()
    if include_claimable and row_ids:
        from app.core.security import claimable_well_ids  # noqa: PLC0415

        unadopted = set(
            db.scalars(
                select(Well.id).where(
                    Well.id.in_(row_ids),
                    Well.id.in_(claimable_well_ids()),
                )
            )
        )

    features = [
        MapFeature(
            geometry={"type": "Point", "coordinates": [row.longitude, row.latitude]},
            properties={
                "id": str(row.id),
                "well_id": row.well_id,
                "name": row.well_name,
                "score": row.feasibility_score,
                "confidence": row.confidence_score,
                "confidence_band": row.data_confidence,
                "recommendation": row.recommendation,
                "temperature_c": row.temperature_c,
                "temperature_status": row.temperature_status,
                "depth_m": row.total_depth_m,
                "status": row.status,
                "region": row.region,
                "operator": row.operator,
                "is_mock": (row.source or "").startswith("mock_"),
                # False means the caller already holds this well and can open its
                # record. True means it belongs to no project and can be adopted.
                # A well inside *another* organisation's project is not returned
                # at all, so this flag is the only tenancy signal the map sends.
                "claimable": row.id in unadopted,
            },
        )
        for row in rows
    ]

    return MapFeatureCollection(
        features=features,
        spatial_dialect=spatial_dialect(db),
    )


@router.get("/facets", summary="Distinct values for the filter panel")
def well_facets(db: DbSession, caller: CurrentCaller) -> dict[str, Any]:
    """Distinct values and ranges for populating the map filter panel.

    Computed from the data rather than hard-coded, so a filter option cannot
    exist for which there are no wells.

    Deliberately **not** tenant-scoped. A facet list is metadata about the shape
    of the national inventory - "there are wells in Norfolk" leaks nothing that
    a well list would not, and scoping the options to the caller's projects
    would produce a filter panel whose contents depend on unrelated activity,
    which reads as arbitrary to the user. The moment a facet could reveal a
    specific well's attributes rather than the shape of the inventory, it
    belongs behind ``scoped_well_query``.
    """
    from app.models.well import Well

    def distinct(column: Any) -> list[str]:
        # A plain DISTINCT over the column. An earlier version joined against a
        # ``select(Well.id)`` subquery, which SQLAlchemy correctly warned was a
        # cartesian product: the multiplication was masked by DISTINCT in the
        # result but not in the scan, which grew quadratically with the
        # inventory.
        values = db.scalars(select(column).distinct().limit(500))
        return sorted(v for v in values if v)

    def _range(column: Any) -> dict[str, float | None]:
        row = db.execute(select(func.min(column), func.max(column))).one()
        return {"min": row[0], "max": row[1]}

    total = db.scalar(select(func.count()).select_from(Well)) or 0

    return {
        "statuses": distinct(Well.status),
        "purposes": distinct(Well.original_purpose),
        "regions": distinct(Well.region),
        "counties": distinct(Well.county),
        "recommendations": distinct(Well.recommendation),
        "confidence_bands": distinct(Well.data_confidence),
        "temperature_range_c": _range(Well.temperature_c),
        "depth_range_m": _range(Well.total_depth_m),
        "score_range": _range(Well.feasibility_score),
        "total_wells": total,
    }


@router.get(
    "/{well_uuid}",
    response_model=WellDetail,
    summary="Full well record",
)
def get_well(
    well_uuid: uuid.UUID,
    db: DbSession,
    caller: CurrentCaller,
) -> WellDetail:
    """Everything the well detail page needs in one request.

    Temperatures, integrity, logs and the provenance block are eager-loaded, so
    the page makes a single call and cannot render a well with a score but no
    evidence behind it.
    """
    stmt = select(Well).where(Well.id == well_uuid)
    stmt = scoped_well_query(stmt, caller)
    well = db.scalar(stmt)

    if well is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "well not found, or not visible to this tenant. Wells are national "
                "data but are only reachable once they are referenced by a project "
                "or analysis belonging to your organisation."
            ),
        )

    return WellDetail.model_validate(well)


@router.get(
    "/{well_uuid}/demand",
    summary="Matched heat demand near a well",
)
def get_well_demand(
    well_uuid: uuid.UUID,
    db: DbSession,
    caller: CurrentCaller,
    radius_m: Annotated[float, Query(gt=0, le=20_000)] = 2000.0,
    min_connection_potential: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """The buildings near a well and their aggregated demand.

    Returns the aggregate plus the individual buildings, so the detail page can
    show both the headline number and what it is made of.
    """
    stmt = select(Well).where(Well.id == well_uuid)
    stmt = scoped_well_query(stmt, caller)
    well = db.scalar(stmt)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    match = qs.match_demand_to_well(
        db, well, radius_m=radius_m, limit=limit,
        min_connection_potential=min_connection_potential,
    )

    return {
        "well_id": well.well_id,
        "radius_m": match.radius_m,
        "building_count": match.building_count,
        "total_annual_demand_kwh": match.total_annual_demand_kwh,
        "total_peak_demand_kw": match.total_peak_demand_kw,
        "nearest_building_distance_m": match.nearest_building_distance_m,
        "weighted_centre_latitude": match.weighted_latitude,
        "weighted_centre_longitude": match.weighted_longitude,
        "dominant_building_type": match.dominant_building_type,
        "average_required_supply_temperature_c": match.average_supply_temperature_c,
        "demand_confidence": match.confidence,
        "notes": match.notes,
        "spatial_dialect": spatial_dialect(db),
        "buildings": [
            {
                "id": str(b.id),
                "building_type": b.building_type,
                "latitude": b.latitude,
                "longitude": b.longitude,
                "postcode": b.postcode,
                "floor_area_m2": b.floor_area_m2,
                "annual_heat_demand_kwh": b.annual_heat_demand_kwh,
                "peak_heat_demand_kw": b.peak_heat_demand_kw,
                "required_supply_temperature_c": b.required_supply_temperature_c,
                "current_fuel": b.current_fuel,
                "connection_potential": b.connection_potential,
                "distance_m": round(d, 1),
                "status": b.status,
            }
            for b, d in match.buildings
        ],
    }


@router.get("/{well_uuid}/evidence", summary="Evidence held for a well")
def get_well_evidence(
    well_uuid: uuid.UUID,
    db: DbSession,
    caller: CurrentCaller,
    critical_only: bool = False,
) -> dict[str, Any]:
    """Evidence and claims behind a well's conclusions.

    The point of this endpoint is answerability: every number on the detail page
    should be traceable from here to a source document.
    """
    stmt = select(Well).where(Well.id == well_uuid)
    stmt = scoped_well_query(stmt, caller)
    well = db.scalar(stmt)
    if well is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="well not found")

    evidence = qs.well_evidence(db, well.id)
    claims = qs.well_claims(db, well.id, critical_only=critical_only)

    return {
        "well_id": well.well_id,
        "evidence": [
            {
                "id": str(e.id),
                "source": e.source,
                "source_url": e.source_url,
                "source_title": e.source_title,
                "source_date": str(e.source_date) if e.source_date else None,
                "document_type": e.document_type,
                "reliability": e.reliability,
                "relevance": e.relevance,
                "quality": e.quality,
                "excerpt": e.excerpt,
                "page_reference": e.page_reference,
                "status": e.status,
                "is_mock": e.is_mock,
            }
            for e in evidence
        ],
        "claims": [
            {
                "id": str(c.id),
                "field_name": c.field_name,
                "claim": c.claim,
                "status": c.status,
                "confidence": c.confidence,
                "agent": c.agent,
                "is_critical": c.is_critical,
                "evidence_id": str(c.evidence_id) if c.evidence_id else None,
            }
            for c in claims
        ],
        "counts": {
            "evidence": len(evidence),
            "claims": len(claims),
            "sources": len({e.source for e in evidence}),
            "conflicting_sources": len(
                [c for c in claims if c.contradicted_by_id is not None]
            ),
        },
    }
