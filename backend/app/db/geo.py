"""Dialect-aware geospatial expressions.

The production target is PostgreSQL + PostGIS. To keep the application runnable
and testable without a PostGIS server, every spatial query in the codebase is
built through the helpers in this module. They emit PostGIS SQL when the bound
engine is PostgreSQL and an algebraically equivalent great-circle (haversine)
SQL expression when it is SQLite.

The two paths are deliberately given different names in the query log via
`spatial_dialect_label()` so that a reviewer can confirm which one ran.

Accuracy note: the haversine fallback models the Earth as a sphere of radius
6371008.8 m. For the distances this platform cares about (well to building,
0.1-20 km) the error against the WGS84 ellipsoid is well under 1%. It is *not*
suitable for cadastral or volumetric work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, literal
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

EARTH_RADIUS_M = 6371008.8
"""Mean Earth radius (IUGG), metres. Used by the SQLite haversine fallback."""


def spatial_dialect_label(bind: Any) -> str:
    """Return ``postgis`` or ``haversine`` depending on the bound dialect."""
    try:
        return "postgis" if bind.dialect.name == "postgresql" else "haversine"
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def _lat_expr(lat: InstrumentedAttribute, lon: InstrumentedAttribute) -> ColumnElement[float]:
    return func.radians(lon).label("_lon_rad"), func.radians(lat).label("_lat_rad")


def distance_m(
    bind: Any,
    lat1: InstrumentedAttribute,
    lon1: InstrumentedAttribute,
    lat2: InstrumentedAttribute,
    lon2: InstrumentedAttribute,
) -> ColumnElement[float]:
    """Great-circle distance in metres between two lat/lon column pairs.

    Used to express "distance from the candidate well to an arbitrary row"
    when one side is a literal coordinate.
    """
    if spatial_dialect_label(bind) == "postgis":

        return func.ST_Distance(
            func.ST_SetSRID(func.ST_MakePoint(lon1, lat1), 4326),
            func.ST_SetSRID(func.ST_MakePoint(lon2, lat2), 4326),
        )

    lon1r, lat1r = _lat_expr(lat1, lon1)
    lon2r, lat2r = _lat_expr(lat2, lon2)
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = func.pow(func.sin(dlat / 2.0), 2) + func.cos(lat1r) * func.cos(lat2r) * func.pow(
        func.sin(dlon / 2.0), 2
    )
    # Clamp to 1.0 before asin. SQLite has no LEAST function, so use a CASE
    # expression that both backends understand - the clamp exists because
    # floating point can push `a` fractionally above 1 for antipodal points,
    # which makes asin return NaN rather than an error.
    a = case((a > 1.0, literal(1.0)), else_=a)
    return (2.0 * EARTH_RADIUS_M * func.asin(func.sqrt(a))).label("distance_m")


def distance_to_point_m(
    bind: Any,
    lat: InstrumentedAttribute,
    lon: InstrumentedAttribute,
    point_lat: float,
    point_lon: float,
) -> ColumnElement[float]:
    """Distance in metres from each row's (lat, lon) to a fixed coordinate."""
    return distance_m(bind, lat, lon, literal(point_lat), literal(point_lon))


def within_radius(
    bind: Any,
    lat: InstrumentedAttribute,
    lon: InstrumentedAttribute,
    centre_lat: float,
    centre_lon: float,
    radius_m: float,
) -> ColumnElement[bool]:
    """Boolean predicate: row lies within ``radius_m`` of the given coordinate."""
    if spatial_dialect_label(bind) == "postgis":
        from geoalchemy2 import functions as gaf  # noqa: F401,PLC0415

        return (
            func.ST_DWithin(
                func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
                func.ST_SetSRID(func.ST_MakePoint(literal(centre_lon), literal(centre_lat)), 4326),
                radius_m,
            )
        )

    return distance_to_point_m(bind, lat, lon, centre_lat, centre_lon) <= radius_m


def bounding_box(
    lat: InstrumentedAttribute,
    lon: InstrumentedAttribute,
    centre_lat: float,
    centre_lon: float,
    radius_m: float,
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """Cheap pre-filter: index-friendly lat/lon window around a coordinate.

    Used to narrow candidates before the exact (more expensive) distance test.
    The caller must still apply :func:`within_radius` for correctness.
    """
    dlat = radius_m / 111_320.0
    # Longitude degrees shrink with latitude; guard against division by ~0.
    import math  # noqa: PLC0415

    cos_lat = max(math.cos(math.radians(centre_lat)), 1e-6)
    dlon = radius_m / (111_320.0 * cos_lat)
    return (lat >= centre_lat - dlat) & (lat <= centre_lat + dlat), (
        lon >= centre_lon - dlon
    ) & (lon <= centre_lon + dlon)


def point_geometry(lat: InstrumentedAttribute, lon: InstrumentedAttribute) -> ColumnElement[Any]:
    """Build a WGS84 geometry from separate lat/lon columns."""
    return func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
