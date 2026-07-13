"""MigrationIQ — Hugging Face Space demo."""

from __future__ import annotations

import json
from pathlib import Path

import gradio as gr
import plotly.graph_objects as go

from sqlshift import __product_name__, __version__
from sqlshift.knowledge.behavior import BEHAVIOR_DIFFERENCES
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

EMPTY_ANALYSIS = (
    "Run **Analyze** on the source SQL to view complexity metrics, "
    "risk factors, and migration recommendations."
)
EMPTY_REPO = (
    "Select source and target platforms, then click **Run scan** to analyze "
    "the bundled sample repository (`examples/vertica_legacy/`)."
)
EMPTY_CONVERT = "Click **Convert** to generate target-platform SQL."

# Dark theme palette
C_BG = "#0f1419"
C_PANEL = "#1a2332"
C_BORDER = "#2d3a4f"
C_TEXT = "#e2e8f0"
C_MUTED = "#94a3b8"
C_ACCENT = "#3b82f6"

CUSTOM_CSS = f"""
.gradio-container {{
    max-width: 1320px !important;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
    background: {C_BG} !important;
}}
.header-block {{
    border-bottom: 1px solid {C_BORDER};
    padding-bottom: 1rem;
    margin-bottom: 0.25rem;
}}
.header-block h1 {{
    font-size: 1.35rem;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin: 0;
    color: {C_TEXT};
}}
.header-block p {{
    margin: 0.3rem 0 0;
    color: {C_MUTED};
    font-size: 0.85rem;
}}
.panel-label {{
    color: {C_MUTED};
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 0.5rem;
}}
footer {{ display: none !important; }}
.prose {{ color: {C_TEXT} !important; }}
"""


def _risk_label(score: int) -> str:
    if score < 30:
        return "Low"
    if score < 60:
        return "Medium"
    return "High"


def _risk_gauge(score: int) -> go.Figure:
    color = "#22c55e" if score < 30 else "#eab308" if score < 60 else "#ef4444"
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"suffix": " / 100", "font": {"color": C_TEXT, "size": 28}},
            title={"text": f"Risk · {_risk_label(score)}", "font": {"color": C_MUTED, "size": 13}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": C_MUTED},
                "bar": {"color": color, "thickness": 0.75},
                "bgcolor": C_PANEL,
                "borderwidth": 1,
                "bordercolor": C_BORDER,
                "steps": [
                    {"range": [0, 30], "color": "#14532d"},
                    {"range": [30, 60], "color": "#713f12"},
                    {"range": [60, 100], "color": "#7f1d1d"},
                ],
            },
        )
    )
    fig.update_layout(
        height=240,
        margin=dict(t=50, b=20, l=40, r=40),
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        font={"family": "Inter, system-ui, sans-serif", "color": C_TEXT},
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
                marker_color=["#22c55e", "#eab308", "#ef4444", "#64748b"],
                text=[
                    d.auto_migratable,
                    d.requires_review,
                    d.requires_redesign,
                    d.recommended_retirement,
                ],
                textposition="outside",
                textfont={"color": C_TEXT},
            )
        ]
    )
    fig.update_layout(
        title={"text": "Object distribution", "font": {"size": 13, "color": C_MUTED}},
        height=300,
        margin=dict(t=50, b=40),
        yaxis_title="Count",
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        font={"family": "Inter, system-ui, sans-serif", "color": C_TEXT},
        xaxis={"gridcolor": C_BORDER, "color": C_MUTED},
        yaxis={"gridcolor": C_BORDER, "color": C_MUTED},
    )
    return fig


def analyze_sql(sql: str, source: str, target: str) -> tuple[str, go.Figure, str]:
    if not sql.strip():
        return "Paste source SQL above to begin analysis.", _risk_gauge(0), "—"

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
        "### Assessment",
        "",
        "| Field | Value |",
        "|-------|-------|",
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
        lines += ["**Load pattern**", ""]
        for k, v in incremental.items():
            lines.append(f"- {k.replace('_', ' ').title()}: `{v}`")

    if obj.business_rules:
        lines += ["", "**Business rules**", ""]
        for rule in obj.business_rules:
            lines.append(rule)

    badge = f"{obj.complexity_score} / 100 · {_risk_label(obj.complexity_score)}"
    return "\n".join(lines), _risk_gauge(obj.complexity_score), badge


