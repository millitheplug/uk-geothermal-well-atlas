"""Dashboard and candidate-ranking endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.agents.orchestrator import STAGE_ORDER
from app.api.deps import DbSession, Pagination
from app.core.enums import DataConfidence, EpistemicStatus, Recommendation, WellStatus
from app.core.security import CurrentCaller
from app.engineering.scoring import WEIGHTS
from app.models.analysis import Analysis
from app.models.heat import Building
from app.models.well import Well
from app.schemas.well import (
    CandidateRow,
    CandidateTable,
    NationalDashboard,
    RiskCategory,
)
from app.services import query_service as qs

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

#: Recommendations counted as "high potential".
HIGH_POTENTIAL = {Recommendation.HIGH_PRIORITY.value, Recommendation.MEDIUM_PRIORITY.value}

#: Confidence bands that mean the well needs more data before a decision.
NEEDS_DATA_BANDS = {
    DataConfidence.LOW.value,
    DataConfidence.VERY_LOW.value,
    DataConfidence.UNKNOWN.value,
}


@router.get("/national", response_model=NationalDashboard, summary="National headline figures")
def national_dashboard(
    db: DbSession,
    caller: CurrentCaller,
    include_mock: Annotated[bool, Query()] = True,
) -> NationalDashboard:
    """Headline counts and aggregates for the national view.

    Every aggregate distinguishes zero from unknown. A national mean temperature
    over the wells that have one is returned with a null, not a zero, when no
    well has a temperature at all - and the caveat says which case applies.
    """
    # Filters must be applied to the inner select, never to a query that
    # already selects FROM the subquery: adding a `Well.*` predicate there
    # re-introduces the wells table and produces a cartesian product.
    # The subquery projects the columns the aggregates need, not just the id, so
    # downstream queries can aggregate from it without reintroducing `wells` and
    # creating a cartesian product.
    def filtered(*conditions: Any):
        stmt = select(
            Well.id,
            Well.temperature_c,
            Well.total_depth_m,
            Well.feasibility_score,
        )
        if not include_mock:
            stmt = stmt.where(~Well.source.like("mock_%"))
        for condition in conditions:
            stmt = stmt.where(condition)
        return stmt.subquery()

    base = filtered()

    total = db.scalar(select(func.count()).select_from(base)) or 0

    def count_where(*conditions: Any) -> int:
        sub = filtered(*conditions)
        return int(db.scalar(select(func.count()).select_from(sub)) or 0)

    with_temp = count_where(Well.temperature_c.isnot(None))
    without_temp = total - with_temp

    # A "candidate" is a well that clears the minimum screen: it has a
    # temperature measurement and a non-UNKNOWN integrity assessment. A well
    # missing either cannot be screened at all, so counting it as a candidate
    # would overstate how much of the resource has actually been assessed.
    from app.models.well import WellIntegrity

    assessed_integrity = select(WellIntegrity.well_id).where(
        WellIntegrity.status != "unknown"
    )
    candidates = db.scalar(
        select(func.count()).select_from(
            filtered(
                Well.temperature_c.isnot(None),
                Well.id.in_(assessed_integrity),
            )
        )
    ) or 0

    high_potential = count_where(Well.recommendation.in_(HIGH_POTENTIAL))
    needs_data = count_where(Well.data_confidence.in_(NEEDS_DATA_BANDS))

    # Averages aggregate the subquery's own columns. Selecting `Well.temperature_c`
    # while the FROM is the subquery would re-introduce the wells table and give a
    # cartesian product, which silently averages the whole table instead.
    temp_rows = filtered(Well.temperature_c.isnot(None))
    depth_rows = filtered(Well.total_depth_m.isnot(None))
    avg_temp = db.scalar(select(func.avg(temp_rows.c.temperature_c)))
    avg_depth = db.scalar(select(func.avg(depth_rows.c.total_depth_m)))
    # Thermal capacity is not stored on the well; it comes from the analyses.
    capacity = _total_estimated_capacity(db, include_mock)
    demand_opportunity = _demand_opportunity(db, include_mock)

    # Breakdowns group the well columns themselves, so they read from `Well`
    # under the same include_mock scope rather than from the id subquery.
    breakdowns = {
        "recommendation": _breakdown(db, include_mock, Well.recommendation),
        "confidence": _breakdown(db, include_mock, Well.data_confidence),
        "status": _breakdown(db, include_mock, Well.status),
        "purpose": _breakdown(db, include_mock, Well.original_purpose),
        "region": _breakdown(db, include_mock, Well.region),
    }

    histogram = _score_histogram(db, filtered)

    caveats = [
        "Thermal capacity is a sum of ESTIMATES. No flow test has been performed on "
        "any well in this dataset unless its evidence explicitly states otherwise.",
        "Feasibility scores exist only for wells that have been analysed. Wells with no "
        "score are not non-candidates; they are unassessed.",
    ]
    if without_temp:
        caveats.append(
            f"{without_temp} of {total} wells have no temperature measurement. Their "
            "thermal potential is unknown, not zero, and they are excluded from the "
            "average temperature."
        )
    if include_mock:
        caveats.insert(
            0,
            "This view includes synthetic development data. No well shown here "
            "corresponds to a real UK borehole.",
        )

    return NationalDashboard(
        total_wells=total,
        wells_with_temperature=with_temp,
        wells_without_temperature=without_temp,
        candidate_wells=candidates,
        high_potential_wells=high_potential,
        average_temperature_c=avg_temp,
        average_depth_m=avg_depth,
        total_estimated_thermal_capacity_mwt=(
            capacity / 1000.0 if capacity is not None else None
        ),
        total_estimated_thermal_capacity_status=EpistemicStatus.ESTIMATE.value,
        nearby_heat_demand_opportunity_gwh=demand_opportunity,
        wells_needing_more_data=needs_data,
        recommendation_breakdown=breakdowns["recommendation"],
        confidence_breakdown=breakdowns["confidence"],
        status_breakdown=breakdowns["status"],
        purpose_breakdown=breakdowns["purpose"],
        region_breakdown=breakdowns["region"],
        score_histogram=histogram,
        risk_category_totals=_risk_totals(db, caller),
        is_mock=include_mock,
        caveats=caveats,
    )


def _total_estimated_capacity(db: DbSession, include_mock: bool) -> float | None:
    """Sum the latest analysis thermal output per well, in kW.

    A plain SUM over all analyses would double-count any well assessed more than
    once - and wells routinely are, under bear, base and bull scenarios. This
    counts each well once, by its most recent analysis.
    """
    latest = qs.AnalysisWellDemand.subquery()
    stmt = (
        select(func.sum(latest.c.thermal_output_kw))
        .where(latest.c.rn == 1, latest.c.thermal_output_kw.isnot(None))
    )
    if not include_mock:
        # Correlated subquery rather than NOT IN: a well with no analysis at all
        # has a NULL well_id in the ranked set, and NOT IN over a NULL returns no
        # rows, which would silently zero the total.
        stmt = stmt.where(
            latest.c.well_id.in_(select(Well.id).where(Well.source.notlike("mock_%")))
        )
    return db.scalar(stmt)


def _demand_opportunity(db: DbSession, include_mock: bool) -> float | None:
    """Heat demand within 5 km of at least one well, in GWh.

    Deliberately not the national total: a national demand figure would say
    nothing about whether any of it is reachable from a well.
    """
    wells = db.execute(select(Well.id, Well.latitude, Well.longitude)).all()
    if not wells:
        return None

    buildings = db.execute(
        select(Building.id, Building.latitude, Building.longitude, Building.annual_heat_demand_kwh)
    ).all()

    if not buildings:
        return None

    total = 0.0
    for _bid, blat, blon, demand in buildings:
        if not demand:
            continue
        for _wid, wlat, wlon in wells:
            if qs.haversine_m(wlat, wlon, blat, blon) <= 5000.0:
                total += float(demand)
                break

    return total / 1e9


def _breakdown(db: DbSession, include_mock: bool, column: Any) -> dict[str, int]:
    """Counts of wells grouped by one of their own columns.

    Scoped the same way as every other figure on this endpoint, so the parts
    always add up to the total the reader can see.
    """
    stmt = select(column, func.count())
    if not include_mock:
        stmt = stmt.where(~Well.source.like("mock_%"))
    rows = db.execute(stmt.group_by(column)).all()
    return {
        str(key if key is not None else "unknown"): int(value) for key, value in rows
    }


def _score_histogram(db: DbSession, filtered, bins: int = 10) -> list[dict[str, Any]]:
    """Score distribution in ten-point bands.

    Banded rather than raw so the chart is readable and so a handful of wells at
    a precise score do not dominate it. Nulls are reported as their own bucket:
    an unassessed well is not a low-scoring well.
    """
    unassessed = db.scalar(
        select(func.count()).select_from(filtered(Well.feasibility_score.is_(None)))
    ) or 0

    buckets = [
        {
            "range": f"{i * 10}-{(i + 1) * 10}",
            "lower": i * 10,
            "upper": (i + 1) * 10,
            "count": 0,
        }
        for i in range(bins)
    ]

    # Read the score from the subquery, not from Well: mixing the two FROM
    # sources would pair every scored well with every unscored one.
    scored = filtered(Well.feasibility_score.isnot(None))
    for score in db.execute(select(scored.c.feasibility_score)):
        index = min(int(score[0] // 10), bins - 1)
        buckets[index]["count"] += 1

    if unassessed:
        buckets.append(
            {
                "range": "not assessed",
                "lower": None,
                "upper": None,
                "count": int(unassessed),
            }
        )
    return buckets


def _risk_totals(db: DbSession, caller: CurrentCaller) -> dict[str, int]:
    """Count of risks per category across the caller's analyses."""
    from app.models.analysis import Risk

    rows = db.execute(
        select(Risk.category, func.count())
        .join(Analysis, Analysis.id == Risk.analysis_id)
        .where(Analysis.tenant_id == caller.tenant_id)
        .group_by(Risk.category)
    ).all()
    return {str(category): int(count) for category, count in rows}


