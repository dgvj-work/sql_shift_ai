"""Gradio event handlers for SQLShiftAI workbench."""

from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path

import plotly.graph_objects as go

from sqlshift.assistant.copilot import MigrationCopilot
from sqlshift.dbt_generator.decomposer import decompose_to_dbt, format_dbt_project, is_dbt_target
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


def _sanitize_project(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.lower()).strip("_") or "migration_project"


def _apply_dark_layout(fig: go.Figure, height: int = 260) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(t=40, b=40, l=30, r=20),
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        font={"color": C_TEXT, "family": "Inter, system-ui, sans-serif"},
        xaxis={"gridcolor": "#334155", "zerolinecolor": "#334155", "color": C_TEXT},
        yaxis={"gridcolor": "#334155", "zerolinecolor": "#334155", "color": C_TEXT},
    )
    return fig


def _risk_gauge(score: int) -> go.Figure:
    score = max(0, min(100, int(score or 0)))
    color = "#22c55e" if score < 30 else "#eab308" if score < 60 else "#ef4444"
    label = "Low" if score < 30 else "Medium" if score < 60 else "High"
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={"suffix": " / 100", "font": {"color": C_TEXT, "size": 28}},
            title={"text": f"Portfolio risk · {label}", "font": {"color": C_MUTED, "size": 13}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": C_MUTED, "tickfont": {"color": C_MUTED}},
                "bar": {"color": color, "thickness": 0.8},
                "bgcolor": "#0f172a",
                "bordercolor": "#334155",
                "steps": [
                    {"range": [0, 30], "color": "#14532d"},
                    {"range": [30, 60], "color": "#713f12"},
                    {"range": [60, 100], "color": "#7f1d1d"},
                ],
            },
        )
    )
    return _apply_dark_layout(fig, height=280)


def _distribution_chart(report: MigrationReport) -> go.Figure:
    d = report.dashboard
    fig = go.Figure(
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
            textfont={"color": C_TEXT, "size": 14},
        )
    )
    fig.update_layout(title={"text": "Object distribution", "font": {"color": C_MUTED, "size": 13}})
    return _apply_dark_layout(fig, height=280)


def _distribution_chart_empty() -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=["Auto-migrate", "Review", "Redesign", "Retire"],
            y=[0, 0, 0, 0],
            marker_color=["#22c55e", "#eab308", "#ef4444", "#64748b"],
            text=[0, 0, 0, 0],
            textposition="outside",
            textfont={"color": C_TEXT},
        )
    )
    fig.update_layout(
        title={"text": "Object distribution (run scan)", "font": {"color": C_MUTED, "size": 13}},
        yaxis={"range": [0, 5]},
    )
    return _apply_dark_layout(fig, height=280)


def figure_to_html(fig: go.Figure) -> str:
    """Reliable Plotly HTML embed for Gradio (avoids blank Plot widgets)."""
    return fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )


def empty_lineage_plot() -> go.Figure:
    return lineage_to_plotly(build_lineage_graph([], Dialect.VERTICA))


def _resolve_repo_path(upload_file, use_sample: bool) -> Path | None:
    if use_sample:
        return EXAMPLES_DIR if EXAMPLES_DIR.exists() else None
    if not upload_file:
        return None

    # Gradio File may return str path, Path, or tempfile-like object
    if isinstance(upload_file, (list, tuple)) and upload_file:
        upload_file = upload_file[0]
    path = Path(str(upload_file.name if hasattr(upload_file, "name") else upload_file))
    if not path.exists():
        return None
    if path.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="sqlshiftai_"))
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        return tmp
    if path.is_dir():
        return path
    return None


def _report_to_dict(report: MigrationReport | None) -> dict | None:
    if report is None:
        return None
    return report.model_dump(mode="json")


def _dict_to_report(data: dict | MigrationReport | None) -> MigrationReport | None:
    if data is None:
        return None
    if isinstance(data, MigrationReport):
        return data
    if isinstance(data, dict):
        try:
            return MigrationReport.model_validate(data)
        except Exception:
            return None
    return None