def convert_sql(sql: str, source: str, target: str) -> tuple[str, str, str]:
    if not sql.strip():
        return "", EMPTY_CONVERT, "—"

    source_d = Dialect(source)
    target_d = Dialect(target if target != "dbt-snowflake" else "snowflake")

    translated, confidence, auto_converted, requires_review = translate_sql(sql, source_d, target_d)

    notes = [
        f"**Confidence:** {confidence:.0f}%",
        f"**Route:** {source} → {target}",
        "",
    ]
    if auto_converted:
        notes.append("**Transformations applied**")
        for item in auto_converted[:10]:
            notes.append(f"- {item}")
        notes.append("")
    if requires_review:
        notes.append("**Review required**")
        for item in requires_review[:10]:
            notes.append(f"- {item}")

    return translated, "\n".join(notes), f"{confidence:.0f}%"


def analyze_repository(source: str, target: str) -> tuple[str, str, go.Figure, str]:
    source_d = Dialect(source)
    target_d = Dialect(target if target != "dbt-snowflake" else "snowflake")

    if not EXAMPLES_DIR.exists():
        return (
            "Sample repository path not found on this deployment.",
            "",
            _dashboard_chart_empty(),
            "",
        )

    pipeline = MigrationPipeline(source=source_d, target=target_d)
    report = pipeline.analyze(str(EXAMPLES_DIR))
    report = pipeline.convert(report)
    report = pipeline.validate(report)

    d = report.dashboard
    summary = f"""### Scan results · `{EXAMPLES_DIR.name}/`

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

    rows = "### Objects\n\n"
    rows += "| Object | Type | Complexity | Risk | Confidence |\n"
    rows += "|--------|------|------------|------|------------|\n"
    for obj in report.objects:
        rows += (
            f"| {obj.name} | {obj.object_type.value} "
            f"| {obj.complexity_score} | {obj.risk_level.value} "
            f"| {obj.conversion_confidence:.0f}% |\n"
        )

    graph = build_lineage_graph(report.objects, source_d)
    if report.objects:
        rows += f"\n### Lineage\n\n```\n{format_lineage_tree(graph, report.objects[0].name)}\n```"

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

    return summary, rows, _dashboard_chart(report), export


def _dashboard_chart_empty() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        height=300,
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            {
                "text": "Run scan to view distribution",
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"size": 13, "color": C_MUTED},
            }
        ],
    )
    return fig


def migration_assistant(
    message: str,
    history: list[dict],
    sql: str,
    source: str,
    target: str,
) -> tuple[list[dict], str]:
    """Rule-based migration assistant — no external API required."""
    if not message.strip():
        return history, ""

    msg = message.strip().lower()
    reply_parts: list[str] = []

    if any(w in msg for w in ("zeroifnull", "nvl", "isnull")):
        reply_parts.append(
            "Vertica `ZEROIFNULL(expr)` maps to Snowflake `COALESCE(expr, 0)`. "
            "`NVL` and `ISNULL` map to `COALESCE` with the same arguments."
        )
    elif "datediff" in msg or "date arithmetic" in msg or "dateadd" in msg:
        reply_parts.append(
            "Vertica `DATEDIFF('day', a, b)` becomes Snowflake `DATEDIFF(day, a, b)` "
            "(unit without quotes). Date subtraction like `col - 90` becomes "
            "`DATEADD(day, -90, col)`."
        )
    elif "procedure" in msg or "stored proc" in msg:
        reply_parts.append(
            "Vertica procedures use `AS $$ BEGIN ... END; $$`. Snowflake expects "
            "`LANGUAGE SQL` with `:PARAM` bindings. Temp tables should use "
            "`CREATE OR REPLACE TEMPORARY TABLE`. Review transaction boundaries."
        )
    elif "risk" in msg and "score" in msg:
        reply_parts.append(
            "Risk score (0–100) combines SQL size, join/CTE count, temp tables, "
            "dynamic SQL, unsupported syntax, and downstream dependencies. "
            "Below 30 = low, 30–60 = medium, above 60 = high."
        )
    elif "lineage" in msg:
        reply_parts.append(
            "Lineage is built from table read/write dependencies across scanned files. "
            "Use the Repository Scan tab to view upstream/downstream relationships."
        )
    elif "dbt" in msg:
        reply_parts.append(
            "For dbt migration, select **dbt-snowflake** as target. The CLI flag "
            "`--generate-dbt` decomposes procedures into staging/intermediate/mart models."
        )
    elif "upload" in msg or "repository" in msg or "repo" in msg:
        reply_parts.append(
            "Paste SQL directly in the converter tab. For full repository analysis, "
            "use the CLI: `sqlshift analyze ./your_repo --source vertica --target snowflake`."
        )
    elif "convert" in msg or "translate" in msg:
        if sql.strip():
            _, notes, conf = convert_sql(sql, source, target)
            preview = sql[:120].replace("\n", " ")
            reply_parts.append(
                f"Quick conversion preview ({conf} confidence) for `{preview}...`:\n\n{notes}"
            )
        else:
            reply_parts.append(
                "Paste SQL in the source panel, set platforms, and click **Convert**. "
                "I can also run a preview if you ask again with SQL loaded."
            )
    elif "behavior" in msg or "null" in msg or "empty string" in msg:
        diffs = [d for d in BEHAVIOR_DIFFERENCES if d.source_platform == source][:3]
        if diffs:
            reply_parts.append("Platform behavior differences to watch:\n")
            for d in diffs:
                reply_parts.append(f"- **{d.name}**: {d.description}")
        else:
            reply_parts.append("Check NULL handling, timezone, and merge semantics between platforms.")
    elif "help" in msg or "how" in msg:
        reply_parts.append(
            "**Workflow:**\n"
            "1. Paste legacy SQL in Source SQL\n"
            "2. Select source/target platform\n"
            "3. **Analyze** for risk and complexity\n"
            "4. **Convert** for target dialect output\n\n"
            "Ask about: ZEROIFNULL, procedures, DATEADD, dbt, risk scores, lineage."
        )
    else:
        reply_parts.append(
            "I can help with dialect conversion rules, risk scoring, procedure migration, "
            "dbt decomposition, and platform behavior differences. "
            "Try: *How does ZEROIFNULL convert?* or *Explain risk score*."
        )

    reply = "\n\n".join(reply_parts)
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    return history, ""


DARK_THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    neutral_hue=gr.themes.colors.gray,
).set(
    body_background_fill=C_BG,
    body_background_fill_dark=C_BG,
    background_fill_primary=C_PANEL,
    background_fill_primary_dark=C_PANEL,
    background_fill_secondary="#151d28",
    background_fill_secondary_dark="#151d28",
    border_color_primary=C_BORDER,
    border_color_primary_dark=C_BORDER,
    body_text_color=C_TEXT,
    body_text_color_dark=C_TEXT,
    block_background_fill=C_PANEL,
    block_background_fill_dark=C_PANEL,
    block_label_text_color=C_MUTED,
    block_label_text_color_dark=C_MUTED,
    input_background_fill="#151d28",
    input_background_fill_dark="#151d28",
    button_primary_background_fill=C_ACCENT,
    button_primary_background_fill_dark=C_ACCENT,
    button_primary_text_color="#ffffff",
    button_primary_text_color_dark="#ffffff",
)

with gr.Blocks(title="MigrationIQ") as demo:
    gr.HTML(
        f"""
        <div class="header-block">
            <h1>{__product_name__}</h1>
            <p>Data platform migration toolkit · v{__version__} ·
            Vertica · Oracle · Redshift → Snowflake · dbt</p>
        </div>
        """
    )

    with gr.Tabs():
        with gr.Tab("SQL Converter"):
            with gr.Row():
                with gr.Column(scale=3):
                    sql_input = gr.Code(
                        label="Source SQL",
                        language="sql",
                        value=EXAMPLE_SQL,
                        lines=20,
                    )
                with gr.Column(scale=1, min_width=240):
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
                        analyze_btn = gr.Button("Analyze", variant="secondary")
                        convert_btn = gr.Button("Convert", variant="primary")
                    risk_badge = gr.Textbox(
                        label="Risk score",
                        interactive=False,
                        value="—",
                    )
                    confidence_badge = gr.Textbox(
                        label="Conversion confidence",
                        interactive=False,
                        value="—",
                        max_lines=1,
                    )

            with gr.Row():
                with gr.Column(scale=3):
                    converted_output = gr.Code(
                        label="Converted SQL",
                        language="sql",
                        lines=18,
                        interactive=False,
                        value="",
                    )
                with gr.Column(scale=2):
                    conversion_notes = gr.Markdown(value=EMPTY_CONVERT)

            with gr.Row():
                with gr.Column(scale=2):
                    analyze_output = gr.Markdown(value=EMPTY_ANALYSIS)
                with gr.Column(scale=1, min_width=280):
                    risk_chart = gr.Plot(value=_risk_gauge(0), label="Risk gauge")

            with gr.Accordion("Migration assistant", open=False):
                gr.Markdown(
                    "Ask about conversion rules, platform differences, or migration workflow. "
                    "Loads context from the SQL panel above."
                )
                assistant_chat = gr.Chatbot(
                    label="Assistant",
                    height=260,
                    value=[],
                    placeholder="Ask about conversion rules, platform differences, or workflow…",
                )
                assistant_input = gr.Textbox(
                    label="Question",
                    placeholder="e.g. How does ZEROIFNULL convert to Snowflake?",
                    lines=1,
                    max_lines=3,
                )
                assistant_btn = gr.Button("Send", variant="secondary", size="sm")

            convert_btn.click(
                convert_sql,
                [sql_input, source_dd, target_dd],
                [converted_output, conversion_notes, confidence_badge],
            )
            analyze_btn.click(
                analyze_sql,
                [sql_input, source_dd, target_dd],
                [analyze_output, risk_chart, risk_badge],
            )
            assistant_btn.click(
                migration_assistant,
                [assistant_input, assistant_chat, sql_input, source_dd, target_dd],
                [assistant_chat, assistant_input],
            )
            assistant_input.submit(
                migration_assistant,
                [assistant_input, assistant_chat, sql_input, source_dd, target_dd],
                [assistant_chat, assistant_input],
            )

            # Pre-load analysis for the example SQL so panels are not empty on open
            demo.load(
                analyze_sql,
                [sql_input, source_dd, target_dd],
                [analyze_output, risk_chart, risk_badge],
            )

        with gr.Tab("Repository Scan"):
            gr.Markdown(
                "Analyzes the **bundled sample repository** shipped with this deployment. "
                "For your own codebase, use the CLI: "
                "`sqlshift analyze ./path --source vertica --target snowflake`."
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
                with gr.Column(scale=2):
                    repo_summary = gr.Markdown(value=EMPTY_REPO)
                with gr.Column(scale=1, min_width=280):
                    repo_chart = gr.Plot(value=_dashboard_chart_empty(), label="Distribution")

            repo_details = gr.Markdown()
            repo_json = gr.Code(label="JSON export", language="json", lines=10, value="")

            repo_btn.click(
                analyze_repository,
                [repo_source, repo_target],
                [repo_summary, repo_details, repo_chart, repo_json],
            )

        with gr.Tab("Reference"):
            gr.Markdown(
                """
