"""SQL parsing utilities built on sqlglot."""

from __future__ import annotations

import logging
import re
from typing import Any

import sqlglot
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from morphsql.models import Dialect

# Suppress noisy sqlglot fallback warnings for Vertica-specific DDL
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECT_MAP = {
    # Vertica is not a sqlglot dialect; PostgreSQL is the closest parser.
    Dialect.VERTICA: "postgres",
    Dialect.ORACLE: "oracle",
    Dialect.SNOWFLAKE: "snowflake",
    Dialect.BIGQUERY: "bigquery",
    Dialect.REDSHIFT: "redshift",
    Dialect.DBT_SNOWFLAKE: "snowflake",
    Dialect.PANDAS: "postgres",
    Dialect.PYSPARK: "postgres",
}


def get_sqlglot_dialect(dialect: Dialect) -> str:
    return DIALECT_MAP.get(dialect, "snowflake")


def parse_sql(sql: str, dialect: Dialect) -> exp.Expression | None:
    """Parse SQL into an AST, returning None on failure."""
    try:
        return parse_one(sql, read=get_sqlglot_dialect(dialect))
    except (ParseError, ValueError):
        return None


def parse_sql_multi(sql: str, dialect: Dialect) -> list[exp.Expression]:
    """Parse multiple statements from a SQL script."""
    try:
        return sqlglot.parse(sql, read=get_sqlglot_dialect(dialect))
    except (ParseError, ValueError):
        return []


def extract_tables(sql: str, dialect: Dialect) -> set[str]:
    """Extract referenced table names from SQL."""
    tables: set[str] = set()
    statements = parse_sql_multi(sql, dialect)
    if not statements:
        # Fallback to generic/snowflake parser for dialects with limited sqlglot support
        statements = parse_sql_multi(sql, Dialect.SNOWFLAKE)
    for statement in statements:
        for table in statement.find_all(exp.Table):
            name = _table_name(table)
            if name:
                tables.add(name.upper())
    return tables


def extract_columns(sql: str, dialect: Dialect) -> dict[str, list[str]]:
    """Extract column references grouped by table alias/name."""
    columns: dict[str, list[str]] = {}
    for statement in parse_sql_multi(sql, dialect):
        for col in statement.find_all(exp.Column):
            table = col.table or "_unqualified"
            col_name = col.name.upper() if col.name else ""
            if col_name:
                columns.setdefault(table.upper(), []).append(col_name)
    return columns


def count_sql_complexity(sql: str, dialect: Dialect) -> dict[str, int]:
    """Compute structural complexity metrics."""
    statements = parse_sql_multi(sql, dialect)
    if not statements:
        return _regex_complexity(sql)

    metrics = {
        "statements": len(statements),
        "ctes": 0,
        "joins": 0,
        "subqueries": 0,
        "window_functions": 0,
        "aggregations": 0,
        "case_expressions": 0,
        "temp_tables": 0,
        "dynamic_sql": 0,
        "cursors": 0,
        "lines": sql.count("\n") + 1,
    }

    for stmt in statements:
        metrics["ctes"] += len(list(stmt.find_all(exp.CTE)))
        metrics["joins"] += len(list(stmt.find_all(exp.Join)))
        metrics["subqueries"] += len(list(stmt.find_all(exp.Subquery)))
        metrics["window_functions"] += len(list(stmt.find_all(exp.Window)))
        metrics["aggregations"] += len(
            list(stmt.find_all(exp.AggFunc)) + list(stmt.find_all(exp.Count))
        )
        metrics["case_expressions"] += len(list(stmt.find_all(exp.Case)))

    metrics["temp_tables"] = len(re.findall(r"CREATE\s+(?:LOCAL\s+)?TEMP", sql, re.I))
    metrics["dynamic_sql"] = len(re.findall(r"EXECUTE\s+IMMEDIATE|EXEC\s*\(", sql, re.I))
    metrics["cursors"] = len(re.findall(r"\bCURSOR\b", sql, re.I))

    return metrics


