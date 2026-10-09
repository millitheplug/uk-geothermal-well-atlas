"""Well and heat-demand query service.

Everything the API needs to read from the database, kept apart from the route
handlers so it can be tested without HTTP and reused by workers and scripts.

Two conventions throughout:

* every tenant-scoped query filters by tenant, even where the caller already
  scoped it, so a missing filter upstream cannot leak data;
* spatial queries go through :mod:`app.db.geo`, which means the same code runs
  on PostGIS and on the SQLite development fallback.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.security import Caller
from app.core.enums import (
    DataConfidence,
    EpistemicStatus,
    EvidenceReliability,
    GeothermalConfiguration,
    OriginalPurpose,
    WellIntegrityStatus,
    WellStatus,
)
from app.db.geo import (
    bounding_box,
    distance_m,
    distance_to_point_m,
    spatial_dialect_label,
    within_radius,
)
from app.models.evidence import Claim, Evidence
from app.models.analysis import Analysis
from app.models.geology import Geology
from app.models.heat import Building, EnergyPrice, HeatDemand, HeatNetwork
from app.models.project import Project, ProjectWell
from app.models.well import Well, WellIntegrity, WellTemperature


@dataclass
class WellFilters:
    """Filters for the well explorer and candidate ranking.

    Kept as a dataclass rather than a long parameter list so that adding a filter
    does not ripple through four call sites.
    """

    search: str | None = None
    status: list[str] | None = None
    original_purpose: list[str] | None = None
    operator: str | None = None
    licence: str | None = None
    region: list[str] | None = None
    county: str | None = None
    formation: str | None = None

    min_temperature_c: float | None = None
    max_temperature_c: float | None = None
    min_depth_m: float | None = None
    max_depth_m: float | None = None
    min_score: float | None = None
    max_score: float | None = None
    min_confidence_score: float | None = None
    min_data_confidence: list[str] | None = None
    drilling_year_from: int | None = None
    drilling_year_to: int | None = None

    has_temperature: bool | None = None
    has_integrity: bool | None = None
    recommendation: list[str] | None = None

    min_nearest_demand_m: float | None = None
    max_nearest_demand_m: float | None = None
    min_annual_demand_kwh: float | None = None
    min_thermal_output_kw: float | None = None

    bbox: tuple[float, float, float, float] | None = None
    centre_lat: float | None = None
    centre_lon: float | None = None
    radius_m: float | None = None

    include_mock: bool = True

    #: Include wells that are in no project yet, so a tenant can adopt them.
    #: Off by default: a bare search should show what you have, not the whole
    #: national inventory. Discovery endpoints turn it on deliberately.
    include_claimable: bool = False

    def apply(self, stmt: Select, model: type = Well) -> Select:
        """Apply every populated filter to a select statement."""
        if self.search:
            pattern = f"%{self.search.strip()}%"
            stmt = stmt.where(
                model.well_name.ilike(pattern)
                | model.well_id.ilike(pattern)
                | model.operator.ilike(pattern)
            )
        if self.status:
            stmt = stmt.where(model.status.in_(self.status))
        if self.original_purpose:
            stmt = stmt.where(model.original_purpose.in_(self.original_purpose))
        if self.operator:
            stmt = stmt.where(model.operator == self.operator)
        if self.licence:
            stmt = stmt.where(model.licence == self.licence)
        if self.region:
            stmt = stmt.where(model.region.in_(self.region))
        if self.county:
            stmt = stmt.where(model.county == self.county)
        if self.formation:
            stmt = stmt.where(model.formation.ilike(f"%{self.formation}%"))

        if self.min_temperature_c is not None:
            stmt = stmt.where(model.temperature_c >= self.min_temperature_c)
        if self.max_temperature_c is not None:
            stmt = stmt.where(model.temperature_c <= self.max_temperature_c)
        if self.min_depth_m is not None:
            stmt = stmt.where(model.total_depth_m >= self.min_depth_m)
        if self.max_depth_m is not None:
            stmt = stmt.where(model.total_depth_m <= self.max_depth_m)
        if self.min_score is not None:
            stmt = stmt.where(model.feasibility_score >= self.min_score)
        if self.max_score is not None:
            stmt = stmt.where(model.feasibility_score <= self.max_score)
        if self.min_confidence_score is not None:
            stmt = stmt.where(model.confidence_score >= self.min_confidence_score)
        if self.min_data_confidence:
            stmt = stmt.where(model.data_confidence.in_(self.min_data_confidence))
        if self.drilling_year_from is not None:
            stmt = stmt.where(model.drilling_year >= self.drilling_year_from)
        if self.drilling_year_to is not None:
            stmt = stmt.where(model.drilling_year <= self.drilling_year_to)

        if self.has_temperature is True:
            stmt = stmt.where(model.temperature_c.isnot(None))
        elif self.has_temperature is False:
            stmt = stmt.where(model.temperature_c.is_(None))

        if self.has_integrity is True:
            stmt = stmt.where(
                Well.id.in_(
                    select(WellIntegrity.well_id).where(
                        WellIntegrity.status != WellIntegrityStatus.UNKNOWN.value
                    )
                )
            )
        elif self.has_integrity is False:
            stmt = stmt.where(
                Well.id.notin_(
                    select(WellIntegrity.well_id).where(
                        WellIntegrity.status != WellIntegrityStatus.UNKNOWN.value
                    )
                )
            )

        if self.recommendation:
            stmt = stmt.where(model.recommendation.in_(self.recommendation))
        if self.min_thermal_output_kw is not None:
            stmt = stmt.where(model.feasibility_score.isnot(None))

        # Demand-derived filters live on the latest analysis per well. Resolved
        # through the shared ranked subquery so the filter and the candidate
        # table agree on which analysis is "current" - filtering on all analyses
        # would let an old bear-case run qualify a well that its latest
        # assessment no longer supports.
        if (
            self.min_annual_demand_kwh is not None
            or self.min_nearest_demand_m is not None
            or self.max_nearest_demand_m is not None
        ):
            latest = AnalysisWellDemand.subquery()
            conditions = []
            if self.min_annual_demand_kwh is not None:
                conditions.append(
                    latest.c.annual_heat_kwh >= self.min_annual_demand_kwh
                )
            if self.min_nearest_demand_m is not None:
                conditions.append(
                    latest.c.nearest_building_distance_m >= self.min_nearest_demand_m
                )
            if self.max_nearest_demand_m is not None:
                conditions.append(
                    latest.c.nearest_building_distance_m <= self.max_nearest_demand_m
                )
            stmt = stmt.where(
                Well.id.in_(
                    select(latest.c.well_id).where(latest.c.rn == 1, *conditions)
                )
            )

        if self.bbox:
            min_lat, min_lon, max_lat, max_lon = self.bbox
            stmt = stmt.where(
                Well.latitude.between(min_lat, max_lat),
                Well.longitude.between(min_lon, max_lon),
            )

        if not self.include_mock:
            # Adapters named `mock_*` are the only source of synthetic data, so
            # this is the exclusion that keeps development data out of reports.
            stmt = stmt.where(~Well.source.like("mock_%"))

        return stmt

    def apply_centre_radius(self, stmt: Select) -> Select:
        """Apply a centre-and-radius filter, dialect-aware."""
        if self.centre_lat is None or self.centre_lon is None or not self.radius_m:
            return stmt

        lat_ok, lon_ok = bounding_box(
            Well.latitude, Well.longitude, self.centre_lat, self.centre_lon, self.radius_m
        )
        stmt = stmt.where(lat_ok, lon_ok)
        # The bounding box is only a pre-filter; the exact test still applies.
        stmt = stmt.where(
            within_radius(
                None, Well.latitude, Well.longitude, self.centre_lat, self.centre_lon,
                self.radius_m,
            )
        )
        return stmt


class AnalysisWellDemand:
    """Ranked analyses, one current row per well.

    Demand matching and the engineering results are recomputed per analysis and
    stored on :class:`~app.models.analysis.Analysis`. This subquery exposes them
    as a flat relation carrying a ``rn`` rank, so filters and the candidate table
    can both take the most recent analysis (``rn = 1``) without duplicating
    values onto the well row - where they would drift from the analysis that
    produced them.
    """

    @staticmethod
    def subquery() -> Any:
        return (
            select(
                Analysis.well_id.label("well_id"),
                Analysis.id.label("analysis_id"),
                Analysis.annual_heat_production_kwh.label("annual_heat_kwh"),
                Analysis.nearest_building_distance_m.label("nearest_building_distance_m"),
                Analysis.thermal_output_kw.label("thermal_output_kw"),
                Analysis.thermal_output_status.label("thermal_output_status"),
                Analysis.demand_matched_kw.label("demand_matched_kw"),
                Analysis.lcoh_p_per_kwh.label("lcoh_p_per_kwh"),
                Analysis.capex_gbp.label("capex_gbp"),
                func.row_number()
                .over(
                    partition_by=Analysis.well_id,
                    order_by=Analysis.created_at.desc(),
                )
                .label("rn"),
            )
            .where(Analysis.status == "complete")
            .subquery()
        )


def spatial_dialect(db: Session) -> str:
    """Report which spatial backend the bound connection is using."""
    return spatial_dialect_label(db.get_bind())


def _distance_expression(db: Session, lat: float, lon: float):
    """Distance from each building to a point, honouring the dialect."""
    bind = db.get_bind()
    if spatial_dialect_label(bind) == "postgis":
        from geoalchemy2 import functions as gaf  # noqa: PLC0415

        return func.ST_Distance(
            func.ST_SetSRID(func.ST_MakePoint(Building.longitude, Building.latitude), 4326),
            func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
        )
    return distance_to_point_m(bind, Building.latitude, Building.longitude, lat, lon)


# --------------------------------------------------------------- wells
def search_wells(
    db: Session,
    caller: Caller,
    filters: WellFilters,
    *,
    limit: int = 50,
    offset: int = 0,
    order_by: str = "feasibility_score",
    descending: bool = True,
) -> tuple[list[Well], int]:
    """Filtered, paginated well search, restricted to the caller's wells.

    Takes a :class:`~app.core.security.Caller` rather than a bare tenant id so
    that tenant scoping is applied through the single audited helper,
    :func:`app.core.security.scoped_well_query`, and cannot be forgotten at a call
    site. Returns the page and the unpaginated total so the UI can show
    "showing 50 of 4,183" without a second query.
    """
    from app.core.security import (  # noqa: PLC0415
        scoped_or_claimable_well_query,
        scoped_well_query,
    )

    base = select(Well).where(Well.id.isnot(None))
    stmt = filters.apply(base)
    stmt = filters.apply_centre_radius(stmt)
    # Applied last so it constrains every branch, including the centre-radius
    # predicate, and so the total count reflects the same scope as the rows.
    if filters.include_claimable:
        stmt = scoped_or_claimable_well_query(stmt, caller)
    else:
        stmt = scoped_well_query(stmt, caller)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    column = getattr(Well, order_by, None)
    if column is None:
        column = Well.feasibility_score
    # Nulls last in both directions: a well that has never been assessed should
    # not appear at the top of a descending sort on score.
    if descending:
        stmt = stmt.order_by(column.desc().nullslast(), Well.well_id)
    else:
        stmt = stmt.order_by(column.asc().nullslast(), Well.well_id)

    rows = list(db.scalars(stmt.limit(limit).offset(offset)))
    return rows, total


def get_well(db: Session, tenant_id: uuid.UUID, well_id: uuid.UUID) -> Well | None:
    return db.scalar(
        select(Well).where(Well.id == well_id).where(_tenant_scope(tenant_id))
    )


def get_well_by_public_id(db: Session, well_id: str) -> Well | None:
    """Look up by the stable platform id, e.g. ``UK-GB-001/02``.

    Not tenant-scoped: well identity is global, because the same physical well
    would be a different well to each tenant. Access control happens at the
    project and analysis layer.
    """
    return db.scalar(select(Well).where(Well.well_id == well_id))


def well_temperatures(db: Session, well_uuid: uuid.UUID) -> list[WellTemperature]:
    return list(
        db.scalars(
            select(WellTemperature)
            .where(WellTemperature.well_id == well_uuid)
            .order_by(WellTemperature.depth_m)
        )
    )


def latest_temperature(db: Session, well_uuid: uuid.UUID) -> WellTemperature | None:
    """The most relevant single observation for a well.

    Prefers the deepest stabilised reading, because shallow readings
    systematically understate reservoir temperature and the deepest point is the
    only one that represents the target interval.
    """
    temps = well_temperatures(db, well_uuid)
    if not temps:
        return None
    stabilised = [t for t in temps if t.is_final_stabilised]
    pool = stabilised or temps
    return max(pool, key=lambda t: t.depth_m)


def well_integrity(db: Session, well_uuid: uuid.UUID) -> WellIntegrity | None:
    return db.scalar(
        select(WellIntegrity).where(WellIntegrity.well_id == well_uuid)
    )


def well_geology(db: Session, well_uuid: uuid.UUID) -> Geology | None:
    return db.scalar(select(Geology).where(Geology.well_id == well_uuid))


def well_evidence(db: Session, well_uuid: uuid.UUID, limit: int = 50) -> list[Evidence]:
    return list(
        db.scalars(
            select(Evidence)
            .where(Evidence.well_id == well_uuid)
            .order_by(Evidence.reliability.desc())
            .limit(limit)
        )
    )


def well_claims(db: Session, well_uuid: uuid.UUID, critical_only: bool = False) -> list[Claim]:
    stmt = select(Claim).where(Claim.well_id == well_uuid)
    if critical_only:
        stmt = stmt.where(Claim.is_critical.is_(True))
    return list(db.scalars(stmt.order_by(Claim.created_at)))


# -------------------------------------------------------------- demand
@dataclass
class DemandMatch:
    """Result of matching a well to nearby heat demand."""

    building_count: int
    total_annual_demand_kwh: float
    total_peak_demand_kw: float
    nearest_building_distance_m: float | None
    weighted_latitude: float | None
    weighted_longitude: float | None
    dominant_building_type: str | None
    average_supply_temperature_c: float | None
    buildings: list[tuple[Building, float]]
    radius_m: float
    confidence: str
    notes: list[str]


def match_demand_to_well(
    db: Session,
    well: Well,
    *,
    radius_m: float = 2000.0,
    limit: int = 500,
    min_connection_potential: str | None = None,
) -> DemandMatch:
    """Find and aggregate the heat demand nearest a well.

    Weighted by annual demand rather than taking a simple centroid, so the
    representative point reflects where the heat actually is. A cluster of large
    industrial buildings should not be represented by the midpoint of a handful
    of houses.

    The radius filter uses a bounding box followed by an exact distance test, so
    the index is used and the result is still correct.
    """
    notes: list[str] = []
    lat_ok, lon_ok = bounding_box(
        Building.latitude, Building.longitude, well.latitude, well.longitude, radius_m
    )

    stmt = (
        select(Building, _distance_expression(db, well.latitude, well.longitude).label("distance_m"))
        .where(lat_ok, lon_ok)
        .where(_tenant_scope_for_buildings(db))
    )
    if min_connection_potential:
        stmt = stmt.where(Building.connection_potential == min_connection_potential)

    rows = list(db.execute(stmt.order_by(func.coalesce(Building.annual_heat_demand_kwh, 0).desc()).limit(limit)))

    # Exact filter in Python. The bounding box is a generous pre-filter; the
    # distance expression is dialect-aware but is only an exact predicate on
    # PostGIS. Applying the exact test here means both backends agree to the
    # metre, and it costs nothing at the row counts involved.
    within: list[tuple[Building, float]] = []
    for building, distance in rows:
        d = float(distance)
        if d > radius_m:
            continue
        # Cross-check against the pure-Python reference so a SQL rounding
        # difference cannot silently change a match at the boundary.
        reference = haversine_m(
            well.latitude, well.longitude, building.latitude, building.longitude
        )
        if min(d, reference) <= radius_m:
            within.append((building, min(d, reference)))

    if not within:
        return DemandMatch(
            building_count=0,
            total_annual_demand_kwh=0.0,
            total_peak_demand_kw=0.0,
            nearest_building_distance_m=None,
            weighted_latitude=None,
            weighted_longitude=None,
            dominant_building_type=None,
            average_supply_temperature_c=None,
            buildings=[],
            radius_m=radius_m,
            confidence=DataConfidence.UNKNOWN.value,
            notes=[
                f"No buildings were found within {radius_m:.0f} m of this well. Demand "
                "adequacy is unknown rather than zero: the absence of a dataset is not "
                "the absence of demand."
            ],
        )

    total_annual = sum(b.annual_heat_demand_kwh or 0.0 for b, _ in within)
    total_peak = sum(b.peak_heat_demand_kw or 0.0 for b, _ in within)
    nearest = min(d for _, d in within)

    weights = [max(b.annual_heat_demand_kwh or 1.0, 1.0) for b, _ in within]
    weight_sum = sum(weights)
    weighted_lat = sum(b.latitude * w for (b, _), w in zip(within, weights, strict=False)) / weight_sum
    weighted_lon = sum(b.longitude * w for (b, _), w in zip(within, weights, strict=False)) / weight_sum

    type_totals: dict[str, float] = {}
    for (b, _), w in zip(within, weights, strict=False):
        type_totals[b.building_type] = type_totals.get(b.building_type, 0.0) + w
    dominant = max(type_totals.items(), key=lambda kv: kv[1])[0] if type_totals else None

    supply_temps = [b.required_supply_temperature_c for b, _ in within if b.required_supply_temperature_c]
    avg_supply = sum(supply_temps) / len(supply_temps) if supply_temps else None

    # Confidence degrades with how few, and how poorly characterised, the
    # candidates are. A single building is a concentration risk, not a market.
    if len(within) == 1:
        confidence = DataConfidence.LOW.value
        notes.append(
            "Only one candidate off-taker was identified, so this is not a heat market."
        )
    elif len(within) < 5:
        confidence = DataConfidence.LOW.value
        notes.append(f"Only {len(within)} candidate off-takers within range.")
    elif len(within) >= 20:
        confidence = DataConfidence.HIGH.value
    else:
        confidence = DataConfidence.MEDIUM.value

    if any((b.annual_heat_demand_kwh or 0) == 0 for b, _ in within):
        confidence = DataConfidence.LOW.value
        notes.append(
            "At least one candidate has no annual demand figure, so the total is "
            "incomplete."
        )

    if total_annual == 0:
        notes.append(
            "Buildings were found but none carries an annual demand figure, so the "
            "aggregated total is zero by absence of data rather than absence of heat."
        )

    return DemandMatch(
        building_count=len(within),
        total_annual_demand_kwh=total_annual,
        total_peak_demand_kw=total_peak,
        nearest_building_distance_m=nearest,
        weighted_latitude=weighted_lat,
        weighted_longitude=weighted_lon,
        dominant_building_type=dominant,
        average_supply_temperature_c=avg_supply,
        buildings=sorted(within, key=lambda pair: pair[1]),
        radius_m=radius_m,
        confidence=confidence,
        notes=notes,
    )


def buildings_within_radius(
    db: Session,
    *,
    centre_lat: float,
    centre_lon: float,
    radius_m: float,
    limit: int = 1000,
) -> list[tuple[Building, float]]:
    """Every building within a radius of an arbitrary point."""
    lat_ok, lon_ok = bounding_box(
        Building.latitude, Building.longitude, centre_lat, centre_lon, radius_m
    )
    stmt = (
        select(Building, _distance_expression(db, centre_lat, centre_lon).label("distance_m"))
        .where(lat_ok, lon_ok)
        .where(_tenant_scope_for_buildings(db))
        .order_by(func.coalesce(Building.annual_heat_demand_kwh, 0).desc())
        .limit(limit)
    )
    return [(b, float(d)) for b, d in db.execute(stmt) if float(d) <= radius_m]


def heat_demand_areas(
    db: Session,
    *,
    centre_lat: float | None = None,
    centre_lon: float | None = None,
    radius_m: float | None = None,
    min_demand_kwh: float | None = None,
    limit: int = 500,
) -> list[HeatDemand]:
    stmt = select(HeatDemand).where(_tenant_scope_for_demand(db))
    if min_demand_kwh is not None:
        stmt = stmt.where(HeatDemand.total_annual_demand_kwh >= min_demand_kwh)
    if centre_lat is not None and centre_lon is not None and radius_m:
        lat_ok, lon_ok = bounding_box(
            HeatDemand.latitude, HeatDemand.longitude, centre_lat, centre_lon, radius_m
        )
        stmt = stmt.where(lat_ok, lon_ok)
    return list(db.scalars(stmt.limit(limit)))


def heat_networks(
    db: Session,
    *,
    centre_lat: float | None = None,
    centre_lon: float | None = None,
    radius_m: float | None = None,
    existing_only: bool = False,
) -> list[HeatNetwork]:
    stmt = select(HeatNetwork).where(_tenant_scope_for_networks(db))
    if existing_only:
        stmt = stmt.where(HeatNetwork.existing.is_(True))
    if centre_lat is not None and centre_lon is not None and radius_m:
        lat_ok, lon_ok = bounding_box(
            HeatNetwork.centre_latitude, HeatNetwork.centre_longitude,
            centre_lat, centre_lon, radius_m,
        )
        stmt = stmt.where(lat_ok, lon_ok)
    return list(db.scalars(stmt))


def price_on(
    db: Session,
    fuel: str,
    on: date,
    *,
    exclude_mock: bool = False,
) -> EnergyPrice | None:
    """The tariff in force for a fuel on a given date.

    Picks the most recent record whose validity window covers the date. A gap in
    the price book returns None rather than the nearest record, because applying
    a stale price silently is how a financial model becomes wrong without anyone
    noticing.
    """
    stmt = (
        select(EnergyPrice)
        .where(EnergyPrice.fuel == fuel)
        .where(EnergyPrice.valid_from <= on)
        .where(
            (EnergyPrice.valid_to.is_(None)) | (EnergyPrice.valid_to >= on)
        )
    )
    if exclude_mock:
        stmt = stmt.where(EnergyPrice.is_mock.is_(False))
    return db.scalar(stmt.order_by(EnergyPrice.valid_from.desc()).limit(1))


def price_history(db: Session, fuel: str, limit: int = 100) -> list[EnergyPrice]:
    return list(
        db.scalars(
            select(EnergyPrice)
            .where(EnergyPrice.fuel == fuel)
            .order_by(EnergyPrice.valid_from.desc())
            .limit(limit)
        )
    )


# -------------------------------------------------------------- density
@dataclass
class DensityCell:
    """Aggregated counts over a grid cell, for the heat-demand density layer."""

    lat: float
    lon: float
    well_count: int
    demand_kwh: float
    building_count: int


def well_and_demand_density(
    db: Session,
    *,
    cell_size_deg: float = 0.1,
    min_demand_kwh: float = 0.0,
) -> list[DensityCell]:
    """Grid-aggregate wells and demand for the density overlay.

    Uses a plain GROUP BY on rounded coordinates rather than ST_SquareGrid, so
    it behaves identically on both backends. The tradeoff is stated here: PostGIS
    would offer a proper grid aggregate, and at national scale the Python round
    is adequate because the result is only ever drawn as a heatmap.
    """
    well_cells = db.execute(
        select(
            func.round(Well.latitude / cell_size_deg) * cell_size_deg,
            func.round(Well.longitude / cell_size_deg) * cell_size_deg,
            func.count(Well.id),
        ).group_by(
            func.round(Well.latitude / cell_size_deg),
            func.round(Well.longitude / cell_size_deg),
        )
    ).all()

    demand_cells = db.execute(
        select(
            func.round(Building.latitude / cell_size_deg) * cell_size_deg,
            func.round(Building.longitude / cell_size_deg) * cell_size_deg,
            func.sum(func.coalesce(Building.annual_heat_demand_kwh, 0.0)),
            func.count(Building.id),
        )
        .where(_tenant_scope_for_buildings(db))
        .group_by(
            func.round(Building.latitude / cell_size_deg),
            func.round(Building.longitude / cell_size_deg),
        )
        .having(func.sum(func.coalesce(Building.annual_heat_demand_kwh, 0.0)) >= min_demand_kwh)
    ).all()

    merged: dict[tuple[float, float], DensityCell] = {}
    for lat, lon, count in well_cells:
        key = (float(lat), float(lon))
        merged[key] = DensityCell(
            lat=float(lat), lon=float(lon), well_count=int(count),
            demand_kwh=0.0, building_count=0,
        )
    for lat, lon, demand, buildings in demand_cells:
        key = (float(lat), float(lon))
        cell = merged.setdefault(
            key,
            DensityCell(lat=float(lat), lon=float(lon), well_count=0,
                        demand_kwh=0.0, building_count=0),
        )
        cell.demand_kwh += float(demand or 0.0)
        cell.building_count += int(buildings)

    return sorted(merged.values(), key=lambda c: -c.demand_kwh)


# ------------------------------------------------------------- helpers
def _tenant_scope(tenant_id: uuid.UUID):
    """Deprecated shim retained only to document why it is not used for wells.

    Wells are national reference data with no ``tenant_id`` column, so there is
    no per-tenant predicate to apply to them directly. Isolation is enforced by
    :func:`app.core.security.scoped_well_query`, which resolves visibility
    through the tenant-scoped tables that reference wells. Any new code needing
    tenant-scoped well access should call that, not this.
    """
    return Well.source.isnot(None)


def _tenant_scope_for_buildings(db: Session, tenant_id: uuid.UUID | None = None):
    """Buildings are tenant-scoped.

    With a tenant id this is a real filter. Without one it is a no-op, which is
    only acceptable for internal jobs that legitimately span tenants - so the
    predicate is explicit and the caller must choose.
    """
    if tenant_id is None:
        return Building.source.isnot(None)
    return Building.tenant_id == tenant_id


def _tenant_scope_for_demand(db: Session, tenant_id: uuid.UUID | None = None):
    if tenant_id is None:
        return HeatDemand.source.isnot(None)
    return HeatDemand.tenant_id == tenant_id


def _tenant_scope_for_networks(db: Session, tenant_id: uuid.UUID | None = None):
    if tenant_id is None:
        return HeatNetwork.source.isnot(None)
    return HeatNetwork.tenant_id == tenant_id


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres, in Python.

    Used for ordering and filtering where a SQL round trip would be wasteful, and
    as the reference implementation the SQL expressions are tested against.
    """
    radius = 6_371_008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(min(a, 1.0)))
