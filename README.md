# MorphSQL

Convert Vertica / Oracle / Redshift / BigQuery / Snowflake SQL to **pandas** (notebook-ready), **Snowflake**, **BigQuery**, or **dbt**.

[![Space](https://img.shields.io/badge/🤗%20Space-MorphSQL-blue)](https://huggingface.co/spaces/dgvj-work/sqlshift-ai)
[![GitHub](https://img.shields.io/badge/GitHub-dgvj--work%2Fsql__shift__ai-blue)](https://github.com/dgvj-work/sql_shift_ai)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

Built for data scientists: convert → sample preview → download `.py`.

```python
from sqlshift.ai import pipeline
print(pipeline("sql-migration")("SELECT ZEROIFNULL(a) FROM t", source="vertica", target="pandas"))
```


---

## What makes this different from SQL converters

| Capability | SQL converters | MorphSQL |
|-----------|----------------|-------------|
| Single query translation | Yes | Yes |
| **Repository-level discovery** | No | Yes |
| **Dependency lineage graphs** | No | Yes |
| **Portfolio risk scoring** | Partial | Yes |
| **Workload rationalization** | No | Yes |
| **dbt project decomposition** | No | Yes |
| **Validation & reconciliation** | No | Yes |
| **Migration runbook generation** | No | Yes |
| **LLM copilot grounded in scan** | No | Yes |

---

## Quick start

```bash
git clone https://github.com/dgvj-work/sql_shift_ai.git
cd sql_shift_ai
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,demo]"

# Full local verification
./scripts/run_local.sh

# Launch interactive workbench
python app.py
```

### CLI

```bash
# Analyze repository
sqlshift analyze ./examples/vertica_legacy --source vertica --target snowflake -o report/

# Full migration pipeline
sqlshift migrate ./examples/vertica_legacy --output migration-output/
```

### Python SDK

```python
from sqlshift.pipeline import MigrationPipeline
from sqlshift.models import Dialect
from sqlshift.intelligence.runbook import generate_runbook

pipeline = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE)
report = pipeline.analyze("./examples/vertica_legacy")
report = pipeline.convert(report)
report = pipeline.validate(report)

print(generate_runbook(report))
```

---

## Platform capabilities

### 1. Migration Workbench
Scan zip files or directories containing SQL, stored procedures, views, and dbt models. Produces executive summary, object inventory, and portfolio metrics.

### 2. Dependency Lineage
Interactive Plotly graph of read/write dependencies across discovered objects.

### 3. Risk & Rationalization
Each object scored 0–100 with recommended action: migrate, review, rewrite, or retire.

### 4. Hybrid Translation
Deterministic rules (ZEROIFNULL, DATEADD, procedure wrappers) + sqlglot dialect transpilation.

### 5. dbt Architecture
Decomposes stored procedures into staging / intermediate / mart models with schema tests.

### 6. Validation Suite
Generates reconciliation checks: row counts, null rates, metric tolerance, structural compilation.

### 7. Migration Runbook
Phased cutover plan with object action table and validation checklist.

### 8. Migration Copilot
LLM advisor (Hugging Face Inference API) grounded in your scan context. Ask about cutover planning, lineage impact, dbt strategy, and platform behavior differences.

---

## Hugging Face deployment

```bash
huggingface-cli login
huggingface-cli repo create sql_shift_ai --type space --space_sdk gradio
bash scripts/deploy_hf.sh dgvj-work/sql_shift_ai
```

Set `HF_TOKEN` in Space secrets (automatic on HF). Optional: `SQLSHIFTAI_MODEL` to change copilot model.

---

## Project structure

```
sqlshift/           Core package
demo/               Gradio handlers + theme
app.py              Hugging Face Space entry
examples/           Sample Vertica legacy repo
PROJECT.md          AI/developer context handoff doc
tests/
```

**For AI continuation:** read [`PROJECT.md`](PROJECT.md) — contains full architecture, module map, and roadmap.

---

## Supported routes

| Source | Target | Status |
|--------|--------|--------|
| Vertica | Snowflake / dbt-snowflake | Supported |
| Vertica | BigQuery | Supported |
| Oracle | Snowflake / dbt-snowflake / BigQuery | Supported |
| Redshift | Snowflake / dbt-snowflake / BigQuery | Supported |
| BigQuery | Snowflake / dbt-snowflake | Supported |
| Snowflake | BigQuery | Supported |

---

## Author

Digvijay Waghela · digvijay.vaghela@yahoo.com · Apache 2.0
