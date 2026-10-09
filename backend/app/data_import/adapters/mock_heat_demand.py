"""Development heat-demand and energy-price datasets.

Entirely synthetic, as with the well dataset. The buildings are placed in clusters
around a subset of the development wells so that the demand-matching path is
exercised end to end, and deliberately left sparse elsewhere so the "no demand
near this well" case is represented too.

Demand figures are derived from floor area and a typical UK heat intensity, then
perturbed. They are ESTIMATE-status throughout: no building in this dataset has
been metered, and the ingestion code labels them accordingly.
"""

from __future__ import annotations

import math
import random
from datetime import date
from typing import Any

from app.core.enums import EpistemicStatus

SEED = 20260908
REFERENCE_DATE = date(2026, 9, 8)

#: Annual heat demand per m2 of floor area, kWh/m2/yr. UK figures vary widely by
#: building type and vintage; these are mid-range and deliberately on the
#: conservative side for domestic stock.
HEAT_INTENSITY_KWH_PER_M2 = {
    "domestic": 105.0,
    "commercial": 130.0,
    "industrial": 85.0,
    "public": 145.0,
}

#: Wells that get a demand cluster, and the radius over which it is spread.
#: Wells absent from this map are the no-nearby-demand case.
DEMAND_CLUSTER_WELLS: tuple[str, ...] = (
    "UK-MOCK-CRN-001",
    "UK-MOCK-WLN-002",
    "UK-MOCK-YOR-003",
    "UK-MOCK-LAN-004",
    "UK-MOCK-DEV-008",
    "UK-MOCK-ERA-014",
    "UK-MOCK-AB-015",
    "UK-MOCK-WM-017",
)

#: Postcode districts used for the synthetic clusters.
CLUSTER_POSTCODES: dict[str, str] = {
    "UK-MOCK-CRN-001": "TR21",
    "UK-MOCK-WLN-002": "TN21",
    "UK-MOCK-YOR-003": "LS11",
    "UK-MOCK-LAN-004": "PR1",
    "UK-MOCK-DEV-008": "EX31",
    "UK-MOCK-ERA-014": "DE4",
    "UK-MOCK-AB-015": "KY2",
    "UK-MOCK-WM-017": "WR5",
}


def building_records() -> list[dict[str, Any]]:
    """Synthetic buildings clustered around the development wells."""
    from app.data_import.adapters.dev_wells import WELL_SPECS  # noqa: PLC0415

    rng = random.Random(SEED)
    records: list[dict[str, Any]] = []

    wells = {spec[0]: spec for spec in WELL_SPECS}

    for well_id in DEMAND_CLUSTER_WELLS:
        spec = wells.get(well_id)
        if spec is None:
            continue

        _, _, _, lat, lon, county, region, *_ = spec
        postcode = CLUSTER_POSTCODES.get(well_id, "SW1")

        # Cluster size varies a lot, because off-taker count is what separates a
        # heat market from a single connection.
        count = rng.randint(6, 120)

        for index in range(count):
            # Radially distributed around the well, in metres.
            radius = rng.uniform(80.0, 1800.0)
            bearing = rng.uniform(0.0, 2 * math.pi)
            d_lat = (radius * math.cos(bearing)) / 111_320.0
            d_lon = (radius * math.sin(bearing)) / (
                111_320.0 * math.cos(math.radians(lat))
            )

            # Weighted towards domestic, with a realistic minority of larger
            # commercial and industrial loads.
            roll = rng.random()
            if roll < 0.70:
                building_type = "domestic"
            elif roll < 0.88:
                building_type = "commercial"
            elif roll < 0.97:
                building_type = "public"
            else:
                building_type = "industrial"

            if building_type == "domestic":
                floor_area = rng.uniform(55.0, 260.0)
                supply_temp = rng.choice([70.0, 75.0, 80.0, 90.0])
                fuel = rng.choice(["gas", "gas", "gas", "electric", "oil"])
            elif building_type == "commercial":
                floor_area = rng.uniform(400.0, 6_500.0)
                supply_temp = rng.choice([55.0, 60.0, 70.0, 80.0])
                fuel = rng.choice(["gas", "electric", "gas"])
            elif building_type == "public":
                floor_area = rng.uniform(1_200.0, 12_000.0)
                supply_temp = rng.choice([70.0, 80.0, 90.0])
                fuel = rng.choice(["gas", "electric"])
            else:
                floor_area = rng.uniform(3_000.0, 25_000.0)
                supply_temp = rng.choice([60.0, 70.0, 80.0, 95.0])
                fuel = rng.choice(["gas", "electric", "gas", "biomass"])

            intensity = HEAT_INTENSITY_KWH_PER_M2[building_type]
            annual = floor_area * intensity * rng.uniform(0.82, 1.18)

            # Peak load from an average UK load profile.
            peak_kw = annual / (rng.uniform(1400.0, 2200.0))

            # Connection potential: correlated with being on gas, which is
            # nearest the existing network and cheapest to connect to.
            if fuel == "gas":
                potential = rng.choice(["high", "high", "medium", "low"])
            elif fuel == "electric":
                potential = rng.choice(["medium", "medium", "low"])
            else:
                potential = rng.choice(["low", "low", "unknown"])

            records.append(
                {
                    "id": f"{postcode}-{index:04d}",
                    "postcode": postcode,
                    "address_reference": f"{postcode} {rng.randint(1, 99)}",
                    "latitude": round(lat + d_lat, 6),
                    "longitude": round(lon + d_lon, 6),
                    "region": region,
                    "building_type": building_type,
                    "floor_area_m2": round(floor_area, 1),
                    "construction_year": rng.randint(1850, 2020),
                    "annual_heat_demand_kwh": round(annual, 0),
                    "peak_heat_demand_kw": round(peak_kw, 2),
                    "required_supply_temperature_c": supply_temp,
                    "current_fuel": fuel,
                    "current_heating": (
                        "gas boiler" if fuel == "gas"
                        else "electric resistance" if fuel == "electric"
                        else "oil boiler"
                    ),
                    "connection_potential": potential,
                    "is_connected_to_network": rng.random() < 0.08,
                    "cluster_well": well_id,
                }
            )

    return records


