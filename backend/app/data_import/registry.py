"""Adapter registry.

One place that knows every adapter and how to run it. The CLI and the API both
resolve adapters through here, so adding a real NSTA adapter means adding one
entry rather than editing two places.

Every adapter declares whether it produces mock data. That flag is not
decorative: it propagates to the dataset row, to every well row's ``source``, and
to the API response, so the frontend can watermark synthetic results and no
report can present them as production data.
"""

from __future__ import annotations

import logging
from typing import Any

from app.data_import.adapters.mock_heat import (
    MockBuildingAdapter,
    MockEnergyPriceAdapter,
    MockHeatDemandAreaAdapter,
    MockHeatNetworkAdapter,
    MockRegulatoryAdapter,
)
from app.data_import.adapters.mock_wells import (
    MockGeologyAdapter,
    MockIntegrityAdapter,
    MockTemperatureAdapter,
    MockWellAdapter,
    recompute_all_temperatures,
)
from app.data_import.adapters.nsta_wells import NstaOnshoreWellAdapter
from app.data_import.base import Adapter, ImportResult

logger = logging.getLogger(__name__)

#: Run order matters: wells must exist before temperatures, integrity or geology
#: can reference them, and temperatures must exist before the roll-up.
ADAPTERS: dict[str, type[Adapter]] = {
    "mock_wells": MockWellAdapter,
    "mock_temperatures": MockTemperatureAdapter,
    "mock_integrity": MockIntegrityAdapter,
    "mock_geology": MockGeologyAdapter,
    "mock_buildings": MockBuildingAdapter,
    "mock_demand_areas": MockHeatDemandAreaAdapter,
    "mock_heat_networks": MockHeatNetworkAdapter,
    "mock_energy_prices": MockEnergyPriceAdapter,
    "mock_regulatory": MockRegulatoryAdapter,
    # Real data. Deliberately absent from BOOTSTRAP_ORDER: real records are
    # loaded only on request (`cli ingest nsta_wells`), never as a side effect
    # of seeding the synthetic development set.
    "nsta_wells": NstaOnshoreWellAdapter,
}

#: Default order for a full bootstrap.
BOOTSTRAP_ORDER: tuple[str, ...] = (
    "mock_wells",
    "mock_temperatures",
    "mock_integrity",
    "mock_geology",
    "mock_buildings",
    "mock_demand_areas",
    "mock_heat_networks",
    "mock_energy_prices",
    "mock_regulatory",
)


def get_adapter(name: str) -> Adapter:
    """Instantiate one adapter by name."""
    try:
        return ADAPTERS[name]()
    except KeyError as exc:
        available = ", ".join(sorted(ADAPTERS))
        raise KeyError(f"unknown adapter '{name}'. Available: {available}") from exc


def list_adapters() -> list[dict[str, Any]]:
    """Describe every registered adapter, for the API and the CLI."""
    return [
        {
            "name": name,
            "source": cls.source,
            "is_mock": cls.is_mock,
            "class": f"{cls.__module__}.{cls.__name__}",
            "dataset_name": None,  # filled in on demand
        }
        for name, cls in sorted(ADAPTERS.items())
    ]


def run_adapter(name: str, *, limit: int | None = None, dry_run: bool = False) -> ImportResult:
    """Run one adapter."""
    adapter = get_adapter(name)
    logger.info("running adapter %s (limit=%s dry_run=%s)", name, limit, dry_run)
    return adapter.run(limit=limit, dry_run=dry_run)


def run_bootstrap(
    *, limit: int | None = None, dry_run: bool = False
) -> dict[str, Any]:
    """Run every adapter in dependency order.

    Returns per-adapter results plus a summary. A failure in one adapter does not
    stop the others: a broken heat-demand import should not prevent wells from
    loading, and the results make it obvious which one failed.
    """
    results: list[ImportResult] = []
    for name in BOOTSTRAP_ORDER:
        try:
            results.append(run_adapter(name, limit=limit, dry_run=dry_run))
        except Exception as exc:  # noqa: BLE001 - report, do not abort
            logger.exception("adapter %s failed", name)
            result = ImportResult(source=ADAPTERS[name].source)
            result.errors.append(f"{type(exc).__name__}: {exc}")
            results.append(result)

    temperature_rollup = 0
    if not dry_run and any(r.source == "mock_nsta_temps" and r.ok for r in results):
        from app.db.session import session_scope  # noqa: PLC0415

        with session_scope() as db:
            temperature_rollup = recompute_all_temperatures(db)

    return {
        "adapters": [r.to_dict() for r in results],
        "summary": {
            "adapters_run": len(results),
            "adapters_failed": sum(1 for r in results if not r.ok),
            "wells_created": sum(r.wells_created for r in results),
            "wells_updated": sum(r.wells_updated for r in results),
            "wells_skipped": sum(r.wells_skipped for r in results),
            "buildings_created": sum(r.buildings_created for r in results),
            "temperatures_created": sum(r.temperatures_created for r in results),
            "records_read": sum(r.records_read for r in results),
            "records_rejected": sum(r.records_rejected for r in results),
            "temperature_rollup_rows": temperature_rollup,
        },
        "is_mock_data": True,
        "warning": (
            "All development adapters produce synthetic data. No row written by "
            "this run corresponds to a real UK well, and no result may be presented "
            "as production data."
        ),
    }
