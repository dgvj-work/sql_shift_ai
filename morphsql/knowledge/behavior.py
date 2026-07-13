"""Platform behavior difference knowledge base."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BehaviorDifference:
    name: str
    source_platform: str
    target_platform: str
    description: str
    impact: str
    detection_pattern: str
    recommendation: str
    severity: str = "medium"


BEHAVIOR_DIFFERENCES: list[BehaviorDifference] = [
    BehaviorDifference(
        name="empty_string_vs_null",
        source_platform="oracle",
        target_platform="snowflake",
        description="Oracle treats empty strings as NULL; Snowflake preserves empty strings.",
        impact="Row count and NULL rate differences in string columns.",
        detection_pattern=r"''|EMPTY",
        recommendation="Use NULLIF(TRIM(column), '') to normalize empty strings.",
        severity="high",
    ),
    BehaviorDifference(
        name="empty_string_vs_null_vertica",
        source_platform="vertica",
        target_platform="snowflake",
        description="Vertica and Snowflake may handle empty strings differently in comparisons.",
        impact="Filter predicates may include/exclude different rows.",
        detection_pattern=r"=\s*''|<> ''|IS NULL",
        recommendation="Explicitly handle empty strings with NULLIF and COALESCE.",
        severity="medium",
    ),
    BehaviorDifference(
        name="integer_division",
        source_platform="vertica",
        target_platform="snowflake",
        description="Integer division behavior may differ between platforms.",
        impact="Numeric calculations may produce truncated vs decimal results.",
        detection_pattern=r"/\s*\d+|/\s*\w+",
        recommendation="Use explicit CAST to DECIMAL or FLOAT before division.",
        severity="medium",
    ),
    BehaviorDifference(
        name="case_sensitivity",
        source_platform="vertica",
        target_platform="snowflake",
        description="Vertica is case-sensitive for quoted identifiers; Snowflake uppercases unquoted.",
        impact="Column and table name resolution failures or wrong joins.",
        detection_pattern=r'"[^"]+"',
        recommendation="Standardize identifier casing and use consistent quoting.",
        severity="high",
    ),
    BehaviorDifference(
        name="timezone_behavior",
        source_platform="vertica",
        target_platform="snowflake",
        description="TIMESTAMP WITH TIME ZONE handling differs across platforms.",
        impact="Date boundary comparisons may shift by timezone offset.",
        detection_pattern=r"TIMESTAMP|TIMEZONE|AT TIME ZONE",
        recommendation="Normalize all timestamps to UTC using CONVERT_TIMEZONE.",
        severity="high",
    ),
    BehaviorDifference(
        name="date_trunc_semantics",
        source_platform="vertica",
        target_platform="snowflake",
        description="DATE_TRUNC unit boundaries may differ at month/quarter/year edges.",
        impact="Aggregated period metrics may not reconcile.",
        detection_pattern=r"DATE_TRUNC|TRUNC\s*\(",
        recommendation="Validate period boundaries with sample date edge cases.",
        severity="medium",
    ),
    BehaviorDifference(
        name="floating_point_precision",
        source_platform="vertica",
        target_platform="snowflake",
        description="FLOAT/DOUBLE precision and rounding differ between engines.",
        impact="Checksum and aggregate metric mismatches within tolerance.",
        detection_pattern=r"\bFLOAT\b|\bDOUBLE\b|\bREAL\b",
        recommendation="Use DECIMAL for financial metrics; set numeric tolerance in validation.",
        severity="medium",
    ),
    BehaviorDifference(
        name="default_ordering",
        source_platform="vertica",
        target_platform="snowflake",
        description="Results without ORDER BY have no guaranteed row order.",
        impact="Row-by-row comparison tests may show false differences.",
        detection_pattern=r"SELECT(?!.*ORDER BY)",
        recommendation="Always add deterministic ORDER BY in reconciliation queries.",
        severity="low",
    ),
    BehaviorDifference(
        name="merge_semantics",
        source_platform="vertica",
        target_platform="snowflake",
        description="MERGE duplicate-match behavior may differ when multiple source rows match.",
        impact="Upsert operations may update different rows.",
        detection_pattern=r"\bMERGE\s+INTO\b",
        recommendation="Deduplicate source before MERGE; add unique key constraints.",
        severity="high",
    ),
    BehaviorDifference(
        name="boolean_handling",
        source_platform="vertica",
        target_platform="snowflake",
        description="Boolean type support and casting differ; Vertica often uses INT flags.",
        impact="Filter conditions on boolean-like columns may behave differently.",
        detection_pattern=r"\bBOOLEAN\b|=\s*[01]\s",
        recommendation="Explicitly cast boolean flags: column::BOOLEAN or column = 1.",
        severity="medium",
    ),
    BehaviorDifference(
        name="zeroifnull_isnull",
        source_platform="vertica",
        target_platform="snowflake",
        description="Vertica ZEROIFNULL/ISNULL functions map to COALESCE/NVL differently.",
        impact="NULL handling in arithmetic expressions produces different results.",
        detection_pattern=r"ZEROIFNULL|ISNULL|NVL",
        recommendation="Replace with COALESCE(column, 0) and validate NULL cases.",
        severity="medium",
    ),
    BehaviorDifference(
        name="sequence_handling",
        source_platform="oracle",
        target_platform="snowflake",
        description="Oracle sequences vs Snowflake sequences/auto-increment differ.",
        impact="Generated key values will not match between source and target.",
        detection_pattern=r"\bSEQUENCE\b|\.NEXTVAL|AUTO_INCREMENT",
        recommendation="Use Snowflake sequences; do not reconcile auto-generated keys.",
        severity="low",
    ),
    BehaviorDifference(
        name="rownum_vs_qualify",
        source_platform="oracle",
        target_platform="snowflake",
        description="Oracle ROWNUM filtering does not map 1:1 to Snowflake QUALIFY/ROW_NUMBER.",
        impact="Top-N queries may return different rows.",
        detection_pattern=r"\bROWNUM\b",
        recommendation="Rewrite as QUALIFY ROW_NUMBER() OVER (...) <= N.",
        severity="high",
    ),
    BehaviorDifference(
        name="redshift_encoding",
        source_platform="redshift",
        target_platform="snowflake",
        description="Redshift column ENCODE / DISTKEY / SORTKEY have no Snowflake equivalent.",
        impact="Physical design must be redesigned (clustering keys, search optimization).",
        detection_pattern=r"\b(DISTKEY|SORTKEY|DISTSTYLE|ENCODE)\b",
        recommendation="Drop distribution clauses; model clustering separately in Snowflake.",
        severity="medium",
    ),
    BehaviorDifference(
        name="redshift_listagg",
        source_platform="redshift",
        target_platform="bigquery",
        description="LISTAGG / WITHIN GROUP semantics differ from BigQuery STRING_AGG.",
        impact="Concatenated string order or NULL handling may differ.",
        detection_pattern=r"\bLISTAGG\b",
        recommendation="Validate STRING_AGG ORDER BY and NULL treatment.",
        severity="medium",
    ),
    BehaviorDifference(
        name="bigquery_struct",
        source_platform="bigquery",
        target_platform="snowflake",
        description="BigQuery STRUCT/ARRAY types map to Snowflake VARIANT/ARRAY with different access paths.",
        impact="Nested field projections may fail or need FLATTEN.",
        detection_pattern=r"\b(STRUCT|ARRAY)\s*<|\bUNNEST\b",
        recommendation="Model nested data as VARIANT and rewrite UNNEST to FLATTEN.",
        severity="high",
    ),
    BehaviorDifference(
        name="snowflake_variant",
        source_platform="snowflake",
        target_platform="bigquery",
        description="Snowflake VARIANT/FLATTEN patterns need BigQuery JSON/UNNEST rewrites.",
        impact="Semi-structured queries will not transpile cleanly.",
        detection_pattern=r"\b(VARIANT|FLATTEN|OBJECT_INSERT)\b",
        recommendation="Rewrite to JSON functions and UNNEST in BigQuery.",
        severity="high",
    ),
    BehaviorDifference(
        name="vertica_to_bigquery_types",
        source_platform="vertica",
        target_platform="bigquery",
        description="Vertica numeric/date types map to BigQuery INT64/FLOAT64/DATE with different casting rules.",
        impact="Implicit casts that worked in Vertica may fail in BigQuery.",
        detection_pattern=r"\b(CAST|::|NUMERIC|FLOAT)\b",
        recommendation="Use explicit CAST to BigQuery types (INT64, FLOAT64, NUMERIC).",
        severity="medium",
    ),
]


def get_behavior_warnings(
    sql: str,
    source: str,
    target: str,
) -> list[BehaviorDifference]:
    """Return applicable behavior warnings for a SQL object."""
    import re

    warnings: list[BehaviorDifference] = []
    for diff in BEHAVIOR_DIFFERENCES:
        if diff.source_platform != source:
            continue
        if diff.target_platform != target:
            continue
        if re.search(diff.detection_pattern, sql, re.IGNORECASE):
            warnings.append(diff)
    return warnings


def format_behavior_warning(diff: BehaviorDifference) -> str:
    return (
        f"[{diff.severity.upper()}] {diff.name}: {diff.description} "
        f"Recommendation: {diff.recommendation}"
    )
