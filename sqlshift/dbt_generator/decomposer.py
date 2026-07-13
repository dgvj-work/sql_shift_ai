"""Stored procedure and SQL to dbt project decomposition."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from sqlshift.models import Dialect, MigrationObject, ObjectType
from sqlshift.parser.sql_parser import count_sql_complexity, extract_tables


def decompose_to_dbt(
    obj: MigrationObject,
    source: Dialect,
    project_name: str = "migration_project",
) -> dict[str, str]:
    """
    Decompose a SQL object into a dbt project structure.

    Returns dict of {relative_path: file_content}.
    """
    files: dict[str, str] = {}
    base_name = _sanitize_name(obj.name)
    complexity = count_sql_complexity(obj.source_sql, source)

    # Project config
    files["dbt_project.yml"] = yaml.dump({
        "name": project_name,
        "version": "1.0.0",
        "profile": project_name,
        "model-paths": ["models"],
        "macro-paths": ["macros"],
        "seed-paths": ["seeds"],
        "test-paths": ["tests"],
        "models": {
            project_name: {
                "staging": {"+materialized": "view"},
                "intermediate": {"+materialized": "view"},
                "marts": {"+materialized": "table"},
            }
        },
    }, default_flow_style=False)

    # Sources
    source_tables = extract_tables(obj.source_sql, source)
    if source_tables:
        sources: dict[str, Any] = {
            "version": 2,
            "sources": [{
                "name": source.value,
                "database": "{{ var('source_database', 'RAW') }}",
                "schema": "{{ var('source_schema', 'PUBLIC') }}",
                "tables": [
                    {"name": t.split(".")[-1].lower(), "identifier": t.split(".")[-1]}
                    for t in sorted(source_tables)
                ],
            }],
        }
        files["models/staging/_sources.yml"] = yaml.dump(sources, default_flow_style=False)

    # Decompose based on complexity
    cte_count = complexity.get("ctes", 0)
    if cte_count >= 3 or obj.object_type == ObjectType.STORED_PROCEDURE:
        models = _decompose_by_ctes(obj, base_name)
    else:
        models = _simple_decomposition(obj, base_name)

    for path, content in models.items():
        files[f"models/{path}"] = content

    # Schema YAML with tests
    schema = _generate_schema_yml(models, base_name)
    files[f"models/marts/_schema_{base_name}.yml"] = schema

    # Migration validation analysis
    files["analyses/migration_validation.sql"] = _generate_validation_analysis(obj, base_name, source)

    # Macros for common patterns
    if re.search(r"ZEROIFNULL|NVL|ISNULL", obj.source_sql, re.I):
        files["macros/null_safe.sql"] = _null_safe_macro()

    obj.dbt_models = list(models.keys())
    return files


def write_dbt_project(
    files: dict[str, str],
    output_dir: str | Path,
) -> Path:
    """Write dbt project files to disk."""
    output_dir = Path(output_dir)
    for rel_path, content in files.items():
        file_path = output_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return output_dir


def _decompose_by_ctes(obj: MigrationObject, base_name: str) -> dict[str, str]:
    """Split a large SQL object into staging/intermediate/mart models."""
    models: dict[str, str] = {}

    # Extract CTEs
    cte_pattern = r"(\w+)\s+AS\s*\("
    ctes = re.findall(cte_pattern, obj.source_sql, re.IGNORECASE)

    if ctes:
        for i, cte_name in enumerate(ctes[:8]):
            layer = "staging" if i < len(ctes) // 2 else "intermediate"
            safe_name = _sanitize_name(cte_name)
            models[f"{layer}/stg_{base_name}_{safe_name}.sql"] = (
                f"{{{{ config(materialized='view') }}}}\n\n"
                f"-- Decomposed from {obj.name} CTE: {cte_name}\n"
                f"-- TODO: Extract CTE body and add ref() dependencies\n\n"
                f"SELECT *\nFROM {{{{ source('{obj.object_type.value}', '{safe_name}') }}}}\n"
            )

    # Final mart model
    models[f"marts/{base_name}.sql"] = (
        f"{{{{ config(materialized='table') }}}}\n\n"
        f"-- Converted from: {obj.name}\n"
        f"-- Source: {obj.source_path}\n\n"
        f"{_wrap_as_dbt_model(obj.target_sql or obj.source_sql, base_name)}\n"
    )

    return models


def _simple_decomposition(obj: MigrationObject, base_name: str) -> dict[str, str]:
    """Simple single-model decomposition for smaller SQL objects."""
    return {
        f"marts/{base_name}.sql": (
            f"{{{{ config(materialized='table') }}}}\n\n"
            f"-- Converted from: {obj.name}\n\n"
            f"{_wrap_as_dbt_model(obj.target_sql or obj.source_sql, base_name)}\n"
        ),
    }


def _wrap_as_dbt_model(sql: str, model_name: str) -> str:
    """Clean SQL for dbt model usage."""
    # Remove CREATE statements, keep SELECT logic
    sql = re.sub(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:VIEW|TABLE)\s+\S+\s+AS\s*", "", sql, flags=re.I)
    sql = re.sub(r";\s*$", "", sql.strip())
    if not sql.upper().strip().startswith("SELECT") and not sql.upper().strip().startswith("WITH"):
        sql = f"-- Original procedural logic requires decomposition\n-- {sql[:200]}..."
    return sql


def _generate_schema_yml(models: dict[str, str], base_name: str) -> str:
    """Generate dbt schema.yml with tests."""
    schema: dict[str, Any] = {
        "version": 2,
        "models": [{
            "name": base_name,
            "description": f"Migrated model converted from legacy {base_name}",
            "columns": [
                {
                    "name": "id",
                    "description": "Primary identifier",
                    "tests": ["not_null", "unique"],
                },
            ],
        }],
    }
    return yaml.dump(schema, default_flow_style=False)


def _generate_validation_analysis(obj: MigrationObject, base_name: str, source: Dialect) -> str:
    source_name = source.value.replace("-", "_")
    return f"""-- Migration validation analysis for {obj.name}
-- Run after dbt build to compare source vs target

-- Row count comparison
SELECT 'source' AS platform, COUNT(*) AS row_count
FROM {{{{ source('{source_name}', '{base_name}') }}}}
UNION ALL
SELECT 'target' AS platform, COUNT(*) AS row_count
FROM {{{{ ref('{base_name}') }}}};

-- Null rate comparison (adjust columns as needed)
-- SELECT
--   COUNT(*) AS total_rows,
--   SUM(CASE WHEN column_name IS NULL THEN 1 ELSE 0 END) AS null_count
-- FROM {{{{ ref('{base_name}') }}}};
"""


def _null_safe_macro() -> str:
    return """{% macro null_safe(column, default=0) %}
    COALESCE({{ column }}, {{ default }})
{% endmacro %}
"""


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.lower()).strip("_")