def heat_demand_area_records() -> list[dict[str, Any]]:
    """Settlement-level demand aggregates, as published zoning datasets provide."""
    from app.data_import.adapters.dev_wells import WELL_SPECS  # noqa: PLC0415

    rng = random.Random(SEED + 1)
    records: list[dict[str, Any]] = []

    for well_id in DEMAND_CLUSTER_WELLS:
        spec = next((s for s in WELL_SPECS if s[0] == well_id), None)
        if spec is None:
            continue

        _, _, _, lat, lon, county, region, *_ = spec
        postcode = CLUSTER_POSTCODES.get(well_id, "SW1")

        households = rng.randint(400, 4_500)
        population = int(households * rng.uniform(2.1, 2.5))
        domestic_share = rng.uniform(0.55, 0.78)

        records.append(
            {
                "area_code": postcode,
                "area_name": f"{postcode} sector, {county}",
                "area_type": "postcode_sector",
                "latitude": lat,
                "longitude": lon,
                "region": region,
                "population": population,
                "household_count": households,
                "total_annual_demand_kwh": round(
                    households * 11_500 * rng.uniform(0.85, 1.20)
                ),
                "domestic_share_pct": round(domestic_share, 3),
                "peak_demand_kw": round(households * 1.45, 1),
                "gas_network_present": rng.random() < 0.82,
                "average_supply_temperature_c": rng.choice([70.0, 75.0, 80.0]),
                "upgrade_potential_score": round(rng.uniform(0.25, 0.90), 2),
            }
        )

    return records


def heat_network_records() -> list[dict[str, Any]]:
    """Existing and planned heat networks near the development wells."""
    from app.data_import.adapters.dev_wells import WELL_SPECS  # noqa: PLC0415

    records: list[dict[str, Any]] = []
    wells = {spec[0]: spec for spec in WELL_SPECS}

    networks = [
        ("UK-MOCK-LAN-004", "Example Preston District Heating", "Example Energy",
         "district", True, True, "gas CHP", 80.0, 45.0, 62_000.0, 14.5, 3_400.0),
        ("UK-MOCK-ERA-014", "Example Derbyshire Heat Network", "Central Gas",
         "industrial estate", True, True, "gas boiler", 95.0, 60.0, 48_000.0, 6.2, 980.0),
        ("UK-MOCK-WM-017", "Worcestershire Civic Heat Scheme", "Example Council",
         "public", True, True, "gas CHP", 85.0, 55.0, 22_000.0, 2.1, 610.0),
        ("UK-MOCK-DEV-008", "Barnstaple Renewable Heat Network", "Example Trust",
         "planned", False, None, "planned biomass and geothermal", 70.0, 40.0, 0.0, 0.0, 0.0),
        ("UK-MOCK-AB-015", "Kirkcaldy Energy Centre", "North Sea Gas",
         "district", True, True, "gas CHP", 85.0, 50.0, 40_000.0, 9.8, 2_150.0),
    ]

    for (
        well_id, name, operator, network_type, existing, operational,
        heat_source, flow_temp, return_temp, length_m, buildings, delivered_gwh,
    ) in networks:
        spec = wells.get(well_id)
        if spec is None:
            continue

        _, _, _, lat, lon, county, region, *_ = spec
        d_lat = 0.006
        d_lon = 0.010

        records.append(
            {
                "name": name,
                "operator": operator,
                "centre_latitude": round(lat + d_lat, 6),
                "centre_longitude": round(lon + d_lon, 6),
                "region": region,
                "existing": existing,
                "operational": operational,
                "network_type": network_type,
                "current_heat_source": heat_source,
                "current_heat_source_capacity_mw": (
                    round(delivered_gwh * 1000.0 / 3500.0, 2) if delivered_gwh else None
                ),
                "flow_temperature_c": flow_temp,
                "return_temperature_c": return_temp,
                "network_length_m": length_m,
                "connected_buildings": int(buildings),
                "annual_delivered_heat_gwh": delivered_gwh,
                "spare_capacity_mw": round(
                    (delivered_gwh * 1000.0 / 3500.0) * 0.22, 2
                ) if delivered_gwh else None,
                "reinforcement_required": bool(existing) and delivered_gwh < 1_000.0,
                "near_well": well_id,
            }
        )

    return records


