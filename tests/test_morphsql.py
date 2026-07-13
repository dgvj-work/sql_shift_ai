"""Tests for MorphSQL."""

import re
from pathlib import Path

import pytest

from morphsql.models import Dialect, MigrationObject, ObjectType
from morphsql.scanner.repository import scan_directory
from morphsql.translator.engine import translate_sql
from morphsql.risk.scorer import score_object, extract_business_rules
from morphsql.parser.sql_parser import count_sql_complexity, extract_tables
from morphsql.pipeline import MigrationPipeline
from morphsql.validation.reconciliation import generate_incremental_strategy

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
        from morphsql.dbt_generator.decomposer import decompose_to_dbt, format_dbt_project, is_dbt_target

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
        from morphsql.eval import ensure_pairs_file, run_eval

        ensure_pairs_file()
        results, summary = run_eval(limit=20, categories=["function", "date"])
        assert summary["n_pairs"] >= 5
        assert 0 <= summary["token_f1"] <= 1
        assert len(results) == summary["n_pairs"]

    def test_behavior_rag_retrieves(self):
        from morphsql.intelligence.rag import get_rag

        hits = get_rag().retrieve("empty string NULL oracle snowflake", top_k=3)
        assert hits
        assert hits[0].name

    def test_hero_agent(self):
        from demo.handlers import run_hero_agent

        md, out, badge, share = run_hero_agent(
            "SELECT ZEROIFNULL(a) FROM t WHERE d >= CURRENT_DATE - 7",
            "vertica",
            "snowflake",
        )
        assert "COALESCE" in out.upper()
        assert "Confidence" in md or "%" in md or "VERTICA" in md.upper()
        assert "%" in badge
        assert "MorphSQL" in share or "morphsql" in share.lower() or "Open Space" in share
        assert "dgvj-work/morphsql" in share or "GitHub" in share

    def test_ai_risk_model_and_pipeline(self):
        from morphsql.ai import pipeline, train_and_save

        train_and_save()
        risk = pipeline("sql-risk-classification")
        out = risk("CREATE PROCEDURE p AS BEGIN EXECUTE IMMEDIATE 'x'; END;")
        assert out["label"] in {"low", "medium", "high"}
        assert 0 <= out["score"] <= 1
        mig = pipeline("sql-migration")(
            "SELECT ZEROIFNULL(a) FROM t", source="vertica", target="snowflake"
        )
        assert "COALESCE" in mig["converted_sql"].upper()
        assert "predict_risk" in mig["tools_used"] or mig["risk"]

    def test_ai_chat_agent(self):
        from morphsql.ai.agent import chat_agent

        history, msg, sql, badge = chat_agent(
            "Convert this SQL and predict migration risk",
            [],
            "SELECT ZEROIFNULL(x) FROM t",
            "vertica",
            "snowflake",
        )
        assert len(history) >= 2
        assert "COALESCE" in sql.upper()
        assert msg == ""

    def test_sql_to_pandas_from_each_source(self):
        import pandas as pd

        cases = [
            (
                Dialect.VERTICA,
                "SELECT customer_id, ZEROIFNULL(order_amount) AS order_amount, "
                "NVL(discount, 0) AS discount FROM staging.orders "
                "WHERE order_date >= CURRENT_DATE - 30",
                "staging.orders",
                {
                    "customer_id": [1, 2],
                    "order_amount": [None, 10.0],
                    "discount": [None, 1.0],
                    "order_date": [pd.Timestamp.today(), pd.Timestamp.today()],
                },
            ),
            (
                Dialect.ORACLE,
                "SELECT NVL(amount, 0) AS amount, SYSDATE AS ts FROM dual",
                None,
                None,
            ),
            (
                Dialect.REDSHIFT,
                "SELECT GETDATE() AS ts, name FROM users WHERE id > 1 LIMIT 5",
                "users",
                {"ts": [1, 2], "name": ["a", "b"], "id": [1, 3]},
            ),
            (
                Dialect.BIGQUERY,
                "SELECT IFNULL(a, 0) AS a, b FROM t WHERE a IS NOT NULL",
                "t",
                {"a": [None, 2], "b": [9, 8]},
            ),
            (
                Dialect.SNOWFLAKE,
                "SELECT COALESCE(x, 0) AS x FROM analytics.facts WHERE dt >= CURRENT_DATE",
                "analytics.facts",
                {"x": [None, 5], "dt": [pd.Timestamp.today(), pd.Timestamp.today()]},
            ),
        ]
        for source, sql, table_key, frame in cases:
            code, conf, auto, _review = translate_sql(sql, source, Dialect.PANDAS)
            assert conf >= 50
            assert "import pandas as pd" in code
            assert "result" in code
            assert any("pandas" in a.lower() or "→" in a for a in auto)
            ns: dict = {"pd": pd, "np": __import__("numpy")}
            if table_key and frame is not None:
                ns["tables"] = {table_key: pd.DataFrame(frame)}
            else:
                ns["tables"] = {}
            exec(code, ns, ns)
            assert isinstance(ns["result"], pd.DataFrame)

    def test_sql_to_pyspark_from_each_source(self):
        cases = [
            (
                Dialect.VERTICA,
                "SELECT customer_id, ZEROIFNULL(order_amount) AS order_amount "
                "FROM staging.orders WHERE order_date >= CURRENT_DATE - 30",
            ),
            (
                Dialect.ORACLE,
                "SELECT NVL(amount, 0) AS amount, SYSDATE AS ts FROM dual",
            ),
            (
                Dialect.REDSHIFT,
                "SELECT GETDATE() AS ts, name FROM users WHERE id > 1 LIMIT 5",
            ),
            (
                Dialect.BIGQUERY,
                "SELECT IFNULL(a, 0) AS a, b FROM t WHERE a IS NOT NULL",
            ),
            (
                Dialect.SNOWFLAKE,
                "SELECT COALESCE(x, 0) AS x FROM analytics.facts WHERE dt >= CURRENT_DATE",
            ),
        ]
        for source, sql in cases:
            code, conf, auto, _review = translate_sql(sql, source, Dialect.PYSPARK)
            assert conf >= 50
            assert "from pyspark.sql" in code
            assert "result" in code
            assert any("pyspark" in a.lower() or "→" in a for a in auto)

    def test_hero_agent_pandas_primary(self):
        from demo.handlers import run_hero_agent

        md, out, badge, share = run_hero_agent(
            "SELECT COALESCE(a, 0) AS a FROM t",
            "snowflake",
            "pandas",
        )
        assert "import pandas as pd" in out
        assert "fillna" in out or "tables[" in out or "_coalesce" in out
        assert "pandas" in share.lower() or "Python" in share
        assert "%" in badge
        assert "pandas" in md.lower() or "PANDAS" in md.upper() or "Python" in md

    def test_hero_agent_pyspark(self):
        from demo.handlers import run_hero_agent

        md, out, badge, share = run_hero_agent(
            "SELECT COALESCE(a, 0) AS a FROM t",
            "snowflake",
            "pyspark",
        )
        assert "from pyspark.sql" in out
        assert "F.coalesce" in out or "tables[" in out or "result" in out
        assert "pyspark" in share.lower() or "PySpark" in share or "Python" in share
        assert "%" in badge

    def test_sample_preview_and_convert_for_ui(self):
        import pandas as pd
        from demo.handlers import convert_for_ui, run_sample_preview

        notes, output, status, share, preview, path, nb, api = convert_for_ui(
            "SELECT customer_id, ZEROIFNULL(order_amount) AS order_amount "
            "FROM staging.orders WHERE order_date >= CURRENT_DATE - 7",
            "vertica",
            "pandas",
        )
        assert "import pandas" in output
        assert path.endswith(".py")
        assert "notebook" in nb.lower() or "MorphSQL" in nb
        assert "pipeline" in api
        assert preview is None or isinstance(preview, pd.DataFrame)
        df, note = run_sample_preview(output, "pandas", sql="SELECT a FROM staging.orders")
        assert isinstance(df, pd.DataFrame)
        assert "preview" in note.lower() or "Sample" in note

        _, spark_out, _, _, spark_preview, spark_path, spark_nb, _ = convert_for_ui(
            "SELECT COALESCE(a, 0) AS a FROM t",
            "snowflake",
            "pyspark",
        )
        assert "from pyspark.sql" in spark_out
        assert spark_path.endswith(".py")
        assert "pyspark" in spark_path or "morphsql_pyspark" in spark_path
        assert isinstance(spark_preview, pd.DataFrame)
        assert "Spark" in spark_nb or "pyspark" in spark_nb.lower()

        for tgt in ("snowflake", "bigquery", "dbt-snowflake"):
            _, out, _, _, prev, _, _, _ = convert_for_ui(
                "SELECT COALESCE(a, 0) AS a FROM t WHERE a IS NOT NULL",
                "snowflake",
                tgt,
            )
            assert out.strip()
            assert isinstance(prev, pd.DataFrame), f"preview missing for {tgt}"
            df2, note2 = run_sample_preview(
                out, tgt, sql="SELECT COALESCE(a, 0) AS a FROM t", source="snowflake"
            )
            assert isinstance(df2, pd.DataFrame)
            assert "preview" in note2.lower() or "Sample" in note2

        # Procedure → dbt must still produce a sample preview
        proc = (
            "CREATE OR REPLACE PROCEDURE p(load_date DATE) AS $$ BEGIN "
            "CREATE LOCAL TEMP TABLE tmp ON COMMIT PRESERVE ROWS AS "
            "SELECT customer_id, ZEROIFNULL(amount) AS amount FROM staging.orders "
            "WHERE order_date = load_date; "
            "INSERT INTO analytics.daily SELECT * FROM tmp; END; $$;"
        )
        _, _, _, _, proc_prev, _, _, _ = convert_for_ui(proc, "vertica", "dbt-snowflake")
        assert isinstance(proc_prev, pd.DataFrame), "procedure dbt preview missing"

    def test_sql_upload_convert_and_download(self):
        import tempfile
        import zipfile
        from pathlib import Path

        import pandas as pd
        from demo.handlers import convert_upload_for_ui, load_sql_from_upload

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            sql_path = td / "orders.sql"
            sql_path.write_text(
                "SELECT COALESCE(order_amount, 0) AS order_amount FROM staging.orders",
                encoding="utf-8",
            )
            loaded = load_sql_from_upload(str(sql_path))
            assert "order_amount" in loaded

            sql_in, notes, output, status, share, preview, path, nb, api = convert_upload_for_ui(
                str(sql_path), "", "snowflake", "pandas"
            )
            assert "order_amount" in sql_in
            assert "import pandas" in output
            assert Path(path).exists() and path.endswith(".py")
            assert "orders" in Path(path).name
            assert isinstance(preview, pd.DataFrame)

            spark_path = convert_upload_for_ui(str(sql_path), "", "snowflake", "pyspark")[6]
            assert Path(spark_path).exists() and spark_path.endswith(".py")
            assert "pyspark" in Path(spark_path).name

            # Zip of two SQL files → zip download
            zpath = td / "bundle.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.write(sql_path, arcname="a.sql")
                zf.writestr("b.sql", "SELECT IFNULL(x, 0) AS x FROM t")
            batch = convert_upload_for_ui(str(zpath), "", "snowflake", "pandas")
            assert batch[6].endswith(".zip")
            assert Path(batch[6]).exists()
            with zipfile.ZipFile(batch[6]) as zf:
                names = zf.namelist()
            assert any(n.endswith("_pandas.py") for n in names)
            assert len(names) >= 2

    def test_is_pandas_target(self):
        from morphsql.translator.pandas_codegen import is_pandas_target

        assert is_pandas_target("pandas")
        assert is_pandas_target(Dialect.PANDAS)
        assert not is_pandas_target("snowflake")

    def test_is_pyspark_target(self):
        from morphsql.translator.pyspark_codegen import is_pyspark_target

        assert is_pyspark_target("pyspark")
        assert is_pyspark_target(Dialect.PYSPARK)
        assert is_pyspark_target("spark")
        assert not is_pyspark_target("pandas")
        assert not is_pyspark_target("snowflake")

    def test_cte_query_to_dbt_models(self):
        from morphsql.dbt_generator.decomposer import decompose_to_dbt

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
        targets = [
            Dialect.PANDAS,
            Dialect.PYSPARK,
            Dialect.SNOWFLAKE,
            Dialect.DBT_SNOWFLAKE,
            Dialect.BIGQUERY,
        ]
        for source, sql in samples.items():
            for target in targets:
                translated, conf, auto, review = translate_sql(sql, source, target)
                assert translated.strip(), f"{source.value}→{target.value} returned empty SQL"
                assert conf >= 0
                if target == Dialect.PANDAS:
                    assert "import pandas as pd" in translated
                    continue
                if target == Dialect.PYSPARK:
                    assert "from pyspark.sql" in translated
                    continue
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
        from morphsql.pipeline import MigrationPipeline
        from morphsql.intelligence.runbook import generate_runbook, generate_executive_summary

        pipeline = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE)
        report = pipeline.analyze(EXAMPLES)
        runbook = generate_runbook(report)
        assert "Migration Runbook" in runbook
        assert "Phase 1" in runbook
        summary = generate_executive_summary(report)
        assert "objects" in summary.lower()

    def test_rationalization(self):
        from morphsql.pipeline import MigrationPipeline
        from morphsql.intelligence.rationalization import generate_rationalization

        report = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE).analyze(EXAMPLES)
        rat = generate_rationalization(report)
        assert "Workload rationalization" in rat

    def test_copilot_context(self):
        from morphsql.assistant.copilot import MigrationCopilot
        from morphsql.pipeline import MigrationPipeline

        report = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE).analyze(EXAMPLES)
        ctx = MigrationCopilot().build_context(report)
        assert "Objects discovered" in ctx

    def test_copilot_fallback(self):
        from morphsql.assistant.copilot import MigrationCopilot

        reply = MigrationCopilot()._fallback(
            "explain cutover plan", None, "", "vertica", "snowflake"
        )
        assert "cutover" in reply.lower() or "phase" in reply.lower()

    def test_copilot_priority_with_report(self):
        from morphsql.assistant.copilot import MigrationCopilot
        from morphsql.pipeline import MigrationPipeline

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