### CLI

```bash
pip install sqlshift-ai
sqlshift analyze ./legacy_sql --source vertica --target snowflake
sqlshift convert ./legacy_sql --source vertica --target dbt-snowflake --generate-dbt
sqlshift migrate ./legacy_sql --output migration-output
```

### Supported routes

| Source | Target | Status |
|--------|--------|--------|
| Vertica | Snowflake / dbt | Supported |
| Oracle | Snowflake | Beta |
| Redshift | Snowflake | Beta |

### Conversion pipeline

1. Vertica syntax removal (SEGMENTED BY, PROJECTION, etc.)
2. Function mapping (ZEROIFNULL, DATEDIFF, date arithmetic)
3. Procedure wrapper → Snowflake LANGUAGE SQL
4. sqlglot dialect transpilation
5. Cross-platform behavior checks
                """
            )

    gr.Markdown(
        f"<p style='color:{C_MUTED};font-size:0.78rem;margin-top:1rem'>"
        f"MigrationIQ · Apache 2.0 · "
        f"<a href='https://github.com/dgvj-work/sql_shift_ai' style='color:{C_ACCENT}'>GitHub</a>"
        f"</p>"
    )


if __name__ == "__main__":
    demo.launch(theme=DARK_THEME, css=CUSTOM_CSS)
