# MorphSQL

Convert Vertica / Oracle / Redshift / BigQuery / Snowflake SQL to **pandas** or **PySpark** (notebook-ready), **Snowflake**, **BigQuery**, or **dbt**.

[![Space](https://img.shields.io/badge/🤗%20Space-MorphSQL-blue)](https://huggingface.co/spaces/dgvj-work/morphsql)
[![GitHub](https://img.shields.io/badge/GitHub-dgvj--work%2Fmorphsql-blue)](https://github.com/dgvj-work/morphsql)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://python.org)

Built for data scientists: upload or paste SQL → convert → sample preview → download `.py` / `.sql`.

## Naming

| Layer | Name |
|-------|------|
| **Product** | **MorphSQL** |
| Python import / CLI / PyPI | `morphsql` |
| Hugging Face Space / model | `dgvj-work/morphsql` |
| GitHub | `dgvj-work/morphsql` (rename from `sql_shift_ai` if still pending) |

```python
from morphsql.ai import pipeline
print(pipeline("sql-migration")("SELECT COALESCE(a, 0) FROM t", source="snowflake", target="pandas"))
print(pipeline("sql-migration")("SELECT COALESCE(a, 0) FROM t", source="snowflake", target="pyspark"))
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
git clone https://github.com/dgvj-work/morphsql.git
cd morphsql
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
morphsql analyze ./examples/vertica_legacy --source vertica --target snowflake -o report/

# Full migration pipeline
morphsql migrate ./examples/vertica_legacy --output migration-output/
```

### Python SDK

```python
from morphsql.pipeline import MigrationPipeline
from morphsql.models import Dialect
from morphsql.intelligence.runbook import generate_runbook

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
# one-time
pip install -U "huggingface_hub[cli]"
hf auth login

# create the Space once in the UI (Gradio SDK) or:
#   hf repo create morphsql --type space --space_sdk gradio --organization dgvj-work

# deploy Space + model + dataset
./scripts/deploy_hf.sh
# → https://huggingface.co/spaces/dgvj-work/morphsql
```

**One-time Hub setup (if not done yet)**
1. GitHub: Settings → General → Repository name → rename `sql_shift_ai` → `morphsql`
2. Hugging Face: create Gradio Space + model repos named `morphsql` under `dgvj-work`, then run `./scripts/deploy_hf.sh`

Preflight only (no upload):

```bash
python scripts/check_space.py
```

The Space card / metadata lives in `README_HF_SPACE.md` (copied to Space `README.md` on deploy).
Set `HF_TOKEN` in Space secrets (automatic on HF). Optional: `MORPHSQL_MODEL` to change the copilot model.

---

## Project structure

```
morphsql/           Core package
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