@router.get("/candidates", response_model=CandidateTable, summary="Ranked candidate table")
def candidate_table(
    db: DbSession,
    caller: CurrentCaller,
    page: Pagination,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    min_confidence_score: Annotated[float | None, Query(ge=0, le=1)] = None,
    min_temperature_c: Annotated[float | None, Query(ge=0, le=400)] = None,
    max_temperature_c: Annotated[float | None, Query(ge=0, le=400)] = None,
    min_depth_m: Annotated[float | None, Query(ge=0)] = None,
    max_depth_m: Annotated[float | None, Query(ge=0)] = None,
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    region: Annotated[list[str] | None, Query()] = None,
    recommendation: Annotated[list[str] | None, Query()] = None,
    max_nearest_demand_m: Annotated[float | None, Query(ge=0)] = None,
    min_annual_demand_kwh: Annotated[float | None, Query(ge=0)] = None,
    min_data_confidence: Annotated[list[str] | None, Query()] = None,
    has_temperature: Annotated[bool | None, Query()] = None,
    has_integrity: Annotated[bool | None, Query()] = None,
    centre_lat: Annotated[float | None, Query(ge=49, le=62)] = None,
    centre_lon: Annotated[float | None, Query(ge=-9, le=3)] = None,
    radius_m: Annotated[float | None, Query(gt=0, le=500_000)] = None,
    include_mock: bool = True,
    order_by: Annotated[str, Query()] = "feasibility_score",
    descending: Annotated[bool, Query()] = True,
) -> CandidateTable:
    """The candidate ranking table.

    Joined against the latest analysis per well so every column the specification
    asks for comes from one consistent row. Ranking basis is echoed back so the
    UI can label the sorted column.
    """
    filters = qs.WellFilters(
        min_score=min_score,
        min_confidence_score=min_confidence_score,
        min_temperature_c=min_temperature_c,
        max_temperature_c=max_temperature_c,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        status=status_filter,
        region=region,
        recommendation=recommendation,
        max_nearest_demand_m=max_nearest_demand_m,
        min_annual_demand_kwh=min_annual_demand_kwh,
        min_data_confidence=min_data_confidence,
        has_temperature=has_temperature,
        has_integrity=has_integrity,
        centre_lat=centre_lat,
        centre_lon=centre_lon,
        radius_m=radius_m,
        include_mock=include_mock,
    )

    rows, total = qs.search_wells(
        db, caller, filters,
        limit=page["limit"], offset=page["offset"],
        order_by=order_by, descending=descending,
    )

    analyses = _latest_analyses_by_well(db, [r.id for r in rows])

    items = [
        CandidateRow(
            rank=page["offset"] + index + 1,
            well_id=row.well_id,
            well_uuid=row.id,
            well_name=row.well_name,
            latitude=row.latitude,
            longitude=row.longitude,
            region=row.region,
            status=row.status,
            total_depth_m=row.total_depth_m,
            temperature_c=row.temperature_c,
            temperature_status=row.temperature_status,
            temperature_confidence=row.temperature_confidence,
            nearest_building_distance_m=(
                analyses[row.id].nearest_building_distance_m if row.id in analyses else None
            ),
            annual_demand_kwh=(
                analyses[row.id].annual_heat_production_kwh if row.id in analyses else None
            ),
            thermal_output_kw=(
                analyses[row.id].thermal_output_kw if row.id in analyses else None
            ),
            thermal_output_status=(
                analyses[row.id].thermal_output_status if row.id in analyses else "UNKNOWN"
            ),
            capex_gbp=analyses[row.id].capex_gbp if row.id in analyses else None,
            lcoh_p_per_kwh=analyses[row.id].lcoh_p_per_kwh if row.id in analyses else None,
            feasibility_score=row.feasibility_score,
            confidence_score=row.confidence_score,
            recommendation=row.recommendation,
            is_mock=(row.source or "").startswith("mock_"),
        )
        for index, row in enumerate(rows)
    ]

    return CandidateTable(
        items=items,
        total=total,
        limit=page["limit"],
        offset=page["offset"],
        ranking_basis=order_by,
        includes_mock_data=include_mock and any(i.is_mock for i in items),
    )


