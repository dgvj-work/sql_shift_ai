"""Hybrid SQL translation engine: rules + dialect conversion."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from sqlshift.knowledge.behavior import get_behavior_warnings
from sqlshift.models import Dialect, MigrationObject
from sqlshift.parser.sql_parser import (
    detect_unsupported_features,
    get_sqlglot_dialect,
    parse_sql_multi,
)

# Vertica-specific DDL/DML syntax to strip or replace before transpilation
VERTICA_SYNTAX_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bSEGMENTED\s+BY\s+HASH\s*\([^)]+\)\s*ALL\s*NODES", ""),
    (r"\bENCODED\s+BY\s+[^;\n]+", ""),
    (r"\bINCLUDE\s+SCHEMA\s+PRIVILEGES\b", ""),
    (r"\bON\s+COMMIT\s+PRESERVE\s+ROWS\b", ""),
    (r"\bPROJECTION\s+\w+\b", ""),
    # Vertica ORDER BY on CREATE TABLE (not SELECT) — strip trailing table ordering clause
    (r"(CREATE\s+(?:OR\s+REPLACE\s+)?(?:LOCAL\s+TEMP|TEMP|TEMPORARY)?\s*TABLE\s+[\w.]+\s*\([^;]+\))\s*ORDER\s+BY[^;]+", r"\1"),
]

# Statement-level patterns applied after function mapping
POST_TRANSFORM_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bCREATE\s+LOCAL\s+TEMP\s+TABLE\b", "CREATE OR REPLACE TEMPORARY TABLE"),
    (r"\bCREATE\s+TEMP\s+TABLE\b", "CREATE OR REPLACE TEMPORARY TABLE"),
    (r"\bCREATE\s+TEMPORARY\s+TABLE\b", "CREATE OR REPLACE TEMPORARY TABLE"),
    (r"\bSYSDATE\b", "CURRENT_TIMESTAMP()"),
    (r"\bGETDATE\s*\(\s*\)", "CURRENT_TIMESTAMP()"),
    # Vertica DATEDIFF('unit', start, end) → Snowflake DATEDIFF(unit, start, end)
    (r"DATEDIFF\s*\(\s*'(\w+)'\s*,", r"DATEDIFF(\1, "),
]


def _replace_function_calls(sql: str, func_name: str, replacer) -> tuple[str, bool]:
    """Replace function calls preserving parenthesized arguments."""
    pattern = re.compile(rf"\b{re.escape(func_name)}\s*\(", re.IGNORECASE)
    changed = False
    parts: list[str] = []
    last = 0

    for match in pattern.finditer(sql):
        parts.append(sql[last:match.start()])
        start_paren = match.end() - 1
        depth = 0
        end_paren = start_paren
        for i in range(start_paren, len(sql)):
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
                if depth == 0:
                    end_paren = i
                    break

        args = sql[start_paren + 1:end_paren]
        replacement = replacer(args)
        parts.append(replacement)
        changed = True
        last = end_paren + 1

    parts.append(sql[last:])
    return "".join(parts), changed


def _apply_function_mappings(sql: str) -> tuple[str, list[str]]:
    """Apply Vertica/Oracle → Snowflake function mappings."""
    applied: list[str] = []

    def zeroifnull(args: str) -> str:
        return f"COALESCE({args.strip()}, 0)"

    def nvl(args: str) -> str:
        return f"COALESCE({args.strip()})"

    def isnull(args: str) -> str:
        return f"COALESCE({args.strip()})"

    def to_char(args: str) -> str:
        return f"TO_VARCHAR({args.strip()})"

    def string_agg_to_listagg(args: str) -> str:
        return f"LISTAGG({args.strip()})"

    mappings = [
        ("ZEROIFNULL", zeroifnull, "ZEROIFNULL → COALESCE(expr, 0)"),
        ("NVL", nvl, "NVL → COALESCE"),
        ("ISNULL", isnull, "ISNULL → COALESCE"),
        ("TO_CHAR", to_char, "TO_CHAR → TO_VARCHAR"),
        ("STRING_AGG", string_agg_to_listagg, "STRING_AGG → LISTAGG"),
        ("APPROXIMATE_COUNT_DISTINCT", lambda a: f"APPROX_COUNT_DISTINCT({a.strip()})",
         "APPROXIMATE_COUNT_DISTINCT → APPROX_COUNT_DISTINCT"),
    ]

    for func_name, replacer, label in mappings:
        sql, changed = _replace_function_calls(sql, func_name, replacer)
        if changed:
            applied.append(label)

    return sql, applied


def _apply_date_arithmetic(sql: str) -> tuple[str, list[str]]:
    """Convert Vertica date - N patterns to Snowflake DATEADD."""
    applied: list[str] = []
    # Match: identifier - integer in date comparison contexts (load_date - 90, CURRENT_DATE - 365)
    pattern = re.compile(
        r"(?<![\w.])([A-Za-z_][\w.]*|CURRENT_DATE|CURRENT_TIMESTAMP)\s*-\s*(\d+)(?!\.\d)",
    )

    def replacer(match: re.Match) -> str:
        applied.append(f"Date arithmetic: {match.group(0)} → DATEADD")
        col = match.group(1)
        days = match.group(2)
        return f"DATEADD(day, -{days}, {col})"

    new_sql = pattern.sub(replacer, sql)
    return new_sql, applied


def _apply_syntax_replacements(sql: str) -> tuple[str, list[str]]:
    """Apply Vertica-specific syntax stripping."""
    applied: list[str] = []
    for pattern, replacement in VERTICA_SYNTAX_REPLACEMENTS:
        if re.search(pattern, sql, re.IGNORECASE | re.DOTALL):
            sql = re.sub(pattern, replacement, sql, flags=re.IGNORECASE | re.DOTALL)
            applied.append(f"Removed Vertica-specific syntax")
    return sql, applied


def _apply_post_transforms(sql: str) -> tuple[str, list[str]]:
    """Apply post-processing replacements."""
    applied: list[str] = []
    for pattern, replacement in POST_TRANSFORM_REPLACEMENTS:
        if re.search(pattern, sql, re.IGNORECASE):
            sql = re.sub(pattern, replacement, sql, flags=re.IGNORECASE)
            applied.append(f"Pattern: {pattern[:40]}")
    return sql, applied


def _convert_procedure_wrapper(sql: str, target: Dialect) -> tuple[str, list[str]]:
    """Convert Vertica/Oracle procedure wrappers to Snowflake procedure syntax."""
    applied: list[str] = []
    if target not in (Dialect.SNOWFLAKE, Dialect.DBT_SNOWFLAKE):
        return sql, applied

    proc_match = re.search(
        r"CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+([\w.]+)\s*\(([^)]*)\)",
        sql,
        re.IGNORECASE,
    )
    if not proc_match:
        return sql, applied

    proc_name = proc_match.group(1)
    params = proc_match.group(2).strip()

    # Extract body between BEGIN and END
    body_match = re.search(r"\bBEGIN\b(.*?)\bEND\s*;?\s*\$\$?", sql, re.IGNORECASE | re.DOTALL)
    if not body_match:
        return sql, applied

    body = body_match.group(1).strip()
    # Remove COMMIT statements (Snowflake procedures handle transactions differently)
    body = re.sub(r"\bCOMMIT\s*;", "", body, flags=re.IGNORECASE)

    # Normalize parameter references: load_date → :LOAD_DATE for Snowflake
    if params:
        for param in params.split(","):
            param = param.strip()
            if not param:
                continue
            parts = param.split()
            pname = parts[0]  # e.g. load_date from "load_date DATE"
            body = re.sub(
                rf"\b{re.escape(pname)}\b",
                f":{pname.upper()}",
                body,
                flags=re.IGNORECASE,
            )

    snowflake_proc = f"""CREATE OR REPLACE PROCEDURE {proc_name}({params.upper() if params else ""})
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
BEGIN
{body}
    RETURN 'OK';
