"""SQLShiftAI — Hugging Face Space: SQL Migration Agent."""

from __future__ import annotations

import gradio as gr

from sqlshift import __product_name__, __version__
from sqlshift.eval.pairs import ensure_pairs_file
from demo.handlers import (
    FEATURE_SQL_PATH,
    HERO_EXAMPLE,
    analyze_sql_object,
    copilot_chat,
    get_leaderboard_md,
    get_sample_workbench,
    report_to_context,
    run_behavior_rag,
    run_eval_suite,
    run_feature_migration,
    run_hero_agent,
    run_migration_workbench,
    submit_eval_score,
)
from demo.theme import CUSTOM_CSS, build_theme

SOURCE_CHOICES = ["vertica", "oracle", "redshift", "bigquery", "snowflake"]
TARGET_CHOICES = ["snowflake", "dbt-snowflake", "bigquery"]

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

ensure_pairs_file()
_SAMPLE = get_sample_workbench()
_SAMPLE_INSPECTOR = analyze_sql_object(EXAMPLE_SQL, "vertica", "snowflake")
_HERO = run_hero_agent(HERO_EXAMPLE, "vertica", "snowflake")
_FEATURE_SRC = FEATURE_SQL_PATH.read_text(encoding="utf-8") if FEATURE_SQL_PATH.exists() else HERO_EXAMPLE
_FEATURE = run_feature_migration("dbt-snowflake")


