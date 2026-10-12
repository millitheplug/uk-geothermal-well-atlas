"""Download the NSTA onshore England petroleum wellbore dataset.

Source: "UK England onshore petroleum wellbores top holes (WGS84)", published by
the North Sea Transition Authority (ArcGIS owner ``NSTA_GIS``) under the NSTA
Open User Licence. This replaced the older "NSTA Onshore Wells (BNG)" item
(1200c2c8a87f4c5083b40068d96dd120), which now returns 403 after NSTA's GIS
platform migration.

The file is written under ``data/adapters/`` which is gitignored: the data is
fetched from the publisher, never committed. The output is a GeoJSON
FeatureCollection with a ``metadata`` block (publisher, licence, service URL,
download time, record count) and a sidecar ``.sha256`` so a dataset version can
be verified by the importer.

Nothing here normalises, fills or reinterprets values. Fields the publisher left
empty stay empty, so the importer can label them UNKNOWN.

Usage (from the repository root)::

    python -m scripts.fetch_nsta_onshore_wells
    python -m scripts.fetch_nsta_onshore_wells --out data/adapters/nsta/wells.geojson
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ITEM_URL = "https://www.arcgis.com/home/item.html?id=d40f9dc58ca84268935582152a5b20f9"
SERVICE_URL = (
    "https://services-eu1.arcgis.com/OZMfUznmLTnWccBc/arcgis/rest/services/"
    "UKCS onshore petroleum wells top holes WGS84/FeatureServer/0"
)
LICENCE = "NSTA Open User Licence"
PUBLISHER = "North Sea Transition Authority"
DEFAULT_OUT = Path("data/adapters/nsta/nsta_onshore_wells_wgs84.geojson")
PAGE_SIZE = 2000  # the service's maxRecordCount
TIMEOUT_S = 120


def _get_json(params: dict[str, Any], path: str = "/query") -> dict[str, Any]:
    url = urllib.parse.quote(SERVICE_URL, safe=":/") + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed https host
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"service error: {payload['error']}")
    return payload


def fetch_all() -> list[dict[str, Any]]:
    expected = _get_json({"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]
    features: list[dict[str, Any]] = []
    offset = 0
    while offset < expected:
        page = _get_json(
            {
                "where": "1=1",
                "outFields": "*",
                "outSR": 4326,
                "orderByFields": "OBJECTID",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
                "f": "geojson",
            }
        )
        batch = page.get("features", [])
        if not batch:
            break
        features.extend(batch)
        offset += len(batch)

    ids = [f["properties"]["OBJECTID"] for f in features]
    if len(features) != expected or len(set(ids)) != len(ids):
        raise RuntimeError(
            f"incomplete or duplicated download: expected {expected}, "
            f"got {len(features)} ({len(set(ids))} unique)"
        )
    return features


def coverage(features: list[dict[str, Any]]) -> dict[str, int]:
    """Count populated values for the fields the atlas depends on."""
    keys = ("MXTDTEMPC", "MNTDTEMPC", "TDTVDSSM", "TDMDDEPM", "COMPLESTAT", "ONS_COUNTY")
    props = [f["properties"] for f in features]
    return {k: sum(1 for p in props if p.get(k) not in (None, "")) for k in keys}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    features = fetch_all()
    collection = {
        "type": "FeatureCollection",
        "name": "nsta_onshore_wellbores_top_holes_wgs84",
        "metadata": {
            "publisher": PUBLISHER,
            "licence": LICENCE,
            "attribution": "Contains data from the North Sea Transition Authority.",
            "source_item": ITEM_URL,
            "service": SERVICE_URL,
            "downloaded_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "record_count": len(features),
            "field_coverage": coverage(features),
            "is_mock": False,
        },
        "features": features,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(collection).encode()
    args.out.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    args.out.with_suffix(args.out.suffix + ".sha256").write_text(f"{digest}  {args.out.name}\n")

    print(f"wrote {len(features)} wellbores to {args.out}")
    print(f"sha256 {digest}")
    print(f"field coverage {collection['metadata']['field_coverage']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
