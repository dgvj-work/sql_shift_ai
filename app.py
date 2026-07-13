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
    convert_for_ui,
    get_leaderboard_md,
    on_example_selected,
    run_behavior_rag,
    run_eval_suite,
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
                <div class="eyebrow">AI / ML · DATA SCIENCE · SQL → PANDAS</div>
                <h1>{__product_name__}</h1>
                <p>Turn warehouse SQL into notebook-ready <strong>pandas</strong> features for
                training, EDA, or HF pipelines — with live preview and a downloadable <code>.py</code>.</p>
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
                        label="Sample preview (pandas only)",
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
MorphSQL is a **deterministic** SQL→pandas codegen tool (not a chat LLM). Use it when you have
warehouse SQL for labels/features and want a Python frame for training or evaluation.

**Typical path**
1. Convert feature SQL → pandas
2. Point `tables[...]` at parquet / `datasets` / warehouse extracts
3. Feed `result` into sklearn, XGBoost, or a Transformers training loop

## Why data scientists use this
Warehouse SQL often lives in BI tools. MorphSQL rewrites dialect quirks (NVL, ZEROIFNULL, dates)
into pandas you can run in Jupyter / Colab.

## Recommended workflow
1. Convert SQL → **Python (pandas)**
2. Check the **sample preview**
3. Download `.py` or copy the **HF pipeline** snippet
4. Replace synthetic tables with real data

## Output choices
| Convert to | Best for |
|---|---|
| **Python (pandas)** | Feature engineering, EDA, model training prep |
| **Snowflake / BigQuery SQL** | Keeping transforms in the warehouse |
| **dbt project** | Productionizing SQL into models |

```python
from sqlshift.ai import pipeline
out = pipeline("sql-migration")(sql, source="snowflake", target="pandas")
# out["converted_sql"] → exec / save as features.py
```

[Space]({SPACE_URL}) · [GitHub]({GITHUB_URL})
"""
                )

            with gr.Tab("More"):
                gr.Markdown("Optional extras. Day-to-day use is the **Convert** tab.")

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