def run_migration_workbench(
    upload_file,
    use_sample: bool,
    source: str,
    target: str,
) -> tuple:
    """Full migration intelligence pipeline for workbench tab."""
    empty_msg = (
        "Enable **Use sample repository** or upload a zip file, "
        "then click **Run migration intelligence**."
    )
    empty_risk = _risk_gauge(0)
    empty_dist = _distribution_chart_empty()
    empty_lineage = empty_lineage_plot()
    empty = (
        empty_msg,
        "No objects yet.",
        "No rationalization yet.",
        "No runbook yet.",
        "No dbt preview yet.",
        "No validation results yet.",
        "Portfolio risk: —",
        empty_risk,
        empty_dist,
        empty_lineage,
        json.dumps({"status": "waiting_for_input"}, indent=2),
        None,
    )

    try:
        repo_path = _resolve_repo_path(upload_file, bool(use_sample))
    except Exception as exc:
        return (
            f"Failed to open repository: {exc}",
            *empty[1:],
        )

    if repo_path is None:
        return empty

    try:
        source_d = Dialect(source)
        wants_dbt = is_dbt_target(target)
        target_d = Dialect("snowflake" if wants_dbt else target)

        pipeline = MigrationPipeline(source=source_d, target=target_d)
        report = pipeline.analyze(str(repo_path))
        report = pipeline.convert(report)
        report = pipeline.validate(report)
        if wants_dbt:
            report.target_dialect = Dialect.DBT_SNOWFLAKE

        exec_summary = generate_executive_summary(report)
        runbook = generate_runbook(report)
        rationalization = generate_rationalization(report)

        dbt_preview = "No suitable object for dbt decomposition."
        candidates = sorted(report.objects, key=lambda o: o.complexity_score, reverse=True)
        dbt_parts = ["### dbt project preview (Snowflake)\n"]
        shown = 0
        for obj in candidates:
            if obj.object_type.value not in ("stored_procedure", "sql_script", "view"):
                continue
            files = decompose_to_dbt(obj, source_d, project_name=_sanitize_project(obj.name))
            dbt_parts.append(f"#### `{obj.name}` → {len(files)} files\n")
            # Show model SQL files first
            model_files = [p for p in sorted(files) if p.startswith("models/") and p.endswith(".sql")]
            for rel in model_files[:5]:
                dbt_parts.append(f"**{rel}**\n```sql\n{files[rel][:1200]}\n```\n")
            shown += 1
            if shown >= 2:
                break
        if shown:
            dbt_preview = "\n".join(dbt_parts)
        elif not wants_dbt:
            dbt_preview = (
                "Target is not **dbt-snowflake**. "
                "Select **dbt-snowflake** as the target to generate staging / intermediate / mart models, "
                "or open Architecture (dbt) after a dbt-snowflake run."
            )

        val_lines = ["### Validation results\n"]
        passed = sum(1 for r in report.validation_results if r.passed)
        total = len(report.validation_results)
        val_lines.append(f"**{passed}/{total}** checks passed\n")
        for r in report.validation_results[:20]:
            status = "PASS" if r.passed else "FAIL"
            val_lines.append(f"- **[{status}]** {r.object_name} · {r.check_name}")
            if r.root_cause:
                val_lines.append(f"  - {r.root_cause}")
            if r.recommendation and not r.passed:
                val_lines.append(f"  - Fix: {r.recommendation}")
        validation_md = "\n".join(val_lines) if total else "No validation checks generated."

        obj_lines = [
            "### Discovered objects\n",
            "| Object | Type | Complexity | Risk | Confidence | Category |",
            "|--------|------|------------|------|------------|----------|",
        ]
        for obj in report.objects:
            obj_lines.append(
                f"| {obj.name} | {obj.object_type.value} | {obj.complexity_score} "
                f"| {obj.risk_level.value} | {obj.conversion_confidence:.0f}% "
                f"| {obj.migration_category.value.replace('_', ' ')} |"
            )
        if not report.objects:
            obj_lines.append("| — | — | — | — | — | No objects found |")

        metrics_md = (
            f"**Portfolio risk:** {int(report.dashboard.migration_risk_score)} / 100  ·  "
            f"**Objects:** {report.dashboard.total_objects}  ·  "
            f"**Auto-migrate:** {report.dashboard.auto_migratable}  ·  "
            f"**Review:** {report.dashboard.requires_review}  ·  "
            f"**Redesign:** {report.dashboard.requires_redesign}  ·  "
            f"**Retire:** {report.dashboard.recommended_retirement}"
        )

        graph = build_lineage_graph(report.objects, source_d)
        lineage_fig = lineage_to_plotly(graph, report.objects)
        risk_fig = _risk_gauge(int(report.dashboard.migration_risk_score))
        dist_fig = _distribution_chart(report)

        export = json.dumps(
            {
                "repository": str(repo_path),
                "source": source,
                "target": target,
                "dashboard": report.dashboard.model_dump(mode="json"),
                "objects": [
                    {
                        "name": o.name,
                        "type": o.object_type.value,
                        "complexity": o.complexity_score,
                        "risk": o.risk_level.value,
                        "confidence": o.conversion_confidence,
                        "category": o.migration_category.value,
                    }
                    for o in report.objects
                ],
            },
            indent=2,
        )

        return (
            exec_summary + "\n\n" + metrics_md,
            "\n".join(obj_lines),
            rationalization,
            runbook,
            dbt_preview,
            validation_md,
            metrics_md,
            risk_fig,
            dist_fig,
            lineage_fig,
            export,
            _report_to_dict(report),
        )
    except Exception as exc:
        return (
            f"**Workbench error:** {type(exc).__name__}: {exc}",
            *empty[1:],
        )


