"""Hybrid SQL translation engine: source/target-gated rules + sqlglot."""

from __future__ import annotations

import re

from sqlshift.knowledge.behavior import get_behavior_warnings
from sqlshift.models import Dialect, MigrationObject
from sqlshift.parser.sql_parser import (
    detect_unsupported_features,
    get_sqlglot_dialect,
    parse_sql_multi,
)

# All conversion routes exposed by the product
SOURCE_DIALECTS = (
    Dialect.VERTICA,
    Dialect.ORACLE,
    Dialect.REDSHIFT,
    Dialect.BIGQUERY,
    Dialect.SNOWFLAKE,
)
TARGET_DIALECTS = (
    Dialect.SNOWFLAKE,
    Dialect.DBT_SNOWFLAKE,
    Dialect.BIGQUERY,
)

# Vertica-specific DDL/DML syntax to strip before transpilation
VERTICA_SYNTAX_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bSEGMENTED\s+BY\s+HASH\s*\([^)]+\)\s*ALL\s*NODES", ""),
    (r"\bENCODED\s+BY\s+[^;\n]+", ""),
    (r"\bINCLUDE\s+SCHEMA\s+PRIVILEGES\b", ""),
    (r"\bON\s+COMMIT\s+PRESERVE\s+ROWS\b", ""),
    (r"\bPROJECTION\s+\w+\b", ""),
    (
        r"(CREATE\s+(?:OR\s+REPLACE\s+)?(?:LOCAL\s+TEMP|TEMP|TEMPORARY)?\s*TABLE\s+[\w.]+\s*\([^;]+\))\s*ORDER\s+BY[^;]+",
        r"\1",
    ),
]

ORACLE_SYNTAX_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bFROM\s+DUAL\b", ""),
]

REDSHIFT_SYNTAX_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bDISTSTYLE\s+\w+\b", ""),
    (r"\bDISTKEY\s*\([^)]*\)", ""),
    (r"\bSORTKEY\s*\([^)]*\)", ""),
    (r"\bENCODE\s+\w+\b", ""),
]


def normalize_target(target: Dialect) -> Dialect:
    """Map product targets to the SQL dialect family used for conversion."""
    if target == Dialect.DBT_SNOWFLAKE:
        return Dialect.SNOWFLAKE
    return target


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
        parts.append(replacer(args))
        changed = True
        last = end_paren + 1

    parts.append(sql[last:])
    return "".join(parts), changed


