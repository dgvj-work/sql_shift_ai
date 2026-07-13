"""MigrationIQ — Hugging Face Space demo."""

from __future__ import annotations

import json
from pathlib import Path

import gradio as gr
import plotly.graph_objects as go

from sqlshift import __product_name__, __version__
from sqlshift.lineage.builder import build_lineage_graph, format_lineage_tree
from sqlshift.models import Dialect, MigrationObject, ObjectType
from sqlshift.pipeline import MigrationPipeline
from sqlshift.translator.engine import translate_sql
from sqlshift.validation.reconciliation import generate_incremental_strategy

EXAMPLE_SQL = """CREATE OR REPLACE PROCEDURE SP_BUILD_CUSTOMER_DAILY(load_date DATE)
AS $$
BEGIN
    CREATE LOCAL TEMP TABLE tmp_txns ON COMMIT PRESERVE ROWS AS
    SELECT
        customer_id,
        order_id,
        order_amount,
        ZEROIFNULL(discount_amount) AS discount_amount
    FROM staging.customer_transactions
    WHERE order_date = load_date;

    DELETE FROM analytics.customer_daily WHERE activity_date = load_date;

    INSERT INTO analytics.customer_daily
    SELECT
        customer_id,
        load_date,
        COUNT(DISTINCT order_id) AS order_count,
        SUM(order_amount - ZEROIFNULL(discount_amount)) AS total_spend,
        CASE
            WHEN COUNT(DISTINCT order_id) >= 5 AND SUM(order_amount) > 500
            THEN 'HIGH_VALUE'
            ELSE 'STANDARD'
        END AS customer_segment
    FROM tmp_txns
    GROUP BY customer_id, load_date;
END;
$$;"""

EXAMPLES_DIR = Path(__file__).parent / "examples" / "vertica_legacy"

CUSTOM_CSS = """
:root {
    --panel-border: #e2e8f0;
    --text-muted: #64748b;
    --accent: #1e40af;
}
.gradio-container {
    max-width: 1280px !important;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
}
.header-block {
    border-bottom: 1px solid var(--panel-border);
    padding-bottom: 1.25rem;
    margin-bottom: 0.5rem;
}
.header-block h1 {
    font-size: 1.5rem;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin: 0;
    color: #0f172a;
}
.header-block p {
    margin: 0.35rem 0 0;
    color: var(--text-muted);
    font-size: 0.9rem;
}
footer { display: none !important; }
"""


def analyze_sql(sql: str, source: str, target: str) -> tuple[str, go.Figure | None]:
    if not sql.strip():
        return "Enter SQL to analyze.", None

    from sqlshift.parser.sql_parser import count_sql_complexity, detect_unsupported_features
    from sqlshift.risk.scorer import extract_business_rules, score_object

    source_d = Dialect(source)
    target_d = Dialect(target if target != "dbt-snowflake" else "snowflake")

    obj = MigrationObject(name="input", object_type=ObjectType.SQL_SCRIPT, source_sql=sql)
    obj = score_object(obj, source_d, target_d)
    obj.business_rules = extract_business_rules(sql)
    complexity = count_sql_complexity(sql, source_d)
    unsupported = detect_unsupported_features(sql, source_d, target_d)
    incremental = generate_incremental_strategy(sql)

    lines = [
        "### Assessment Summary",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Complexity | {obj.complexity_score} / 100 |",
        f"| Risk | {obj.risk_level.value.title()} |",
        f"| Category | {obj.migration_category.value.replace('_', ' ').title()} |",
        f"| Lines | {complexity.get('lines', 0)} |",
        f"| CTEs | {complexity.get('ctes', 0)} |",
        f"| Joins | {complexity.get('joins', 0)} |",
        f"| Temp tables | {complexity.get('temp_tables', 0)} |",
        f"| Window functions | {complexity.get('window_functions', 0)} |",
        "",
    ]

    if obj.risk_factors:
        lines += ["**Risk factors**", ""]
        for rf in obj.risk_factors:
            lines.append(f"- {rf.description} (+{rf.score})")
        lines.append("")

    if unsupported:
        lines += ["**Unsupported syntax**", ""]
        for feat in unsupported:
            lines.append(f"- {feat}")
        lines.append("")

    if incremental:
        lines += ["**Incremental load pattern**", ""]
        for k, v in incremental.items():
            lines.append(f"- {k.replace('_', ' ').title()}: `{v}`")

    if obj.business_rules:
        lines += ["", "**Business rules**", ""]
        for rule in obj.business_rules:
            lines.append(rule)

    return "\n".join(lines), _risk_gauge(obj.complexity_score)


