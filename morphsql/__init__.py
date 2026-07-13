"""MorphSQL — AI SQL Migration Agent."""

__version__ = "0.4.0"
__product_name__ = "MorphSQL"

from morphsql.models import (
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
