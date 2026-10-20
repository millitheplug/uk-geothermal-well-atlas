"""Geospatial and heat-demand endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession, spatial_dialect
from app.core.security import CurrentCaller
from app.schemas.well import (
    HeatCluster,
    MapFeature,
    MapFeatureCollection,
    NearbyBuilding,
)
from app.services import query_service as qs

router = APIRouter(prefix="/heat", tags=["heat"])

#: Cell size for clustering, in degrees. 0.01 deg is about 1.1 km, which matches
#: the scale at which a heat cluster is meaningful for district heating.
DEFAULT_CELL_DEG = 0.01

#: A cell is a cluster only if it holds at least this much annual demand.
#: Below roughly 50 MWh a group of buildings is not a district scheme.
MIN_CLUSTER_DEMAND_KWH = 50_000.0


@router.get("/buildings", response_model=list[NearbyBuilding], summary="Buildings near a point")
def nearby_buildings(
    db: DbSession,
    caller: CurrentCaller,
    lat: Annotated[float, Query(ge=49, le=62, description="Centre latitude")],
    lon: Annotated[float, Query(ge=-9, le=3, description="Centre longitude")],
    radius_m: Annotated[float, Query(gt=0, le=20_000)] = 2000.0,
    building_type: Annotated[list[str] | None, Query()] = None,
    min_demand_kwh: Annotated[float | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[NearbyBuilding]:
    """Buildings within a radius, ordered by demand.

    Distance is included on every row so the frontend can draw circles without a
    second request.
    """
    rows = qs.buildings_within_radius(
        db, centre_lat=lat, centre_lon=lon, radius_m=radius_m, limit=limit * 4
    )

    filtered = [
        (b, d)
        for b, d in rows
        if (not building_type or b.building_type in building_type)
        and (min_demand_kwh is None or (b.annual_heat_demand_kwh or 0) >= min_demand_kwh)
    ]

    return [
        NearbyBuilding(
            id=b.id,
            building_type=b.building_type,
            latitude=b.latitude,
            longitude=b.longitude,
            postcode=b.postcode,
            floor_area_m2=b.floor_area_m2,
            annual_heat_demand_kwh=b.annual_heat_demand_kwh,
            peak_heat_demand_kw=b.peak_heat_demand_kw,
            required_supply_temperature_c=b.required_supply_temperature_c,
            current_fuel=b.current_fuel,
            connection_potential=b.connection_potential,
            distance_m=round(d, 1),
        )
        for b, d in filtered[:limit]
    ]


@router.get("/buildings/map", response_model=MapFeatureCollection, summary="Building points")
def building_map_features(
    db: DbSession,
    caller: CurrentCaller,
    centre_lat: Annotated[float | None, Query(ge=49, le=62)] = None,
    centre_lon: Annotated[float | None, Query(ge=-9, le=3)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=50_000)] = None,
    min_demand_kwh: Annotated[float | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=20_000)] = 8000,
) -> MapFeatureCollection:
    """GeoJSON points for the heat-demand layer."""
    if centre_lat is not None and centre_lon is not None and radius_m:
        rows = qs.buildings_within_radius(
            db,
            centre_lat=centre_lat,
            centre_lon=centre_lon,
            radius_m=radius_m,
            limit=limit,
        )
    else:
        rows = []

    features = [
        MapFeature(
            geometry={"type": "Point", "coordinates": [b.longitude, b.latitude]},
            properties={
                "id": str(b.id),
                "building_type": b.building_type,
                "annual_heat_demand_kwh": b.annual_heat_demand_kwh,
                "peak_heat_demand_kw": b.peak_heat_demand_kw,
                "required_supply_temperature_c": b.required_supply_temperature_c,
                "connection_potential": b.connection_potential,
                "current_fuel": b.current_fuel,
                "distance_m": round(d, 1),
                "status": b.status,
            },
        )
        for b, d in rows
        if min_demand_kwh is None or (b.annual_heat_demand_kwh or 0) >= min_demand_kwh
    ]

    return MapFeatureCollection(features=features, spatial_dialect=spatial_dialect(db))


@router.get("/clusters", response_model=list[HeatCluster], summary="Potential heat clusters")
def heat_clusters(
    db: DbSession,
    caller: CurrentCaller,
    cell_deg: Annotated[float, Query(gt=0.001, le=1.0)] = DEFAULT_CELL_DEG,
    min_demand_kwh: Annotated[float, Query(ge=0)] = MIN_CLUSTER_DEMAND_KWH,
    nearest_wells: bool = True,
) -> list[HeatCluster]:
    """Grid-clustered heat demand, with the nearest well for each cluster.

    Uses a rectangular grid rather than ST_ClusterDBSCAN so the result is
    identical on both spatial backends. The tradeoff is stated: a grid does not
    respect the shape of a real cluster and will split an elongated one. That is
    acceptable for a screening overlay and keeps development and production
    consistent, which matters more than cluster purity at this stage.
    """
    cells = qs.well_and_demand_density(db, cell_size_deg=cell_deg, min_demand_kwh=0.0)

    demand_cells = [c for c in cells if c.demand_kwh >= min_demand_kwh]

    # Well positions, so each cluster can be attributed to its nearest candidate.
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.well import Well  # noqa: PLC0415

    well_rows = db.execute(
        select(
            Well.well_id,
            Well.latitude,
            Well.longitude,
            Well.feasibility_score,
            Well.id,
        )
    ).all()

    clusters: list[HeatCluster] = []
    for index, cell in enumerate(sorted(demand_cells, key=lambda c: -c.demand_kwh)):
        nearest_id: str | None = None
        nearest_uuid: uuid.UUID | None = None
        nearest_distance: float | None = None

        if nearest_wells and well_rows:
            # The publisher's id is unique, so it decides any tie before the
            # score or UUID is ever compared.
            distances = [
                (qs.haversine_m(cell.lat, cell.lon, lat, lon), well_id, score, well_uuid)
                for well_id, lat, lon, score, well_uuid in well_rows
            ]
            best = min(distances)
            nearest_distance = best[0]
            # Only attribute a cluster to a well within a workable connection
            # distance; beyond about 3 km the pipe cost rules the pair out.
            if best[0] <= 3000.0:
                nearest_id = best[1]
                nearest_uuid = best[3]

        # Cluster radius from the cell diagonal.
        radius = qs.haversine_m(cell.lat, cell.lon, cell.lat + cell_deg, cell.lon) / 2.0

        clusters.append(
            HeatCluster(
                cluster_id=f"cluster-{index + 1}",
                building_count=cell.building_count,
                total_annual_demand_kwh=cell.demand_kwh,
                total_peak_demand_kw=cell.demand_kwh / 1000.0 * 0.18,
                centroid_latitude=cell.lat,
                centroid_longitude=cell.lon,
                radius_m=radius,
                nearest_well_id=nearest_id,
                nearest_well_uuid=nearest_uuid,
                nearest_well_distance_m=round(nearest_distance, 1) if nearest_distance else None,
                is_clustered_with_postgis=False,
            )
        )

    return clusters


@router.get("/density", summary="Well and heat-demand density grid")
def density_grid(
    db: DbSession,
    caller: CurrentCaller,
    cell_deg: Annotated[float, Query(gt=0.001, le=1.0)] = 0.1,
    min_demand_kwh: Annotated[float, Query(ge=0)] = 0.0,
) -> dict[str, Any]:
    """Aggregated counts per grid cell, for the density overlay.

    The UI renders this as two superimposed heatmaps: well density, which shows
    where the resource documentation is, and demand density, which shows where
    the customers are. Where they do not overlap is the interesting part.
    """
    cells = qs.well_and_demand_density(
        db, cell_size_deg=cell_deg, min_demand_kwh=min_demand_kwh
    )

    return {
        "cell_deg": cell_deg,
        "cells": [
            {
                "latitude": c.lat,
                "longitude": c.lon,
                "well_count": c.well_count,
                "building_count": c.building_count,
                "demand_kwh": c.demand_kwh,
            }
            for c in cells
        ],
        "count": len(cells),
        "totals": {
            "wells": sum(c.well_count for c in cells),
            "buildings": sum(c.building_count for c in cells),
            "demand_gwh": sum(c.demand_kwh for c in cells) / 1e6,
        },
        "spatial_dialect": spatial_dialect(db),
    }


@router.get("/corridors", summary="Indicative network corridors to nearest demand")
def network_corridors(
    db: DbSession,
    caller: CurrentCaller,
    limit_wells: Annotated[int, Query(ge=1, le=500)] = 100,
    max_distance_m: Annotated[float, Query(gt=0, le=50_000)] = 5000.0,
    min_demand_kwh: Annotated[float, Query(ge=0)] = 500_000.0,
) -> dict[str, Any]:
    """Straight-line corridors from wells to their nearest meaningful demand.

    **Indicative only.** These are not routes: they ignore obstacles, land
    ownership, existing utilities and wayleaves, and a straight line almost never
    coincides with a buildable pipeline. They exist to show which wells have a
    short enough connection to be worth a route survey.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.well import Well  # noqa: PLC0415

    wells = db.execute(
        select(Well.id, Well.well_id, Well.well_name, Well.latitude, Well.longitude, Well.feasibility_score)
        .where(Well.feasibility_score.isnot(None))
        .order_by(Well.feasibility_score.desc())
        .limit(limit_wells)
    ).all()

    corridors: list[dict[str, Any]] = []
    total_length = 0.0

    for well_id, well_ref, name, wlat, wlon, score in wells:
        buildings = qs.buildings_within_radius(
            db, centre_lat=wlat, centre_lon=wlon, radius_m=max_distance_m, limit=800
        )
        meaningful = [
            (b, d)
            for b, d in buildings
            if (b.annual_heat_demand_kwh or 0) >= min_demand_kwh
        ]
        if not meaningful:
            continue

        # Connect to the nearest significant demand, not the nearest building:
        # a single house 200 m away is not a heat network anchor.
        target, distance = min(meaningful, key=lambda pair: pair[1])
        total_length += distance

        corridors.append(
            {
                "well_id": well_ref,
                "well_name": name,
                "well_uuid": str(well_id),
                "feasibility_score": score,
                "target_building_id": str(target.id),
                "target_demand_kwh": target.annual_heat_demand_kwh,
                "distance_m": round(distance, 1),
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[wlon, wlat], [target.longitude, target.latitude]],
                },
                "indicative": True,
                "note": (
                    "Straight-line indication only. Not a route: ground conditions, "
                    "utilities, easements and land ownership are all unassessed."
                ),
            }
        )

    return {
        "corridors": corridors,
        "count": len(corridors),
        "total_straight_line_length_km": round(total_length / 1000.0, 2),
        "max_distance_m": max_distance_m,
        "caveat": (
            "Total length is the sum of straight lines and therefore understates the "
            "real pipeline route by a substantial margin. Use it to compare wells, "
            "not to estimate pipe cost."
        ),
        "spatial_dialect": spatial_dialect(db),
    }