def _latest_analyses_by_well(db: DbSession, well_ids: list[uuid.UUID]) -> dict[uuid.UUID, Analysis]:
    """The most recent complete analysis for each of the given wells."""
    if not well_ids:
        return {}

    # `db.scalars`, not `db.execute`: execute over an ORM select returns rows of
    # scalar ids, so `analysis.well_id` would fail with a KeyError on the column
    # name rather than the object.
    ordered = db.scalars(
        select(Analysis)
        .where(Analysis.well_id.in_(well_ids), Analysis.status == "complete")
        .order_by(Analysis.well_id, Analysis.created_at.desc())
    )

    latest: dict[uuid.UUID, Analysis] = {}
    for analysis in ordered:
        latest.setdefault(analysis.well_id, analysis)
    return latest


@router.get("/summary", summary="Pipeline stage summary and scoring weights")
def pipeline_summary(caller: CurrentCaller) -> dict[str, Any]:
    """The nine assessment stages and the weights used to combine them.

    Exposed so the UI can explain the score without duplicating the weighting in
    TypeScript, which would inevitably drift from the backend.
    """
    return {
        "stages": [
            {"stage": str(stage), "order": index + 1}
            for index, stage in enumerate(STAGE_ORDER)
        ],
        "weights": dict(WEIGHTS),
        "weights_sum": sum(WEIGHTS.values()),
        "recommendation_levels": [level.value for level in Recommendation],
        "confidence_bands": [band.value for band in DataConfidence],
        "well_statuses": [s.value for s in WellStatus],
        "risk_categories": [c.value for c in RiskCategory],
    }