END;
$$;"""

    applied.append("Converted procedure wrapper to Snowflake syntax")
    return snowflake_proc, applied


def _transpile_statements(sql: str, source: Dialect, target: Dialect) -> tuple[str, list[str], list[str]]:
    """Transpile individual SQL statements via sqlglot."""
    auto: list[str] = []
    review: list[str] = []
    source_dialect = get_sqlglot_dialect(source)
    target_dialect = get_sqlglot_dialect(target)

    statements = parse_sql_multi(sql, source)
    if not statements:
        statements = parse_sql_multi(sql, Dialect.SNOWFLAKE)  # fallback parser

    if not statements:
        return sql, auto, review

    translated_parts: list[str] = []
    for stmt in statements:
        try:
            translated = stmt.sql(dialect=target_dialect, pretty=True)
            translated_parts.append(translated)
            auto.append("Dialect transpilation")
        except Exception:
            try:
                translated_parts.append(stmt.sql(dialect=source_dialect, pretty=True))
                review.append("Statement retained in source dialect — manual review required")
            except Exception:
                review.append("Unparseable statement skipped")

    if translated_parts:
        return ";\n\n".join(translated_parts), auto, review
    return sql, auto, review


def translate_sql(
    sql: str,
    source: Dialect,
    target: Dialect,
) -> tuple[str, float, list[str], list[str]]:
    """
    Translate SQL using hybrid rule-based + sqlglot approach.

    Returns: (translated_sql, confidence, auto_converted, requires_review)
    """
    auto_converted: list[str] = []
    requires_review: list[str] = []
    confidence = 100.0
    original = sql

    working_sql = sql

    # Step 1: Vertica syntax cleanup
    if source == Dialect.VERTICA:
        working_sql, applied = _apply_syntax_replacements(working_sql)
        auto_converted.extend(applied)

    # Step 2: Function mappings (must happen before sqlglot)
    working_sql, func_applied = _apply_function_mappings(working_sql)
    auto_converted.extend(func_applied)

    # Step 3: Date arithmetic
    working_sql, date_applied = _apply_date_arithmetic(working_sql)
    auto_converted.extend(date_applied)

    # Step 4: Post transforms (temp tables, datediff, etc.)
    working_sql, post_applied = _apply_post_transforms(working_sql)
    auto_converted.extend(post_applied)

    # Step 5: Procedure wrapper conversion (for procedural SQL)
    is_procedure = bool(re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b", working_sql, re.I))
    if is_procedure:
        working_sql, proc_applied = _convert_procedure_wrapper(working_sql, target)
        auto_converted.extend(proc_applied)
        requires_review.append("Verify procedure parameter bindings and temp table scope")
        confidence -= 5
    else:
        # Step 6: sqlglot transpilation for non-procedural SQL
        transpiled, t_auto, t_review = _transpile_statements(working_sql, source, target)
        if t_auto:
            working_sql = transpiled
            auto_converted.extend(t_auto)
        requires_review.extend(t_review)
        if t_review:
            confidence -= len(t_review) * 5

    # Step 7: Unsupported features (only flag if not already converted)
    unsupported = detect_unsupported_features(original, source, target)
    converted_funcs = {a.split("→")[0].strip().upper() for a in func_applied if "→" in a}
    for feature in unsupported:
        feat_upper = feature.upper().replace(" ", "")
        if any(cf in feat_upper or feat_upper in cf for cf in converted_funcs):
            continue
        requires_review.append(f"Unsupported: {feature}")
        confidence -= 3

    # Step 8: Behavior warnings
    target_dialect = get_sqlglot_dialect(target)
    warnings = get_behavior_warnings(original, source.value, target_dialect)
    for warning in warnings:
        requires_review.append(f"Behavior: {warning.name.replace('_', ' ')}")
        if warning.severity == "high":
            confidence -= 5
        elif warning.severity == "medium":
            confidence -= 2

    # Step 9: Manual review patterns
    manual_patterns = {
        "Dynamic SQL": r"EXECUTE\s+IMMEDIATE|EXEC\s*\(",
        "Cursor processing": r"\bCURSOR\b",
        "Exception handling": r"\bEXCEPTION\s+WHEN\b",
    }
    for name, pattern in manual_patterns.items():
        if re.search(pattern, original, re.IGNORECASE):
            requires_review.append(name)
            confidence -= 8

    confidence = max(0.0, min(100.0, confidence))
    return working_sql.strip(), confidence, list(dict.fromkeys(auto_converted)), list(dict.fromkeys(requires_review))


def translate_object(
    obj: MigrationObject,
    source: Dialect,
    target: Dialect,
) -> MigrationObject:
    """Translate a single migration object."""
    target_sql, confidence, auto_converted, requires_review = translate_sql(
        obj.source_sql, source, target
    )
    obj.target_sql = target_sql
    obj.conversion_confidence = confidence
    obj.auto_converted = auto_converted
    obj.requires_review = requires_review
    obj.unsupported_features = detect_unsupported_features(obj.source_sql, source, target)
    return obj


def translate_objects(
    objects: list[MigrationObject],
    source: Dialect,
    target: Dialect,
) -> list[MigrationObject]:
    """Translate all migration objects."""
    return [translate_object(obj, source, target) for obj in objects]