def convert_sql(sql: str, source: str, target: str) -> tuple[str, str, str]:
    if not sql.strip():
        return "", "Enter SQL to convert.", ""

    source_d = Dialect(source)
    target_d = Dialect(target if target != "dbt-snowflake" else "snowflake")

    translated, confidence, auto_converted, requires_review = translate_sql(sql, source_d, target_d)

    notes = [
        f"**Confidence:** {confidence:.0f}%",
        f"**Source:** {source} → **Target:** {target}",
        "",
    ]
    if auto_converted:
        notes.append("**Applied transformations**")
        for item in auto_converted[:12]:
            notes.append(f"- {item}")
        notes.append("")
    if requires_review:
        notes.append("**Manual review**")
        for item in requires_review[:12]:
            notes.append(f"- {item}")

    return translated, "\n".join(notes), f"{confidence:.0f}%"


def analyze_repository(source: str, target: str) -> tuple[str, str, go.Figure | None, str]:
    source_d = Dialect(source)
    target_d = Dialect(target if target != "dbt-snowflake" else "snowflake")

    if not EXAMPLES_DIR.exists():
        return "Example repository not found.", "", None, ""

    pipeline = MigrationPipeline(source=source_d, target=target_d)
    report = pipeline.analyze(str(EXAMPLES_DIR))
    report = pipeline.convert(report)
    report = pipeline.validate(report)

    d = report.dashboard
    summary = f"""### Repository Scan

| Metric | Value |
|--------|-------|
| Objects | {d.total_objects} |
| Auto-migratable | {d.auto_migratable} |
| Needs review | {d.requires_review} |
| Manual redesign | {d.requires_redesign} |
| Retire / consolidate | {d.recommended_retirement} |
| Avg. risk score | {d.migration_risk_score:.0f} / 100 |
| Conversion | {d.conversion_completed_pct:.0f}% |
| Validation | {d.validation_passed_pct:.0f}% |
"""

    rows = "| Object | Type | Complexity | Risk | Confidence |\n"
    rows += "|--------|------|------------|------|------------|\n"
    for obj in report.objects:
        rows += (
            f"| {obj.name} | {obj.object_type.value} "
            f"| {obj.complexity_score} | {obj.risk_level.value} "
            f"| {obj.conversion_confidence:.0f}% |\n"
        )

    graph = build_lineage_graph(report.objects, source_d)
    lineage = ""
    if report.objects:
        lineage = f"\n### Lineage\n\n```\n{format_lineage_tree(graph, report.objects[0].name)}\n```"

    export = json.dumps(
        {
            "source": source,
            "target": target,
            "dashboard": d.model_dump(),
            "objects": [
                {
                    "name": o.name,
                    "type": o.object_type.value,
                    "complexity": o.complexity_score,
                    "risk": o.risk_level.value,
                    "confidence": o.conversion_confidence,
                }
                for o in report.objects
            ],
        },
        indent=2,
    )

    return summary, rows + lineage, _dashboard_chart(report), export


