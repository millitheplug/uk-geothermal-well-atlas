"""Controlled vocabularies for the domain.

`EpistemicStatus` is the backbone of the evidence discipline in this platform.
Every number that reaches a user-facing surface carries one of these labels.
It is deliberately strict: anything not directly read from a source document is
never `MEASURED` or `FACT`.
"""

from __future__ import annotations

from enum import StrEnum


class EpistemicStatus(StrEnum):
    """Provenance of a value. Ordered from strongest to weakest."""

    FACT = "FACT"
    """Directly stated in a cited source document (e.g. operator licence)."""

    MEASURED = "MEASURED"
    """Instrument reading recorded in a well log or temperature survey."""

    DERIVED = "DERIVED"
    """Computed from FACT/MEASURED values by a transparent formula."""

    ESTIMATE = "ESTIMATE"
    """Third-party or analyst estimate; method documented, source cited."""

    MODELLED = "MODELLED"
    """Output of a simulation or correlation model rather than a direct reading.
    Distinct from ESTIMATE because the method is a published model rather than a
    judgement, and therefore reproducible and auditable in a way an estimate is
    not."""

    ASSUMPTION = "ASSUMPTION"
    """Chosen by the analyst or defaulted by the system. Not observed."""

    UNKNOWN = "UNKNOWN"
    """No defensible value available. Must never be silently imputed."""


