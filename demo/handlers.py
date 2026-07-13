"""Gradio event handlers for MigrationIQ workbench."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import plotly.graph_objects as go

from sqlshift.assistant.copilot import MigrationCopilot
from sqlshift.dbt_generator.decomposer import decompose_to_dbt
from sqlshift.intelligence.lineage_viz import lineage_to_plotly
from sqlshift.intelligence.rationalization import generate_rationalization
from sqlshift.intelligence.runbook import generate_executive_summary, generate_runbook
from sqlshift.lineage.builder import build_lineage_graph
from sqlshift.models import Dialect, MigrationObject, MigrationReport, ObjectType
from sqlshift.pipeline import MigrationPipeline
from sqlshift.translator.engine import translate_sql
from demo.theme import C_MUTED, C_PANEL, C_TEXT

EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "vertica_legacy"
_copilot = MigrationCopilot()


def _risk_gauge(score: int) -> go.Figure:
    color = "#22c55e" if score < 30 else "#eab308" if score < 60 else "#ef4444"
    label = "Low" if score < 30 else "Medium" if score < 60 else "High"
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"suffix": " / 100", "font": {"color": C_TEXT, "size": 26}},
            title={"text": f"Risk · {label}", "font": {"color": C_MUTED, "size": 12}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": C_MUTED},
                "bar": {"color": color, "thickness": 0.75},
                "bgcolor": C_PANEL,
                "bordercolor": "#2d3a4f",
                "steps": [
                    {"range": [0, 30], "color": "#14532d"},
                    {"range": [30, 60], "color": "#713f12"},
                    {"range": [60, 100], "color": "#7f1d1d"},
                ],
            },
        )
    )
    fig.update_layout(
        height=220,
        margin=dict(t=45, b=15, l=30, r=30),
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        font={"color": C_TEXT},
    )
    return fig


def _distribution_chart(report: MigrationReport) -> go.Figure:
    d = report.dashboard
    fig = go.Figure(
        go.Bar(
            x=["Auto-migrate", "Review", "Redesign", "Retire"],
            y=[d.auto_migratable, d.requires_review, d.requires_redesign, d.recommended_retirement],
            marker_color=["#22c55e", "#eab308", "#ef4444", "#64748b"],
            textfont={"color": C_TEXT},
        )
    )
    fig.update_layout(
        height=260,
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        font={"color": C_TEXT},
        margin=dict(t=30, b=30),
    )
    return fig


def _resolve_repo_path(upload_file, use_sample: bool) -> Path | None:
    if use_sample:
        return EXAMPLES_DIR if EXAMPLES_DIR.exists() else None
    if not upload_file:
        return None
    path = Path(upload_file) if isinstance(upload_file, str) else Path(str(upload_file))
    if path.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="migrationiq_"))
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        return tmp
    if path.is_dir():
        return path
    return None


def run_migration_workbench(
    upload_file,
    use_sample: bool,
    source: str,
    target: str,
) -> tuple:
    """Full migration intelligence pipeline for workbench tab."""
    empty_msg = (
        "Upload a `.zip` of your SQL repository **or** enable "
        "**Use sample repository** to run the migration workbench."
    )
    repo_path = _resolve_repo_path(upload_file, use_sample)
    if repo_path is None:
        return (
            empty_msg,
            "",
            "",
            "",
            "",
            "",
            _risk_gauge(0),
            _distribution_chart_empty(),
            lineage_to_plotly(build_lineage_graph([], Dialect.VERTICA)),
            json.dumps({"status": "no_input"}),
            None,
        )

    source_d = Dialect(source)
    target_d = Dialect(target if target != "dbt-snowflake" else "snowflake")

    pipeline = MigrationPipeline(source=source_d, target=target_d)
    report = pipeline.analyze(str(repo_path))
    report = pipeline.convert(report)
    report = pipeline.validate(report)

    exec_summary = generate_executive_summary(report)
    runbook = generate_runbook(report)
    rationalization = generate_rationalization(report)

    # dbt preview for highest-complexity migratable object
    dbt_preview = ""
    candidates = sorted(report.objects, key=lambda o: o.complexity_score, reverse=True)
    for obj in candidates:
        if obj.object_type.value in ("stored_procedure", "sql_script", "view"):
            files = decompose_to_dbt(obj, source_d)
            parts = [f"### dbt scaffold preview: `{obj.name}`\n"]
            for rel, content in sorted(files.items())[:6]:
                parts.append(f"**{rel}**\n```\n{content[:800]}\n```\n")
            dbt_preview = "\n".join(parts)
            break

    # validation summary
    val_lines = ["### Validation results\n"]
    passed = sum(1 for r in report.validation_results if r.passed)
    val_lines.append(f"**{passed}/{len(report.validation_results)}** checks passed\n")
    for r in report.validation_results[:12]:
        status = "PASS" if r.passed else "FAIL"
        val_lines.append(f"- [{status}] `{r.object_name}` · {r.check_name}")
        if r.root_cause:
            val_lines.append(f"  - {r.root_cause}")
    validation_md = "\n".join(val_lines)

    obj_lines = ["### Discovered objects\n"]
    obj_lines.append("| Object | Type | Complexity | Risk | Confidence | Category |")
    obj_lines.append("|--------|------|------------|------|------------|----------|")
    for obj in report.objects:
        obj_lines.append(
            f"| {obj.name} | {obj.object_type.value} | {obj.complexity_score} "
            f"| {obj.risk_level.value} | {obj.conversion_confidence:.0f}% "
            f"| {obj.migration_category.value.replace('_', ' ')} |"
        )

    graph = build_lineage_graph(report.objects, source_d)
    lineage_fig = lineage_to_plotly(graph, report.objects)

    export = json.dumps(
        {
            "repository": str(repo_path),
            "source": source,
            "target": target,
            "dashboard": report.dashboard.model_dump(),
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
        default=str,
    )

    return (
        exec_summary,
        "\n".join(obj_lines),
        rationalization,
        runbook,
        dbt_preview,
        validation_md,
        _risk_gauge(int(report.dashboard.migration_risk_score)),
        _distribution_chart(report),
        lineage_fig,
        export,
        report,
    )


def _distribution_chart_empty() -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        height=260,
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[
            dict(
                text="Run workbench to view distribution",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font={"size": 12, "color": C_MUTED},
            )
        ],
    )
    return fig


def analyze_sql_object(sql: str, source: str, target: str) -> tuple[str, go.Figure, str, str]:
    if not sql.strip():
        return "Paste SQL to analyze.", _risk_gauge(0), "—", ""

    from sqlshift.parser.sql_parser import count_sql_complexity, detect_unsupported_features
    from sqlshift.risk.scorer import extract_business_rules, score_object

    source_d = Dialect(source)
    target_d = Dialect(target if target != "dbt-snowflake" else "snowflake")
    obj = MigrationObject(name="input", object_type=ObjectType.SQL_SCRIPT, source_sql=sql)
    obj = score_object(obj, source_d, target_d)
    complexity = count_sql_complexity(sql, source_d)
    unsupported = detect_unsupported_features(sql, source_d, target_d)
    rules = extract_business_rules(sql)

    lines = [
        "### Object assessment",
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
        "",
    ]
    if obj.risk_factors:
        lines += ["**Risk factors**", ""] + [f"- {rf.description}" for rf in obj.risk_factors] + [""]
    if unsupported:
        lines += ["**Unsupported syntax**", ""] + [f"- {u}" for u in unsupported]

    converted, conf, _, review = translate_sql(sql, source_d, target_d)
    badge = f"{obj.complexity_score} / 100"
    return "\n".join(lines), _risk_gauge(obj.complexity_score), badge, converted


def copilot_chat(
    message: str,
    history: list,
    report: MigrationReport | None,
    sql: str,
    source: str,
    target: str,
) -> tuple[list, str]:
    if not message.strip():
        return history, ""

    reply = _copilot.respond(message, history, report, sql, source, target)
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    return history, ""


def report_to_context(report: MigrationReport | None) -> str:
    if report is None:
        return "No scan loaded."
    return _copilot.build_context(report)
