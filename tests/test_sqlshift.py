"""Tests for SQLShiftAI."""

import re
from pathlib import Path

import pytest

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

    def test_vertica_to_bigquery_zeroifnull_and_dates(self):
        sql = "SELECT ZEROIFNULL(amount) FROM t WHERE d >= CURRENT_DATE - 7"
        translated, _, auto, _ = translate_sql(sql, Dialect.VERTICA, Dialect.BIGQUERY)
        upper = translated.upper()
        # BigQuery accepts IFNULL or COALESCE (sqlglot may normalize)
        assert "IFNULL" in upper or "COALESCE" in upper
        assert "DATE_SUB" in upper or "INTERVAL" in upper
        assert auto

    def test_oracle_nvl_to_snowflake(self):
        sql = "SELECT NVL(amount, 0) AS amt FROM dual"
        translated, _, auto, _ = translate_sql(sql, Dialect.ORACLE, Dialect.SNOWFLAKE)
        assert "COALESCE" in translated.upper()
        assert any("NVL" in a for a in auto)

    def test_oracle_to_bigquery(self):
        sql = "SELECT NVL(amount, 0) FROM orders"
        translated, conf, _, _ = translate_sql(sql, Dialect.ORACLE, Dialect.BIGQUERY)
        upper = translated.upper()
        assert "IFNULL" in upper or "COALESCE" in upper
        assert conf > 0

    def test_redshift_getdate_to_snowflake(self):
        sql = "SELECT GETDATE(), NVL(x, 0) FROM t"
        translated, _, auto, _ = translate_sql(sql, Dialect.REDSHIFT, Dialect.SNOWFLAKE)
        assert "CURRENT_TIMESTAMP" in translated.upper()
        assert "COALESCE" in translated.upper()
        assert auto

    def test_redshift_listagg_to_bigquery(self):
        sql = "SELECT LISTAGG(name, ',') FROM users"
        translated, _, auto, _ = translate_sql(sql, Dialect.REDSHIFT, Dialect.BIGQUERY)
        assert "STRING_AGG" in translated.upper()
        assert auto

    def test_bigquery_to_snowflake(self):
        sql = "SELECT IFNULL(amount, 0), STRING_AGG(name, ',') FROM t"
        translated, _, auto, _ = translate_sql(sql, Dialect.BIGQUERY, Dialect.SNOWFLAKE)
        assert "COALESCE" in translated.upper()
        assert "LISTAGG" in translated.upper()
        assert auto

    def test_snowflake_to_bigquery(self):
        sql = "SELECT IFF(a IS NULL, 0, a), LISTAGG(name, ',') FROM t"
        translated, _, auto, _ = translate_sql(sql, Dialect.SNOWFLAKE, Dialect.BIGQUERY)
        assert re.search(r"\bIF\s*\(", translated, re.I)
        assert "STRING_AGG" in translated.upper()
        assert auto

    def test_dbt_snowflake_target_matches_snowflake_sql(self):
        sql = "SELECT ZEROIFNULL(x) FROM t"
        snow, _, _, _ = translate_sql(sql, Dialect.VERTICA, Dialect.SNOWFLAKE)
        dbt, _, _, _ = translate_sql(sql, Dialect.VERTICA, Dialect.DBT_SNOWFLAKE)
        assert "COALESCE" in snow.upper() and "COALESCE" in dbt.upper()

    def test_vertica_procedure_to_dbt_models(self):
        from sqlshift.dbt_generator.decomposer import decompose_to_dbt, format_dbt_project, is_dbt_target

        assert is_dbt_target("dbt-snowflake")
        sql = Path("examples/vertica_legacy/procedures/SP_BUILD_CUSTOMER_DAILY.sql").read_text()
        translated, _, _, _ = translate_sql(sql, Dialect.VERTICA, Dialect.SNOWFLAKE)
        obj = MigrationObject(
            name="SP_BUILD_CUSTOMER_DAILY",
            object_type=ObjectType.STORED_PROCEDURE,
            source_sql=sql,
            target_sql=translated,
        )
        files = decompose_to_dbt(obj, Dialect.VERTICA)
        assert "dbt_project.yml" in files
        assert any(p.startswith("models/staging/") and p.endswith(".sql") for p in files)
        assert any(p.startswith("models/marts/") and p.endswith(".sql") for p in files)
        mart = next(v for k, v in files.items() if k.startswith("models/marts/") and k.endswith(".sql"))
        assert "source(" in "\n".join(files.values()) or "ref(" in mart
        assert "END AS" in mart.upper() or "CUSTOMER_SEGMENT" in mart.upper()
        assert "{{ var('load_date') }}" in "\n".join(files.values())
        rendered = format_dbt_project(files)
        assert "models/staging/" in rendered
        assert "COALESCE" in rendered.upper()

    def test_eval_suite_runs(self):
        from sqlshift.eval import ensure_pairs_file, run_eval

        ensure_pairs_file()
        results, summary = run_eval(limit=20, categories=["function", "date"])
        assert summary["n_pairs"] >= 5
        assert 0 <= summary["token_f1"] <= 1
        assert len(results) == summary["n_pairs"]

    def test_behavior_rag_retrieves(self):
        from sqlshift.intelligence.rag import get_rag

        hits = get_rag().retrieve("empty string NULL oracle snowflake", top_k=3)
        assert hits
        assert hits[0].name

    def test_hero_agent(self):
        from demo.handlers import run_hero_agent

        md, out, badge = run_hero_agent(
            "SELECT ZEROIFNULL(a) FROM t WHERE d >= CURRENT_DATE - 7",
            "vertica",
            "snowflake",
        )
        assert "COALESCE" in out.upper()
        assert "Agent" in md or "Confidence" in md
        assert "%" in badge

    def test_cte_query_to_dbt_models(self):
        from sqlshift.dbt_generator.decomposer import decompose_to_dbt

        sql = Path("examples/vertica_legacy/queries/customer_lifetime_value.sql").read_text()
        translated, _, _, _ = translate_sql(sql, Dialect.VERTICA, Dialect.SNOWFLAKE)
        obj = MigrationObject(
            name="customer_lifetime_value",
            object_type=ObjectType.SQL_SCRIPT,
            source_sql=sql,
            target_sql=translated,
        )
        files = decompose_to_dbt(obj, Dialect.VERTICA)
        assert any("marts/" in p for p in files)
        assert any(p.endswith(".sql") and "stg_" in p or "int_" in p or "marts/" in p for p in files)
        joined = "\n".join(files.values())
        assert "COALESCE" in joined.upper()
        assert "source(" in joined or "ref(" in joined

    def test_procedure_to_bigquery(self):
        sql = """CREATE OR REPLACE PROCEDURE p(load_date DATE) AS $$
        BEGIN
            DELETE FROM t WHERE d = load_date;
        END; $$;"""
        translated, _, auto, _ = translate_sql(sql, Dialect.VERTICA, Dialect.BIGQUERY)
        assert "CREATE OR REPLACE PROCEDURE" in translated.upper()
        assert "LANGUAGE SQL" not in translated.upper()
        assert any("BigQuery" in a for a in auto)

    def test_conversion_matrix_produces_output(self):
        """Every exposed source→target pair must return non-empty converted SQL."""
        samples = {
            Dialect.VERTICA: "SELECT ZEROIFNULL(a) AS x FROM staging.t WHERE d >= CURRENT_DATE - 1",
            Dialect.ORACLE: "SELECT NVL(a, 0) AS x FROM orders WHERE created_at >= SYSDATE",
            Dialect.REDSHIFT: "SELECT GETDATE() AS ts, NVL(a, 0) AS x FROM t",
            Dialect.BIGQUERY: "SELECT IFNULL(a, 0) AS x, STRING_AGG(b, ',') FROM t GROUP BY a",
            Dialect.SNOWFLAKE: "SELECT COALESCE(a, 0) AS x, LISTAGG(b, ',') FROM t GROUP BY a",
        }
        targets = [Dialect.SNOWFLAKE, Dialect.DBT_SNOWFLAKE, Dialect.BIGQUERY]
        for source, sql in samples.items():
            for target in targets:
                translated, conf, auto, review = translate_sql(sql, source, target)
                assert translated.strip(), f"{source.value}→{target.value} returned empty SQL"
                assert conf >= 0
                # Same-family routes may only apply light transforms; others must change or note work
                if source != target and not (
                    source == Dialect.SNOWFLAKE and target == Dialect.DBT_SNOWFLAKE
                ):
                    assert auto or translated != sql or review, (
                        f"{source.value}→{target.value} produced no conversion signal"
                    )


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
