"""MigrationIQ — Hugging Face Space: full migration intelligence workbench."""

from __future__ import annotations

import gradio as gr

from sqlshift import __product_name__, __version__
from demo.handlers import (
    analyze_sql_object,
    copilot_chat,
    report_to_context,
    run_migration_workbench,
)
from demo.theme import CUSTOM_CSS, DARK_THEME

EXAMPLE_SQL = """CREATE OR REPLACE PROCEDURE SP_BUILD_CUSTOMER_DAILY(load_date DATE)
AS $$
BEGIN
    CREATE LOCAL TEMP TABLE tmp_txns ON COMMIT PRESERVE ROWS AS
    SELECT customer_id, order_id, order_amount,
           ZEROIFNULL(discount_amount) AS discount_amount
    FROM staging.customer_transactions
    WHERE order_date = load_date;

    DELETE FROM analytics.customer_daily WHERE activity_date = load_date;

    INSERT INTO analytics.customer_daily
    SELECT customer_id, load_date,
           COUNT(DISTINCT order_id) AS order_count,
           SUM(order_amount - ZEROIFNULL(discount_amount)) AS total_spend
    FROM tmp_txns GROUP BY customer_id, load_date;
END;
$$;"""

with gr.Blocks(title="MigrationIQ") as demo:
    report_state = gr.State(value=None)

    gr.HTML(
        f"""
        <div class="header-block">
            <h1>{__product_name__}</h1>
            <p>Data platform migration intelligence · v{__version__} ·
            Discovery · Lineage · Assessment · Architecture · Validation · Copilot</p>
        </div>
        """
    )

    with gr.Tabs():
        # ── Migration Workbench ──────────────────────────────────────────
        with gr.Tab("Migration Workbench"):
            gr.Markdown(
                "Analyze an entire SQL repository — not single queries. "
                "Upload a `.zip` of legacy SQL, dbt models, and procedures, "
                "or use the bundled Vertica sample."
            )
            with gr.Row():
                repo_upload = gr.File(
                    label="Repository upload (.zip)",
                    file_types=[".zip"],
                    type="filepath",
                )
                use_sample = gr.Checkbox(
                    label="Use sample repository",
                    value=True,
                )
            with gr.Row():
                wb_source = gr.Dropdown(
                    ["vertica", "oracle", "redshift", "bigquery"],
                    value="vertica",
                    label="Source platform",
                )
                wb_target = gr.Dropdown(
                    ["snowflake", "dbt-snowflake", "bigquery"],
                    value="snowflake",
                    label="Target platform",
                )
                wb_run = gr.Button("Run migration intelligence", variant="primary")

            wb_summary = gr.Markdown(
                value="Enable **Use sample repository** or upload a `.zip`, then click **Run migration intelligence**."
            )

            with gr.Row():
                wb_risk = gr.Plot(label="Portfolio risk")
                wb_dist = gr.Plot(label="Object distribution")

            with gr.Tabs():
                with gr.Tab("Objects"):
                    wb_objects = gr.Markdown()
                with gr.Tab("Rationalization"):
                    wb_rational = gr.Markdown()
                with gr.Tab("Runbook"):
                    wb_runbook = gr.Markdown()
                with gr.Tab("Architecture (dbt)"):
                    wb_dbt = gr.Markdown()
                with gr.Tab("Validation"):
                    wb_validation = gr.Markdown()
                with gr.Tab("Lineage"):
                    wb_lineage = gr.Plot(label="Dependency graph")
                with gr.Tab("Export"):
                    wb_json = gr.Code(language="json", lines=14, label="JSON export")

            wb_run.click(
                run_migration_workbench,
                [repo_upload, use_sample, wb_source, wb_target],
                [
                    wb_summary,
                    wb_objects,
                    wb_rational,
                    wb_runbook,
                    wb_dbt,
                    wb_validation,
                    wb_risk,
                    wb_dist,
                    wb_lineage,
                    wb_json,
                    report_state,
                ],
            )

        # ── Object Inspector ─────────────────────────────────────────────
        with gr.Tab("Object Inspector"):
            gr.Markdown("Deep-dive on a single SQL object — assess complexity, convert dialect, preview output.")
            with gr.Row():
                with gr.Column(scale=3):
                    sql_input = gr.Code(label="Source SQL", language="sql", value=EXAMPLE_SQL, lines=18)
                with gr.Column(scale=1):
                    obj_source = gr.Dropdown(
                        ["vertica", "oracle", "redshift"], value="vertica", label="Source"
                    )
                    obj_target = gr.Dropdown(
                        ["snowflake", "dbt-snowflake"], value="snowflake", label="Target"
                    )
                    obj_analyze = gr.Button("Assess object", variant="secondary")
                    obj_risk_badge = gr.Textbox(label="Risk score", interactive=False, value="—")
            with gr.Row():
                obj_analysis = gr.Markdown()
                obj_risk_chart = gr.Plot(label="Risk gauge")
            obj_converted = gr.Code(label="Converted SQL", language="sql", lines=16, interactive=False)

            obj_analyze.click(
                analyze_sql_object,
                [sql_input, obj_source, obj_target],
                [obj_analysis, obj_risk_chart, obj_risk_badge, obj_converted],
            )
            demo.load(
                analyze_sql_object,
                [sql_input, obj_source, obj_target],
                [obj_analysis, obj_risk_chart, obj_risk_badge, obj_converted],
            )

        # ── Migration Copilot ──────────────────────────────────────────
        with gr.Tab("Migration Copilot"):
            gr.Markdown(
                "LLM-powered migration advisor grounded in your scan results. "
                "Run the **Migration Workbench** first to load repository context. "
                "Uses Hugging Face Inference API (`Qwen/Qwen2.5-3B-Instruct` by default)."
            )
            copilot_context = gr.Markdown(value="*No repository scan loaded yet.*")
            copilot_chatbot = gr.Chatbot(
                label="Copilot",
                height=360,
                value=[],
                placeholder="Ask about migration scope, cutover plan, lineage impact, dbt strategy…",
            )
            with gr.Row():
                copilot_input = gr.Textbox(
                    label="Message",
                    placeholder="What should we migrate first based on risk scores?",
                    scale=4,
                )
                copilot_send = gr.Button("Send", variant="primary", scale=1)

            with gr.Accordion("SQL context (optional)", open=False):
                copilot_sql = gr.Code(label="SQL for context", language="sql", lines=8, value="")
                copilot_source = gr.Dropdown(["vertica", "oracle", "redshift"], value="vertica")
                copilot_target = gr.Dropdown(["snowflake", "dbt-snowflake"], value="snowflake")

            def _refresh_context(report):
                return report_to_context(report)

            report_state.change(_refresh_context, [report_state], [copilot_context])

            copilot_send.click(
                copilot_chat,
                [copilot_input, copilot_chatbot, report_state, copilot_sql, copilot_source, copilot_target],
                [copilot_chatbot, copilot_input],
            )
            copilot_input.submit(
                copilot_chat,
                [copilot_input, copilot_chatbot, report_state, copilot_sql, copilot_source, copilot_target],
                [copilot_chatbot, copilot_input],
            )

        # ── Reference ────────────────────────────────────────────────────
        with gr.Tab("Reference"):
            gr.Markdown(
                """
### What MigrationIQ does

MigrationIQ is a **data platform migration intelligence system** — not a simple SQL converter.

| Capability | Description |
|------------|-------------|
| **Repository discovery** | Scan zip files, directories, procedures, views, dbt models |
| **Dependency lineage** | Table and object-level dependency graphs |
| **Risk scoring** | Complexity, unsupported syntax, downstream impact |
| **Workload rationalization** | Migrate / review / rewrite / retire recommendations |
| **Hybrid translation** | Rule-based + sqlglot dialect conversion |
| **dbt architecture** | Decompose procedures into staging/intermediate/mart |
| **Validation suite** | Reconciliation tests, null rates, checksums |
| **Migration runbook** | Phase plan, object actions, cutover checklist |
| **Migration copilot** | LLM advisor grounded in scan context |

### CLI

```bash
pip install sqlshift-ai
sqlshift migrate ./legacy_sql --source vertica --target snowflake --output out/
```

### Context handoff

For AI continuation, read `PROJECT.md` in the repository root.
                """
            )

    gr.Markdown(
        "<p style='color:#94a3b8;font-size:0.78rem;margin-top:1rem'>"
        "MigrationIQ · Apache 2.0 · "
        "<a href='https://github.com/dgvj-work/sql_shift_ai' style='color:#3b82f6'>GitHub</a>"
        "</p>"
    )


if __name__ == "__main__":
    demo.launch(theme=DARK_THEME, css=CUSTOM_CSS)
