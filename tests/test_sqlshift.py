"""Tests for SQLShiftAI."""

import pytest
from pathlib import Path

from sqlshift.models import Dialect, MigrationObject, ObjectType
from sqlshift.scanner.repository import scan_directory
from sqlshift.translator.engine import translate_sql
from sqlshift.risk.scorer import score_object, extract_business_rules
from sqlshift.parser.sql_parser import count_sql_complexity, extract_tables
from sqlshift.pipeline import MigrationPipeline
from sqlshift.validation.reconciliation import generate_incremental_strategy

EXAMPLES = Path(__file__).parent.parent / "examples" / "vertica_legacy"


class TestScanner:
    def test_scan_directory_finds_objects(self):
        objects = scan_directory(EXAMPLES)
        assert len(objects) >= 4
        types = {o.object_type for o in objects}
        assert ObjectType.STORED_PROCEDURE in types or ObjectType.SQL_SCRIPT in types

    def test_objects_have_sql_content(self):
        objects = scan_directory(EXAMPLES)
        for obj in objects:
            assert len(obj.source_sql) > 0
            assert obj.name


class TestParser:
    def test_extract_tables(self):
        sql = "SELECT a FROM staging.customers JOIN analytics.orders ON a.id = b.id"
        tables = extract_tables(sql, Dialect.VERTICA)
        assert "STAGING.CUSTOMERS" in tables or "CUSTOMERS" in str(tables).upper()

    def test_complexity_metrics(self):
        sql = "WITH cte AS (SELECT 1) SELECT * FROM cte JOIN t ON 1=1"
        metrics = count_sql_complexity(sql, Dialect.VERTICA)
        assert metrics["ctes"] >= 1
        assert metrics["joins"] >= 1


class TestTranslator:
    def test_zeroifnull_maps_to_coalesce_with_default(self):
        sql = "SELECT ZEROIFNULL(amount) FROM staging.transactions"
        translated, confidence, _, _ = translate_sql(sql, Dialect.VERTICA, Dialect.SNOWFLAKE)
        assert "COALESCE(amount," in translated.replace(" ", "") and ",0)" in translated.replace(" ", "")
        assert confidence > 0

    def test_procedure_parameter_binding(self):
        sql = """CREATE OR REPLACE PROCEDURE p(load_date DATE) AS $$
        BEGIN
            DELETE FROM t WHERE d = load_date;
        END; $$;"""
        translated, _, _, _ = translate_sql(sql, Dialect.VERTICA, Dialect.SNOWFLAKE)
        assert ":LOAD_DATE" in translated
        assert "WHERE d = :LOAD_DATE" in translated

    def test_date_arithmetic_uses_dateadd(self):
        sql = "SELECT * FROM t WHERE order_date >= CURRENT_DATE - 365"
        translated, _, _, _ = translate_sql(sql, Dialect.VERTICA, Dialect.SNOWFLAKE)
        assert "DATEADD" in translated.upper()

    def test_detects_dynamic_sql_review(self):
        sql = "EXECUTE IMMEDIATE 'SELECT 1'"
        _, _, _, review = translate_sql(sql, Dialect.VERTICA, Dialect.SNOWFLAKE)
        assert any("dynamic" in r.lower() for r in review)


class TestRiskScorer:
    def test_score_simple_query(self):
        obj = MigrationObject(name="TEST", object_type=ObjectType.SQL_SCRIPT, source_sql="SELECT 1")
        scored = score_object(obj, Dialect.VERTICA, Dialect.SNOWFLAKE)
        assert scored.complexity_score >= 0
        assert scored.risk_level is not None

    def test_extract_business_rules(self):
        sql = """SELECT CASE WHEN x > 5 THEN 'HIGH' WHEN x > 2 THEN 'MED' ELSE 'LOW' END FROM t"""
        rules = extract_business_rules(sql)
        assert len(rules) >= 1


class TestPipeline:
    def test_full_analyze(self):
        pipeline = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE)
        report = pipeline.analyze(EXAMPLES)
        assert report.dashboard.total_objects >= 4
        assert len(report.objects) >= 4

    def test_convert_pipeline(self):
        pipeline = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE)
        report = pipeline.analyze(EXAMPLES)
        report = pipeline.convert(report)
        converted = sum(1 for o in report.objects if o.target_sql)
        assert converted >= 1

    def test_validate_pipeline(self):
        pipeline = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE)
        report = pipeline.analyze(EXAMPLES)
        report = pipeline.convert(report)
        report = pipeline.validate(report)
        assert len(report.validation_results) > 0


class TestIntelligence:
    def test_runbook_generation(self):
        from sqlshift.pipeline import MigrationPipeline
        from sqlshift.intelligence.runbook import generate_runbook, generate_executive_summary

        pipeline = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE)
        report = pipeline.analyze(EXAMPLES)
        runbook = generate_runbook(report)
        assert "Migration Runbook" in runbook
        assert "Phase 1" in runbook
        summary = generate_executive_summary(report)
        assert "objects" in summary.lower()

    def test_rationalization(self):
        from sqlshift.pipeline import MigrationPipeline
        from sqlshift.intelligence.rationalization import generate_rationalization

        report = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE).analyze(EXAMPLES)
        rat = generate_rationalization(report)
        assert "Workload rationalization" in rat

    def test_copilot_context(self):
        from sqlshift.assistant.copilot import MigrationCopilot
        from sqlshift.pipeline import MigrationPipeline

        report = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE).analyze(EXAMPLES)
        ctx = MigrationCopilot().build_context(report)
        assert "Objects discovered" in ctx

    def test_copilot_fallback(self):
        from sqlshift.assistant.copilot import MigrationCopilot

        reply = MigrationCopilot()._fallback(
            "explain cutover plan", None, "", "vertica", "snowflake"
        )
        assert "cutover" in reply.lower() or "phase" in reply.lower()

    def test_copilot_priority_with_report(self):
        from sqlshift.assistant.copilot import MigrationCopilot
        from sqlshift.pipeline import MigrationPipeline

        report = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE).analyze(
            EXAMPLES
        )
        reply = MigrationCopilot().respond(
            "What should we migrate first?",
            [],
            report,
            "",
            "vertica",
            "snowflake",
        )
        assert "Start with" in reply or "Recommended" in reply or "first" in reply.lower()


class TestIncrementalStrategy:
    def test_delete_insert_pattern(self):
        sql = "DELETE FROM t WHERE d = 1; INSERT INTO t SELECT * FROM s"
        result = generate_incremental_strategy(sql)
        assert result["legacy_pattern"] == "Delete and reload"
        assert result["dbt_materialized"] == "incremental"
