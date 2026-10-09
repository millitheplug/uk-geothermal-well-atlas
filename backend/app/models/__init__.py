"""SQLAlchemy model registry.

Importing this package makes every table available on `Base.metadata`, which is
what `create_all()` and Alembic's autogenerate rely on.
"""

from app.db.base import Base
from app.models.analysis import (
    Analysis,
    FinancialModel,
    RegulatoryRequirement,
    Risk,
    Scenario,
    ValidationAction,
)
from app.models.evidence import (
    Assumption,
    CalculationTrace,
    Claim,
    Dataset,
    Evidence,
)
from app.models.geology import Formation, Geology, GeothermalSetting
from app.models.heat import Building, EnergyPrice, HeatDemand, HeatNetwork
from app.models.project import Project, ProjectWell
from app.models.user import APIKey, AuditLog, Tenant, User, UserRole
from app.models.well import Well, WellIntegrity, WellLog, WellTemperature

__all__ = [
    "APIKey",
    "Analysis",
    "Assumption",
    "AuditLog",
    "Base",
    "Building",
    "CalculationTrace",
    "Claim",
    "Dataset",
    "EnergyPrice",
    "Evidence",
    "FinancialModel",
    "Formation",
    "Geology",
    "GeothermalSetting",
    "HeatDemand",
    "HeatNetwork",
    "Project",
    "ProjectWell",
    "RegulatoryRequirement",
    "Risk",
    "Scenario",
    "Tenant",
    "User",
    "UserRole",
    "ValidationAction",
    "Well",
    "WellIntegrity",
    "WellLog",
    "WellTemperature",
]
