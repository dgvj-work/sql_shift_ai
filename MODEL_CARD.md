---
language: en
license: apache-2.0
library_name: sqlshift-ai
# Product name on the Hub UI / Space: MorphSQL
pipeline_tag: text-classification
tags:
  - morphsql
  - agent
  - code
  - sql
  - text-generation
  - text-classification
  - rag
  - sklearn
  - migration
  - dbt
  - snowflake
datasets:
  - dgvj-work/vertica-snowflake-pairs
---

# MorphSQL

Convert Vertica / Oracle / Redshift / BigQuery SQL to **pandas**, **PySpark**, Snowflake, BigQuery, or dbt.

> Brand: **MorphSQL** · Package import: `sqlshift` · Hub slug: `dgvj-work/sqlshift-ai`

## Artifacts
- `risk_classifier.joblib` — migration risk (`low` / `medium` / `high`)
- `rewrite_vocabulary.json` — rewrite lexicon
- `config.json` — dialect metadata

## Quick start

```python
from sqlshift.ai import pipeline

print(pipeline("sql-migration")("SELECT COALESCE(a, 0) FROM t", source="snowflake", target="pandas"))
print(pipeline("sql-migration")("SELECT COALESCE(a, 0) FROM t", source="snowflake", target="pyspark"))
print(pipeline("sql-risk-classification")("EXECUTE IMMEDIATE 'x'"))
```

## Demo
https://huggingface.co/spaces/dgvj-work/sqlshift-ai

Author: Digvijay Waghela · Apache-2.0
