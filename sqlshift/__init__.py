"""SQLShiftAI — Data platform migration intelligence toolkit."""

__version__ = "0.3.0"
__product_name__ = "SQLShiftAI"

from sqlshift.models import (
    Dialect,
    MigrationObject,
    MigrationReport,
    ObjectType,
    RiskLevel,
)

__all__ = [
    "__version__",
    "__product_name__",
    "Dialect",
    "MigrationObject",
    "MigrationReport",
    "ObjectType",
    "RiskLevel",
]