def analyze_sql_object(sql: str, source: str, target: str) -> tuple[str, go.Figure, str, str, str]:
    """Assess + convert a single SQL object.

    Returns: analysis_md, risk_fig, badge, converted_sql_or_dbt, notes_md
    """
    if not (sql or "").strip():
        return (
            "Paste SQL above, then click **Assess & Convert**.",
            _risk_gauge(0),
            "—",
            "",
            "Waiting for SQL input.",
        )

    try:
        from sqlshift.parser.sql_parser import count_sql_complexity, detect_unsupported_features
        from sqlshift.risk.scorer import extract_business_rules, score_object
        from sqlshift.validation.reconciliation import generate_incremental_strategy

        source_d = Dialect(source)
        wants_dbt = is_dbt_target(target)
        target_d = Dialect("snowflake" if wants_dbt else target)

        # Infer object type for better dbt decomposition
        obj_type = ObjectType.SQL_SCRIPT
        if re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b", sql, re.I):
            obj_type = ObjectType.STORED_PROCEDURE
        elif re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\b", sql, re.I):
            obj_type = ObjectType.VIEW

        obj = MigrationObject(name="input_object", object_type=obj_type, source_sql=sql)
        obj = score_object(obj, source_d, target_d)
        complexity = count_sql_complexity(sql, source_d)
        unsupported = detect_unsupported_features(sql, source_d, target_d)
        rules = extract_business_rules(sql)
        incremental = generate_incremental_strategy(sql)

        converted, conf, auto, review = translate_sql(sql, source_d, target_d)
        obj.target_sql = converted
        obj.conversion_confidence = conf
        obj.auto_converted = auto
        obj.requires_review = review

        output_sql = converted
        dbt_note = ""
        if wants_dbt:
            files = decompose_to_dbt(obj, source_d, project_name="input_object")
            output_sql = format_dbt_project(files)
            dbt_note = (
                f"**dbt project generated:** {len(files)} files "
                f"({len(obj.dbt_models)} models) — staging / intermediate / marts\n\n"
            )

        lines = [
            "### Object assessment",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Complexity | {obj.complexity_score} / 100 |",
            f"| Risk | {obj.risk_level.value.title()} |",
            f"| Category | {obj.migration_category.value.replace('_', ' ').title()} |",
            f"| Conversion confidence | {conf:.0f}% |",
            f"| Output | {'dbt models (Snowflake)' if wants_dbt else target} |",
            f"| Lines | {complexity.get('lines', 0)} |",
            f"| CTEs | {complexity.get('ctes', 0)} |",
            f"| Joins | {complexity.get('joins', 0)} |",
            f"| Temp tables | {complexity.get('temp_tables', 0)} |",
            f"| Window functions | {complexity.get('window_functions', 0)} |",
            "",
        ]
        if wants_dbt and obj.dbt_models:
            lines += ["**dbt models**", ""] + [f"- `{m}`" for m in obj.dbt_models] + [""]
        if obj.risk_factors:
            lines += ["**Risk factors**", ""] + [f"- {rf.description}" for rf in obj.risk_factors] + [""]
        if unsupported:
            lines += ["**Unsupported syntax**", ""] + [f"- {u}" for u in unsupported] + [""]
        if rules:
            lines += ["**Business rules**", ""] + [f"- {r}" for r in rules[:5]] + [""]
        if incremental:
            lines += ["**Incremental pattern**", ""]
            for k, v in incremental.items():
                lines.append(f"- {k.replace('_', ' ').title()}: {v}")

        notes = [
            f"**Route:** {source} → {target}",
            f"**Confidence:** {conf:.0f}%",
            "",
        ]
        if dbt_note:
            notes.append(dbt_note)
        if auto:
            notes.append("**SQL transformations**")
            notes.extend(f"- {a}" for a in auto[:10])
            notes.append("")
        if review:
            notes.append("**Manual review**")
            notes.extend(f"- {r}" for r in review[:10])

        badge = f"{obj.complexity_score} / 100 · {obj.risk_level.value.title()} · {conf:.0f}% conf"
        return (
            "\n".join(lines),
            _risk_gauge(obj.complexity_score),
            badge,
            output_sql,
            "\n".join(notes),
        )
    except Exception as exc:
        return (
            f"**Assessment error:** {type(exc).__name__}: {exc}",
            _risk_gauge(0),
            "Error",
            "",
            str(exc),
        )


