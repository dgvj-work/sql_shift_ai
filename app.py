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

_BOOT = convert_for_ui(HERO_EXAMPLE, "vertica", "pandas")


def _build_demo() -> gr.Blocks:
    with gr.Blocks(title=f"{__product_name__} — SQL → pandas") as demo:
        eval_state = gr.State(value={})
        eval_category = gr.State(value="all")

        gr.HTML(
            f"""
            <div class="header-block">
                <div class="eyebrow">FOR DATA SCIENTISTS · SQL → PANDAS</div>
                <h1>{__product_name__}</h1>
                <p>Paste warehouse SQL, get notebook-ready <strong>pandas</strong> code,
                optionally preview it on sample data, then download the <code>.py</code> file.</p>
            </div>
            """
        )

        with gr.Tabs():
            with gr.Tab("Convert"):
                gr.Markdown(
                    "1. Choose input dialect + output type  ·  "
                    "2. Paste SQL or load an example  ·  "
                    "3. **Convert** → preview + download"
                )

                example = gr.Dropdown(
                    choices=PLAYGROUND_EXAMPLE_LABELS,
                    value=PLAYGROUND_EXAMPLE_LABELS[0],
                    label="Load a data-science example",
                    info="Fills SQL, sets From/To, converts, and runs a sample preview.",
                )

                with gr.Row():
                    source = gr.Dropdown(
                        choices=SOURCE_DROPDOWN,
                        value="vertica",
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
                        placeholder="Paste warehouse SQL used in notebooks / ETL…",
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
                    )
                    preview = gr.Dataframe(
                        label="Sample preview (pandas only)",
                        value=_BOOT[4],
                        wrap=True,
                    )

                notes = gr.Markdown(value=_BOOT[0])
                with gr.Accordion("Notebook starter cell", open=False):
                    notebook = gr.Code(
                        language="python",
                        value=_BOOT[6],
                        lines=10,
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
## Why data scientists use this
Warehouse SQL (Vertica / Oracle / Redshift / BigQuery / Snowflake) often lives in
BI tools. MorphSQL turns those queries into **pandas** you can drop into Jupyter,
Colab, or a feature pipeline — without rewriting null-handling and date filters by hand.

## Recommended workflow
1. Convert SQL → **Python (pandas)**
2. Check the **sample preview** (synthetic tables)
3. Download the `.py` file or paste into a notebook
4. Replace `tables['…']` with `pd.read_parquet` / `pd.read_sql` / Snowflake connector frames

## Output choices
| Convert to | Best for |
|---|---|
| **Python (pandas)** | Feature engineering, EDA, notebook migration |
| **Snowflake / BigQuery SQL** | Keeping work in the warehouse |
| **dbt project** | Productionizing SQL into models |

## Notebook pattern
```python
import pandas as pd
from sqlshift.ai import pipeline

out = pipeline("sql-migration")(
    open("legacy.sql").read(),
    source="vertica",
    target="pandas",
)
# out["converted_sql"] is Python source — exec or save as .py
```

Or load warehouse extracts directly:
```python
tables = {{
    "staging.orders": pd.read_parquet("orders.parquet"),
}}
# then run the MorphSQL-generated script so `result` is your frame
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
