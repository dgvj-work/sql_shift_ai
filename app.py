"""MorphSQL — Hugging Face Space (conversion-first, DS-friendly)."""

from __future__ import annotations

import gradio as gr

from sqlshift import __product_name__, __version__
from sqlshift.ai.risk_model import train_and_save
from sqlshift.eval.pairs import ensure_pairs_file
from demo.handlers import (
    HERO_EXAMPLE,
    PLAYGROUND_EXAMPLE_LABELS,
    SOURCE_DROPDOWN,
    TARGET_DROPDOWN,
    analyze_sql_object_ui,
    convert_for_ui,
    copilot_chat,
    get_leaderboard_md,
    on_example_selected,
    run_behavior_rag,
    run_eval_suite,
    run_feature_migration,
    run_workbench_ui,
    submit_eval_score,
)
from demo.theme import CUSTOM_CSS, build_theme

SPACE_URL = "https://huggingface.co/spaces/dgvj-work/sqlshift-ai"
GITHUB_URL = "https://github.com/dgvj-work/sql_shift_ai"

ensure_pairs_file()
train_and_save()

_BOOT = convert_for_ui(HERO_EXAMPLE, "snowflake", "pandas")


def _build_demo() -> gr.Blocks:
    with gr.Blocks(title=f"{__product_name__} — SQL → pandas") as demo:
        eval_state = gr.State(value={})
        eval_category = gr.State(value="all")

        gr.HTML(
            f"""
            <div class="header-block">
                <div class="eyebrow">AI / ML · DATA SCIENCE · SQL → PANDAS / PYSPARK</div>
                <h1>{__product_name__}</h1>
                <p>Turn warehouse SQL into notebook-ready <strong>pandas</strong> or
                <strong>PySpark</strong> for training, EDA, or Spark jobs — with a live
                sample preview and downloadable <code>.py</code>.</p>
            </div>
            """
        )

        with gr.Tabs():
            with gr.Tab("Convert"):
                gr.Markdown(
                    "1. Choose input dialect + output  ·  "
                    "2. Paste SQL or load an example  ·  "
                    "3. **Convert** → preview + download + HF API snippet"
                )

                example = gr.Dropdown(
                    choices=PLAYGROUND_EXAMPLE_LABELS,
                    value=PLAYGROUND_EXAMPLE_LABELS[0],
                    label="Load a data-science / AI example",
                    info="Fills SQL, converts, runs sample preview.",
                )

                with gr.Row():
                    source = gr.Dropdown(
                        choices=SOURCE_DROPDOWN,
                        value="snowflake",
                        label="SQL is written for",
                    )
                    target = gr.Dropdown(
                        choices=TARGET_DROPDOWN,
                        value="pandas",
                        label="Convert to",
                    )
                    convert_btn = gr.Button("Convert", variant="primary")

                status = gr.Textbox(
                    label="Status",
                    value=_BOOT[2],
                    interactive=False,
                    max_lines=1,
                )

                with gr.Row():
                    sql_in = gr.Textbox(
                        label="Input SQL",
                        value=HERO_EXAMPLE,
                        lines=12,
                        max_lines=24,
                        placeholder="Paste warehouse SQL used in notebooks / feature pipelines…",
                    )
                    sql_out = gr.Textbox(
                        label="Output code",
                        value=_BOOT[1],
                        lines=12,
                        max_lines=24,
                    )

                with gr.Row():
                    download = gr.File(
                        label="Download output (.py / .sql)",
                        value=_BOOT[5],
                        elem_classes=["download-box"],
                    )
                    preview = gr.Dataframe(
                        label="Sample preview",
                        value=_BOOT[4],
                        wrap=True,
                        elem_classes=["preview-table"],
                    )

                notes = gr.Markdown(value=_BOOT[0])
                with gr.Accordion("Notebook starter cell", open=False):
                    notebook = gr.Code(
                        language="python",
                        value=_BOOT[6],
                        lines=10,
                    )
                with gr.Accordion("Hugging Face pipeline API (AI / ML)", open=True):
                    gr.Markdown(
                        "Same style as `transformers.pipeline` — use in Colab, HF Jobs, or training scripts."
                    )
                    api_code = gr.Code(
                        language="python",
                        value=_BOOT[7],
                        lines=12,
                    )
                share = gr.Markdown(value=_BOOT[3])

                outs = [
                    sql_in,
                    source,
                    target,
                    notes,
                    sql_out,
                    status,
                    share,
                    preview,
                    download,
                    notebook,
                    api_code,
                ]
                example.change(on_example_selected, inputs=[example], outputs=outs)

                convert_outs = [
                    notes,
                    sql_out,
                    status,
                    share,
                    preview,
                    download,
                    notebook,
                    api_code,
                ]
                convert_btn.click(
                    convert_for_ui,
                    inputs=[sql_in, source, target],
                    outputs=convert_outs,
                )
                sql_in.submit(
                    convert_for_ui,
                    inputs=[sql_in, source, target],
                    outputs=convert_outs,
                )

            with gr.Tab("Guide"):
                gr.Markdown(
                    f"""
## For AI / ML practitioners
MorphSQL is a **deterministic** SQL→pandas / PySpark codegen tool (not a chat LLM). Use it when you have
warehouse SQL for labels/features and want a Python frame for training or Spark jobs.

**Typical path**
1. Convert feature SQL → pandas or PySpark
2. Point `tables[...]` at parquet / `datasets` / warehouse extracts / Spark tables
3. Feed `result` into sklearn, XGBoost, Transformers, or Spark ML

## Why data scientists use this
Warehouse SQL often lives in BI tools. MorphSQL rewrites dialect quirks (NVL, ZEROIFNULL, dates)
into pandas or PySpark you can run in Jupyter / Colab / Databricks.

## Recommended workflow
1. Convert SQL → **Python (pandas)** or **Python (PySpark)**
2. Check the **sample preview** (works for every output target)
3. Copy the **HF pipeline** snippet
4. Replace synthetic tables with real data

## Output choices
| Convert to | Best for |
|---|---|
| **Python (pandas)** | Feature engineering, EDA, model training prep |
| **Python (PySpark)** | Large-scale Spark DataFrame transforms |
| **Snowflake / BigQuery SQL** | Keeping transforms in the warehouse |
| **dbt project** | Productionizing SQL into models |

## More tab (Lab)
| Tool | Use when |
|---|---|
| **Object assess** | Need risk/complexity scoring for one SQL object |
| **Repository workbench** | Scanning a SQL repo (sample or zip) with lineage + validation |
| **ML feature SQL** | Migrating Vertica feature-engineering SQL → Snowflake/dbt |
| **Copilot** | Migration Q&A (keyword / optional HF LLM) |
| **Behavior notes / Eval** | Dialect quirks lookup and offline conversion scoring |

```python
from sqlshift.ai import pipeline
out = pipeline("sql-migration")(sql, source="snowflake", target="pandas")
# or target="pyspark"
# out["converted_sql"] → exec / save as features.py
```

[Space]({SPACE_URL}) · [GitHub]({GITHUB_URL})
"""
                )

            with gr.Tab("More"):
                gr.Markdown(
                    "Lab extras beyond day-to-day Convert: assess objects, scan a repo, "
                    "migrate feature SQL, ask the copilot, or run offline eval."
                )
                report_state = gr.State(value=None)

                with gr.Accordion("Object assess & convert", open=False):
                    gr.Markdown(
                        "Score complexity/risk and convert a single SQL object "
                        "(pandas, PySpark, warehouse SQL, or dbt)."
                    )
                    with gr.Row():
                        assess_source = gr.Dropdown(
                            choices=SOURCE_DROPDOWN, value="vertica", label="Source"
                        )
                        assess_target = gr.Dropdown(
                            choices=TARGET_DROPDOWN, value="snowflake", label="Target"
                        )
                        assess_btn = gr.Button("Assess & Convert", variant="secondary")
                    assess_sql = gr.Textbox(
                        label="SQL object",
                        value="SELECT customer_id, ZEROIFNULL(order_amount) AS order_amount "
                        "FROM staging.orders WHERE order_date >= CURRENT_DATE - 30",
                        lines=8,
                    )
                    assess_badge = gr.Textbox(label="Score", interactive=False, max_lines=1)
                    with gr.Row():
                        assess_analysis = gr.Markdown()
                        assess_risk = gr.HTML()
                    assess_out = gr.Textbox(label="Converted output", lines=10)
                    assess_notes = gr.Markdown()
                    assess_btn.click(
                        analyze_sql_object_ui,
                        [assess_sql, assess_source, assess_target],
                        [assess_analysis, assess_risk, assess_badge, assess_out, assess_notes],
                    )

                with gr.Accordion("Repository workbench", open=False):
                    gr.Markdown(
                        "Scan the sample Vertica repo (or upload a `.zip`), then convert / "
                        "validate / preview dbt + lineage."
                    )
                    with gr.Row():
                        wb_source = gr.Dropdown(
                            choices=SOURCE_DROPDOWN, value="vertica", label="Source"
                        )
                        wb_target = gr.Dropdown(
                            choices=TARGET_DROPDOWN, value="snowflake", label="Target"
                        )
                        wb_sample = gr.Checkbox(value=True, label="Use sample repository")
                    wb_upload = gr.File(label="Or upload SQL repo (.zip)", file_types=[".zip"])
                    wb_btn = gr.Button("Run migration intelligence", variant="secondary")
                    wb_summary = gr.Markdown()
                    wb_metrics = gr.Markdown()
                    with gr.Row():
                        wb_risk = gr.HTML()
                        wb_dist = gr.HTML()
                    wb_objects = gr.Markdown()
                    wb_lineage = gr.HTML()
                    with gr.Row():
                        wb_rationalization = gr.Markdown()
                        wb_runbook = gr.Markdown()
                    with gr.Row():
                        wb_dbt = gr.Markdown()
                        wb_validation = gr.Markdown()
                    wb_export = gr.Code(language="json", lines=8, label="Export JSON")
                    wb_btn.click(
                        run_workbench_ui,
                        [wb_upload, wb_sample, wb_source, wb_target],
                        [
                            wb_summary,
                            wb_objects,
                            wb_rationalization,
                            wb_runbook,
                            wb_dbt,
                            wb_validation,
                            wb_metrics,
                            wb_risk,
                            wb_dist,
                            wb_lineage,
                            wb_export,
                            report_state,
                        ],
                    )

                with gr.Accordion("ML feature SQL migration", open=False):
                    gr.Markdown(
                        "Convert `examples/ml_features/churn_feature_sql.sql` "
                        "(Vertica feature engineering) → Snowflake SQL or a dbt feature mart."
                    )
                    with gr.Row():
                        feat_target = gr.Dropdown(
                            choices=[
                                ("Snowflake SQL", "snowflake"),
                                ("dbt project (Snowflake)", "dbt-snowflake"),
                            ],
                            value="snowflake",
                            label="Output",
                        )
                        feat_btn = gr.Button("Migrate feature SQL", variant="secondary")
                    feat_md = gr.Markdown()
                    feat_out = gr.Textbox(label="Output", lines=14)
                    feat_btn.click(run_feature_migration, [feat_target], [feat_md, feat_out])

                with gr.Accordion("Migration copilot", open=False):
                    gr.Markdown(
                        "Ask migration questions. Uses keyword/HF fallback guidance "
                        "(set `HF_TOKEN` for LLM replies)."
                    )
                    copilot = gr.Chatbot(label="Copilot", height=320)
                    copilot_msg = gr.Textbox(
                        label="Message",
                        placeholder="e.g. How should I handle ZEROIFNULL on Snowflake?",
                        lines=2,
                    )
                    with gr.Row():
                        copilot_source = gr.Dropdown(
                            choices=SOURCE_DROPDOWN, value="vertica", label="Source"
                        )
                        copilot_target = gr.Dropdown(
                            choices=TARGET_DROPDOWN, value="snowflake", label="Target"
                        )
                        copilot_btn = gr.Button("Ask", variant="secondary")
                    copilot_sql = gr.Textbox(
                        label="Optional SQL context",
                        value="SELECT ZEROIFNULL(amount) FROM staging.transactions",
                        lines=3,
                    )
                    copilot_btn.click(
                        copilot_chat,
                        [
                            copilot_msg,
                            copilot,
                            report_state,
                            copilot_sql,
                            copilot_source,
                            copilot_target,
                        ],
                        [copilot, copilot_msg],
                    )
                    copilot_msg.submit(
                        copilot_chat,
                        [
                            copilot_msg,
                            copilot,
                            report_state,
                            copilot_sql,
                            copilot_source,
                            copilot_target,
                        ],
                        [copilot, copilot_msg],
                    )

                with gr.Accordion("Dialect behavior notes", open=False):
                    rag_q = gr.Textbox(
                        label="Question",
                        value="Oracle empty string vs Snowflake NULL",
                        lines=2,
                    )
                    with gr.Row():
                        rag_source = gr.Dropdown(
                            choices=SOURCE_DROPDOWN, value="oracle", label="From"
                        )
                        rag_target = gr.Dropdown(
                            choices=[
                                ("Snowflake SQL", "snowflake"),
                                ("BigQuery SQL", "bigquery"),
                            ],
                            value="snowflake",
                            label="To",
                        )
                        rag_run = gr.Button("Search", variant="secondary")
                    rag_out = gr.Markdown()
                    rag_run.click(
                        run_behavior_rag,
                        [rag_q, rag_source, rag_target],
                        [rag_out],
                    )

                with gr.Accordion("Offline conversion eval", open=False):
                    with gr.Row():
                        eval_limit = gr.Slider(10, 200, value=40, step=10, label="Pairs")
                        eval_run = gr.Button("Run eval", variant="secondary")
                    eval_summary = gr.Markdown()
                    eval_detail = gr.Markdown()
                    with gr.Row():
                        lb_name = gr.Textbox(label="Handle", value="hf-user")
                        lb_submit = gr.Button("Submit local score")
                    leaderboard_md = gr.Markdown(value=get_leaderboard_md())
                    eval_run.click(
                        run_eval_suite,
                        [eval_limit, eval_category],
                        [eval_summary, eval_detail, eval_state],
                    )
                    lb_submit.click(
                        submit_eval_score, [lb_name, eval_state], [leaderboard_md]
                    )

        gr.Markdown(
            f"<p class='footer-viral'>{__product_name__} v{__version__} · "
            f"<a href='{SPACE_URL}'>Space</a> · "
            f"<a href='{GITHUB_URL}'>GitHub</a> · Apache-2.0</p>"
        )
    return demo


demo = _build_demo()


if __name__ == "__main__":
    demo.launch(theme=build_theme(), css=CUSTOM_CSS)