def get_sample_workbench() -> tuple:
    """Precompute sample workbench outputs so UI is never blank on load."""
    return run_migration_workbench(None, True, "vertica", "snowflake")


def copilot_chat(
    message: str,
    history: list | None,
    report_data: dict | MigrationReport | None,
    sql: str,
    source: str,
    target: str,
) -> tuple[list, str]:
    history = list(history or [])
    if not (message or "").strip():
        return history, ""

    report = _dict_to_report(report_data)
    normalized: list[dict] = []
    for turn in history:
        if isinstance(turn, dict) and "role" in turn and "content" in turn:
            normalized.append({"role": turn["role"], "content": str(turn["content"])})
        elif isinstance(turn, (list, tuple)) and len(turn) == 2:
            if turn[0]:
                normalized.append({"role": "user", "content": str(turn[0])})
            if turn[1]:
                normalized.append({"role": "assistant", "content": str(turn[1])})

    reply = _copilot.respond(message.strip(), normalized, report, sql or "", source, target)
    normalized.append({"role": "user", "content": message.strip()})
    normalized.append({"role": "assistant", "content": reply})
    return normalized, ""


def report_to_context(report_data: dict | MigrationReport | None) -> str:
    report = _dict_to_report(report_data)
    if report is None:
        return (
            "No repository scan loaded yet. "
            "Open Migration Workbench, run a scan, then return here — "
            "the copilot will use that context."
        )
    ctx = _copilot.build_context(report)
    # Avoid markdown code fences that can go white-on-white in Gradio themes
    safe = ctx[:2500].replace("`", "'")
    return f"### Active scan context\n\n{safe}"


HERO_EXAMPLE = """SELECT
    customer_id,
    ZEROIFNULL(order_amount) AS order_amount,
    NVL(discount, 0) AS discount
FROM staging.orders
WHERE order_date >= CURRENT_DATE - 30"""

FEATURE_SQL_PATH = Path(__file__).parent.parent / "examples" / "ml_features" / "churn_feature_sql.sql"


def run_hero_agent(sql: str, source: str, target: str) -> tuple[str, str, str]:
    """One-shot agent demo: convert + explain + risk summary."""
    from sqlshift.intelligence.rag import get_rag
    from sqlshift.risk.scorer import score_object

    sql = sql or HERO_EXAMPLE
    source_d = Dialect(source)
    wants_dbt = is_dbt_target(target)
    target_d = Dialect("snowflake" if wants_dbt else target)

    converted, conf, auto, review = translate_sql(sql, source_d, target_d)
    obj = MigrationObject(
        name="hero_query",
        object_type=ObjectType.SQL_SCRIPT,
        source_sql=sql,
        target_sql=converted,
    )
    obj = score_object(obj, source_d, target_d)

    output = converted
    if wants_dbt:
        files = decompose_to_dbt(obj, source_d, project_name="hero_agent")
        output = format_dbt_project(files, max_files=12)

    rag = get_rag()
    hits = rag.retrieve(sql, top_k=3, source=source, target=target if not wants_dbt else "snowflake")

    explain = [
        f"### SQL Migration Agent · {source} → {target}",
        "",
        f"**Confidence:** {conf:.0f}%  ·  **Risk:** {obj.risk_level.value} "
        f"({obj.complexity_score}/100)  ·  **Category:** "
        f"{obj.migration_category.value.replace('_', ' ')}",
        "",
        "#### What the agent did",
    ]
    if auto:
        explain.extend(f"- {a}" for a in auto[:12])
    else:
        explain.append("- Rule transforms + dialect transpilation")
    if review:
        explain.append("")
        explain.append("#### Needs review")
        explain.extend(f"- {r}" for r in review[:8])
    if hits:
        explain.append("")
        explain.append("#### Retrieved behavior knowledge (RAG)")
        for h in hits:
            explain.append(
                f"- **{h.name}** ({h.severity}): {h.recommendation}"
            )
    explain.append("")
    explain.append(
        "_Agent stack: hybrid rules + sqlglot + behavior RAG"
        + (" + dbt decomposer" if wants_dbt else "")
        + " + optional HF LLM copilot._"
    )
    badge = f"{conf:.0f}% conf · {obj.risk_level.value} · {obj.complexity_score}/100"
    return "\n".join(explain), output, badge