def _build_demo() -> gr.Blocks:
    with gr.Blocks(title="SQLShiftAI · SQL Migration Agent") as demo:
        report_state = gr.State(value=_SAMPLE[11])
        eval_state = gr.State(value={})

        gr.HTML(
            f"""
            <div class="header-block">
                <h1>{__product_name__}</h1>
                <p>SQL Migration Agent · v{__version__} ·
                LLM tools · hybrid codegen · behavior RAG · eval suite · dbt emission</p>
            </div>
            """
        )

        with gr.Tabs():
            # 1) Hero Agent FIRST — HF wow loop
            with gr.Tab("Agent Demo"):
                gr.Markdown(
                    "Paste legacy SQL → the agent **converts**, **explains**, "
                    "retrieves **behavior knowledge**, and optionally emits a **dbt project**. "
                    "This is the 30-second Hugging Face demo loop."
                )
                with gr.Row():
                    with gr.Column(scale=3):
                        hero_sql = gr.Code(
                            label="Source SQL",
                            language="sql",
                            value=HERO_EXAMPLE,
                            lines=12,
                        )
                    with gr.Column(scale=1, min_width=220):
                        hero_source = gr.Dropdown(SOURCE_CHOICES, value="vertica", label="Source")
                        hero_target = gr.Dropdown(TARGET_CHOICES, value="snowflake", label="Target")
                        hero_run = gr.Button("Run agent", variant="primary")
                        hero_badge = gr.Textbox(label="Score", interactive=False, value=_HERO[2])
                hero_explain = gr.Markdown(value=_HERO[0])
                hero_out = gr.Code(
                    label="Agent output",
                    language="sql",
                    lines=14,
                    interactive=False,
                    value=_HERO[1],
                )
                hero_run.click(
                    run_hero_agent,
                    [hero_sql, hero_source, hero_target],
                    [hero_explain, hero_out, hero_badge],
                )

            # 2) Eval + Leaderboard
            with gr.Tab("Eval & Leaderboard"):
                gr.Markdown(
                    "Benchmark the hybrid translator on the bundled "
                    "**Vertica/Oracle/Redshift/BigQuery → Snowflake** pair dataset "
                    "(also publishable to the Hub). Metrics: exact match, token F1, fuzzy Dice."
                )
                with gr.Row():
                    eval_limit = gr.Slider(10, 200, value=50, step=10, label="Pairs to evaluate")
                    eval_cat = gr.Dropdown(
                        ["all", "function", "date", "aggregate", "ddl", "ml_feature"],
                        value="all",
                        label="Category",
                    )
                    eval_run = gr.Button("Run eval suite", variant="primary")
                eval_summary = gr.Markdown("Click **Run eval suite** to score conversion quality.")
                eval_detail = gr.Markdown("")
                with gr.Row():
                    lb_name = gr.Textbox(label="Your name / handle", value="hf-demo")
                    lb_submit = gr.Button("Submit score to leaderboard")
                leaderboard_md = gr.Markdown(value=get_leaderboard_md())
                eval_run.click(
                    run_eval_suite,
                    [eval_limit, eval_cat],
                    [eval_summary, eval_detail, eval_state],
                )
                lb_submit.click(submit_eval_score, [lb_name, eval_state], [leaderboard_md])

            # 3) Behavior RAG
            with gr.Tab("Behavior RAG"):
                gr.Markdown(
                    "Retrieve platform behavior differences (NULL semantics, timezones, ROWNUM, MERGE…) "
                    "with keyword search, or **sentence-transformers** when installed."
                )
                rag_q = gr.Textbox(
                    label="Question or SQL snippet",
                    value="How do empty strings and NULL differ between Oracle and Snowflake?",
                    lines=3,
                )
                with gr.Row():
                    rag_source = gr.Dropdown(SOURCE_CHOICES, value="oracle", label="Source")
                    rag_target = gr.Dropdown(TARGET_CHOICES, value="snowflake", label="Target")
                    rag_run = gr.Button("Retrieve", variant="primary")
                rag_out = gr.Markdown(
                    value=run_behavior_rag(
                        "How do empty strings and NULL differ between Oracle and Snowflake?",
                        "oracle",
                        "snowflake",
                    )
                )
                rag_run.click(run_behavior_rag, [rag_q, rag_source, rag_target], [rag_out])

            # 4) ML / Feature SQL
            with gr.Tab("ML Feature SQL"):
                gr.Markdown(
                    "For **data scientists**: migrate feature-engineering / label SQL into "
                    "Snowflake or a **dbt feature mart** ready for training pipelines."
                )
                feat_src = gr.Code(
                    label="Legacy feature SQL (Vertica)",
                    language="sql",
                    value=_FEATURE_SRC,
                    lines=16,
                    interactive=False,
                )
                feat_target = gr.Dropdown(
                    ["snowflake", "dbt-snowflake"],
                    value="dbt-snowflake",
                    label="Target",
                )
                feat_run = gr.Button("Migrate features", variant="primary")
                feat_md = gr.Markdown(value=_FEATURE[0])
                feat_out = gr.Code(
                    label="Migrated features / dbt mart",
                    language="sql",
                    lines=16,
                    interactive=False,
                    value=_FEATURE[1],
                )
                feat_run.click(run_feature_migration, [feat_target], [feat_md, feat_out])

            # 5) Object Inspector
            with gr.Tab("Object Inspector"):
                gr.Markdown(
                    "Deep-dive a single SQL object. Choose **dbt-snowflake** for staging / intermediate / marts."
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
                        obj_source = gr.Dropdown(SOURCE_CHOICES, value="vertica", label="Source platform")
                        obj_target = gr.Dropdown(TARGET_CHOICES, value="snowflake", label="Target platform")
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
                        obj_risk_chart = gr.Plot(value=_SAMPLE_INSPECTOR[1], label="Risk gauge")
                with gr.Row():
                    with gr.Column(scale=3):
                        obj_converted = gr.Code(
                            label="Converted output (SQL or dbt project)",
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

            # 6) Migration Workbench
            with gr.Tab("Migration Workbench"):
                gr.Markdown(
                    "Repository-level agent: upload a zip or use the bundled Vertica sample."
                )
                with gr.Row():
                    repo_upload = gr.File(label="Repository upload (zip)", file_types=[".zip"], type="filepath")
                    use_sample = gr.Checkbox(label="Use sample repository", value=True)
                with gr.Row():
                    wb_source = gr.Dropdown(SOURCE_CHOICES, value="vertica", label="Source platform")
                    wb_target = gr.Dropdown(TARGET_CHOICES, value="snowflake", label="Target platform")
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
                        wb_json = gr.Code(language="json", lines=14, label="JSON export", value=_SAMPLE[10])
                wb_outputs = [
                    wb_summary, wb_objects, wb_rational, wb_runbook, wb_dbt, wb_validation,
                    wb_metrics, wb_risk, wb_dist, wb_lineage, wb_json, report_state,
                ]
                wb_run.click(
                    run_migration_workbench,
                    [repo_upload, use_sample, wb_source, wb_target],
                    wb_outputs,
                )

            # 7) Copilot
            with gr.Tab("Migration Copilot"):
                gr.Markdown(
                    "Grounded migration copilot. Works offline via knowledge base; "
                    "set `HF_TOKEN` for full LLM answers via Hugging Face Inference."
                )
                copilot_context = gr.Markdown(value=report_to_context(_SAMPLE[11]))
                copilot_chatbot = gr.Chatbot(
                    label="Copilot",
                    height=400,
                    value=[{
                        "role": "assistant",
                        "content": "Sample repository context is loaded. Try: What should we migrate first?",
                    }],
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
                    copilot_sql = gr.Code(label="SQL for context", language="sql", lines=8, value="")
                    with gr.Row():
                        copilot_source = gr.Dropdown(SOURCE_CHOICES, value="vertica", label="Source")
                        copilot_target = gr.Dropdown(TARGET_CHOICES, value="snowflake", label="Target")
                report_state.change(report_to_context, [report_state], [copilot_context])
                copilot_inputs = [
                    copilot_input, copilot_chatbot, report_state,
                    copilot_sql, copilot_source, copilot_target,
                ]
                copilot_send.click(copilot_chat, copilot_inputs, [copilot_chatbot, copilot_input])
                copilot_input.submit(copilot_chat, copilot_inputs, [copilot_chatbot, copilot_input])

            # 8) Reference
            with gr.Tab("Reference"):
                gr.Markdown(
                    """
### SQLShiftAI — SQL Migration Agent

Not a toy SQL converter. Hybrid **rules + sqlglot + RAG + optional LLM** that:

| Capability | Description |
|------------|-------------|
| Agent Demo | One-shot convert + explain + RAG |
| Eval suite | Exact / token F1 / fuzzy on Hub-ready pairs |
| Behavior RAG | Retrieve NULL/timezone/MERGE diffs |
| ML Feature SQL | Feature/label SQL → Snowflake / dbt mart |
| Object Inspector | Single-object risk + conversion / dbt |
| Workbench | Repo scan, lineage, runbook, validation |
| Copilot | Grounded HF Inference advisor |

### Dataset & model story
- Pair dataset: `datasets/vertica_snowflake_pairs.jsonl`
- Publish: `python scripts/publish_dataset.py --repo YOUR_USER/vertica-snowflake-pairs`
- Hybrid core today; LoRA fine-tune on the pair set is the next model-card release.

```bash
pip install sqlshift-ai
sqlshift migrate ./legacy_sql --source vertica --target snowflake --output out/
```
                    """
                )

        gr.Markdown(
            "<p style='color:#94a3b8;font-size:0.78rem;margin-top:1rem'>"
            "SQLShiftAI · SQL Migration Agent · Apache 2.0 · "
            "<a href='https://github.com/dgvj-work/sql_shift_ai' style='color:#3b82f6'>GitHub</a>"
            "</p>"
        )

    return demo


demo = _build_demo()


if __name__ == "__main__":
    demo.launch(theme=build_theme(), css=CUSTOM_CSS)