def detect_unsupported_features(sql: str, source: Dialect, target: Dialect) -> list[str]:
    """Detect platform-specific features that may not translate cleanly."""
    unsupported: list[str] = []
    sql_upper = sql.upper()

    vertica_patterns = {
        "PROJECTION": r"\bPROJECTION\b",
        "SEGMENTED BY": r"\bSEGMENTED\s+BY\b",
        "ENCODED BY": r"\bENCODED\s+BY\b",
        "PARTITION BY (Vertica)": r"\bPARTITION\s+BY\s+\w+\s+GROUP\s+BY",
        "ISNULL (Vertica)": r"\bISNULL\s*\(",
        "ZEROIFNULL": r"\bZEROIFNULL\s*\(",
        "NVL (Oracle-style in Vertica)": r"\bNVL\s*\(",
        "TIMESERIES": r"\bTIMESERIES\b",
        "INTERPOLATE": r"\bINTERPOLATE\b",
    }

    oracle_patterns = {
        "CONNECT BY": r"\bCONNECT\s+BY\b",
        "ROWNUM": r"\bROWNUM\b",
        "DUAL table": r"\bFROM\s+DUAL\b",
        "PL/SQL block": r"\bBEGIN\b.*\bEND\b",
        "EXCEPTION handler": r"\bEXCEPTION\s+WHEN\b",
        "PACKAGE": r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PACKAGE\b",
    }

    redshift_patterns = {
        "DISTSTYLE": r"\bDISTSTYLE\b",
        "DISTKEY": r"\bDISTKEY\b",
        "SORTKEY": r"\bSORTKEY\b",
        "SUPER type": r"\bSUPER\b",
        "Spectrum external": r"\bSPECTRUM\b|\bEXTERNAL\s+SCHEMA\b",
    }

    bigquery_patterns = {
        "ARRAY/STRUCT": r"\b(ARRAY|STRUCT)\s*<",
        "QUALIFY": r"\bQUALIFY\b",
        "SCRIPTING DECLARE": r"\bDECLARE\s+\w+\s+(INT64|STRING|BOOL|FLOAT64)\b",
        "SAFE. functions": r"\bSAFE\.\w+",
    }

    snowflake_patterns = {
        "VARIANT/OBJECT": r"\b(VARIANT|OBJECT|ARRAY)\b",
        "FLATTEN": r"\bFLATTEN\s*\(",
        "MATCH_RECOGNIZE": r"\bMATCH_RECOGNIZE\b",
        "JavaScript procedure": r"\bLANGUAGE\s+JAVASCRIPT\b",
    }

    patterns: dict[str, str] = {}
    if source == Dialect.VERTICA:
        patterns.update(vertica_patterns)
    elif source == Dialect.ORACLE:
        patterns.update(oracle_patterns)
    elif source == Dialect.REDSHIFT:
        patterns.update(redshift_patterns)
    elif source == Dialect.BIGQUERY:
        patterns.update(bigquery_patterns)
    elif source == Dialect.SNOWFLAKE:
        patterns.update(snowflake_patterns)

    for feature, pattern in patterns.items():
        if re.search(pattern, sql_upper):
            unsupported.append(feature)

    if target in (Dialect.SNOWFLAKE, Dialect.DBT_SNOWFLAKE, Dialect.BIGQUERY):
        if re.search(r"\bEXECUTE\s+IMMEDIATE\b", sql_upper):
            unsupported.append("Dynamic SQL (requires manual redesign)")

    return unsupported


def _table_name(table: exp.Table) -> str | None:
    parts = []
    for attr in ("catalog", "db", "name"):
        val = getattr(table, attr, None)
        if val:
            parts.append(str(val))
    return ".".join(parts) if parts else None


def _regex_complexity(sql: str) -> dict[str, int]:
    """Fallback complexity when parsing fails."""
    return {
        "statements": len(re.findall(r";", sql)) + 1,
        "ctes": len(re.findall(r"\bWITH\b", sql, re.I)),
        "joins": len(re.findall(r"\bJOIN\b", sql, re.I)),
        "subqueries": len(re.findall(r"\(\s*SELECT\b", sql, re.I)),
        "window_functions": len(re.findall(r"\bOVER\s*\(", sql, re.I)),
        "aggregations": len(re.findall(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", sql, re.I)),
        "case_expressions": len(re.findall(r"\bCASE\b", sql, re.I)),
        "temp_tables": len(re.findall(r"CREATE\s+(?:LOCAL\s+)?TEMP", sql, re.I)),
        "dynamic_sql": len(re.findall(r"EXECUTE\s+IMMEDIATE|EXEC\s*\(", sql, re.I)),
        "cursors": len(re.findall(r"\bCURSOR\b", sql, re.I)),
        "lines": sql.count("\n") + 1,
        "parse_failed": 1,
    }
