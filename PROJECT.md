# MorphSQL — Project Context Document

> **Purpose:** Give this file to any AI assistant or new developer to continue work without prior conversation context.

## Naming

| Layer | Name |
|-------|------|
| **Product (UI, docs, Hugging Face Space title)** | **MorphSQL** |
| Python import | `sqlshift` |
| PyPI package | `sqlshift-ai` |
| GitHub repo | `sql_shift_ai` |
| HF Space / model slug | `dgvj-work/sqlshift-ai` |

Always use **MorphSQL** as the public product name. Do not invent alternate brands (SQLShiftAI, etc.) in UI copy.

## What this project is

**MorphSQL** is an open-source **SQL migration toolkit** (package import: `sqlshift`).

It is **not** only a single-query converter. It analyzes legacy SQL repositories and produces:

1. **Discovery** — scan zip files/directories for SQL, procedures, views, dbt models
2. **Lineage** — dependency graphs (table/object level)
3. **Risk assessment** — complexity scoring, unsupported syntax, downstream impact
4. **Workload rationalization** — migrate / review / rewrite / retire per object
5. **Hybrid translation** — rule-based + sqlglot dialect conversion (pandas / PySpark / warehouse / dbt)
6. **dbt architecture** — decompose procedures into staging/intermediate/mart
7. **Validation** — reconciliation tests (row count, null rate, checksums)
8. **Migration runbook** — phased cutover plan with object action table
9. **Migration copilot** — LLM advisor grounded in scan context (HF Inference API)

## Repository layout

```
sql_shift_ai/
├── app.py                    # Hugging Face Gradio Space (MorphSQL UI)
├── demo/
│   ├── handlers.py           # Gradio event handlers
│   └── theme.py              # Dark theme CSS/constants
├── sqlshift/                 # Core Python package
│   ├── scanner/              # Repository discovery
│   ├── parser/               # SQL parsing (sqlglot)
│   ├── lineage/              # Dependency graphs (networkx)
│   ├── translator/           # Hybrid SQL conversion (+ pandas/pyspark codegen)
│   ├── risk/                 # Complexity & risk scoring
│   ├── dbt_generator/        # dbt project decomposition
│   ├── validation/           # Reconciliation tests
│   ├── knowledge/            # Platform behavior differences KB
│   ├── intelligence/         # Runbook, rationalization, lineage viz
│   ├── assistant/            # LLM copilot (huggingface_hub)
│   ├── report/               # HTML report generation
│   ├── pipeline.py           # Agent orchestration
│   ├── models.py             # Pydantic data models
│   └── cli.py                # `sqlshift` CLI
├── examples/vertica_legacy/  # Sample legacy Vertica repository
├── tests/
├── PROJECT.md                # This file
├── README.md
├── README_HF_SPACE.md        # HF Space card (title: MorphSQL)
├── MODEL_CARD.md
└── pyproject.toml
```

## Architecture

```
Repository (zip / directory)
        ↓
MigrationPipeline.analyze()     → Discovery + Lineage + Risk
        ↓
MigrationPipeline.convert()     → Hybrid SQL translation
        ↓
MigrationPipeline.validate()    → Reconciliation tests
        ↓
generate_runbook()              → Cutover plan
generate_rationalization()      → Migrate/retire recommendations
decompose_to_dbt()              → dbt scaffold
MigrationCopilot.respond()      → LLM Q&A grounded in report
```

## Key modules

| Module | File | Purpose |
|--------|------|---------|
| Pipeline | `sqlshift/pipeline.py` | Orchestrates full workflow |
| Translator | `sqlshift/translator/engine.py` | ZEROIFNULL, DATEADD, procedure wrappers, sqlglot |
| Pandas / PySpark | `sqlshift/translator/*_codegen.py` | Notebook / Spark DataFrame codegen |
| Copilot | `sqlshift/assistant/copilot.py` | HF Inference API + fallback KB |
| Runbook | `sqlshift/intelligence/runbook.py` | Migration runbook markdown |
| Lineage viz | `sqlshift/intelligence/lineage_viz.py` | Plotly network graph |
| Rationalization | `sqlshift/intelligence/rationalization.py` | Workload action plan |

## CLI commands

```bash
sqlshift analyze PATH -s vertica -t snowflake
sqlshift convert PATH -s snowflake -t pandas
sqlshift migrate PATH -s vertica -t snowflake -o migration-output
sqlshift version
```

## Hugging Face

- Space title: **MorphSQL**
- Space URL: https://huggingface.co/spaces/dgvj-work/sqlshift-ai
- Deploy: `./scripts/deploy_hf.sh`
- Preflight: `python scripts/check_space.py`
- Copilot model env: `MORPHSQL_MODEL` (fallback: `SQLSHIFTAI_MODEL`)

## Gradio UI tabs

1. **Convert** — primary: paste/upload SQL → pandas/PySpark/SQL/dbt + preview + download
2. **Guide** — how-to for DS / AI users
3. **More** — object assess, repo workbench, feature SQL, copilot, RAG, eval
