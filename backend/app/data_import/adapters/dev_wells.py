"""Development well dataset.

**Every value in this module is synthetic.** Names, operators, licences,
coordinates, depths and temperatures are invented. They are plausible - a
Cornwall slate-hosted gas well really can be 1,800 m deep at 92 degC - because
plausibility is what makes the engineering path exercisable, but no row here
corresponds to a real borehole and none of it may be presented as production
data.

Every row is stamped ``is_mock=True`` at the dataset level and ``source``
beginning ``mock_`` at the row level, and both are surfaced in the API so the
frontend can watermark it. See ``docs/data-sources.md`` for how to swap in the
real NSTA download without touching the application.

The spread is deliberate. The set contains wells that should score highly, wells
that should score poorly, and wells whose score must be suppressed because the
evidence is thin - because a sample set where everything is a good candidate
tests almost nothing about the scoring.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from app.core.enums import (
    EpistemicStatus,
    WellIntegrityStatus,
)

#: Fixed seed. A development dataset that changes between runs makes every
#: regression test and every screenshot non-reproducible.
SEED = 20260908

#: Reference "today" for recency calculations, so the dataset does not drift as
#: real time passes.
REFERENCE_DATE = date(2026, 9, 8)


def _rng(seed: int = SEED) -> random.Random:
    return random.Random(seed)


# (well_id, name, operator, lat, lon, county, region, licence, year, purpose,
#  depth_m, temperature_c, temperature_method, status, formation, integrity,
#  casing, chemistry, salinity, ph, scaling)
#: The canonical well list. Hand-authored rather than generated so the intended
#: spread of cases is explicit and reviewable.
WELL_SPECS: tuple[tuple[Any, ...], ...] = (
    # ---- strong candidates: hot, deep, intact, near demand --------------
    (
        "UK-MOCK-CRN-001", "Cornwall Geothermal Trial 1", "Example Offshore Energy",
        50.2660, -5.0500, "Cornwall", "South West", "UK-OG-450/1", 1987,
        "gas", 2100.0, 94.0, "static_bht", "suspended", "Carboniferous Slate",
        "good_condition", True, None, 42.0, 6.9, "low",
    ),
    (
        "UK-MOCK-WLN-002", "Wealden Capture Test 4", "Southern Gas plc",
        51.1180, 0.2900, "East Sussex", "South East", "UK-OG-220/7", 1993,
        "gas", 1650.0, 88.0, "static_bht", "producing", "Hastings Beds Sandstone",
        "good_condition", True, None, 55.0, 7.1, "low",
    ),
    (
        "UK-MOCK-YOR-003", "Yorkshire Coalbed Methane 12", "Northern Energy Ltd",
        53.7900, -1.5500, "West Yorkshire", "Yorkshire and the Humber", "UK-OG-110/3",
        1996, "coalbed_methane", 980.0, 58.0, "production_log", "plugged_abandoned",
        "Middle Coal Measures", "partially_mechanical", True, None, 68.0, 6.4, "moderate",
    ),
    (
        "UK-MOCK-LAN-004", "Lancashire Deep Test 2", "Example Petroleum",
        53.5400, -2.6400, "Lancashire", "North West", "UK-OG-440/5", 1979,
        "oil", 2450.0, 91.0, "static_bht", "non_producing", "Manchester Marlstone",
        "partially_mechanical", True, None, 38.0, 6.8, "low",
    ),
    # ---- moderate: hot but cold-chain, or near but shallow --------------
    (
        "UK-MOCK-CHE-005", "Cheshire Stratigraphic 8", "Example Petroleum",
        53.2500, -2.6800, "Cheshire", "North West", "UK-OG-442/8", 1981,
        "exploration", 760.0, 51.0, "regional_estimate", "abandoned",
        "Sherwood Sandstone", "abandoned_no_access", False, None, None, None, None,
    ),
    (
        "UK-MOCK-NTH-006", "Northumberland Waterbore 3", "Northumbria Water",
        55.1300, -1.7600, "Northumberland", "North East", "UK-OG-130/2", 1991,
        "water_abstraction", 420.0, 44.0, "max_dynamic", "abandoned",
        "Carboniferous Limestone", "abandoned_no_access", False, None, 12.0, 7.4, "low",
    ),
    (
        "UK-MOCK-WLS-007", "Wales Oil Exploration 21", "Example Exploration",
        51.6800, -3.4400, "Powys", "Wales", "UK-OG-440/11", 1974,
        "oil", 1380.0, 79.0, "circulation_test", "plugged_abandoned",
        "Dolomite Sandstone", "poor_unknown", False, None, 88.0, 5.8, "high",
    ),
    (
        "UK-MOCK-DEV-008", "Devon Oil Field 19", "Southwest Petroleum",
        50.7200, -3.5300, "Devon", "South West", "UK-OG-451/6", 1969,
        "oil", 1720.0, 84.0, "static_bht", "plugged_abandoned",
        "Bideford Formation", "partially_mechanical", True, None, 62.0, 6.2, "moderate",
    ),
    # ---- suppressed by weak evidence: the interesting cases --------------
    (
        "UK-MOCK-KEN-009", "Kent Wealden Appraisal 6", "Southern Gas plc",
        51.3300, 0.5400, "Kent", "South East", "UK-OG-221/4", 1965,
        "gas", 1950.0, None, None, "abandoned", "Hastings Beds Sandstone",
        "poor_unknown", False, None, None, None, None,
    ),
    (
        "UK-MOCK-HAM-010", "Hampshire Basin Test 1", "Example Exploration",
        50.9600, -1.4000, "Hampshire", "South East", "UK-OG-222/1", 1972,
        "exploration", 1100.0, None, None, "abandoned", "Bracklesham Beds",
        None, False, None, None, None, None,
    ),
    # ---- conflicting sources --------------------------------------------
    (
        "UK-MOCK-YOR-011", "Yorkshire Appraisal 7", "Northern Energy Ltd",
        53.8200, -1.4200, "North Yorkshire", "Yorkshire and the Humber", "UK-OG-112/5",
        1988, "gas", 2050.0, 74.0, "regional_estimate", "non_producing",
        "Carboniferous Limestone", "partially_mechanical", True, None, 71.0, 6.1, "high",
    ),
    # ---- deep and hot but very badly conditioned ------------------------
    (
        "UK-MOCK-NTH-012", "North Sea Deep Test 1", "Example Offshore Energy",
        57.9000, -1.9800, "Aberdeenshire", "Scotland", "UK-OG-230/1", 1984,
        "gas", 3800.0, 118.0, "static_bht", "plugged_abandoned",
        "Fetich Formation", "poor_unknown", False, None, 145.0, 4.9, "severe",
    ),
    # ---- shallow, cool, intact: a genuine non-candidate -----------------
    (
        "UK-MOCK-LIN-013", "Lincolnshire Waterbore 22", "Anglian Water",
        53.0400, -0.6400, "Lincolnshire", "East Midlands", "UK-OG-140/7", 1994,
        "water_abstraction", 310.0, 39.0, "max_dynamic", "plugged_abandoned",
        "Chalk", "abandoned_no_access", False, None, 8.0, 7.6, "none",
    ),
    # ---- long-lived producing well, still warm --------------------------
    (
        "UK-MOCK-ERA-014", "East Midlands Gas 30", "Central Gas",
        52.9400, -1.1500, "Derbyshire", "East Midlands", "UK-OG-241/9", 1967,
        "gas", 1540.0, 66.0, "production_log", "producing", "Carboniferous Gritstone",
        "good_condition", True, None, 34.0, 7.3, "low",
    ),
    (
        "UK-MOCK-AB-015", "Scottish Central Gas 5", "North Sea Gas",
        56.0000, -3.7500, "Fife", "Scotland", "UK-OG-250/2", 1970,
        "gas", 1850.0, 71.0, "production_log", "producing", "Carboniferous Coal Measures",
        "partially_mechanical", True, None, 48.0, 6.6, "moderate",
    ),
    (
        "UK-MOCK-BR-016", "Bristol Channel Margin 3", "Example Offshore Energy",
        51.4400, -2.9800, "Bristol", "South West", "UK-OG-453/2", 1986,
        "oil", 1600.0, 76.0, "static_bht", "non_producing", "Westbury Formation",
        "partially_mechanical", True, None, 57.0, 6.5, "moderate",
    ),
    (
        "UK-MOCK-WM-017", "West Midlands Gas 11", "Midlands Gas",
        52.4800, -2.0100, "Worcestershire", "West Midlands", "UK-OG-243/4", 1974,
        "gas", 1320.0, 63.0, "max_dynamic", "suspended", "Bridlington Sandstone",
        "partially_mechanical", True, None, 51.0, 6.7, "moderate",
    ),
    (
        "UK-MOCK-NI-018", "Northern Ireland Oil 2", "Example Petroleum",
        54.5600, -6.9400, "Fermanagh", "Northern Ireland", "UK-OG-160/1", 1963,
        "oil", 900.0, 55.0, "regional_estimate", "abandoned", "Ballyshannon Sandstone",
        "abandoned_no_access", False, None, None, None, None,
    ),
    (
        "UK-MOCK-EO-019", "East of England Water 8", "Anglian Water",
        52.2000, 0.4200, "Cambridgeshire", "East of England", "UK-OG-246/6", 1990,
        "water_abstraction", 520.0, 41.0, "max_dynamic", "abandoned",
        "Chalk Group", "abandoned_no_access", False, None, 9.0, 7.5, "low",
    ),
    (
        "UK-MOCK-HL-020", "Highlands Hydrocarbon 1", "Example Exploration",
        57.4800, -4.2200, "Highland", "Scotland", "UK-OG-255/1", 1978,
        "oil", 1450.0, 68.0, "circulation_test", "plugged_abandoned",
        "Orcadian Flagstone", "abandoned_no_access", False, None, 74.0, 6.0, "moderate",
    ),
)


def well_records() -> list[dict[str, Any]]:
    """The raw well records, in the shape an external source would deliver.

    Field names deliberately mirror published UK datasets - ``wellname``,
    ``wellname_lat``, ``totaldepth``, ``bht`` - rather than the platform's names,
    so the normalisation path is genuinely exercised rather than bypassed.
    """
    rng = _rng()
    records: list[dict[str, Any]] = []

    for spec in WELL_SPECS:
        (
            well_id, name, operator, lat, lon, county, region, licence, year,
            purpose, depth, temperature, method, status, formation, integrity,
            casing, chemistry, salinity, ph, scaling,
        ) = spec

        record: dict[str, Any] = {
            "wellname": name,
            "wellname_full": name,
            "id": well_id,
            "well_id": well_id,
            "wellname_lat": float(f"{lat:.5f}"),
            "wellname_long": float(f"{lon:.5f}"),
            "latitude": lat,
            "longitude": lon,
            "county": county,
            "region": region,
            "licence": licence,
            "operator": operator,
            "drilling_year": year,
            "purpose": purpose,
            "totaldepth": f"{depth:.1f} m" if depth else None,
            "total_depth_m": depth,
            "status": status,
            "formation": formation,
            "stratigraphical_unit": formation,
            "bht": temperature,
            "temperature_c": temperature,
            "temperature_method": method,
            "temperature_depth_m": depth * 0.98 if (depth and temperature) else None,
            "casing_string": (
                "9 5/8\" casing to 1,850 m; 4 1/2\" tubing to 1,600 m"
                if casing
                else None
            ),
            "completion": "perforated and plugged back" if casing else "drilled dry",
            "spud_date": f"{year}-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}",
            "integrity_status": integrity,
            "water_chemistry_available": bool(chemistry),
            "salinity_ppt": salinity,
            "ph": ph,
            "scaling_tendency": scaling,
        }
        records.append(record)

    return records


def temperature_records() -> list[dict[str, Any]]:
    """Individual temperature observations.

    Includes repeat readings at different depths and dates so the variability
    axis has something real to work with, plus a conflicting pair on one well so
    the cross-source agreement axis is exercised.
    """
    rng = _rng()
    records: list[dict[str, Any]] = []

    for spec in WELL_SPECS:
        (
            well_id, name, operator, lat, lon, county, region, licence, year,
            purpose, depth, temperature, method, status, formation, integrity,
            casing, chemistry, salinity, ph, scaling,
        ) = spec

        if temperature is None:
            continue

        base_year = year + rng.randint(1, 3)

        # Shallow reading: cooler, because geothermal gradient means the shallow
        # formation is cooler than the target.
        records.append(
            {
                "well_id": well_id,
                "depth_m": round(depth * 0.35, 1),
                "temperature_c": round(temperature - (depth * 0.35 / 1000.0) * 12.0, 1),
                "measured_at": f"{base_year}-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}",
                "measurement_method": method or "production_log",
                "is_final_stabilised": True,
                "source": "mock_nsta",
            }
        )

        # Deep reading: the target interval, and the one that matters.
        records.append(
            {
                "well_id": well_id,
                "depth_m": round(depth * 0.98, 1),
                "temperature_c": temperature,
                "measured_at": f"{base_year}-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}",
                "measurement_method": method or "production_log",
                "is_final_stabilised": method in ("static_bht", "circulation_test"),
                "source": "mock_nsta",
            }
        )

        # A later re-survey with small measurement scatter.
        if method in ("static_bht", "circulation_test") and rng.random() > 0.4:
            records.append(
                {
                    "well_id": well_id,
                    "depth_m": round(depth * 0.98, 1),
                    "temperature_c": round(temperature + rng.uniform(-1.5, 1.5), 1),
                    "measured_at": f"{min(base_year + rng.randint(4, 12), 2025)}-"
                    f"{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}",
                    "measurement_method": "static_bht",
                    "is_final_stabilised": True,
                    "source": "mock_nsta",
                }
            )

    # A deliberate conflict: two sources on the same well differing by 35 K.
    # This is the case the cross-source agreement axis exists to catch, and it
    # must appear in the sample data or the confidence scoring is untested.
    records.extend(
        [
            {
                "well_id": "UK-MOCK-YOR-011",
                "depth_m": 2009.0,
                "temperature_c": 74.0,
                "measured_at": "1989-04-11",
                "measurement_method": "regional_estimate",
                "is_final_stabilised": False,
                "source": "mock_bgs",
            },
            {
                "well_id": "UK-MOCK-YOR-011",
                "depth_m": 2009.0,
                "temperature_c": 109.0,
                "measured_at": "1991-06-02",
                "measurement_method": "static_bht",
                "is_final_stabilised": True,
                "source": "mock_nsta",
            },
        ]
    )

    # An unstabilised reading that overstates the sustained temperature. The
    # confidence engine penalises these explicitly.
    records.append(
        {
            "well_id": "UK-MOCK-DEV-008",
            "depth_m": 800.0,
            "temperature_c": 96.0,
            "measured_at": "1969-08-15",
            "measurement_method": "max_dynamic",
            "is_final_stabilised": False,
            "source": "mock_nsta",
        }
    )

    return records


def integrity_records() -> list[dict[str, Any]]:
    """Integrity assessments. Rows only exist for wells that have been assessed."""
    rng = _rng()
    records: list[dict[str, Any]] = []

    for spec in WELL_SPECS:
        (
            well_id, name, operator, lat, lon, county, region, licence, year,
            purpose, depth, temperature, method, status, formation, integrity,
            casing, chemistry, salinity, ph, scaling,
        ) = spec

        if integrity is None:
            continue

        last_check = REFERENCE_DATE - timedelta(days=rng.randint(200, 4000))

        records.append(
            {
                "well_id": well_id,
                "status": integrity,
                "casing_condition_score": {
                    WellIntegrityStatus.GOOD_CONDITION.value: round(rng.uniform(0.80, 0.95), 2),
                    WellIntegrityStatus.PARTIALLY_MECHANICAL.value: round(rng.uniform(0.40, 0.65), 2),
                    WellIntegrityStatus.ABANDONED_NO_ACCESS.value: round(rng.uniform(0.05, 0.25), 2),
                    WellIntegrityStatus.POOR_UNKNOWN.value: round(rng.uniform(0.05, 0.20), 2),
                    WellIntegrityStatus.SUSPENDED_INACCESSIBLE.value: round(rng.uniform(0.20, 0.40), 2),
                }.get(integrity, None),
                "wellhead_condition_score": round(rng.uniform(0.30, 0.90), 2),
                "access_score": round(
                    rng.uniform(0.7, 1.0)
                    if status == "producing"
                    else rng.uniform(0.1, 0.5),
                    2,
                ),
                "abandonment_score": (
                    0.0 if status in ("plugged_abandoned", "abandoned")
                    else 1.0 if status == "producing"
                    else 0.6
                ),
                "requires_reequipment": integrity
                in (
                    WellIntegrityStatus.ABANDONED_NO_ACCESS.value,
                    WellIntegrityStatus.POOR_UNKNOWN.value,
                    WellIntegrityStatus.PARTIALLY_MECHANICAL.value,
                ),
                "last_integrity_check_date": last_check.isoformat(),
            }
        )

    return records


def geology_records() -> list[dict[str, Any]]:
    """Formation-level geology, where available."""
    rng = _rng()
    records: list[dict[str, Any]] = []

    for spec in WELL_SPECS:
        (
            well_id, name, operator, lat, lon, county, region, licence, year,
            purpose, depth, temperature, method, status, formation, integrity,
            casing, chemistry, salinity, ph, scaling,
        ) = spec

        if not chemistry:
            continue

        gradient = round(temperature / (depth / 1000.0), 2) if (temperature and depth) else None

        records.append(
            {
                "well_id": well_id,
                "geothermal_gradient_c_per_km": gradient,
                # UK onshore sandstone and carbonate typically 5-200 mD; coal is far
                # lower, which is why the coalbed methane well scores differently.
                "permeability_md": (
                    round(rng.uniform(15, 180), 1)
                    if purpose != "coalbed_methane"
                    else round(rng.uniform(0.5, 8), 2)
                ),
                "net_thickness_m": round(depth * rng.uniform(0.08, 0.35), 1),
                "reservoir_lithology": formation.split()[-1] if formation else None,
                "water_salinity_ppt": salinity,
                "water_ph": ph,
                "scaling_tendency": scaling,
                "corrosion_tendency": (
                    "high" if (ph is not None and ph < 6.0)
                    else "moderate" if (ph is not None and ph < 7.0)
                    else "low"
                ),
                "chemistry_status": EpistemicStatus.MEASURED.value,
            }
        )

    return records


def dataset_descriptor() -> dict[str, Any]:
    """Provenance for the development dataset."""
    return {
        "source": "mock_nsta",
        "name": "Synthetic UK onshore well dataset (development only)",
        "version": "2026.09.08",
        "description": (
            "Entirely synthetic development dataset. Contains no production well "
            "data. Well names, operators, licences, coordinates, depths, "
            "temperatures and water chemistry are all invented. Provided so the "
            "application can be developed, demonstrated and tested without "
            "accessing licensed data."
        ),
        "source_url": None,
        "download_date": REFERENCE_DATE,
        "published_date": REFERENCE_DATE,
        "licence": (
            "Not applicable. This dataset contains no third-party data and carries "
            "no licence obligation."
        ),
        "reliability": "tier_mock",
        "is_mock": True,
    }
