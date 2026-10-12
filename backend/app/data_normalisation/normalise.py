"""Normalisation: source vocabularies into the platform's controlled terms.

Published UK datasets do not agree with each other on how to spell "abandoned".
The NSTA, BGS and commercial compilations each use their own status list, their
own date formats and their own unit conventions. Normalising here means the rest
of the application sees one vocabulary, and the mapping is auditable rather than
buried in an adapter.

Every mapping records which source value produced which normalised value, so a
row's provenance survives normalisation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.enums import (
    DataConfidence,
    EpistemicStatus,
    OriginalPurpose,
    WellIntegrityStatus,
    WellStatus,
)
from app.data_validation.validators import RejectedRecord, parse_date, parse_float


@dataclass(frozen=True, slots=True)
class Normalisation:
    """One normalised field value plus how it was arrived at."""

    value: Any
    #: Which source value produced this. Kept for audit.
    raw: Any
    #: Epistemic status of the normalised value.
    status: str
    #: Confidence band, where the source supports one.
    confidence: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "raw": self.raw,
            "status": self.status,
            "confidence": self.confidence,
            "note": self.note,
        }


# -------------------------------------------------------- status maps
#: Source status wording -> platform status. Ordered longest-first at match time
#: so "plugged and abandoned" is not consumed by an earlier "abandoned" rule.
WELL_STATUS_MAP: dict[str, WellStatus] = {
    # producing
    "producing": WellStatus.PRODUCING,
    "production": WellStatus.PRODUCING,
    "flowing": WellStatus.PRODUCING,
    "active": WellStatus.PRODUCING,
    "in production": WellStatus.PRODUCING,
    "prod": WellStatus.PRODUCING,
    "ip": WellStatus.PRODUCING,
    # non-producing but live
    "non-producing": WellStatus.NON_PRODUCING,
    "non producing": WellStatus.NON_PRODUCING,
    "nonprod": WellStatus.NON_PRODUCING,
    "temporarily abandoned": WellStatus.NON_PRODUCING,
    "ta": WellStatus.NON_PRODUCING,
    "shut in": WellStatus.NON_PRODUCING,
    "shutin": WellStatus.NON_PRODUCING,
    "suspended": WellStatus.SUSPENDED,
    "completion": WellStatus.COMPLETED,
    "completed": WellStatus.COMPLETED,
    # drilling
    "drilling": WellStatus.DRILLING,
    "being drilled": WellStatus.DRILLING,
    # abandoned
    "plugged and abandoned": WellStatus.PLUGGED_ABANDONED,
    "plugged & abandoned": WellStatus.PLUGGED_ABANDONED,
    "p&a": WellStatus.PLUGGED_ABANDONED,
    "pa": WellStatus.PLUGGED_ABANDONED,
    "abandoned": WellStatus.ABANDONED,
    "dead": WellStatus.ABANDONED,
    "dry and abandoned": WellStatus.ABANDONED,
    "d&a": WellStatus.ABANDONED,
    "exploration": WellStatus.EXPLORATION,
    "prospect": WellStatus.EXPLORATION,
    "unknown": WellStatus.UNKNOWN,
    "": WellStatus.UNKNOWN,
}

WELL_PURPOSE_MAP: dict[str, OriginalPurpose] = {
    "oil": OriginalPurpose.OIL,
    "o": OriginalPurpose.OIL,
    "gas": OriginalPurpose.GAS,
    "g": OriginalPurpose.GAS,
    "oil and gas": OriginalPurpose.GAS,
    "coalbed methane": OriginalPurpose.COALBED_METHANE,
    "cbm": OriginalPurpose.COALBED_METHANE,
    "coal bed methane": OriginalPurpose.COALBED_METHANE,
    "methane": OriginalPurpose.COALBED_METHANE,
    "geothermal": OriginalPurpose.GEOTHERMAL,
    "gs": OriginalPurpose.GEOTHERMAL,
    "water": OriginalPurpose.WATER_ABSTRACTION,
    "water abstraction": OriginalPurpose.WATER_ABSTRACTION,
    "mineral": OriginalPurpose.WATER_ABSTRACTION,
    "structure explosives": OriginalPurpose.STRUCTURE_EXPLOSIVES,
    "seismic": OriginalPurpose.EXPLORATION,
    "exploration": OriginalPurpose.EXPLORATION,
    "stratigraphic": OriginalPurpose.EXPLORATION,
    "unknown": OriginalPurpose.UNKNOWN,
    "": OriginalPurpose.UNKNOWN,
}

INTEGRITY_STATUS_MAP: dict[str, WellIntegrityStatus] = {
    "good": WellIntegrityStatus.GOOD_CONDITION,
    "good condition": WellIntegrityStatus.GOOD_CONDITION,
    "sound": WellIntegrityStatus.GOOD_CONDITION,
    "operable": WellIntegrityStatus.GOOD_CONDITION,
    "producing": WellIntegrityStatus.GOOD_CONDITION,
    "partially mechanical": WellIntegrityStatus.PARTIALLY_MECHANICAL,
    "part mechanical": WellIntegrityStatus.PARTIALLY_MECHANICAL,
    "partially mechanical completion": WellIntegrityStatus.PARTIALLY_MECHANICAL,
    "abandoned": WellIntegrityStatus.ABANDONED_NO_ACCESS,
    "abandoned no access": WellIntegrityStatus.ABANDONED_NO_ACCESS,
    "p&a": WellIntegrityStatus.ABANDONED_NO_ACCESS,
    "plugged": WellIntegrityStatus.ABANDONED_NO_ACCESS,
    "poor": WellIntegrityStatus.POOR_UNKNOWN,
    "poor condition": WellIntegrityStatus.POOR_UNKNOWN,
    "damaged": WellIntegrityStatus.POOR_UNKNOWN,
    "suspended": WellIntegrityStatus.SUSPENDED_INACCESSIBLE,
    "inaccessible": WellIntegrityStatus.SUSPENDED_INACCESSIBLE,
    "unknown": WellIntegrityStatus.UNKNOWN,
    "": WellIntegrityStatus.UNKNOWN,
}

#: Temperature measurement method -> confidence band and epistemic status.
#: This mapping is the single place that decides how much a temperature reading
#: is trusted, and it is deliberately conservative: a production log is a real
#: measurement but of a flowing well, not of the reservoir at rest.
TEMPERATURE_METHOD_MAP: dict[str, tuple[str, str]] = {
    "static_bht": (DataConfidence.HIGH.value, EpistemicStatus.MEASURED.value),
    "static bottom hole temperature": (DataConfidence.HIGH.value, EpistemicStatus.MEASURED.value),
    "circulation_test": (DataConfidence.HIGH.value, EpistemicStatus.MEASURED.value),
    "thermal recovery test": (DataConfidence.HIGH.value, EpistemicStatus.MEASURED.value),
    "max_dynamic": (DataConfidence.MEDIUM.value, EpistemicStatus.MEASURED.value),
    "dynamic": (DataConfidence.MEDIUM.value, EpistemicStatus.MEASURED.value),
    "production_log": (DataConfidence.MEDIUM.value, EpistemicStatus.MEASURED.value),
    "dts": (DataConfidence.MEDIUM.value, EpistemicStatus.MEASURED.value),
    "dts_reprocessed": (DataConfidence.MEDIUM.value, EpistemicStatus.MEASURED.value),
    # NSTA onshore "hole temperature - maximum": a real reading, but the dataset
    # does not say whether it is stabilised or an uncorrected drilling BHT, so it
    # is trusted less than a dynamic log of known type.
    "nsta_max_hole_temperature": (DataConfidence.LOW.value, EpistemicStatus.MEASURED.value),
    "gamma": (DataConfidence.LOW.value, EpistemicStatus.ESTIMATE.value),
    "regional_estimate": (DataConfidence.VERY_LOW.value, EpistemicStatus.ESTIMATE.value),
    "estimate": (DataConfidence.VERY_LOW.value, EpistemicStatus.ESTIMATE.value),
    "analogue": (DataConfidence.VERY_LOW.value, EpistemicStatus.ESTIMATE.value),
    "analogous well": (DataConfidence.VERY_LOW.value, EpistemicStatus.ESTIMATE.value),
    "extrapolated": (DataConfidence.VERY_LOW.value, EpistemicStatus.ESTIMATE.value),
    # MODelled is distinct from ESTIMATE: the method is a published, reproducible
    # model rather than a judgement, so it can be audited. Confidence is still
    # very low because a regional model says nothing about this specific borehole.
    "modelled": (DataConfidence.VERY_LOW.value, EpistemicStatus.MODELLED.value),
    "petrophysical_model": (DataConfidence.VERY_LOW.value, EpistemicStatus.MODELLED.value),
    "basin_model": (DataConfidence.VERY_LOW.value, EpistemicStatus.MODELLED.value),
}

CONFIDENCE_FROM_VARIABILITY = (
    (3.0, DataConfidence.HIGH.value),
    (8.0, DataConfidence.MEDIUM.value),
    (15.0, DataConfidence.LOW.value),
    (float("inf"), DataConfidence.VERY_LOW.value),
)


def _clean(text: Any) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def normalise_status(raw: Any) -> Normalisation:
    """Map any published status wording onto the platform vocabulary."""
    key = _clean(raw)
    if key in WELL_STATUS_MAP:
        return Normalisation(
            value=WELL_STATUS_MAP[key].value,
            raw=raw,
            status=EpistemicStatus.FACT.value,
            confidence=DataConfidence.HIGH.value,
            note=None,
        )

    # Substring fallback, longest match first, for wording we have not seen.
    for candidate in sorted(WELL_STATUS_MAP, key=len, reverse=True):
        if len(candidate) > 3 and candidate in key:
            return Normalisation(
                value=WELL_STATUS_MAP[candidate].value,
                raw=raw,
                status=EpistemicStatus.FACT.value,
                confidence=DataConfidence.MEDIUM.value,
                note=f"matched by substring '{candidate}'",
            )

    # Unrecognised wording is not silently dropped: it becomes UNKNOWN with the
    # original preserved, so the mapping can be extended rather than guessed at.
    return Normalisation(
        value=WellStatus.UNKNOWN.value,
        raw=raw,
        status=EpistemicStatus.UNKNOWN.value,
        confidence=DataConfidence.UNKNOWN.value,
        note=f"unrecognised status '{raw}'; the verbatim value is retained in status_raw",
    )


def normalise_purpose(raw: Any) -> Normalisation:
    key = _clean(raw)
    if key in WELL_PURPOSE_MAP:
        return Normalisation(
            value=WELL_PURPOSE_MAP[key].value,
            raw=raw,
            status=EpistemicStatus.FACT.value,
            confidence=DataConfidence.HIGH.value,
        )
    for candidate in sorted(WELL_PURPOSE_MAP, key=len, reverse=True):
        if len(candidate) > 2 and candidate in key:
            return Normalisation(
                value=WELL_PURPOSE_MAP[candidate].value,
                raw=raw,
                status=EpistemicStatus.FACT.value,
                confidence=DataConfidence.MEDIUM.value,
                note=f"matched by substring '{candidate}'",
            )
    return Normalisation(
        value=OriginalPurpose.UNKNOWN.value,
        raw=raw,
        status=EpistemicStatus.UNKNOWN.value,
        confidence=DataConfidence.UNKNOWN.value,
    )


def normalise_integrity_status(raw: Any) -> Normalisation:
    key = _clean(raw)
    if key in INTEGRITY_STATUS_MAP:
        return Normalisation(
            value=INTEGRITY_STATUS_MAP[key].value,
            raw=raw,
            status=EpistemicStatus.FACT.value,
            confidence=DataConfidence.MEDIUM.value,
            note="assessed from records, not from physical inspection",
        )
    for candidate in sorted(INTEGRITY_STATUS_MAP, key=len, reverse=True):
        if len(candidate) > 3 and candidate in key:
            return Normalisation(
                value=INTEGRITY_STATUS_MAP[candidate].value,
                raw=raw,
                status=EpistemicStatus.FACT.value,
                confidence=DataConfidence.MEDIUM.value,
                note=f"matched by substring '{candidate}'",
            )
    return Normalisation(
        value=WellIntegrityStatus.UNKNOWN.value,
        raw=raw,
        status=EpistemicStatus.UNKNOWN.value,
        confidence=DataConfidence.UNKNOWN.value,
        note="no integrity assessment could be matched to this record",
    )


def normalise_temperature(
    raw_value: Any, raw_method: Any, depth_m: Any = None
) -> Normalisation | None:
    """Normalise a temperature reading and label it honestly.

    Returns ``None`` when there is no usable value, so the caller can leave the
    field null rather than record a placeholder.

    The status is never MEASURED unless the method is a direct reading: a
    regional estimate stays an estimate however precise the number looks.
    """
    try:
        temperature = parse_float(raw_value, "temperature_c")
    except RejectedRecord:
        return None
    if temperature is None:
        return None

    method_key = _clean(raw_method)
    confidence, status = TEMPERATURE_METHOD_MAP.get(
        method_key, (DataConfidence.LOW.value, EpistemicStatus.UNKNOWN.value)
    )

    # depth_m is accepted because every caller has it, but nothing downstream
    # records a depth: Normalisation reports the value, its status and a note.
    note = None
    if method_key not in TEMPERATURE_METHOD_MAP:
        note = (
            f"measurement method '{raw_method}' is not in the recognised set, so the "
            "reading is labelled UNKNOWN rather than assumed reliable"
        )

    return Normalisation(
        value=temperature,
        raw=raw_value,
        status=status,
        confidence=confidence,
        note=note,
    )


def normalise_licence(raw: Any) -> Normalisation | None:
    """Normalise a licence reference.

    UK onshore licences carry a block and licence number. Anything that does not
    parse is kept verbatim with a note rather than being reformatted into
    something that looks valid but is not.
    """
    if raw in (None, ""):
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip()
    match = re.search(r"(\d{2,4})\s*/\s*(\d{1,3})", text)
    if match:
        block, number = match.groups()
        return Normalisation(
            value=f"{block}/{int(number)}",
            raw=raw,
            status=EpistemicStatus.DERIVED.value,
            confidence=DataConfidence.HIGH.value,
            note="block and licence number extracted from the free-text reference",
        )
    return Normalisation(
        value=text,
        raw=raw,
        status=EpistemicStatus.FACT.value,
        confidence=DataConfidence.MEDIUM.value,
        note="licence reference retained verbatim; no block/number pattern matched",
    )


def normalise_region(raw: Any) -> Normalisation | None:
    """Map a county or region name onto one of the platform's map regions.

    Uses ITL1-style regions, which is the level at which national heat-demand and
    licensing statistics are published.
    """
    if raw in (None, ""):
        return None
    key = _clean(raw)
    mapping = {
        "north east": "North East",
        "north west": "North West",
        "yorkshire and the humber": "Yorkshire and the Humber",
        "yorkshire": "Yorkshire and the Humber",
        "east midlands": "East Midlands",
        "west midlands": "West Midlands",
        "east of england": "East of England",
        "east": "East of England",
        "london": "London",
        "south east": "South East",
        "south west": "South West",
        "wales": "Wales",
    }
    if key in mapping:
        return Normalisation(
            value=mapping[key], raw=raw,
            status=EpistemicStatus.DERIVED.value, confidence=DataConfidence.HIGH.value,
        )
    for candidate, region in mapping.items():
        if candidate in key:
            return Normalisation(
                value=region, raw=raw,
                status=EpistemicStatus.DERIVED.value, confidence=DataConfidence.MEDIUM.value,
                note=f"matched '{candidate}' within the supplied value",
            )
    return None


def confidence_from_variability(variability_c: float | None) -> str:
    """Confidence band implied by the spread of repeat measurements."""
    if variability_c is None:
        return DataConfidence.UNKNOWN.value
    for threshold, band in CONFIDENCE_FROM_VARIABILITY:
        if variability_c <= threshold:
            return band
    return DataConfidence.VERY_LOW.value


def normalise_well_record(
    raw: dict[str, Any],
    *,
    source: str,
    source_url: str | None = None,
    dataset_version: str | None = None,
) -> dict[str, Any]:
    """Normalise one raw well record into ORM-shaped keyword arguments.

    Returns a dict ready for ``Well(**kwargs)``. Raises
    :class:`RejectedRecord` when the record cannot be used at all.

    The dataset linkage lives on the ``Dataset`` row plus ``dataset_version`` on
    the well, rather than a ``dataset_id`` column: the same well may be
    corroborated by several dataset versions, and a single foreign key would
    lose that history.
    """
    from app.data_validation.validators import require_present, validate_well_record  # noqa: PLC0415

    result = validate_well_record(raw)
    if not result.is_valid:
        first = result.errors[0]
        raise RejectedRecord(first.code, first.message, first.field)

    cleaned = result.cleaned

    status = normalise_status(raw.get("status", raw.get("well_status")))
    purpose = normalise_purpose(
        raw.get("original_purpose", raw.get("purpose", raw.get("well_type")))
    )
    licence = normalise_licence(cleaned.get("licence"))
    region = normalise_region(
        raw.get("region") or cleaned.get("county") or raw.get("county")
    )

    temperature = normalise_temperature(
        raw.get("temperature_c", raw.get("bottom_hole_temperature", raw.get("bht"))),
        raw.get("temperature_method", raw.get("bht_type")),
        raw.get("temperature_depth_m", raw.get("total_depth_m")),
    )

    well_id = str(require_present(raw, "well_id", "wellname", "id", "name")).strip()
    drilling_year = cleaned.get("drilling_year")

    kwargs: dict[str, Any] = {
        "well_id": well_id,
        "well_name": str(
            raw.get("well_name", raw.get("wellname", raw.get("name", well_id)))
        ).strip(),
        "latitude": cleaned["latitude"],
        "longitude": cleaned["longitude"],
        "status": status.value,
        "status_raw": str(raw.get("status", "")) or None,
        "original_purpose": purpose.value,
        "operator": cleaned.get("operator"),
        "licence": licence.value if licence else cleaned.get("licence"),
        "region": region.value if region else cleaned.get("region"),
        "county": cleaned.get("county"),
        "total_depth_m": cleaned.get("total_depth_m"),
        "formation": cleaned.get("formation"),
        "basin": cleaned.get("basin"),
        "casing_string": cleaned.get("casing_string"),
        "completion_type": cleaned.get("completion_type"),
        "drilling_year": drilling_year,
        "source": source,
        "source_url": source_url,
        "source_record_id": str(raw.get("id", well_id)),
        "dataset_version": dataset_version,
        "data_confidence": DataConfidence.UNKNOWN.value,
        "known_data_gaps": {
            issue.field: issue.message
            for issue in result.warnings
        } or None,
    }

    if temperature is not None:
        kwargs.update(
            {
                "temperature_c": temperature.value,
                "temperature_status": temperature.status,
                "temperature_confidence": temperature.confidence or DataConfidence.LOW.value,
                "temperature_source": str(raw.get("temperature_source", "")) or None,
                "temperature_depth_m": parse_float(
                    raw.get("temperature_depth_m"), "temperature_depth_m"
                ),
            }
        )

    try:
        parsed_year = parse_date(
            raw.get("commissioned_date", raw.get("spud_date")), "commissioned_date"
        )
        if parsed_year:
            kwargs["commissioned_date"] = parsed_year
    except RejectedRecord as exc:
        # A date we cannot read is worth recording, not worth rejecting over.
        kwargs.setdefault("known_data_gaps", {})
        if isinstance(kwargs["known_data_gaps"], dict):
            kwargs["known_data_gaps"]["commissioned_date"] = exc.message

    return kwargs


def touch_timestamp() -> datetime:
    """Current time, used for ingestion bookkeeping."""
    return datetime.now(UTC)
