"""Semantic equivalence validation and reconciliation query generation."""

from __future__ import annotations

from morphsql.models import Dialect, MigrationObject, ValidationResult


def generate_reconciliation_queries(
    obj: MigrationObject,
    source: Dialect,
    target: Dialect,
    source_schema: str = "SOURCE",
    target_schema: str = "TARGET",
) -> dict[str, str]:
    """Generate reconciliation SQL queries for source vs target comparison."""
    table = obj.name
    queries: dict[str, str] = {}

    queries["row_count"] = f"""-- Row count comparison: {table}
SELECT 'source' AS platform, COUNT(*) AS row_count
FROM {source_schema}.{table}
UNION ALL
SELECT 'target' AS platform, COUNT(*) AS row_count
FROM {target_schema}.{table};"""

    queries["distinct_count"] = f"""-- Distinct count comparison: {table}
SELECT 'source' AS platform, COUNT(DISTINCT *) AS distinct_rows
FROM {source_schema}.{table}
UNION ALL
SELECT 'target' AS platform, COUNT(DISTINCT *) AS distinct_rows
FROM {target_schema}.{table};"""

    queries["null_rates"] = f"""-- Null rate analysis: {table}
-- Adjust column list based on actual schema
SELECT
    column_name,
    SUM(CASE WHEN column_value IS NULL THEN 1 ELSE 0 END) AS null_count,
    COUNT(*) AS total_count,
    ROUND(100.0 * SUM(CASE WHEN column_value IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS null_pct
FROM {target_schema}.{table}
GROUP BY column_name;"""

    queries["checksum"] = f"""-- Checksum comparison: {table}
SELECT 'source' AS platform,
       COUNT(*) AS row_count,
       SUM(HASH(*)) AS row_checksum
FROM {source_schema}.{table}
UNION ALL
SELECT 'target' AS platform,
       COUNT(*) AS row_count,
       SUM(HASH(*)) AS row_checksum
FROM {target_schema}.{table};"""

    queries["sample_diff"] = f"""-- Sample record differences: {table}
SELECT s.*
FROM {source_schema}.{table} s
FULL OUTER JOIN {target_schema}.{table} t
  ON s.id = t.id
WHERE s.id IS NULL OR t.id IS NULL
LIMIT 100;"""

    return queries


def generate_dbt_tests(obj: MigrationObject) -> list[str]:
    """Generate dbt test definitions for a migrated object."""
    base = obj.name.lower()
    tests = [
        f"models/{base}.sql -- schema tests: not_null, unique on primary key",
        f"tests/assert_{base}_row_count_reconciliation.sql",
        f"tests/assert_{base}_metric_tolerance.sql",
    ]

    if any("date" in r.lower() or "timestamp" in r.lower() for r in obj.requires_review):
        tests.append(f"tests/assert_{base}_timezone_boundaries.sql")

    if any("null" in r.lower() for r in obj.requires_review):
        tests.append(f"tests/assert_{base}_null_handling.sql")

    obj.tests_generated = tests
    return tests


def simulate_validation(
    obj: MigrationObject,
    tolerance: float = 0.01,
) -> list[ValidationResult]:
    """
    Generate simulated validation results based on detected risk factors.

    In production, this would execute against real databases.
    For the open-source core, we simulate based on risk profile.
    """
    results: list[ValidationResult] = []

    # Row count — likely passes unless behavior differences detected
    null_warnings = [r for r in obj.requires_review if "null" in r.lower() or "empty_string" in r.lower()]
    row_passed = len(null_warnings) == 0
    results.append(ValidationResult(
        object_name=obj.name,
        check_name="row_count",
        passed=row_passed,
        source_value=1_000_000,
        target_value=999_793 if not row_passed else 1_000_000,
        difference=207 if not row_passed else 0,
        root_cause="Empty string vs NULL handling" if not row_passed else "",
        recommendation="NULLIF(TRIM(column), '')" if not row_passed else "No action needed",
    ))

    # Metric tolerance
    float_warnings = [r for r in obj.requires_review if "float" in r.lower() or "precision" in r.lower()]
    results.append(ValidationResult(
        object_name=obj.name,
        check_name="metric_tolerance",
        passed=len(float_warnings) == 0,
        source_value=1.0,
        target_value=1.0 if len(float_warnings) == 0 else 1.0003,
        difference=0 if len(float_warnings) == 0 else 0.0003,
        root_cause="Floating-point precision" if float_warnings else "",
        recommendation=f"Set tolerance to {tolerance}" if float_warnings else "",
    ))

    # Structural
    results.append(ValidationResult(
        object_name=obj.name,
        check_name="structural_compilation",
        passed=obj.conversion_confidence >= 70,
        source_value="compiles",
        target_value="compiles" if obj.conversion_confidence >= 70 else "review_required",
    ))

    # Null rate
    results.append(ValidationResult(
        object_name=obj.name,
        check_name="null_rate",
        passed=len(null_warnings) == 0,
        source_value="2.1%",
        target_value="2.1%" if len(null_warnings) == 0 else "2.4%",
        root_cause="NULL semantics difference" if null_warnings else "",
    ))

    return results


def generate_incremental_strategy(sql: str) -> dict[str, str]:
    """Detect legacy loading pattern and recommend dbt incremental strategy."""
    sql_upper = sql.upper()
    recommendation: dict[str, str] = {}

    if "DELETE FROM" in sql_upper and "INSERT INTO" in sql_upper:
        recommendation = {
            "legacy_pattern": "Delete and reload",
            "dbt_materialized": "incremental",
            "incremental_strategy": "delete+insert",
            "unique_key": "id, load_date",
            "incremental_predicates": "load_date >= current_date - 3",
            "warning": "Consider rolling lookback window for late-arriving records",
        }
    elif "WHERE" in sql_upper and ("LOAD_DATE" in sql_upper or "UPDATED_AT" in sql_upper):
        recommendation = {
            "legacy_pattern": "Timestamp-based incremental load",
            "dbt_materialized": "incremental",
            "incremental_strategy": "merge",
            "unique_key": "id",
            "incremental_predicates": "updated_at > (SELECT MAX(updated_at) FROM {{ this }})",
            "warning": "Validate watermark column has no NULL values",
        }
    elif "MERGE INTO" in sql_upper:
        recommendation = {
            "legacy_pattern": "Merge/upsert",
            "dbt_materialized": "incremental",
            "incremental_strategy": "merge",
            "unique_key": "id",
        }
    else:
        recommendation = {
            "legacy_pattern": "Full refresh",
            "dbt_materialized": "table",
            "incremental_strategy": "N/A",
        }

    return recommendation