def run_eval_suite(limit: int, category: str) -> tuple[str, str, dict]:
    """Run eval suite and return markdown summary, detail table, metrics dict."""
    from sqlshift.eval.metrics import run_eval
    from sqlshift.eval.pairs import ensure_pairs_file

    ensure_pairs_file()
    cats = None if category in ("all", "", None) else [category]
    limit_i = int(limit) if limit else 50
    results, summary = run_eval(limit=limit_i, categories=cats)

    lines = [
        "### Eval suite results",
        "",
        f"| Metric | Score |",
        f"|--------|-------|",
        f"| Pairs | {summary['n_pairs']} |",
        f"| Exact match | {100 * summary['exact_match']:.1f}% |",
        f"| Token F1 | {100 * summary['token_f1']:.1f}% |",
        f"| Fuzzy (Dice) | {100 * summary['fuzzy']:.1f}% |",
        f"| Pass rate | {100 * summary['pass_rate']:.1f}% |",
        "",
        "#### By category",
        "",
        "| Category | N | Exact | Token F1 | Pass |",
        "|----------|---|-------|----------|------|",
    ]
    for cat, stats in summary.get("by_category", {}).items():
        lines.append(
            f"| {cat} | {stats['n']} | {100 * stats['exact_match']:.0f}% "
            f"| {100 * stats['token_f1']:.0f}% | {100 * stats['pass_rate']:.0f}% |"
        )

    detail = [
        "### Sample predictions",
        "",
        "| ID | Pass | F1 | Exact |",
        "|----|------|----|-------|",
    ]
    for r in results[:25]:
        detail.append(
            f"| {r.pair_id} | {'yes' if r.passed else 'no'} "
            f"| {100 * r.token_f1:.0f}% | {100 * r.exact_match:.0f}% |"
        )
    return "\n".join(lines), "\n".join(detail), summary


def submit_eval_score(name: str, summary: dict | None) -> str:
    from sqlshift.eval.leaderboard import format_leaderboard_md, submit_score

    if not summary or not summary.get("n_pairs"):
        return format_leaderboard_md() + "\n\n_Run the eval suite before submitting._"
    board = submit_score(
        name=name or "anonymous",
        exact_match=summary.get("exact_match", 0),
        token_f1=summary.get("token_f1", 0),
        fuzzy=summary.get("fuzzy", 0),
        pass_rate=summary.get("pass_rate", 0),
        n_pairs=summary.get("n_pairs", 0),
        notes="SQLShiftAI hybrid translator",
    )
    return format_leaderboard_md(board)


def run_behavior_rag(query: str, source: str, target: str) -> str:
    from sqlshift.intelligence.rag import get_rag

    return get_rag().answer(query or "NULL empty string timezone", source, target)


def run_feature_migration(target: str) -> tuple[str, str]:
    """Convert ML feature SQL and optionally emit dbt feature mart."""
    sql = FEATURE_SQL_PATH.read_text(encoding="utf-8") if FEATURE_SQL_PATH.exists() else HERO_EXAMPLE
    wants_dbt = is_dbt_target(target) or target == "dbt-snowflake"
    target_d = Dialect.SNOWFLAKE
    converted, conf, auto, review = translate_sql(sql, Dialect.VERTICA, target_d)
    obj = MigrationObject(
        name="churn_features",
        object_type=ObjectType.SQL_SCRIPT,
        source_sql=sql,
        target_sql=converted,
    )
    if wants_dbt:
        files = decompose_to_dbt(obj, Dialect.VERTICA, project_name="ml_feature_mart")
        out = format_dbt_project(files, max_files=14)
    else:
        out = converted

    md = [
        "### ML / DS feature SQL migration",
        "",
        "Legacy Vertica feature engineering SQL → Snowflake"
        + (" dbt feature mart" if wants_dbt else ""),
        "",
        f"**Confidence:** {conf:.0f}%",
        "",
        "This path is for **data scientists / ML engineers** migrating training-feature SQL "
        "into warehouse-native, versioned dbt models.",
        "",
        "**Transforms**",
    ]
    md.extend(f"- {a}" for a in auto[:10])
    if review:
        md.append("")
        md.append("**Review**")
        md.extend(f"- {r}" for r in review[:6])
    return "\n".join(md), out


def get_leaderboard_md() -> str:
    from sqlshift.eval.leaderboard import format_leaderboard_md

    return format_leaderboard_md()

