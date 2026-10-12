# NSTA onshore England petroleum wellbores — snapshot

Real data. Not synthetic. Loaded by `python -m scripts.cli ingest nsta_wells`.

| | |
|---|---|
| Publisher | North Sea Transition Authority (NSTA) |
| Dataset | UK England onshore petroleum wellbores top holes (WGS84) |
| Source | https://www.arcgis.com/home/item.html?id=d40f9dc58ca84268935582152a5b20f9 |
| Records | 2,138 wellbores |
| Integrity | `nsta_onshore_wells_wgs84.geojson.sha256` |
| Refresh | `python -m scripts.fetch_nsta_onshore_wells` |

## Licence

Used under the NSTA User Agreement, which permits copying, publishing,
distributing, transmitting and adapting the information, and exploiting it
**non-commercially**. Use does not imply any endorsement by the NSTA.

Contains information provided by the North Sea Transition Authority and/or other third parties.

## Caveats

- England only. NSTA does not publish onshore data for Scotland, Wales or Northern Ireland.
- Only 33 wells carry a maximum hole temperature, of unstated stabilisation.
- Some depths are missing, zero or negative, and are treated as unknown on import.