class DataConfidence(StrEnum):
    """Ordinal confidence band for a well or a single field."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    VERY_LOW = "very_low"
    UNKNOWN = "unknown"


class WellStatus(StrEnum):
    """Well lifecycle status. Normalised across NSTA/BGS vocabularies."""

    PRODUCING = "producing"
    NON_PRODUCING = "non_producing"
    SUSPENDED = "suspended"
    PLUGGED_ABANDONED = "plugged_abandoned"
    ABANDONED = "abandoned"
    DRILLING = "drilling"
    COMPLETED = "completed"
    EXPLORATION = "exploration"
    UNKNOWN = "unknown"


class OriginalPurpose(StrEnum):
    OIL = "oil"
    GAS = "gas"
    COALBED_METHANE = "coalbed_methane"
    GEOTHERMAL = "geothermal"
    WATER_ABSTRACTION = "water_abstraction"
    STRUCTURE_EXPLOSIVES = "structure_explosives"
    EXPLORATION = "exploration"
    UNKNOWN = "unknown"


class WellIntegrityStatus(StrEnum):
    """Reuse-readiness of the existing wellbore and wellhead."""

    GOOD_CONDITION = "good_condition"
    PARTIALLY_MECHANICAL = "partially_mechanical"
    ABANDONED_NO_ACCESS = "abandoned_no_access"
    SUSPENDED_INACCESSIBLE = "suspended_inaccessible"
    POOR_UNKNOWN = "poor_unknown"
    UNKNOWN = "unknown"


class GeothermalConfiguration(StrEnum):
    CLOSED_LOOP = "closed_loop"
    OPEN_LOOP = "open_loop"
    CLOSED_LOOP_PLUS_HEAT_PUMP = "closed_loop_plus_heat_pump"
    OPEN_LOOP_PLUS_HEAT_PUMP = "open_loop_plus_heat_pump"


class ScoreComponent(StrEnum):
    THERMAL = "thermal"
    INTEGRITY = "integrity"
    DEMAND = "demand"
    ECONOMICS = "economics"
    NETWORK = "network"
    GEOMETRY = "geometry"
    REGULATORY = "regulatory"
    DATA_CONFIDENCE = "data_confidence"


class Recommendation(StrEnum):
    HIGH_PRIORITY = "HIGH PRIORITY"
    MEDIUM_PRIORITY = "MEDIUM PRIORITY"
    LOW_PRIORITY = "LOW PRIORITY"
    DO_NOT_PURSUE = "DO NOT PURSUE"


class RiskCategory(StrEnum):
    WELL_INTEGRITY = "well_integrity"
    TEMPERATURE_UNCERTAINTY = "temperature_uncertainty"
    THERMAL_DECLINE = "thermal_decline"
    CORROSION = "corrosion"
    SCALING = "scaling"
    GROUNDWATER = "groundwater"
    NETWORK_DISTANCE = "network_distance"
    HEAT_DEMAND_UNCERTAINTY = "heat_demand_uncertainty"
    CAPEX = "capex"
    ELECTRICITY_PRICE = "electricity_price"
    HEAT_PRICE = "heat_price"
    REGULATION = "regulation"
    PLANNING = "planning"
    LAND_ACCESS = "land_access"
    CUSTOMER_CONNECTION = "customer_connection"
    CONSTRUCTION = "construction"
    OPERATIONS = "operations"


class Likelihood(StrEnum):
    VERY_UNLIKELY = "very_unlikely"
    UNLIKELY = "unlikely"
    POSSIBLE = "possible"
    LIKELY = "likely"
    VERY_LIKELY = "very_likely"


class Impact(StrEnum):
    NEGLIGIBLE = "negligible"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    SEVERE = "severe"


class EvidenceReliability:
    """Named reliability weights on a 0-1 scale.

    Not an enum: these are numeric weights, not labels. Used as the default
    value for ``Evidence.reliability`` when a source type is known but a
    per-instance judgement has not yet been made.
    """

    OPERATOR_PRIMARY = 0.95
    REGULATOR = 0.92
    NATIONAL_SURVEY = 0.88
    ACADEMIC_PEER_REVIEWED = 0.85
    ACADEMIC = 0.75
    INDUSTRY_REPORT = 0.65
    COMMERCIAL_VENDOR = 0.55
    PRESS = 0.35
    UNVERIFIED = 0.20

    BY_SOURCE_TYPE: dict[str, float] = {
        "operator_well_report": OPERATOR_PRIMARY,
        "nsta_record": REGULATOR,
        "ea_consent": REGULATOR,
        "bgs_publication": NATIONAL_SURVEY,
        "bgs_well_data": NATIONAL_SURVEY,
        "peer_reviewed": ACADEMIC_PEER_REVIEWED,
        "academic": ACADEMIC,
        "industry_report": INDUSTRY_REPORT,
        "vendor_dataset": COMMERCIAL_VENDOR,
        "press": PRESS,
        "unverified": UNVERIFIED,
    }

    @classmethod
    def for_source_type(cls, source_type: str | None) -> float:
        """Default reliability for a document type, defaulting to unverified."""
        if not source_type:
            return cls.UNVERIFIED
        return cls.BY_SOURCE_TYPE.get(source_type, cls.UNVERIFIED)


class AnalysisStage(StrEnum):
    """Progress stages surfaced to the user during an assessment."""

    DATA_VALIDATION = "data_validation"
    GEOLOGY = "geology"
    TEMPERATURE = "temperature"
    WELL_INTEGRITY = "well_integrity"
    HEAT_DEMAND = "heat_demand"
    ENGINEERING = "engineering"
    ECONOMICS = "economics"
    RISK = "risk"
    FINAL_ASSESSMENT = "final_assessment"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class ProjectStage(StrEnum):
    SOURCING = "sourcing"
    SCREENING = "screening"
    DUE_DILIGENCE = "due_diligence"
    VALIDATION = "validation"
    FEED_STUDY = "feed_study"
    INVESTMENT_DECISION = "investment_decision"
    DELIVERY = "delivery"
    OPERATING = "operating"
    CLOSED = "closed"
    REJECTED = "rejected"


class ValidationActionType(StrEnum):
    DESKTOP_STUDY = "desktop_study"
    DATA_ROOM_REQUEST = "data_room_request"
    SITE_VISIT = "site_visit"
    TEMPERATURE_LOGGING = "temperature_logging"
    PRESSURE_TEST = "pressure_test"
    CASING_INSPECTION = "casing_inspection"
    FLOW_TEST = "flow_test"
    GEOCHEMISTRY_SAMPLING = "geochemistry_sampling"
    HEAT_DEMAND_SURVEY = "heat_demand_survey"
    NETWORK_COST_STUDY = "network_cost_study"
    PLANNING_PRE_APPLICATION = "planning_pre_application"
    LAND_ACCESS_NEGOTIATION = "land_access_negotiation"
    COMMERCIAL_TERMS = "commercial_terms"


class ValidationActionPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceReliability(StrEnum):
    """Ingestion-side dataset quality rating, recorded per dataset."""

    TIER_A = "tier_a"  # regulator / national survey primary
    TIER_B = "tier_b"  # academic / curated compilation
    TIER_C = "tier_c"  # commercial / vendor aggregate
    TIER_MOCK = "tier_mock"  # synthetic development data - never production
