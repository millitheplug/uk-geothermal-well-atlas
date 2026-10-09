"""Validation rules for ingested data.

Applied by every adapter before a row is written. The philosophy is that a
malformed record is *rejected with a reason* rather than coerced into shape,
because a well at latitude 54.9000 in the Irish Sea is not a well near Whitehaven
and silently moving it would put a fake point on a national map.

Three tiers:

* **Blocking** - the record cannot be used at all. Latitude, longitude and a
  stable identifier.
* **Quality** - the record is usable but the value is flagged as estimated or
  low confidence. Depth, temperature, status.
* **Advisory** - noted in the validation report, never blocking. Odd operator
  names, missing formations, implausible drilling years.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

#: UK onshore bounding box, with a small margin for offshore-drilled targets
#: whose surface location is still on the UKCS.
UK_MIN_LAT, UK_MAX_LAT = 49.8, 61.2
UK_MIN_LON, UK_MAX_LON = -8.7, 2.2

#: Plausibility bounds. Outside these the value is a data error, not an outlier.
MAX_TOTAL_DEPTH_M = 15_000.0
MIN_PLAUSIBLE_TOTAL_DEPTH_M = 10.0
MAX_TEMPERATURE_C = 400.0
MIN_YEAR = 1900


@dataclass
class ValidationIssue:
    """One problem found in one record."""

    field: str
    code: str
    message: str
    severity: str = "error"  # error | warning | info
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "value": self.value,
        }


@dataclass
class ValidationResult:
    """Outcome of validating one record."""

    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    cleaned: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def error_codes(self) -> list[str]:
        return [i.code for i in self.errors]


class RejectedRecord(Exception):
    """Raised by a normaliser to reject a record with a recorded reason.

    Carrying the reason as an exception means an adapter can let it propagate to
    :meth:`Adapter.run`, which captures it per record and continues.
    """

    def __init__(self, code: str, message: str, field_name: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.field_name = field_name


def parse_float(
    value: Any, field_name: str, *, allow_none: bool = True
) -> float | None:
    """Coerce to float, preserving ``None``.

    Strings with units are handled because published datasets routinely include
    them ("1,850 m", "62.5 degC"). Anything genuinely unparseable is a rejection,
    not a silent ``None``, because the two mean different things.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise RejectedRecord("missing_required_field", f"{field_name} is required", field_name)

    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise RejectedRecord(
                "non_finite_value", f"{field_name} is not finite ({value})", field_name
            )
        return number

    text = str(value).strip()
    # Strip thousands separators and any trailing unit.
    text = re.sub(r"[,_]", "", text)
    match = re.match(r"^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    if not match:
        raise RejectedRecord(
            "unparseable_number", f"could not parse {field_name} from '{value}'", field_name
        )
    return float(match.group(0))


def parse_int(value: Any, field_name: str, *, allow_none: bool = True) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise RejectedRecord("missing_required_field", f"{field_name} is required", field_name)
    number = parse_float(value, field_name, allow_none=False)
    return int(number)


def parse_date(value: Any, field_name: str, *, allow_none: bool = True) -> date | None:
    """Parse the several date formats published UK datasets actually use."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise RejectedRecord("missing_required_field", f"{field_name} is required", field_name)

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    # Ordered most-specific first: a bare year must not be read as a day/month.
    for fmt, order in (
        ("%Y-%m-%d", ("Y", "m", "d")),
        ("%d/%m/%Y", ("d", "m", "Y")),
        ("%m/%d/%Y", ("m", "d", "Y")),
        ("%Y/%m/%d", ("Y", "m", "d")),
        ("%d-%m-%Y", ("d", "m", "Y")),
    ):
        try:
            return _assemble(text, fmt, order)
        except ValueError:
            continue

    if re.fullmatch(r"\d{4}", text):
        return date(int(text), 1, 1)

    raise RejectedRecord(
        "unparseable_date", f"could not parse {field_name} from '{value}'", field_name
    )


def _assemble(text: str, fmt: str, order: tuple[str, ...]) -> date:
    """Build a date from a delimited string according to an explicit order.

    Written out rather than driven by ``strptime`` because the same delimited
    string is ambiguous between UK day-first and US month-first conventions, and
    guessing wrong puts a well survey in the wrong month. Each format is listed
    explicitly so the intended convention is visible at the call site.
    """
    pieces = text.replace("-", "/").replace(".", "/").split("/")
    if len(pieces) != 3:
        raise ValueError(f"{text!r} does not have three components for {fmt}")

    lookup = {"Y": int, "m": int, "d": int}
    values = {key: lookup[key](piece) for key, piece in zip(order, pieces, strict=True)}
    return date(values["Y"], values["m"], values["d"])


def require_present(record: dict[str, Any], field_name: str, *aliases: str) -> Any:
    """Return the first populated value among a field and its aliases."""
    for key in (field_name, *aliases):
        if key in record and record[key] not in (None, ""):
            return record[key]
    raise RejectedRecord(
        "missing_required_field",
        f"none of {', '.join((field_name, *aliases))} is present",
        field_name,
    )


def validate_coordinates(
    latitude: Any, longitude: Any, *, field_lat: str = "latitude", field_lon: str = "longitude"
) -> tuple[float, float]:
    """Reject coordinates outside the UK bounding box.

    Blocking, and deliberately strict. A coordinate that has been transposed
    (54.9 where 245.9 was meant, or a sign error) would place a well in the sea or
    abroad, and a plausible-looking point on the map is worse than no point.
    """
    lat = parse_float(latitude, field_lat, allow_none=False)
    lon = parse_float(longitude, field_lon, allow_none=False)

    if not (UK_MIN_LAT <= lat <= UK_MAX_LAT):
        raise RejectedRecord(
            "latitude_out_of_range",
            f"latitude {lat} is outside the UK bounding box "
            f"({UK_MIN_LAT} to {UK_MAX_LAT})",
            field_lat,
        )
    if not (UK_MIN_LON <= lon <= UK_MAX_LON):
        raise RejectedRecord(
            "longitude_out_of_range",
            f"longitude {lon} is outside the UK bounding box "
            f"({UK_MIN_LON} to {UK_MAX_LON})",
            field_lon,
        )
    return lat, lon


def validate_well_record(record: dict[str, Any]) -> ValidationResult:
    """Validate and clean one well record.

    Returns a :class:`ValidationResult` rather than raising, so a caller can
    accumulate issues across fields and report them all at once. A record with any
    blocking error is marked invalid and must not be written.
    """
    issues: list[ValidationIssue] = []
    cleaned: dict[str, Any] = {}

    # ---- blocking: identity ------------------------------------------
    try:
        raw_id = require_present(record, "well_id", "wellname", "id", "name")
        cleaned["well_id"] = str(raw_id).strip()
    except RejectedRecord as exc:
        issues.append(ValidationIssue(exc.field_name, exc.code, exc.message, "error"))
        return ValidationResult(is_valid=False, issues=issues, cleaned=cleaned)

    # ---- blocking: location ------------------------------------------
    try:
        lat, lon = validate_coordinates(
            record.get("latitude", record.get("lat")),
            record.get("longitude", record.get("lon", record.get("long"))),
        )
        cleaned["latitude"] = lat
        cleaned["longitude"] = lon
    except RejectedRecord as exc:
        issues.append(ValidationIssue(exc.field_name, exc.code, exc.message, "error"))

    # ---- quality: depth ----------------------------------------------
    depth = parse_float(
        record.get("total_depth_m", record.get("totaldepth")), "total_depth_m"
    )
    if depth is not None:
        if depth > MAX_TOTAL_DEPTH_M:
            issues.append(
                ValidationIssue(
                    "total_depth_m",
                    "implausible_depth",
                    f"total depth {depth} m exceeds the {MAX_TOTAL_DEPTH_M} m maximum; "
                    "the value may be in different units or a data error",
                    "warning",
                    depth,
                )
            )
            cleaned["total_depth_m"] = None
        elif depth < MIN_PLAUSIBLE_TOTAL_DEPTH_M:
            issues.append(
                ValidationIssue(
                    "total_depth_m",
                    "implausible_depth",
                    f"total depth {depth} m is shallower than any UK onshore well",
                    "warning",
                    depth,
                )
            )
            cleaned["total_depth_m"] = None
        else:
            cleaned["total_depth_m"] = depth

    # ---- quality: temperature ----------------------------------------
    temperature = parse_float(
        record.get("temperature_c", record.get("bottom_hole_temperature", record.get("bht"))),
        "temperature_c",
    )
    if temperature is not None:
        if temperature > MAX_TEMPERATURE_C:
            issues.append(
                ValidationIssue(
                    "temperature_c",
                    "implausible_temperature",
                    f"temperature {temperature} degC exceeds the {MAX_TEMPERATURE_C} degC "
                    "maximum",
                    "warning",
                    temperature,
                )
            )
            cleaned["temperature_c"] = None
        else:
            cleaned["temperature_c"] = temperature

    # ---- quality: year -----------------------------------------------
    year = parse_int(record.get("drilling_year", record.get("year")), "drilling_year")
    if year is not None:
        if year < MIN_YEAR:
            issues.append(
                ValidationIssue(
                    "drilling_year",
                    "implausible_year",
                    f"drilling year {year} precedes commercial UK onshore drilling",
                    "warning",
                    year,
                )
            )
        else:
            cleaned["drilling_year"] = year

    # ---- advisory: descriptive fields --------------------------------
    for source_key, target_key in (
        ("operator", "operator"),
        ("licence", "licence"),
        ("formation", "formation"),
        ("field", "field_name"),
        ("county", "county"),
        ("region", "region"),
        ("basin", "basin"),
        ("casing_string", "casing_string"),
        ("completion_type", "completion_type"),
    ):
        value = record.get(source_key)
        if value not in (None, ""):
            cleaned[target_key] = str(value).strip()

    if not cleaned.get("operator"):
        issues.append(
            ValidationIssue(
                "operator",
                "missing_operator",
                "no operator recorded; the licence holder cannot be identified",
                "warning",
            )
        )
    if not cleaned.get("formation"):
        issues.append(
            ValidationIssue(
                "formation",
                "missing_formation",
                "no formation recorded, so the geothermal context cannot be established",
                "warning",
            )
        )
    if cleaned.get("total_depth_m") is None:
        issues.append(
            ValidationIssue(
                "total_depth_m",
                "missing_depth",
                "no usable total depth; the well cannot be assessed geometrically",
                "warning",
            )
        )
    if cleaned.get("temperature_c") is None:
        issues.append(
            ValidationIssue(
                "temperature_c",
                "missing_temperature",
                "no temperature measurement; thermal potential is unknown, not zero",
                "warning",
            )
        )

    return ValidationResult(
        is_valid=not any(i.severity == "error" for i in issues),
        issues=issues,
        cleaned=cleaned,
    )


def validate_building_record(record: dict[str, Any]) -> ValidationResult:
    """Validate one building record from a heat demand dataset."""
    issues: list[ValidationIssue] = []
    cleaned: dict[str, Any] = {}

    try:
        lat, lon = validate_coordinates(
            record.get("latitude", record.get("lat")),
            record.get("longitude", record.get("lon")),
        )
        cleaned["latitude"] = lat
        cleaned["longitude"] = lon
    except RejectedRecord as exc:
        issues.append(ValidationIssue(exc.field_name, exc.code, exc.message, "error"))
        return ValidationResult(is_valid=False, issues=issues, cleaned=cleaned)

    for source_key, target_key in (
        ("postcode", "postcode"),
        ("building_type", "building_type"),
        ("current_fuel", "current_fuel"),
        ("current_heating", "current_heating_technology"),
        ("region", "region"),
        ("address_reference", "address_reference"),
    ):
        value = record.get(source_key)
        if value not in (None, ""):
            cleaned[target_key] = str(value).strip()

    for source_key, target_key in (
        ("annual_heat_demand_kwh", "annual_heat_demand_kwh"),
        ("annual_demand_kwh", "annual_heat_demand_kwh"),
        ("peak_heat_demand_kw", "peak_heat_demand_kw"),
        ("floor_area_m2", "floor_area_m2"),
        ("required_supply_temperature_c", "required_supply_temperature_c"),
        ("construction_year", "construction_year"),
    ):
        value = record.get(source_key)
        if value not in (None, ""):
            try:
                cleaned[target_key] = parse_float(value, target_key)
            except RejectedRecord as exc:
                issues.append(
                    ValidationIssue(target_key, exc.code, exc.message, "warning", value)
                )

    if not cleaned.get("building_type"):
        issues.append(
            ValidationIssue(
                "building_type",
                "missing_building_type",
                "no building type; demand aggregation cannot be weighted",
                "warning",
            )
        )
    if not cleaned.get("annual_heat_demand_kwh"):
        issues.append(
            ValidationIssue(
                "annual_heat_demand_kwh",
                "missing_demand",
                "no annual heat demand figure; this building contributes zero by "
                "absence of data, not by absence of heat",
                "warning",
            )
        )

    return ValidationResult(
        is_valid=not any(i.severity == "error" for i in issues),
        issues=issues,
        cleaned=cleaned,
    )


def summarise(results: list[ValidationResult]) -> dict[str, Any]:
    """Aggregate validation results into the report stored on the dataset."""
    total = len(results)
    valid = sum(1 for r in results if r.is_valid)
    code_counts: dict[str, int] = {}
    for result in results:
        for issue in result.issues:
            code_counts[issue.code] = code_counts.get(issue.code, 0) + 1

    # Quality score: the share of records that passed, discounted by how many
    # carried warnings. A dataset where every record passes but most are missing
    # a temperature is not a good dataset for this platform.
    warning_rate = (
        sum(1 for r in results if r.warnings) / total if total else 0.0
    )
    pass_rate = valid / total if total else 0.0
    quality = round(max(0.0, pass_rate * (1.0 - 0.5 * warning_rate)), 4)

    return {
        "records": total,
        "valid": valid,
        "invalid": total - valid,
        "pass_rate": round(pass_rate, 4),
        "warning_rate": round(warning_rate, 4),
        "quality_score": quality,
        "issue_codes": dict(sorted(code_counts.items(), key=lambda kv: -kv[1])),
    }
