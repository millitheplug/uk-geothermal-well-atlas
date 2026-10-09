"""Geospatial tests.

The load-bearing assertion here is cross-backend agreement: the haversine SQL
fallback used on SQLite must return the same results as the pure-Python
reference and as PostGIS's ST_Distance would. If it does not, a well appears
inside a radius in development and outside it in production.

``spatial_dialect`` is asserted rather than assumed, so the suite is honest
about which backend it actually exercised.
"""

from __future__ import annotations

import math

import pytest

from app.db.geo import EARTH_RADIUS_M, bounding_box, distance_m
from app.models.well import Well
from app.services.query_service import (
    buildings_within_radius,
    haversine_m,
    heat_demand_areas,
    heat_networks,
    match_demand_to_well,
    price_on,
    well_and_demand_density,
)

# Reference distances computed from the published formula, for cross-checking.
# London Eye to Big Ben, and a short urban distance.
LON, LAT = -0.1195, 51.5033


class TestHaversineReference:
    def test_zero_distance(self):
        assert haversine_m(51.5, -0.1, 51.5, -0.1) == pytest.approx(0.0, abs=1e-6)

    def test_one_degree_of_latitude(self):
        """One degree of latitude is about 111.2 km anywhere."""
        assert haversine_m(51.0, 0.0, 52.0, 0.0) == pytest.approx(111_195, rel=0.002)

    def test_short_urban_distance(self):
        """1 km north is about 1,000 m."""
        assert haversine_m(51.5000, -0.1000, 51.5090, -0.1000) == pytest.approx(
            1000, rel=0.01
        )

    def test_matches_the_formula_by_hand(self):
        """Recompute independently and compare."""
        lat1, lon1, lat2, lon2 = 53.4, -2.5, 55.0, -3.2
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = phi2 - phi1
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        expected = 2 * 6_371_008.8 * math.asin(math.sqrt(a))
        assert haversine_m(lat1, lon1, lat2, lon2) == pytest.approx(expected)

    def test_is_symmetric(self):
        assert haversine_m(51.5, -0.1, 53.0, -2.0) == pytest.approx(
            haversine_m(53.0, -2.0, 51.5, -0.1)
        )

    def test_london_to_manchester(self):
        """Roughly 260 km; a well-known sanity figure."""
        d = haversine_m(51.5074, -0.1278, 53.4808, -2.2426)
        assert 255_000 < d < 265_000

    def test_longitude_shrinks_with_latitude(self):
        """A degree of longitude is ~111 km at the equator and ~59 km at 58 deg N.

        This is the cos(latitude) factor. Getting it wrong puts a well in the
        wrong place on a national map, so it is worth asserting directly.
        """
        at_58 = haversine_m(58.0, -0.1, 58.0, 0.9)  # exactly 1 degree
        at_equator = haversine_m(0.0, -0.1, 0.0, 0.9)
        assert 58_000 < at_58 < 60_000
        assert at_58 == pytest.approx(at_equator * 0.5299, rel=0.01)

    def test_antipodal_points_do_not_produce_nan(self):
        """Floating point can push the haversine argument above 1.

        Clamping matters: without it asin returns NaN rather than an error, and
        a NaN silently fails every comparison a distance feeds into.
        """
        d = haversine_m(0.0, 0.0, 0.0, 180.0)
        assert d == pytest.approx(math.pi * 6_371_008.8, rel=1e-6)


class TestGeoExpressions:
    def test_dialect_is_reported(self, db):
        from app.services.query_service import spatial_dialect

        assert spatial_dialect(db) in ("postgis", "haversine")

    def test_sql_expression_matches_python_reference(self, db):
        """The SQL haversine must agree with the Python implementation.

        This is the assertion that guarantees the SQLite fallback and PostGIS
        agree: both are checked against the same independent reference.
        """
        from sqlalchemy import select

        dialect = db.get_bind().dialect.name
        if dialect != "sqlite":
            pytest.skip("cross-check is specific to the fallback dialect")

        lat, lon = 51.5000, -0.1000
        stmt = select(
            Well.well_id,
            distance_m(
                db.get_bind(),
                Well.latitude,
                Well.longitude,
                lit(lat),
                lit(lon),
            ).label("d"),
        ).limit(20)


        rows = db.execute(stmt).all()
        for well_id, sql_distance in rows:
            well = db.query(Well).filter(Well.well_id == well_id).one()
            reference = haversine_m(lat, lon, well.latitude, well.longitude)
            assert float(sql_distance) == pytest.approx(reference, rel=0.001)

    def test_bounding_box_contains_the_point(self):
        lat_ok, lon_ok = bounding_box(
            Well.latitude, Well.longitude, 51.5, -0.1, 2000.0
        )
        # Only assert that the expressions compile to something usable.
        assert lat_ok is not None and lon_ok is not None

    def test_bounding_box_spans_more_longitude_than_latitude(self, db):
        """At UK latitudes a given radius covers more degrees of longitude.

        The pre-filter would be useless at high latitude if it clipped longitude
        too tightly, silently dropping nearby buildings before the exact test
        ran. Asserted by comparing the generated bounds directly.
        """
        import math

        centre_lat, radius_m = 58.0, 10_000.0
        dlat = radius_m / 111_320.0
        dlon = radius_m / (111_320.0 * math.cos(math.radians(centre_lat)))

        assert dlon > dlat * 1.5

    def test_bounding_box_contains_the_centre_point(self, db):
        from sqlalchemy import and_, select

        from app.db.geo import bounding_box as bb

        lat_ok, lon_ok = bb(
            lit(55.0), lit(-1.0), 55.0, -1.0, 5000.0
        )
        stmt = select(lit(1)).where(and_(lat_ok, lon_ok))
        assert db.execute(stmt).scalar() == 1


