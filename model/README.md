---
language: en
license: apache-2.0
library_name: morphsql
pipeline_tag: text-classification
tags:
  - code
  - sql
  - agent
  - text-generation
  - text-classification
  - rag
  - sklearn
  - migration
  - snowflake
  - dbt
datasets:
  - dgvj-work/vertica-snowflake-pairs
metrics:
  - accuracy
---

# MorphSQL risk classifier

Small **TF-IDF + LogisticRegression** model that scores SQL migration risk (`low` / `medium` / `high`).

Used by **MorphSQL** ([Space](https://huggingface.co/spaces/dgvj-work/morphsql)).  
Python package import: `morphsql` (PyPI: `morphsql`).

## Files
| File | Purpose |
|------|---------|
| `risk_classifier.joblib` | sklearn pipeline |
| `rewrite_vocabulary.json` | common SQL rewrite map |
| `config.json` | dialects + metadata |

## Usage

```python
from huggingface_hub import hf_hub_download
import joblib

path = hf_hub_download(repo_id="dgvj-work/morphsql", filename="risk_classifier.joblib")
clf = joblib.load(path)
print(clf.predict(["EXECUTE IMMEDIATE 'SELECT 1'"]))
```

```python
from morphsql.ai import pipeline
print(pipeline("sql-risk-classification")("CREATE PROCEDURE p AS BEGIN NULL; END;"))
print(pipeline("sql-migration")("SELECT ZEROIFNULL(a) FROM t"))
```

## Links
- Space: https://huggingface.co/spaces/dgvj-work/morphsql
- Dataset: https://huggingface.co/datasets/dgvj-work/vertica-snowflake-pairs
- GitHub: https://github.com/dgvj-work/morphsql

Author: Digvijay Waghela · Apache-2.0