def _function_mappings(source: Dialect, target: Dialect) -> list[tuple[str, object, str]]:
    """Return function remaps for a source→target pair."""
    target = normalize_target(target)
    mappings: list[tuple[str, object, str]] = []

    if source == Dialect.VERTICA and target == Dialect.SNOWFLAKE:
        mappings = [
            ("ZEROIFNULL", lambda a: f"COALESCE({a.strip()}, 0)", "ZEROIFNULL → COALESCE(expr, 0)"),
            ("NVL", lambda a: f"COALESCE({a.strip()})", "NVL → COALESCE"),
            ("ISNULL", lambda a: f"COALESCE({a.strip()})", "ISNULL → COALESCE"),
            ("TO_CHAR", lambda a: f"TO_VARCHAR({a.strip()})", "TO_CHAR → TO_VARCHAR"),
            ("STRING_AGG", lambda a: f"LISTAGG({a.strip()})", "STRING_AGG → LISTAGG"),
            (
                "APPROXIMATE_COUNT_DISTINCT",
                lambda a: f"APPROX_COUNT_DISTINCT({a.strip()})",
                "APPROXIMATE_COUNT_DISTINCT → APPROX_COUNT_DISTINCT",
            ),
        ]
    elif source == Dialect.VERTICA and target == Dialect.BIGQUERY:
        mappings = [
            ("ZEROIFNULL", lambda a: f"IFNULL({a.strip()}, 0)", "ZEROIFNULL → IFNULL(expr, 0)"),
            ("NVL", lambda a: f"IFNULL({a.strip()})", "NVL → IFNULL"),
            ("ISNULL", lambda a: f"IFNULL({a.strip()})", "ISNULL → IFNULL"),
            ("TO_CHAR", lambda a: f"FORMAT('%s', {a.strip()})", "TO_CHAR → FORMAT"),
            (
                "APPROXIMATE_COUNT_DISTINCT",
                lambda a: f"APPROX_COUNT_DISTINCT({a.strip()})",
                "APPROXIMATE_COUNT_DISTINCT → APPROX_COUNT_DISTINCT",
            ),
        ]
    elif source == Dialect.ORACLE and target == Dialect.SNOWFLAKE:
        mappings = [
            ("NVL", lambda a: f"COALESCE({a.strip()})", "NVL → COALESCE"),
            ("NVL2", lambda a: _nvl2_to_iff(a), "NVL2 → IFF"),
            ("TO_CHAR", lambda a: f"TO_VARCHAR({a.strip()})", "TO_CHAR → TO_VARCHAR"),
            ("SYSDATE", lambda _a: "CURRENT_TIMESTAMP()", "SYSDATE → CURRENT_TIMESTAMP()"),
        ]
    elif source == Dialect.ORACLE and target == Dialect.BIGQUERY:
        mappings = [
            ("NVL", lambda a: f"IFNULL({a.strip()})", "NVL → IFNULL"),
            ("NVL2", lambda a: _nvl2_to_if(a), "NVL2 → IF"),
            ("TO_CHAR", lambda a: f"FORMAT('%s', {a.strip()})", "TO_CHAR → FORMAT"),
            ("SYSDATE", lambda _a: "CURRENT_TIMESTAMP()", "SYSDATE → CURRENT_TIMESTAMP()"),
        ]
    elif source == Dialect.REDSHIFT and target == Dialect.SNOWFLAKE:
        mappings = [
            ("NVL", lambda a: f"COALESCE({a.strip()})", "NVL → COALESCE"),
            ("ISNULL", lambda a: f"COALESCE({a.strip()})", "ISNULL → COALESCE"),
            ("GETDATE", lambda _a: "CURRENT_TIMESTAMP()", "GETDATE → CURRENT_TIMESTAMP()"),
        ]
    elif source == Dialect.REDSHIFT and target == Dialect.BIGQUERY:
        mappings = [
            ("NVL", lambda a: f"IFNULL({a.strip()})", "NVL → IFNULL"),
            ("ISNULL", lambda a: f"IFNULL({a.strip()})", "ISNULL → IFNULL"),
            ("GETDATE", lambda _a: "CURRENT_TIMESTAMP()", "GETDATE → CURRENT_TIMESTAMP()"),
            ("LISTAGG", lambda a: f"STRING_AGG({a.strip()})", "LISTAGG → STRING_AGG"),
        ]
    elif source == Dialect.BIGQUERY and target == Dialect.SNOWFLAKE:
        mappings = [
            ("IFNULL", lambda a: f"COALESCE({a.strip()})", "IFNULL → COALESCE"),
            ("STRING_AGG", lambda a: f"LISTAGG({a.strip()})", "STRING_AGG → LISTAGG"),
            ("SAFE_CAST", lambda a: f"TRY_CAST({a.strip()})", "SAFE_CAST → TRY_CAST"),
        ]
    elif source == Dialect.SNOWFLAKE and target == Dialect.BIGQUERY:
        mappings = [
            ("IFF", lambda a: f"IF({a.strip()})", "IFF → IF"),
            ("LISTAGG", lambda a: f"STRING_AGG({a.strip()})", "LISTAGG → STRING_AGG"),
            ("TRY_CAST", lambda a: f"SAFE_CAST({a.strip()})", "TRY_CAST → SAFE_CAST"),
            ("TO_VARCHAR", lambda a: f"CAST({a.strip()} AS STRING)", "TO_VARCHAR → CAST(... AS STRING)"),
        ]

    return mappings


