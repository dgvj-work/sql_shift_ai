"""SQLShiftAI — Hugging Face Space: full migration intelligence workbench."""

from __future__ import annotations

import gradio as gr

from sqlshift import __product_name__, __version__
from demo.handlers import (
    analyze_sql_object,
    copilot_chat,
    get_sample_workbench,
    report_to_context,
    run_migration_workbench,
)
from demo.theme import CUSTOM_CSS, build_theme

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

# Precompute so Workbench / Inspector are never blank on first paint
_SAMPLE = get_sample_workbench()
_SAMPLE_INSPECTOR = analyze_sql_object(EXAMPLE_SQL, "vertica", "snowflake")


def _build_demo() -> gr.Blocks:
    with gr.Blocks(title="SQLShiftAI") as demo:
        report_state = gr.State(value=_SAMPLE[11])

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
            # 1) Object Inspector FIRST
            with gr.Tab("Object Inspector"):
                gr.Markdown(
                    "Paste a single SQL object (query, view, or procedure). "
                    "Assess migration risk and convert to the target dialect."
                )
                with gr.Row():
                    with gr.Column(scale=3):
                        sql_input = gr.Code(
                            label="Source SQL",
                            language="sql",
                            value=EXAMPLE_SQL,
                            lines=18,
                        )
                    with gr.Column(scale=1, min_width=220):
                        obj_source = gr.Dropdown(
                            ["vertica", "oracle", "redshift", "bigquery"],
                            value="vertica",
                            label="Source platform",
                        )
                        obj_target = gr.Dropdown(
                            ["snowflake", "dbt-snowflake", "bigquery"],
                            value="snowflake",
                            label="Target platform",
                        )
                        obj_analyze = gr.Button("Assess & Convert", variant="primary")
                        obj_risk_badge = gr.Textbox(
                            label="Score",
                            interactive=False,
                            value=_SAMPLE_INSPECTOR[2],
                        )

                with gr.Row():
                    with gr.Column(scale=2):
                        obj_analysis = gr.Markdown(value=_SAMPLE_INSPECTOR[0])
                    with gr.Column(scale=1, min_width=300):
                        obj_risk_chart = gr.Plot(
                            value=_SAMPLE_INSPECTOR[1],
                            label="Risk gauge",
                        )

                with gr.Row():
                    with gr.Column(scale=3):
                        obj_converted = gr.Code(
                            label="Converted SQL",
                            language="sql",
                            lines=16,
                            interactive=False,
                            value=_SAMPLE_INSPECTOR[3],
                        )
                    with gr.Column(scale=2):
                        obj_notes = gr.Markdown(value=_SAMPLE_INSPECTOR[4])

                obj_analyze.click(
                    analyze_sql_object,
                    [sql_input, obj_source, obj_target],
                    [obj_analysis, obj_risk_chart, obj_risk_badge, obj_converted, obj_notes],
                )

            # 2) Migration Workbench
            with gr.Tab("Migration Workbench"):
                gr.Markdown(
                    "Analyze an entire SQL repository — upload a zip file, or use the "
                    "bundled Vertica sample (enabled by default)."
                )
                with gr.Row():
                    repo_upload = gr.File(
                        label="Repository upload (zip)",
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

                wb_summary = gr.Markdown(value=_SAMPLE[0])
                wb_metrics = gr.Markdown(value=_SAMPLE[6])

                with gr.Row():
                    wb_risk = gr.Plot(value=_SAMPLE[7], label="Portfolio risk")
                    wb_dist = gr.Plot(value=_SAMPLE[8], label="Object distribution")

                with gr.Tabs():
                    with gr.Tab("Objects"):
                        wb_objects = gr.Markdown(value=_SAMPLE[1])
                    with gr.Tab("Rationalization"):
                        wb_rational = gr.Markdown(value=_SAMPLE[2])
                    with gr.Tab("Runbook"):
                        wb_runbook = gr.Markdown(value=_SAMPLE[3])
                    with gr.Tab("Architecture (dbt)"):
                        wb_dbt = gr.Markdown(value=_SAMPLE[4])
                    with gr.Tab("Validation"):
                        wb_validation = gr.Markdown(value=_SAMPLE[5])
                    with gr.Tab("Lineage"):
                        wb_lineage = gr.Plot(value=_SAMPLE[9], label="Dependency graph")
                    with gr.Tab("Export"):
                        wb_json = gr.Code(
                            language="json",
                            lines=14,
                            label="JSON export",
                            value=_SAMPLE[10],
                        )

                wb_outputs = [
                    wb_summary,
                    wb_objects,
                    wb_rational,
                    wb_runbook,
                    wb_dbt,
                    wb_validation,
                    wb_metrics,
                    wb_risk,
                    wb_dist,
                    wb_lineage,
                    wb_json,
                    report_state,
                ]
                wb_run.click(
                    run_migration_workbench,
                    [repo_upload, use_sample, wb_source, wb_target],
                    wb_outputs,
                )

            # 3) Migration Copilot
            with gr.Tab("Migration Copilot"):
                gr.Markdown(
                    "Ask migration questions grounded in your latest Workbench scan. "
                    "Works offline with a grounded knowledge base; set HF_TOKEN for full LLM answers."
                )
                copilot_context = gr.Markdown(value=report_to_context(_SAMPLE[11]))
                copilot_chatbot = gr.Chatbot(
                    label="Copilot",
                    height=400,
                    value=[
                        {
                            "role": "assistant",
                            "content": (
                                "Sample repository context is loaded. "
                                "Try asking: What should we migrate first?"
                            ),
                        }
                    ],
                )
                with gr.Row():
                    copilot_input = gr.Textbox(
                        label="Message",
                        placeholder="What should we migrate first based on risk scores?",
                        scale=4,
                        lines=2,
                    )
                    copilot_send = gr.Button("Send", variant="primary", scale=1)

                with gr.Accordion("Extra SQL context (optional)", open=False):
                    copilot_sql = gr.Code(
                        label="SQL for context",
                        language="sql",
                        lines=8,
                        value="",
                    )
                    with gr.Row():
                        copilot_source = gr.Dropdown(
                            ["vertica", "oracle", "redshift"],
                            value="vertica",
                            label="Source",
                        )
                        copilot_target = gr.Dropdown(
                            ["snowflake", "dbt-snowflake"],
                            value="snowflake",
                            label="Target",
                        )

                report_state.change(report_to_context, [report_state], [copilot_context])

                copilot_inputs = [
                    copilot_input,
                    copilot_chatbot,
                    report_state,
                    copilot_sql,
                    copilot_source,
                    copilot_target,
                ]
                copilot_send.click(copilot_chat, copilot_inputs, [copilot_chatbot, copilot_input])
                copilot_input.submit(copilot_chat, copilot_inputs, [copilot_chatbot, copilot_input])

            # 4) Reference
            with gr.Tab("Reference"):
                gr.Markdown(
                    """
### What SQLShiftAI does

SQLShiftAI is a **data platform migration intelligence system** — not a simple SQL converter.

| Capability | Description |
|------------|-------------|
| Object Inspector | Assess and convert a single SQL object |
| Repository discovery | Scan zip files / sample repos |
| Dependency lineage | Interactive object dependency graphs |
| Risk scoring | Complexity, unsupported syntax, impact |
| Workload rationalization | Migrate / review / rewrite / retire |
| dbt architecture | Procedure to staging/intermediate/mart |
| Validation suite | Reconciliation checks |
| Migration runbook | Phased cutover plan |
| Migration copilot | Grounded advisor |

### CLI

```bash
pip install sqlshift-ai
sqlshift migrate ./legacy_sql --source vertica --target snowflake --output out/
```

For AI continuation, read PROJECT.md in the repository root.
                    """
                )

        gr.Markdown(
            "<p style='color:#94a3b8;font-size:0.78rem;margin-top:1rem'>"
            "SQLShiftAI · Apache 2.0 · "
            "<a href='https://github.com/dgvj-work/sql_shift_ai' style='color:#3b82f6'>GitHub</a>"
            "</p>"
        )

    return demo


demo = _build_demo()


if __name__ == "__main__":
    demo.launch(theme=build_theme(), css=CUSTOM_CSS)
