"""Stored procedure and SQL → dbt project decomposition."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from sqlshift.models import Dialect, MigrationObject, ObjectType
from sqlshift.parser.sql_parser import count_sql_complexity, extract_tables


def is_dbt_target(target: str | Dialect) -> bool:
    value = target.value if isinstance(target, Dialect) else str(target)
    return value.lower() in {"dbt-snowflake", "dbt_snowflake"}


def decompose_to_dbt(
    obj: MigrationObject,
    source: Dialect,
    project_name: str = "migration_project",
) -> dict[str, str]:
    """
    Decompose a SQL object into a dbt project structure.

    Uses converted Snowflake SQL (`obj.target_sql`) when available, otherwise source SQL.
    Returns dict of {relative_path: file_content}.
    """
    files: dict[str, str] = {}
    base_name = _sanitize_name(obj.name)
    sql = (obj.target_sql or obj.source_sql or "").strip()
    complexity = count_sql_complexity(obj.source_sql or sql, source)
    source_name = source.value.replace("-", "_")

    files["dbt_project.yml"] = yaml.dump(
        {
            "name": project_name,
            "version": "1.0.0",
            "profile": project_name,
            "model-paths": ["models"],
            "macro-paths": ["macros"],
            "seed-paths": ["seeds"],
            "test-paths": ["tests"],
            "vars": {"load_date": "CURRENT_DATE"},
            "models": {
                project_name: {
                    "staging": {"+materialized": "view"},
                    "intermediate": {"+materialized": "view"},
                    "marts": {"+materialized": "table"},
                }
            },
        },
        default_flow_style=False,
    )

    files["profiles.yml.example"] = (
        f"{project_name}:\n"
        f"  target: dev\n"
        f"  outputs:\n"
        f"    dev:\n"
        f"      type: snowflake\n"
        f"      account: <account>\n"
        f"      user: <user>\n"
        f"      password: <password>\n"
        f"      role: <role>\n"
        f"      database: <database>\n"
        f"      warehouse: <warehouse>\n"
        f"      schema: analytics\n"
        f"      threads: 4\n"
    )

    # Prefer physical source tables from original SQL
    source_tables = extract_tables(obj.source_sql or sql, source)
    # Drop obvious temp / intermediate names
    physical = {
        t
        for t in source_tables
        if not t.upper().startswith("TMP_")
        and "TEMP" not in t.upper()
        and not t.upper().startswith("TEMP_")
    }
    if physical:
        files["models/staging/_sources.yml"] = yaml.dump(
            {
                "version": 2,
                "sources": [
                    {
                        "name": source_name,
                        "description": f"Legacy {source.value} tables landed in Snowflake",
                        "database": "{{ var('source_database', 'RAW') }}",
                        "schema": "{{ var('source_schema', 'PUBLIC') }}",
                        "tables": [
                            {
                                "name": t.split(".")[-1].lower(),
                                "identifier": t.split(".")[-1],
                            }
                            for t in sorted(physical)
                        ],
                    }
                ],
            },
            default_flow_style=False,
        )

    if _looks_like_procedure(sql) or obj.object_type == ObjectType.STORED_PROCEDURE:
        models = _decompose_procedure(sql, base_name, source_name, obj.name)
    elif _has_ctes(sql) and complexity.get("ctes", 0) >= 2:
        models = _decompose_ctes(sql, base_name, source_name, obj.name)
    else:
        models = _simple_decomposition(sql, base_name, source_name, obj.name)

    for path, content in models.items():
        files[f"models/{path}"] = content

    files[f"models/marts/_schema_{base_name}.yml"] = _generate_schema_yml(models, base_name, obj.name)
    files["analyses/migration_validation.sql"] = _generate_validation_analysis(
        obj, base_name, source
    )

    if re.search(r"ZEROIFNULL|NVL|ISNULL|COALESCE\([^,]+,\s*0\)", obj.source_sql or sql, re.I):
        files["macros/null_safe.sql"] = _null_safe_macro()

    files["README.md"] = _project_readme(obj, source, base_name, models)

    obj.dbt_models = list(models.keys())
    return files


def format_dbt_project(files: dict[str, str], max_files: int | None = None) -> str:
    """Render a multi-file dbt project as a single readable text block for the UI."""
    preferred = sorted(
        files.keys(),
        key=lambda p: (
            0 if p.startswith("models/") else 1 if p.endswith(".yml") else 2,
            p,
        ),
    )
    if max_files is not None:
        preferred = preferred[:max_files]

    parts = [
        "-- MorphSQL dbt project (Snowflake)",
        f"-- {len(files)} files generated · copy into a dbt project directory",
        "",
    ]
    for rel in preferred:
        content = files[rel].rstrip()
        parts.append(f"-- ===== {rel} =====")
        parts.append(content)
        parts.append("")
    if max_files is not None and len(files) > max_files:
        remaining = sorted(set(files) - set(preferred))
        parts.append(f"-- … and {len(remaining)} more files: {', '.join(remaining)}")
    return "\n".join(parts).strip() + "\n"


def write_dbt_project(files: dict[str, str], output_dir: str | Path) -> Path:
    """Write dbt project files to disk."""
    output_dir = Path(output_dir)
    for rel_path, content in files.items():
        file_path = output_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return output_dir


def _looks_like_procedure(sql: str) -> bool:
    return bool(re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b", sql, re.I))


def _has_ctes(sql: str) -> bool:
    return bool(re.search(r"\bWITH\b", sql, re.I))


def _decompose_procedure(
    sql: str,
    base_name: str,
    source_name: str,
    original_name: str,
) -> dict[str, str]:
    """
    Turn procedural ETL into layered dbt models.

    CREATE TEMP TABLE x AS SELECT …  → staging / intermediate models
    INSERT INTO target SELECT …      → mart model
    """
    models: dict[str, str] = {}
    temp_model_names: dict[str, str] = {}

    # CREATE [OR REPLACE] [LOCAL] TEMP[ORARY] TABLE name [ON COMMIT …] AS SELECT …;
    temp_pat = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?"
        r"(?:LOCAL\s+)?TEMP(?:ORARY)?\s+TABLE\s+([\w.]+)"
        r"(?:\s+ON\s+COMMIT\s+\w+\s+ROWS)?"
        r"\s+AS\s+(SELECT\b.*?)(?:;|(?=\n\s*(?:CREATE|DELETE|INSERT|COMMIT|RETURN)))",
        re.IGNORECASE | re.DOTALL,
    )
    temps = list(temp_pat.finditer(sql))
    for i, match in enumerate(temps):
        raw_name = match.group(1).split(".")[-1]
        safe = _sanitize_name(raw_name)
        layer = "staging" if i == 0 else "intermediate"
        prefix = "stg" if layer == "staging" else "int"
        model_key = f"{layer}/{prefix}_{base_name}_{safe}.sql"
        model_ref = f"{prefix}_{base_name}_{safe}"
        temp_model_names[raw_name.upper()] = model_ref
        temp_model_names[safe.upper()] = model_ref

        select_sql = match.group(2).strip().rstrip(";")
        select_sql = _rewrite_sql_for_dbt(select_sql, source_name, temp_model_names)
        select_sql = _replace_params_with_vars(select_sql)

        models[model_key] = (
            f"{{{{ config(materialized='view') }}}}\n\n"
            f"-- From procedure {original_name} · temp table {raw_name}\n\n"
            f"{select_sql}\n"
        )

    # INSERT INTO schema.table SELECT …
    insert_pat = re.compile(
        r"INSERT\s+INTO\s+([\w.]+)\s+(SELECT\b.*?)(?:;|(?=\n\s*(?:CREATE|DELETE|INSERT|COMMIT|RETURN))|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    inserts = list(insert_pat.finditer(sql))
    if inserts:
        last = inserts[-1]
        target_table = last.group(1).split(".")[-1]
        mart_name = _sanitize_name(target_table) or base_name
        select_sql = last.group(2).strip().rstrip(";")
        select_sql = _rewrite_sql_for_dbt(select_sql, source_name, temp_model_names)
        select_sql = _replace_params_with_vars(select_sql)
        models[f"marts/{mart_name}.sql"] = (
            f"{{{{ config(materialized='incremental', unique_key='customer_id', "
            f"incremental_strategy='delete+insert') }}}}\n\n"
            f"-- Mart loaded by legacy procedure {original_name}\n"
            f"-- Target table: {last.group(1)}\n\n"
            f"{select_sql}\n"
        )
    elif not models:
        # Fallback: wrap whatever SELECT body we can find
        models.update(_simple_decomposition(sql, base_name, source_name, original_name))
    else:
        # Staging/int models exist but no INSERT — emit a mart that selects from last int model
        last_ref = list(temp_model_names.values())[-1]
        models[f"marts/{base_name}.sql"] = (
            f"{{{{ config(materialized='table') }}}}\n\n"
            f"-- Final model for procedure {original_name}\n\n"
            f"SELECT *\nFROM {{{{ ref('{last_ref}') }}}}\n"
        )

    return models


def _decompose_ctes(
    sql: str,
    base_name: str,
    source_name: str,
    original_name: str,
) -> dict[str, str]:
    """Split WITH cte AS (...) [, ...] SELECT into layered dbt models."""
    models: dict[str, str] = {}
    cte_map: dict[str, str] = {}

    body = re.sub(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:VIEW|TABLE)\s+\S+\s+AS\s*",
        "",
        sql,
        flags=re.I,
    ).strip().rstrip(";")

    if not re.match(r"WITH\b", body, re.I):
        return _simple_decomposition(sql, base_name, source_name, original_name)

    cte_iter = list(re.finditer(r"(\w+)\s+AS\s*\(", body, re.IGNORECASE))
    if not cte_iter:
        return _simple_decomposition(sql, base_name, source_name, original_name)

    last_cte_end = 0
    for idx, start in enumerate(cte_iter):
        name = start.group(1)
        prefix = body[: start.start()].rstrip().upper()
        if idx == 0 and not prefix.endswith("WITH"):
            continue
        if idx > 0 and not (prefix.endswith(",") or prefix.endswith(")")):
            # allow CTEs separated by commas
            pass

        open_paren = start.end() - 1
        depth = 0
        end = open_paren
        for i in range(open_paren, len(body)):
            if body[i] == "(":
                depth += 1
            elif body[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        cte_sql = body[open_paren + 1:end].strip()
        last_cte_end = end + 1

        safe = _sanitize_name(name)
        layer = "staging" if idx == 0 else "intermediate"
        model_prefix = "stg" if layer == "staging" else "int"
        model_ref = f"{model_prefix}_{base_name}_{safe}"
        cte_map[name.upper()] = model_ref

        rewritten = _rewrite_sql_for_dbt(cte_sql, source_name, cte_map)
        rewritten = _replace_params_with_vars(rewritten)
        models[f"{layer}/{model_ref}.sql"] = (
            f"{{{{ config(materialized='view') }}}}\n\n"
            f"-- CTE `{name}` from {original_name}\n\n"
            f"{rewritten}\n"
        )

    if not models:
        return _simple_decomposition(sql, base_name, source_name, original_name)

    rest = body[last_cte_end:].strip().lstrip(",").strip()
    final_match = re.search(r"\bSELECT\b[\s\S]*$", rest, re.I)
    if final_match:
        final_sql = final_match.group(0).strip().rstrip(";")
    else:
        last_ref = list(cte_map.values())[-1]
        final_sql = f"SELECT *\nFROM {{{{ ref('{last_ref}') }}}}"

    final_sql = _rewrite_sql_for_dbt(final_sql, source_name, cte_map)
    final_sql = _replace_cte_refs(final_sql, cte_map)
    final_sql = _replace_params_with_vars(final_sql)
    models[f"marts/{base_name}.sql"] = (
        f"{{{{ config(materialized='table') }}}}\n\n"
        f"-- Final SELECT from {original_name}\n\n"
        f"{final_sql}\n"
    )
    return models


def _simple_decomposition(
    sql: str,
    base_name: str,
    source_name: str,
    original_name: str,
) -> dict[str, str]:
    cleaned = _extract_select_body(sql)
    cleaned = _rewrite_sql_for_dbt(cleaned, source_name, {})
    cleaned = _replace_params_with_vars(cleaned)
    if not re.match(r"^\s*(WITH|SELECT)\b", cleaned, re.I):
        cleaned = (
            f"-- Procedural logic from {original_name} could not be fully auto-extracted.\n"
            f"-- Review and rewrite as declarative dbt SQL.\n"
            f"-- Original converted SQL (truncated):\n"
            f"/*\n{sql[:1500]}\n*/\n"
            f"SELECT 1 AS migration_placeholder\n"
        )
    return {
        f"marts/{base_name}.sql": (
            f"{{{{ config(materialized='table') }}}}\n\n"
            f"-- Converted from: {original_name}\n\n"
            f"{cleaned}\n"
        )
    }


def _extract_select_body(sql: str) -> str:
    sql = sql.strip().rstrip(";")
    sql = re.sub(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:VIEW|TABLE)\s+\S+\s+AS\s*",
        "",
        sql,
        flags=re.I,
    )
    match = re.search(r"\b(WITH|SELECT)\b[\s\S]*$", sql, re.I)
    return match.group(0).strip().rstrip(";") if match else sql


def _rewrite_sql_for_dbt(
    sql: str,
    source_name: str,
    known_models: dict[str, str],
) -> str:
    """Replace physical tables with source()/ref() and map temp tables to refs."""
    pattern = re.compile(r"\b(FROM|JOIN)\s+((?:[\w]+\.)?[\w]+)\b", re.IGNORECASE)

    def from_join_repl(match: re.Match) -> str:
        kw = match.group(1)
        name = match.group(2)
        if name.upper() in {"SELECT", "LATERAL", "UNNEST", "TABLE"}:
            return match.group(0)
        if "{{" in name:
            return match.group(0)
        key = name.upper()
        short = name.split(".")[-1].upper()
        if key in known_models or short in known_models:
            ref = known_models.get(key) or known_models[short]
            return f"{kw} {{{{ ref('{ref}') }}}}"
        if short.startswith("TMP_") or short.startswith("TEMP_"):
            return f"{kw} {{{{ ref('{_sanitize_name(short)}') }}}}"
        table = name.split(".")[-1].lower()
        return f"{kw} {{{{ source('{source_name}', '{table}') }}}}"

    return pattern.sub(from_join_repl, sql)


def _replace_cte_refs(sql: str, cte_map: dict[str, str]) -> str:
    """Replace remaining CTE name references in FROM/JOIN with ref()."""

    def repl(match: re.Match) -> str:
        kw, name = match.group(1), match.group(2)
        key = name.upper()
        if key in cte_map:
            return f"{kw} {{{{ ref('{cte_map[key]}') }}}}"
        return match.group(0)

    return re.sub(r"\b(FROM|JOIN)\s+([\w]+)\b", repl, sql, flags=re.I)


def _replace_params_with_vars(sql: str) -> str:
    """Map Snowflake :PARAM / load_date style params to dbt vars."""

    def bind_repl(match: re.Match) -> str:
        name = match.group(1)
        if name.lower() in {"load_date", "as_of_date", "run_date"}:
            return "{{ var('load_date') }}"
        return "{{ var('" + name.lower() + "') }}"

    sql = re.sub(r":([A-Za-z_][\w]*)", bind_repl, sql)

    # Bare procedure params — skip text already inside Jinja
    parts = re.split(r"(\{\{.*?\}\})", sql, flags=re.DOTALL)
    out: list[str] = []
    for part in parts:
        if part.startswith("{{"):
            out.append(part)
            continue
        for param in ("load_date", "as_of_date", "run_date"):
            part = re.sub(
                rf"(?<![\w.]){param}(?![\w])",
                "{{ var('load_date') }}",
                part,
                flags=re.IGNORECASE,
            )
        out.append(part)
    return "".join(out)


def _generate_schema_yml(models: dict[str, str], base_name: str, original_name: str) -> str:
    mart_names = [
        Path(p).stem for p in models if p.startswith("marts/") and p.endswith(".sql")
    ]
    schema_models = []
    for name in mart_names or [base_name]:
        schema_models.append(
            {
                "name": name,
                "description": f"Migrated dbt model from legacy object {original_name}",
                "columns": [
                    {
                        "name": "customer_id",
                        "description": "Primary business key (adjust as needed)",
                        "tests": ["not_null"],
                    }
                ],
            }
        )
    return yaml.dump({"version": 2, "models": schema_models}, default_flow_style=False)


def _generate_validation_analysis(obj: MigrationObject, base_name: str, source: Dialect) -> str:
    source_name = source.value.replace("-", "_")
    mart = base_name
    if obj.dbt_models:
        marts = [Path(m).stem for m in obj.dbt_models if m.startswith("marts/")]
        if marts:
            mart = marts[0]
    return f"""-- Migration validation analysis for {obj.name}
-- Run after `dbt build` to compare source vs target

SELECT 'source' AS platform, COUNT(*) AS row_count
FROM {{{{ source('{source_name}', '{base_name}') }}}}
UNION ALL
SELECT 'target' AS platform, COUNT(*) AS row_count
FROM {{{{ ref('{mart}') }}}};
"""


def _null_safe_macro() -> str:
    return """{% macro null_safe(column, default=0) %}
    COALESCE({{ column }}, {{ default }})
{% endmacro %}
"""


def _project_readme(
    obj: MigrationObject,
    source: Dialect,
    base_name: str,
    models: dict[str, str],
) -> str:
    model_list = "\n".join(f"- `{m}`" for m in sorted(models))
    return f"""# dbt project — {base_name}

Generated by MorphSQL from `{obj.name}` ({source.value} → dbt-snowflake).

## Models
{model_list}

## Run
```bash
dbt deps
dbt build --vars '{{"load_date": "2024-01-15"}}'
```

Review staging sources in `models/staging/_sources.yml` and adjust database/schema vars.
"""


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.lower()).strip("_")