def _nvl2_to_iff(args: str) -> str:
    parts = [p.strip() for p in _split_args(args)]
    if len(parts) == 3:
        return f"IFF({parts[0]} IS NOT NULL, {parts[1]}, {parts[2]})"
    return f"NVL2({args})"


def _nvl2_to_if(args: str) -> str:
    parts = [p.strip() for p in _split_args(args)]
    if len(parts) == 3:
        return f"IF({parts[0]} IS NOT NULL, {parts[1]}, {parts[2]})"
    return f"NVL2({args})"


def _split_args(args: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in args:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _apply_function_mappings(sql: str, source: Dialect, target: Dialect) -> tuple[str, list[str]]:
    applied: list[str] = []
    for func_name, replacer, label in _function_mappings(source, target):
        # Zero-arg style replacements like SYSDATE() / GETDATE()
        if func_name.upper() in {"SYSDATE", "GETDATE"}:
            bare = re.compile(rf"\b{func_name}\b(?!\s*\()", re.IGNORECASE)
            if bare.search(sql):
                sql = bare.sub("CURRENT_TIMESTAMP()", sql)
                applied.append(label)
            sql, changed = _replace_function_calls(sql, func_name, lambda _a: "CURRENT_TIMESTAMP()")
            if changed and label not in applied:
                applied.append(label)
            continue

        sql, changed = _replace_function_calls(sql, func_name, replacer)
        if changed:
            applied.append(label)
    return sql, applied


def _apply_date_arithmetic(sql: str, target: Dialect) -> tuple[str, list[str]]:
    """Convert `col - N` day arithmetic to target idioms."""
    applied: list[str] = []
    target = normalize_target(target)
    pattern = re.compile(
        r"(?<![\w.])([A-Za-z_][\w.]*|CURRENT_DATE|CURRENT_TIMESTAMP)\s*-\s*(\d+)(?!\.\d)",
    )

    def snowflake_replacer(match: re.Match) -> str:
        applied.append(f"Date arithmetic: {match.group(0)} → DATEADD")
        return f"DATEADD(day, -{match.group(2)}, {match.group(1)})"

    def bigquery_replacer(match: re.Match) -> str:
        applied.append(f"Date arithmetic: {match.group(0)} → DATE_SUB")
        return f"DATE_SUB({match.group(1)}, INTERVAL {match.group(2)} DAY)"

    if target == Dialect.SNOWFLAKE:
        return pattern.sub(snowflake_replacer, sql), applied
    if target == Dialect.BIGQUERY:
        return pattern.sub(bigquery_replacer, sql), applied
    return sql, applied


def _apply_syntax_replacements(sql: str, source: Dialect) -> tuple[str, list[str]]:
    applied: list[str] = []
    replacements: list[tuple[str, str]] = []
    if source == Dialect.VERTICA:
        replacements = VERTICA_SYNTAX_REPLACEMENTS
        label = "Removed Vertica-specific syntax"
    elif source == Dialect.ORACLE:
        replacements = ORACLE_SYNTAX_REPLACEMENTS
        label = "Removed Oracle-specific syntax"
    elif source == Dialect.REDSHIFT:
        replacements = REDSHIFT_SYNTAX_REPLACEMENTS
        label = "Removed Redshift-specific syntax"
    else:
        return sql, applied

    for pattern, replacement in replacements:
        if re.search(pattern, sql, re.IGNORECASE | re.DOTALL):
            sql = re.sub(pattern, replacement, sql, flags=re.IGNORECASE | re.DOTALL)
            if label not in applied:
                applied.append(label)
    return sql, applied


def _post_transforms(target: Dialect) -> list[tuple[str, str, str]]:
    target = normalize_target(target)
    if target == Dialect.SNOWFLAKE:
        return [
            (r"\bCREATE\s+LOCAL\s+TEMP\s+TABLE\b", "CREATE OR REPLACE TEMPORARY TABLE", "LOCAL TEMP → TEMPORARY TABLE"),
            (r"\bCREATE\s+TEMP\s+TABLE\b", "CREATE OR REPLACE TEMPORARY TABLE", "TEMP → TEMPORARY TABLE"),
            (r"\bCREATE\s+TEMPORARY\s+TABLE\b", "CREATE OR REPLACE TEMPORARY TABLE", "TEMPORARY TABLE normalized"),
            (r"\bSYSDATE\b", "CURRENT_TIMESTAMP()", "SYSDATE → CURRENT_TIMESTAMP()"),
            (r"\bGETDATE\s*\(\s*\)", "CURRENT_TIMESTAMP()", "GETDATE → CURRENT_TIMESTAMP()"),
            (r"DATEDIFF\s*\(\s*'(\w+)'\s*,", r"DATEDIFF(\1, ", "DATEDIFF unit quote removed"),
        ]
    if target == Dialect.BIGQUERY:
        return [
            (r"\bCREATE\s+(?:OR\s+REPLACE\s+)?LOCAL\s+TEMP\s+TABLE\b", "CREATE TEMP TABLE", "LOCAL TEMP → TEMP TABLE"),
            (r"\bCREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+TABLE\b", "CREATE TEMP TABLE", "TEMP → CREATE TEMP TABLE"),
            (r"\bSYSDATE\b", "CURRENT_TIMESTAMP()", "SYSDATE → CURRENT_TIMESTAMP()"),
            (r"\bGETDATE\s*\(\s*\)", "CURRENT_TIMESTAMP()", "GETDATE → CURRENT_TIMESTAMP()"),
            (r"DATEDIFF\s*\(\s*'(\w+)'\s*,", r"DATE_DIFF(", "DATEDIFF → DATE_DIFF"),
            (r"\bIFNULL\s*\(", "IFNULL(", "IFNULL retained"),  # no-op marker skipped below
        ]
    return []


def _apply_post_transforms(sql: str, target: Dialect) -> tuple[str, list[str]]:
    applied: list[str] = []
    for pattern, replacement, label in _post_transforms(target):
        if label.endswith("retained"):
            continue
        if re.search(pattern, sql, re.IGNORECASE):
            sql = re.sub(pattern, replacement, sql, flags=re.IGNORECASE)
            applied.append(label)
    return sql, applied


def _convert_procedure_wrapper(sql: str, target: Dialect) -> tuple[str, list[str]]:
    """Convert procedure wrappers for Snowflake or BigQuery targets."""
    applied: list[str] = []
    target = normalize_target(target)

    proc_match = re.search(
        r"CREATE\s+OR\s+REPLACE\s+PROCEDURE\s+([\w.]+)\s*\(([^)]*)\)",
        sql,
        re.IGNORECASE,
    )
    if not proc_match:
        return sql, applied

    proc_name = proc_match.group(1)
    params = proc_match.group(2).strip()
    body_match = re.search(r"\bBEGIN\b(.*?)\bEND\s*;?\s*\$\$?", sql, re.IGNORECASE | re.DOTALL)
    if not body_match:
        return sql, applied

    body = body_match.group(1).strip()
    body = re.sub(r"\bCOMMIT\s*;", "", body, flags=re.IGNORECASE)

    if target == Dialect.SNOWFLAKE:
        if params:
            for param in params.split(","):
                param = param.strip()
                if not param:
                    continue
                pname = param.split()[0]
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

    if target == Dialect.BIGQUERY:
        # BigQuery scripting procedures use BEGIN/END without Snowflake :PARAM binds
        bq_proc = f"""CREATE OR REPLACE PROCEDURE {proc_name}({params})
BEGIN
{body}
END;"""
        applied.append("Converted procedure wrapper to BigQuery syntax")
        return bq_proc, applied

    return sql, applied


def _transpile_statements(sql: str, source: Dialect, target: Dialect) -> tuple[str, list[str], list[str]]:
    """Transpile individual SQL statements via sqlglot."""
    auto: list[str] = []
    review: list[str] = []
    source_dialect = get_sqlglot_dialect(source)
    target_dialect = get_sqlglot_dialect(normalize_target(target))

    # Identity route: keep SQL after rule transforms
    if source_dialect == target_dialect and source == normalize_target(target):
        auto.append("Same dialect family — rule transforms only")
        return sql, auto, review

    statements = parse_sql_multi(sql, source)
    if not statements:
        # Vertica (postgres stand-in) / broken SQL: try snowflake then postgres
        for fallback in (Dialect.SNOWFLAKE, Dialect.REDSHIFT):
            statements = parse_sql_multi(sql, fallback)
            if statements:
                review.append(f"Parsed with {fallback.value} fallback dialect")
                break

    if not statements:
        review.append("Could not parse SQL — returned rule-transformed source")
        return sql, auto, review

    translated_parts: list[str] = []
    for stmt in statements:
        if stmt is None:
            continue
        try:
            translated = stmt.sql(dialect=target_dialect, pretty=True)
            translated_parts.append(translated)
            auto.append(f"Dialect transpilation ({source_dialect} → {target_dialect})")
        except Exception:
            try:
                translated_parts.append(stmt.sql(dialect=source_dialect, pretty=True))
                review.append("Statement retained in source dialect — manual review required")
            except Exception:
                review.append("Unparseable statement skipped")

    if translated_parts:
        # Deduplicate auto notes while keeping order
        auto = list(dict.fromkeys(auto))
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

    if source == target or (source == Dialect.SNOWFLAKE and target == Dialect.DBT_SNOWFLAKE):
        auto_converted.append("Source and target are the same dialect family")

    # Step 1: Source-specific syntax cleanup
    working_sql, applied = _apply_syntax_replacements(working_sql, source)
    auto_converted.extend(applied)

    # Step 2: Source→target function mappings (before transpile)
    working_sql, func_applied = _apply_function_mappings(working_sql, source, target)
    auto_converted.extend(func_applied)

    # Step 3: Target temp-table / sysdate post transforms (safe before transpile)
    working_sql, post_applied = _apply_post_transforms(working_sql, target)
    auto_converted.extend(post_applied)

    # Step 4/5: Procedures vs statement transpile
    is_procedure = bool(re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b", working_sql, re.I))
    if is_procedure:
        working_sql, proc_applied = _convert_procedure_wrapper(working_sql, target)
        auto_converted.extend(proc_applied)
        if not proc_applied:
            requires_review.append("Procedure wrapper could not be auto-converted for this target")
            confidence -= 15
        else:
            requires_review.append("Verify procedure parameter bindings and temp table scope")
            confidence -= 5
    else:
        transpiled, t_auto, t_review = _transpile_statements(working_sql, source, target)
        if t_auto or transpiled != working_sql:
            working_sql = transpiled
            auto_converted.extend(t_auto)
        requires_review.extend(t_review)
        if t_review:
            confidence -= len(t_review) * 5

    # Step 6: Date arithmetic after transpile so sqlglot does not wrap INTERVAL twice
    working_sql, date_applied = _apply_date_arithmetic(working_sql, target)
    auto_converted.extend(date_applied)

    # Step 7: Unsupported features
    unsupported = detect_unsupported_features(original, source, target)
    converted_funcs = {a.split("→")[0].strip().upper() for a in func_applied if "→" in a}
    for feature in unsupported:
        feat_upper = feature.upper().replace(" ", "")
        if any(cf in feat_upper or feat_upper in cf for cf in converted_funcs):
            continue
        requires_review.append(f"Unsupported: {feature}")
        confidence -= 3

    # Step 8: Behavior warnings
    target_dialect = get_sqlglot_dialect(normalize_target(target))
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
    return (
        working_sql.strip(),
        confidence,
        list(dict.fromkeys(auto_converted)),
        list(dict.fromkeys(requires_review)),
    )


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