def energy_price_records() -> list[dict[str, Any]]:
    """A dated tariff book.

    Values are representative of UK non-domestic and domestic heat pricing
    levels, not a published tariff. Recorded as ESTIMATE with a mock flag, and
    split into a tax/levy decomposition so the basis of the headline figure is
    auditable rather than asserted.
    """
    records: list[dict[str, Any]] = []

    # Non-domestic electricity, the dominant OPEX and the heat pump's input.
    for year, base in ((2024, 13.4), (2025, 14.2), (2026, 15.0)):
        levies = round(base * 0.31, 2)
        records.append(
            {
                "fuel": "electricity_nondomestic",
                "price_p_per_kwh": base,
                "levies_p_per_kwh": levies,
                "carbon_price_p_per_kwh": 0.0,
                "standing_charge_p_per_kwh": 0.0,
                "valid_from": date(year, 1, 1),
                "valid_to": date(year, 12, 31),
                "customer_segment": "non-domestic",
                "price_basis": {
                    "energy_p_per_kwh": round(base - levies, 2),
                    "levies_p_per_kwh": levies,
                    "network_charges_p_per_kwh": round(levies * 0.62, 2),
                    "tax_p_per_kwh": round(levies * 0.38, 2),
                },
            }
        )

    # Domestic gas, the price customers compare heat against.
    for year, base in ((2024, 6.4), (2025, 6.6), (2026, 6.9)):
        records.append(
            {
                "fuel": "gas_domestic",
                "price_p_per_kwh": base,
                "levies_p_per_kwh": round(base * 0.28, 2),
                "valid_from": date(year, 1, 1),
                "valid_to": date(year, 12, 31),
                "customer_segment": "domestic",
                "price_basis": {
                    "energy_p_per_kwh": round(base * 0.72, 2),
                    "levies_p_per_kwh": round(base * 0.28, 2),
                },
            }
        )

    # Achievable heat sale price. Recorded as an assumption, not a tariff: no
    # market price for geothermal district heat exists in the UK, so this is the
    # level a scheme would have to achieve.
    for year, base in ((2024, 8.0), (2025, 8.5), (2026, 9.0)):
        records.append(
            {
                "fuel": "heat_district_estimated",
                "price_p_per_kwh": base,
                "valid_from": date(year, 1, 1),
                "valid_to": date(year, 12, 31),
                "customer_segment": "mixed",
                "price_basis": {
                    "note": (
                        "No published UK price exists for geothermal district heat. "
                        "This is the level a scheme would need to achieve, derived "
                        "from a modest premium over domestic gas plus carbon value."
                    )
                },
            }
        )

    return records


