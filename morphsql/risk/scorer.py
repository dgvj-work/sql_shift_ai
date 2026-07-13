"""Migration complexity and risk scoring."""

from __future__ import annotations

import re

from morphsql.models import (
    MigrationCategory,
    MigrationObject,
    ObjectType,
    RiskFactor,
    RiskLevel,
)
from morphsql.parser.sql_parser import count_sql_complexity, detect_unsupported_features
from morphsql.models import Dialect


def score_object(
    obj: MigrationObject,
    source: Dialect,
    target: Dialect,
    dependency_count: int = 0,
    downstream_count: int = 0,
) -> MigrationObject:
    """Compute migration complexity and risk score for an object."""
    complexity = count_sql_complexity(obj.source_sql, source)
    risk_factors: list[RiskFactor] = []
    score = 0

    # Line count
    lines = complexity.get("lines", 0)
    if lines > 2000:
        risk_factors.append(RiskFactor(
            name="large_object", score=25,
            description=f"{lines:,} lines of SQL",
            category="complexity",
        ))
        score += 25
    elif lines > 500:
        risk_factors.append(RiskFactor(
            name="medium_object", score=12,
            description=f"{lines:,} lines of SQL",
            category="complexity",
        ))
        score += 12
    elif lines > 100:
        score += 5

    # Structural complexity
    for metric, threshold, points, label in [
        ("ctes", 20, 10, "High CTE count"),
        ("joins", 30, 12, "High join count"),
        ("subqueries", 15, 8, "Deep subquery nesting"),
        ("window_functions", 10, 6, "Many window functions"),
        ("temp_tables", 5, 10, "Multiple temporary tables"),
        ("dynamic_sql", 1, 20, "Dynamic SQL detected"),
        ("cursors", 1, 18, "Cursor-based processing"),
    ]:
        val = complexity.get(metric, 0)
        if val >= threshold:
            risk_factors.append(RiskFactor(
                name=metric, score=points,
                description=f"{label}: {val}",
                category="complexity",
            ))
            score += points
        elif val > 0 and metric in ("dynamic_sql", "cursors"):
            risk_factors.append(RiskFactor(
                name=metric, score=points,
                description=f"{label}: {val}",
                category="complexity",
            ))
            score += points

    # Unsupported features
    unsupported = detect_unsupported_features(obj.source_sql, source, target)
    if unsupported:
        pts = min(len(unsupported) * 5, 25)
        risk_factors.append(RiskFactor(
            name="unsupported_syntax", score=pts,
            description=f"{len(unsupported)} unsupported features: {', '.join(unsupported[:3])}",
            category="compatibility",
        ))
        score += pts
        obj.unsupported_features = unsupported

    # Dependencies
    if dependency_count > 10:
        risk_factors.append(RiskFactor(
            name="high_dependencies", score=10,
            description=f"{dependency_count} upstream dependencies",
            category="dependency",
        ))
        score += 10
    elif dependency_count > 3:
        score += 4

    if downstream_count > 5:
        risk_factors.append(RiskFactor(
            name="critical_downstream", score=12,
            description=f"{downstream_count} downstream dependents — business-critical",
            category="dependency",
        ))
        score += 12
    elif downstream_count > 0:
        score += 3

    # Object type risk
    type_risk = {
        ObjectType.STORED_PROCEDURE: 15,
        ObjectType.FUNCTION: 10,
        ObjectType.VIEW: 3,
        ObjectType.TABLE: 2,
        ObjectType.SQL_SCRIPT: 5,
        ObjectType.TEMP_TABLE: 4,
    }
    type_score = type_risk.get(obj.object_type, 5)
    if type_score >= 10:
        risk_factors.append(RiskFactor(
            name="object_type", score=type_score,
            description=f"Object type: {obj.object_type.value}",
            category="complexity",
        ))
    score += type_score

    # Business rule complexity
    case_count = complexity.get("case_expressions", 0)
    if case_count > 5:
        risk_factors.append(RiskFactor(
            name="business_logic", score=8,
            description=f"{case_count} CASE expressions — complex business rules",
            category="business",
        ))
        score += 8

    score = min(100, score)
    obj.complexity_score = score
    obj.risk_level = _score_to_risk_level(score)
    obj.risk_factors = risk_factors
    obj.migration_category = _score_to_category(score, obj)
    obj.downstream_count = downstream_count
    obj.dependencies = []  # populated by orchestrator

    return obj


def score_objects(
    objects: list[MigrationObject],
    source: Dialect,
    target: Dialect,
    dependency_map: dict[str, int] | None = None,
    downstream_map: dict[str, int] | None = None,
) -> list[MigrationObject]:
    """Score all objects with optional dependency context."""
    dependency_map = dependency_map or {}
    downstream_map = downstream_map or {}
    return [
        score_object(
            obj, source, target,
            dependency_count=dependency_map.get(obj.name, 0),
            downstream_count=downstream_map.get(obj.name, 0),
        )
        for obj in objects
    ]


def extract_business_rules(sql: str) -> list[str]:
    """Extract human-readable business rules from CASE expressions."""
    rules: list[str] = []
    case_blocks = re.findall(
        r"CASE\s+(.*?)\s+END",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    for i, block in enumerate(case_blocks[:10], 1):
        when_clauses = re.findall(
            r"WHEN\s+(.+?)\s+THEN\s+('[^']*'|\w+)",
            block,
            re.IGNORECASE,
        )
        if when_clauses:
            conditions = [f"  - When {w.strip()} → {t}" for w, t in when_clauses]
            rules.append(f"Business Rule {i}:\n" + "\n".join(conditions))
    return rules


def recommend_workload_action(obj: MigrationObject) -> str:
    """Recommend migrate/rewrite/consolidate/retire action."""
    if obj.complexity_score >= 80:
        return "manual_redesign"
    if obj.complexity_score >= 60:
        return "rewrite"
    if obj.migration_category == MigrationCategory.RETIRE:
        return "retire"
    if obj.complexity_score >= 35:
        return "review_and_migrate"
    if len(obj.requires_review) > 3:
        return "review_and_migrate"
    return "migrate"


def _score_to_risk_level(score: int) -> RiskLevel:
    if score >= 75:
        return RiskLevel.CRITICAL
    if score >= 50:
        return RiskLevel.HIGH
    if score >= 25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _score_to_category(score: int, obj: MigrationObject) -> MigrationCategory:
    if obj.object_type == ObjectType.TEMP_TABLE and score < 30:
        return MigrationCategory.RETIRE
    if score >= 80:
        return MigrationCategory.MANUAL_REDESIGN
    if score >= 55:
        return MigrationCategory.PARTIAL
    if score >= 30 or obj.requires_review:
        return MigrationCategory.AUTO_WITH_REVIEW
    return MigrationCategory.AUTO_MIGRATE