def _risk_gauge(score: int) -> go.Figure:
    color = "#16a34a" if score < 30 else "#ca8a04" if score < 60 else "#dc2626"
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"suffix": " / 100"},
            title={"text": "Risk Score", "font": {"size": 14}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": color, "thickness": 0.7},
                "bgcolor": "#f8fafc",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 30], "color": "#ecfdf5"},
                    {"range": [30, 60], "color": "#fefce8"},
                    {"range": [60, 100], "color": "#fef2f2"},
                ],
            },
        )
    )
    fig.update_layout(
        height=220,
        margin=dict(t=40, b=10, l=30, r=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, system-ui, sans-serif", "color": "#334155"},
    )
    return fig


def _dashboard_chart(report) -> go.Figure:
    d = report.dashboard
    fig = go.Figure(
        data=[
            go.Bar(
                x=["Auto-migrate", "Review", "Redesign", "Retire"],
                y=[
                    d.auto_migratable,
                    d.requires_review,
                    d.requires_redesign,
                    d.recommended_retirement,
                ],
                marker_color=["#16a34a", "#ca8a04", "#dc2626", "#94a3b8"],
                text=[
                    d.auto_migratable,
                    d.requires_review,
                    d.requires_redesign,
                    d.recommended_retirement,
                ],
                textposition="outside",
            )
        ]
    )
    fig.update_layout(
        title={"text": "Object Distribution", "font": {"size": 14}},
        height=280,
        margin=dict(t=40, b=40),
        yaxis_title="Count",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, system-ui, sans-serif", "color": "#334155"},
    )
    return fig


with gr.Blocks(title="MigrationIQ") as demo:
    gr.HTML(
        f"""
        <div class="header-block">
            <h1>{__product_name__}</h1>
            <p>Data platform migration toolkit &nbsp;·&nbsp; v{__version__} &nbsp;·&nbsp;
            Vertica · Oracle · Redshift → Snowflake · dbt</p>
        </div>
        """
    )

    with gr.Tabs():
        with gr.Tab("SQL Converter"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    sql_input = gr.Code(
                        label="Source SQL",
                        language="sql",
                        value=EXAMPLE_SQL,
                        lines=22,
                    )
                with gr.Column(scale=2, min_width=220):
                    source_dd = gr.Dropdown(
                        ["vertica", "oracle", "redshift", "bigquery"],
                        value="vertica",
                        label="Source platform",
                    )
                    target_dd = gr.Dropdown(
                        ["snowflake", "dbt-snowflake", "bigquery"],
                        value="snowflake",
                        label="Target platform",
                    )
                    with gr.Row():
                        analyze_btn = gr.Button("Analyze", variant="secondary", scale=1)
                        convert_btn = gr.Button("Convert", variant="primary", scale=1)

            with gr.Row():
                with gr.Column(scale=3):
                    converted_output = gr.Code(
                        label="Converted SQL",
                        language="sql",
                        lines=22,
                        interactive=False,
                    )
                with gr.Column(scale=2):
                    conversion_notes = gr.Markdown(label="Conversion details")
                    confidence_badge = gr.Textbox(
                        label="Confidence",
                        interactive=False,
                        max_lines=1,
                    )

            with gr.Row():
                analyze_output = gr.Markdown(label="Analysis")
                risk_chart = gr.Plot(label="Risk score")

            convert_btn.click(
                convert_sql,
                [sql_input, source_dd, target_dd],
                [converted_output, conversion_notes, confidence_badge],
            )
            analyze_btn.click(
                analyze_sql,
                [sql_input, source_dd, target_dd],
                [analyze_output, risk_chart],
            )

        with gr.Tab("Repository Scan"):
            gr.Markdown(
                "Scans the bundled Vertica sample repository "
                "(procedures, views, tables, queries)."
            )
            with gr.Row():
                repo_source = gr.Dropdown(
                    ["vertica", "oracle"], value="vertica", label="Source platform"
                )
                repo_target = gr.Dropdown(
                    ["snowflake", "dbt-snowflake"], value="snowflake", label="Target platform"
                )
                repo_btn = gr.Button("Run scan", variant="primary")

            with gr.Row():
                repo_summary = gr.Markdown()
                repo_chart = gr.Plot()

            repo_details = gr.Markdown()
            repo_json = gr.Code(label="JSON export", language="json", lines=12)

            repo_btn.click(
                analyze_repository,
                [repo_source, repo_target],
                [repo_summary, repo_details, repo_chart, repo_json],
            )

        with gr.Tab("Documentation"):
            gr.Markdown(
                """
### Overview

MigrationIQ scans legacy SQL repositories, scores migration risk, converts dialects,
builds lineage graphs, and generates dbt project scaffolding with validation tests.

### CLI

```bash
pip install sqlshift-ai

sqlshift analyze ./legacy_sql --source vertica --target snowflake
sqlshift convert ./legacy_sql --source vertica --target dbt-snowflake --generate-dbt
sqlshift migrate ./legacy_sql --output migration-output
```

### Supported paths

| Source | Target | Status |
|--------|--------|--------|
| Vertica | Snowflake / dbt | Supported |
| Oracle | Snowflake | Beta |
| Redshift | Snowflake | Beta |

### Conversion engine

1. Vertica-specific syntax removal (SEGMENTED BY, PROJECTION, etc.)
2. Function mapping (ZEROIFNULL → COALESCE, DATEDIFF, date arithmetic)
3. Procedure wrapper conversion to Snowflake syntax
4. sqlglot dialect transpilation for DML/DDL statements
5. Behavior difference detection across platforms
                """
            )

    gr.Markdown(
        "<p style='color:#94a3b8;font-size:0.8rem;margin-top:1.5rem'>"
        "MigrationIQ · Apache 2.0 · "
        "<a href='https://github.com/migrationiq/sqlshift-ai'>GitHub</a>"
        "</p>"
    )


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Base(
            primary_hue=gr.themes.colors.blue,
            neutral_hue=gr.themes.colors.gray,
            font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        ),
        css=CUSTOM_CSS,
    )