def regulatory_requirement_records() -> list[dict[str, Any]]:
    """Consents and obligations, with the configuration each applies to."""
    return [
        {
            "jurisdiction": "England",
            "title": "Environmental Permit abstraction licence",
            "description": (
                "Required to abstract groundwater for an open loop. Where the water "
                "is below 23 degC at the point of abstraction, a full licence is "
                "required, and a permit to abstract in a drought-prone area applies "
                "regardless of volume."
            ),
            "authority": "Environment Agency",
            "applies_to_configuration": "open_loop",
            "is_mandatory": True,
            "typical_lead_time_months": 9.0,
            "estimated_cost_gbp": 12_000.0,
            "status": EpistemicStatus.FACT.value,
        },
        {
            "jurisdiction": "England",
            "title": "Discharge consent or permit",
            "description": (
                "Required to return water to surface waters or groundwater. Since "
                "2018 the Environment Agency has generally not issued consents for "
                "the direct discharge of geothermal water, so a second well in a "
                "suitable aquifer is normally required for reinjection."
            ),
            "authority": "Environment Agency",
            "applies_to_configuration": "open_loop",
            "is_mandatory": True,
            "typical_lead_time_months": 18.0,
            "estimated_cost_gbp": 35_000.0,
            "status": EpistemicStatus.FACT.value,
        },
        {
            "jurisdiction": "England",
            "title": "Planning permission for the wellsite and plant",
            "description": (
                "Required for a pumping station, plant enclosure, access track and "
                "any above-ground pipe. Permitted development rights may cover some "
                "elements but rarely the whole scheme."
            ),
            "authority": "Local planning authority",
            "applies_to_configuration": None,
            "is_mandatory": True,
            "typical_lead_time_months": 8.0,
            "estimated_cost_gbp": 28_000.0,
            "status": EpistemicStatus.FACT.value,
        },
        {
            "jurisdiction": "England",
            "title": "Special Protection Area screening",
            "description": (
                "Required where the wellsite or pipeline route lies within or "
                "adjacent to a Special Protection Area. Screening determines "
                "whether an Appropriate Assessment is needed."
            ),
            "authority": "Natural England",
            "applies_to_configuration": None,
            "is_mandatory": True,
            "typical_lead_time_months": 4.0,
            "estimated_cost_gbp": 9_000.0,
            "status": EpistemicStatus.FACT.value,
        },
        {
            "jurisdiction": "England",
            "title": "Mining subsidence assessment",
            "description": (
                "Required within a Coal Authority mining subsidence area. Adds both "
                "a drilling hazard and an increased buried-pipe failure risk over "
                "the asset life."
            ),
            "authority": "The Coal Authority",
            "applies_to_configuration": None,
            "is_mandatory": False,
            "typical_lead_time_months": 3.0,
            "estimated_cost_gbp": 15_000.0,
            "status": EpistemicStatus.FACT.value,
        },
        {
            "jurisdiction": "Scotland",
            "title": "SEPA water use and discharge consents",
            "description": (
                "SEPA administers abstraction and discharge consent in Scotland. "
                "The position on geothermal discharge is broadly similar to the "
                "Environment Agency's."
            ),
            "authority": "SEPA",
            "applies_to_configuration": "open_loop",
            "is_mandatory": True,
            "typical_lead_time_months": 15.0,
            "estimated_cost_gbp": 18_000.0,
            "status": EpistemicStatus.FACT.value,
        },
        {
            "jurisdiction": "Wales",
            "title": "Natural Resources Wales permits",
            "description": (
                "NRW administers water abstraction and discharge permitting in "
                "Wales."
            ),
            "authority": "Natural Resources Wales",
            "applies_to_configuration": "open_loop",
            "is_mandatory": True,
            "typical_lead_time_months": 15.0,
            "estimated_cost_gbp": 18_000.0,
            "status": EpistemicStatus.FACT.value,
        },
    ]


DATASETS = {
    "buildings": {
        "source": "mock_heat_demand",
        "name": "Synthetic building heat demand dataset (development only)",
        "version": "2026.09.08",
        "description": (
            "Entirely synthetic buildings clustered around the development wells. "
            "Demand is derived from floor area and a typical UK heat intensity, then "
            "perturbed. No building has been metered; every figure is an ESTIMATE."
        ),
        "licence": "Not applicable. No third-party data.",
        "reliability": "tier_mock",
        "is_mock": True,
    },
    "heat_demand_areas": {
        "source": "mock_heat_demand_areas",
        "name": "Synthetic settlement heat demand aggregates (development only)",
        "version": "2026.09.08",
        "description": (
            "Entirely synthetic postcode-sector demand aggregates. Represents the "
            "shape of published heat network zoning data without containing any of it."
        ),
        "licence": "Not applicable. No third-party data.",
        "reliability": "tier_mock",
        "is_mock": True,
    },
    "heat_networks": {
        "source": "mock_heat_networks",
        "name": "Synthetic heat networks (development only)",
        "version": "2026.09.08",
        "description": (
            "Entirely synthetic existing and planned heat networks. Names and "
            "operators are invented; the structures are representative of UK "
            "district, industrial estate and public schemes."
        ),
        "licence": "Not applicable. No third-party data.",
        "reliability": "tier_mock",
        "is_mock": True,
    },
    "energy_prices": {
        "source": "mock_energy_prices",
        "name": "Synthetic energy price book (development only)",
        "version": "2026.09.08",
        "description": (
            "Representative UK price levels, not published tariffs. The heat price "
            "in particular is an assumption: no market price for UK geothermal "
            "district heat exists."
        ),
        "licence": "Not applicable. No third-party data.",
        "reliability": "tier_mock",
        "is_mock": True,
    },
}