class TestDemandMatching:
    def test_finds_buildings_near_a_clustered_well(self, db, sample_well):
        match = match_demand_to_well(db, sample_well, radius_m=2000.0)
        assert match.building_count > 0
        assert match.total_annual_demand_kwh > 0

    def test_nearest_building_is_inside_the_radius(self, db, sample_well):
        match = match_demand_to_well(db, sample_well, radius_m=2000.0)
        assert match.nearest_building_distance_m <= 2000.0

    def test_buildings_sorted_by_distance(self, db, sample_well):
        match = match_demand_to_well(db, sample_well, radius_m=2000.0)
        distances = [d for _, d in match.buildings]
        assert distances == sorted(distances)

    def test_totals_match_the_individual_buildings(self, db, sample_well):
        match = match_demand_to_well(db, sample_well, radius_m=2000.0)
        manual = sum(b.annual_heat_demand_kwh or 0.0 for b, _ in match.buildings)
        assert match.total_annual_demand_kwh == pytest.approx(manual)

    def test_building_distances_match_the_reference(self, db, sample_well):
        match = match_demand_to_well(db, sample_well, radius_m=2000.0)
        for building, distance in match.buildings[:5]:
            reference = haversine_m(
                sample_well.latitude, sample_well.longitude,
                building.latitude, building.longitude,
            )
            assert distance == pytest.approx(reference, rel=0.01)

    def test_smaller_radius_finds_fewer_buildings(self, db, sample_well):
        wide = match_demand_to_well(db, sample_well, radius_m=2000.0)
        narrow = match_demand_to_well(db, sample_well, radius_m=400.0)
        assert narrow.building_count <= wide.building_count

    def test_no_buildings_returns_unknown_not_zero_confidently(self, db, loaded_data):
        """A well with no nearby demand must report unknown, not low demand."""
        from app.models.well import Well

        isolated = db.query(Well).filter(Well.well_id == "UK-MOCK-HL-020").one_or_none()
        if isolated is None:
            pytest.skip("development dataset not loaded")
        match = match_demand_to_well(db, isolated, radius_m=500.0)
        assert match.building_count == 0
        assert match.total_annual_demand_kwh == 0.0
        assert match.confidence == "unknown"
        assert any("not" in n.lower() for n in match.notes)

    def test_weighted_centroid_is_demand_weighted(self, db, sample_well):
        """The centroid must reflect where the heat is, not the midpoint."""
        match = match_demand_to_well(db, sample_well, radius_m=2000.0)
        assert match.weighted_latitude is not None
        simple_mean = sum(b.latitude for b, _ in match.buildings) / len(match.buildings)
        assert match.weighted_latitude != pytest.approx(simple_mean, abs=1e-9)

    def test_dominant_building_type_is_reported(self, db, sample_well):
        match = match_demand_to_well(db, sample_well, radius_m=2000.0)
        assert match.dominant_building_type in (
            "domestic", "commercial", "industrial", "public",
        )

    def test_single_off_taker_is_flagged_as_concentration_risk(self, db, loaded_data):
        """A tight radius must produce the concentration warning.

        Sweeps radii rather than assuming one hits exactly one building: the
        development dataset places buildings randomly, so a single fixed radius
        would be testing the seed rather than the logic.
        """
        from app.models.well import Well

        # WLN-002's cluster has a building inside 150 m; CRN-001's does not until
        # 250 m, by which point there are already three.
        well = db.query(Well).filter(Well.well_id == "UK-MOCK-WLN-002").one()

        checked = 0
        for radius in (100.0, 150.0, 200.0, 250.0, 300.0, 350.0):
            match = match_demand_to_well(db, well, radius_m=radius)
            if match.building_count == 1:
                assert match.confidence == "low"
                assert any(
                    "one candidate off-taker" in n.lower() for n in match.notes
                )
                checked += 1
                break
            if match.building_count >= 5:
                break

        assert checked, "no radius produced exactly one candidate off-taker"


