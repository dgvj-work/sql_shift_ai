# SQLShiftAI — Project Context Document

> **Purpose:** Give this file to any AI assistant or new developer to continue work without prior conversation context.

## What this project is

**SQLShiftAI** (PyPI: `sqlshift-ai`, repo: `sql_shift_ai`) is an open-source **data platform migration intelligence system**.

It is **not** a simple SQL query converter. It analyzes entire legacy data platform repositories and produces:

1. **Discovery** — scan zip files/directories for SQL, procedures, views, dbt models
2. **Lineage** — dependency graphs (table/object level)
3. **Risk assessment** — complexity scoring, unsupported syntax, downstream impact
4. **Workload rationalization** — migrate / review / rewrite / retire per object
5. **Hybrid translation** — rule-based + sqlglot dialect conversion
6. **dbt architecture** — decompose procedures into staging/intermediate/mart
7. **Validation** — reconciliation tests (row count, null rate, checksums)
8. **Migration runbook** — phased cutover plan with object action table
9. **Migration copilot** — LLM advisor grounded in scan context (HF Inference API)

## Repository layout

```
sql_shift_ai/
├── app.py                    # Hugging Face Gradio Space (workbench UI)
├── demo/
│   ├── handlers.py           # Gradio event handlers
│   └── theme.py              # Dark theme CSS/constants
├── sqlshift/                 # Core Python package
│   ├── scanner/              # Repository discovery
│   ├── parser/               # SQL parsing (sqlglot)
│   ├── lineage/              # Dependency graphs (networkx)
│   ├── translator/           # Hybrid SQL conversion
│   ├── risk/                 # Complexity & risk scoring
│   ├── dbt_generator/        # dbt project decomposition
│   ├── validation/           # Reconciliation tests
│   ├── knowledge/              # Platform behavior differences KB
│   ├── intelligence/           # Runbook, rationalization, lineage viz
│   ├── assistant/            # LLM copilot (huggingface_hub)
│   ├── report/               # HTML report generation
│   ├── pipeline.py           # Agent orchestration
│   ├── models.py             # Pydantic data models
│   └── cli.py                  # `sqlshift` CLI
├── examples/vertica_legacy/  # Sample legacy Vertica repository
├── tests/
├── PROJECT.md                # This file
├── README.md
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
| Copilot | `sqlshift/assistant/copilot.py` | HF Inference API + fallback KB |
| Runbook | `sqlshift/intelligence/runbook.py` | Migration runbook markdown |
| Lineage viz | `sqlshift/intelligence/lineage_viz.py` | Plotly network graph |
| Rationalization | `sqlshift/intelligence/rationalization.py` | Workload action plan |

## CLI commands

```bash
pip install -e ".[dev,demo]"

sqlshift analyze ./examples/vertica_legacy --source vertica --target snowflake -o out/
sqlshift convert ./examples/vertica_legacy --source vertica --target dbt-snowflake --generate-dbt
sqlshift migrate ./examples/vertica_legacy --output migration-output/
python app.py   # Launch Gradio demo
pytest tests/ -v
```

## Hugging Face Space

- **Entry:** `app.py`
- **Config:** `README_HF_SPACE.md`
- **Model for copilot:** `Qwen/Qwen2.5-3B-Instruct` (env: `SQLSHIFTAI_MODEL`)
- **Token:** `HF_TOKEN` (auto-set on HF Spaces)
- **Deploy:** `bash scripts/deploy_hf.sh`

### Gradio tabs

1. **Migration Workbench** — upload zip or use sample, full pipeline
2. **Object Inspector** — single SQL assess + convert
3. **Migration Copilot** — LLM chat grounded in scan
4. **Reference** — capabilities overview

## Supported migration paths

| Phase | Source | Target | Status |
|-------|--------|--------|--------|
| 1 | Vertica | Snowflake / dbt | Full |
| 2 | Oracle, Redshift | Snowflake | Beta |
| 3 | Snowflake | BigQuery | Planned |

## Data models (`sqlshift/models.py`)

- `MigrationObject` — single discovered artifact with SQL, scores, conversion output
- `MigrationReport` — full scan result with objects, lineage, dashboard, validation
- `DashboardMetrics` — portfolio-level counts and percentages
- `Dialect` enum — vertica, oracle, snowflake, dbt-snowflake, etc.

## Translation engine notes

1. Vertica syntax stripped (SEGMENTED BY, PROJECTION, ON COMMIT PRESERVE ROWS)
2. Functions: `ZEROIFNULL(x)` → `COALESCE(x, 0)`
3. Date arithmetic: `col - 90` → `DATEADD(day, -90, col)`
4. Procedures → Snowflake `LANGUAGE SQL` with `:PARAM` bindings
5. sqlglot transpilation for DML/SELECT statements

## Known limitations (v0.2)

- Validation is simulated (no live DB connections)
- Cost estimates are heuristic
- Dynamic SQL / cursors always flagged for manual review
- Copilot requires HF Inference API (fallback KB when unavailable)

## Planned improvements

- [ ] Live source/target DB validation connectors
- [ ] Column-level lineage UI
- [ ] GitHub PR generation
- [ ] Airflow DAG migration
- [ ] Oracle PL/SQL deep support
- [ ] RAG over customer's full repo for copilot

## Git / release

- **GitHub:** https://github.com/dgvj-work/sql_shift_ai
- **Author:** Digvijay Waghela <digvijay.vaghela@yahoo.com>
- **License:** Apache 2.0
- **Version:** 0.2.0

## How to continue development

1. Read this file + `README.md`
2. Run `./scripts/run_local.sh` to verify setup
3. Core logic lives in `sqlshift/` — UI in `app.py` + `demo/`
4. Add tests in `tests/test_sqlshift.py`
5. Bump version in `sqlshift/__init__.py` and `pyproject.toml`
