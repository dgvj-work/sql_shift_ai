---
title: MorphSQL
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: "5.49.1"
python_version: "3.11"
app_file: app.py
pinned: true
license: apache-2.0
short_description: Upload SQL → pandas / PySpark / Snowflake / BigQuery / dbt + download
tags:
  - sql
  - pandas
  - pyspark
  - code
  - data-science
  - machine-learning
  - feature-extraction
  - snowflake
  - dbt
  - data-engineering
models:
  - dgvj-work/morphsql
datasets:
  - dgvj-work/vertica-snowflake-pairs
suggested_hardware: cpu-basic
---

# MorphSQL

Convert warehouse SQL → **pandas**, **PySpark**, Snowflake, BigQuery, or **dbt** — then **download** the result.

Package / CLI / Hub: `morphsql` · Space: [dgvj-work/morphsql](https://huggingface.co/spaces/dgvj-work/morphsql)

## How to use (30 seconds)

1. Open the **Convert** tab
2. Pick source dialect + **Convert to** target
3. Load an example, paste SQL, or **upload** a `.sql` / `.zip`
4. Click **Convert** or **Upload & Convert → Download**
5. Download the `.py` / `.sql` / `.zip` to your machine

| Target | Download |
|--------|----------|
| pandas / PySpark | `.py` ready for notebooks / Databricks |
| Snowflake / BigQuery | `.sql` |
| dbt | `.txt` project preview (or zip for batches) |

## Python API

```python
from morphsql.ai import pipeline

out = pipeline("sql-migration")(
    "SELECT COALESCE(a, 0) FROM t",
    source="snowflake",
    target="pandas",  # or "pyspark", "snowflake", "bigquery", "dbt-snowflake"
)
print(out["converted_sql"][:500])
```

## More tab

Object risk assess · repo workbench · ML feature SQL · copilot · dialect notes · offline eval

Author: Digvijay Waghela · Apache-2.0 · [GitHub](https://github.com/dgvj-work/morphsql)