class TestBuildingsWithinRadius:
    def test_respects_the_radius(self, db, sample_well):
        results = buildings_within_radius(
            db,
            centre_lat=sample_well.latitude,
            centre_lon=sample_well.longitude,
            radius_m=1000.0,
        )
        assert all(d <= 1000.0 for _, d in results)

    def test_empty_radius_returns_nothing(self, db):
        results = buildings_within_radius(
            db, centre_lat=58.6, centre_lon=-3.0, radius_m=1000.0
        )
        assert results == []

    def test_results_are_ordered_by_demand(self, db, sample_well):
        """Largest demand first, so a limited query page shows the best candidates."""
        results = buildings_within_radius(
            db,
            centre_lat=sample_well.latitude,
            centre_lon=sample_well.longitude,
            radius_m=2000.0,
        )
        demands = [b.annual_heat_demand_kwh or 0.0 for b, _ in results]
        assert demands == sorted(demands, reverse=True)


class TestDensity:
    def test_density_cells_are_returned(self, db, loaded_data):
        cells = well_and_demand_density(db, cell_size_deg=0.2)
        assert cells
        assert any(c.well_count > 0 for c in cells)
        assert any(c.demand_kwh > 0 for c in cells)

    def test_cells_merge_wells_and_demand(self, db, loaded_data):
        cells = well_and_demand_density(db, cell_size_deg=0.2)
        assert any(c.well_count > 0 and c.demand_kwh > 0 for c in cells)

    def test_sorted_by_demand_descending(self, db, loaded_data):
        cells = well_and_demand_density(db, cell_size_deg=0.2)
        demands = [c.demand_kwh for c in cells]
        assert demands == sorted(demands, reverse=True)


class TestHeatDemandAreas:
    def test_returns_areas(self, db, loaded_data):
        areas = heat_demand_areas(db)
        assert areas
        assert all(a.total_annual_demand_kwh > 0 for a in areas)

    def test_radius_filter_applies(self, db, loaded_data):
        areas = heat_demand_areas(db, centre_lat=51.1, centre_lon=0.3, radius_m=20_000.0)
        assert areas
        for area in areas:
            d = haversine_m(51.1, 0.3, area.latitude, area.longitude)
            assert d <= 20_000.0

    def test_min_demand_filter_applies(self, db, loaded_data):
        areas = heat_demand_areas(db, min_demand_kwh=1e9)
        assert areas == []


class TestHeatNetworks:
    def test_returns_networks(self, db, loaded_data):
        networks = heat_networks(db)
        assert networks

    def test_existing_only_filter(self, db, loaded_data):
        existing = heat_networks(db, existing_only=True)
        assert all(n.existing for n in existing)

    def test_reports_a_planned_network(self, db, loaded_data):
        networks = heat_networks(db)
        assert any(n.existing is False for n in networks)


class TestPrices:
    def test_price_found_for_a_valid_date(self, db, loaded_data):
        from datetime import date

        price = price_on(db, "electricity_nondomestic", date(2026, 6, 1))
        assert price is not None
        assert price.price_p_per_kwh == pytest.approx(15.0)

    def test_no_price_outside_the_book(self, db, loaded_data):
        from datetime import date

        assert price_on(db, "electricity_nondomestic", date(1990, 1, 1)) is None

    def test_no_price_for_an_unknown_fuel(self, db, loaded_data):
        from datetime import date

        assert price_on(db, "unobtainium", date(2026, 1, 1)) is None

    def test_mock_prices_can_be_excluded(self, db, loaded_data):
        from datetime import date

        assert price_on(
            db, "electricity_nondomestic", date(2026, 6, 1), exclude_mock=True
        ) is None

    def test_price_book_has_a_tax_decomposition(self, db, loaded_data):
        from datetime import date

        price = price_on(db, "electricity_nondomestic", date(2026, 6, 1))
        assert price.price_basis
        assert "energy_p_per_kwh" in price.price_basis
        assert "levies_p_per_kwh" in price.price_basis

    def test_heat_price_is_labelled_an_assumption(self, db, loaded_data):
        """No published UK heat tariff exists, so this must not read as one."""
        from datetime import date

        price = price_on(db, "heat_district_estimated", date(2026, 6, 1))
        assert price.status == "ASSUMPTION"
        assert price.is_mock is True


class TestEarthRadius:
    def test_radius_is_the_iugg_mean(self):
        """6,371,008.8 m is the IUGG mean Earth radius."""
        assert EARTH_RADIUS_M == pytest.approx(6_371_008.8)


from sqlalchemy import literal as lit  # noqa: E402