@router.get("/demand-summary", summary="Demand breakdown by building type and fuel")
def demand_summary(db: DbSession, caller: CurrentCaller) -> dict[str, Any]:
    """Aggregate demand by building type and current fuel.

    Useful as a screening signal on its own: a district dominated by oil-fired
    homes has a different upgrade story from one dominated by gas, and the
    connection cost of the former is much higher.
    """
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.models.heat import Building  # noqa: PLC0415

    by_type = db.execute(
        select(Building.building_type, func.count(), func.sum(Building.annual_heat_demand_kwh))
        .group_by(Building.building_type)
    ).all()

    by_fuel = db.execute(
        select(Building.current_fuel, func.count(), func.sum(Building.annual_heat_demand_kwh))
        .group_by(Building.current_fuel)
    ).all()

    by_potential = db.execute(
        select(Building.connection_potential, func.count())
        .group_by(Building.connection_potential)
    ).all()

    totals = db.execute(
        select(
            func.count(),
            func.sum(Building.annual_heat_demand_kwh),
            func.sum(Building.peak_heat_demand_kw),
        )
    ).one()

    def _key(value: Any) -> str:
        return str(value) if value not in (None, "") else "unknown"

    return {
        "by_building_type": {
            _key(t): {"count": int(c), "demand_kwh": float(d or 0)}
            for t, c, d in by_type
        },
        "by_fuel": {
            _key(f): {"count": int(c), "demand_kwh": float(d or 0)}
            for f, c, d in by_fuel
        },
        "by_connection_potential": {
            _key(p): int(c) for p, c in by_potential
        },
        "totals": {
            "buildings": int(totals[0] or 0),
            "annual_demand_gwh": float(totals[1] or 0) / 1e6,
            "peak_demand_kw": float(totals[2] or 0),
        },
        "caveat": (
            "Demand figures are modelled from building attributes, not metered. A "
            "building with no recorded demand contributes zero here, which is an "
            "absence of data rather than an absence of heat."
        ),
    }
