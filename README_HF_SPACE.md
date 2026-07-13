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
short_description: SQL → pandas for data scientists (also Snowflake, BigQuery, dbt)
tags:
  - sql
  - pandas
  - code
  - data-science
  - snowflake
  - dbt
  - data-engineering
models:
  - dgvj-work/sqlshift-ai
datasets:
  - dgvj-work/vertica-snowflake-pairs
suggested_hardware: cpu-basic
---

# MorphSQL

**SQL → pandas** for data scientists — plus Snowflake / BigQuery / dbt when you need warehouse output.

## Try
1. Open **Convert**
2. Load a DS example (or paste SQL)
3. See code + **sample preview** + download `.py`

```python
from sqlshift.ai import pipeline
print(pipeline("sql-migration")(
    "SELECT ZEROIFNULL(a) FROM t",
    source="vertica",
    target="pandas",
))
```

Author: Digvijay Waghela · Apache-2.0
