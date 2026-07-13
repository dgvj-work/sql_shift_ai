"""Core data models for SQLShiftAI."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Dialect(str, Enum):
    VERTICA = "vertica"
    ORACLE = "oracle"
    SNOWFLAKE = "snowflake"
    BIGQUERY = "bigquery"
    REDSHIFT = "redshift"
    DBT_SNOWFLAKE = "dbt-snowflake"


class ObjectType(str, Enum):
    TABLE = "table"
    VIEW = "view"
    STORED_PROCEDURE = "stored_procedure"
    FUNCTION = "function"
    SQL_SCRIPT = "sql_script"
    DBT_MODEL = "dbt_model"
    AIRFLOW_DAG = "airflow_dag"
    TEMP_TABLE = "temp_table"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MigrationCategory(str, Enum):
    AUTO_MIGRATE = "automatically_migratable"
    AUTO_WITH_REVIEW = "automatically_migratable_with_review"
    PARTIAL = "partially_migratable"
    MANUAL_REDESIGN = "manual_redesign_required"
    RETIRE = "retire_or_consolidate"


class ColumnLineage(BaseModel):
    column: str
    table: str
    source_columns: list[str] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)


class TableLineage(BaseModel):
    table: str
    upstream: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)
    columns: list[ColumnLineage] = Field(default_factory=list)


class RiskFactor(BaseModel):
    name: str
    score: int
    description: str
    category: str = "complexity"


class MigrationObject(BaseModel):
    name: str
    object_type: ObjectType
    source_path: str = ""
    source_sql: str = ""
    target_sql: str = ""
    complexity_score: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    risk_factors: list[RiskFactor] = Field(default_factory=list)
    migration_category: MigrationCategory = MigrationCategory.AUTO_MIGRATE
    conversion_confidence: float = 0.0
    auto_converted: list[str] = Field(default_factory=list)
    requires_review: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    downstream_count: int = 0
    business_rules: list[str] = Field(default_factory=list)
    dbt_models: list[str] = Field(default_factory=list)
    tests_generated: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DashboardMetrics(BaseModel):
    total_objects: int = 0
    auto_migratable: int = 0
    requires_review: int = 0
    requires_redesign: int = 0
    recommended_retirement: int = 0
    conversion_completed_pct: float = 0.0
    validation_passed_pct: float = 0.0
    lineage_coverage_pct: float = 0.0
    test_coverage_pct: float = 0.0
    migration_risk_score: float = 0.0
    estimated_annual_savings_usd: tuple[float, float] = (0.0, 0.0)


class ValidationResult(BaseModel):
    object_name: str
    check_name: str
    passed: bool
    source_value: str | float | int | None = None
    target_value: str | float | int | None = None
    difference: str | float | int | None = None
    root_cause: str = ""
    recommendation: str = ""


class MigrationReport(BaseModel):
    source_dialect: Dialect
    target_dialect: Dialect
    repository_path: str
    objects: list[MigrationObject] = Field(default_factory=list)
    lineage: list[TableLineage] = Field(default_factory=list)
    dashboard: DashboardMetrics = Field(default_factory=DashboardMetrics)
    validation_results: list[ValidationResult] = Field(default_factory=list)
    behavior_warnings: list[str] = Field(default_factory=list)
    retirement_candidates: list[str] = Field(default_factory=list)
    consolidation_opportunities: list[str] = Field(default_factory=list)
