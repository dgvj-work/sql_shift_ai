---
language: en
license: apache-2.0
library_name: sqlshift-ai
pipeline_tag: text2text-generation
tags:
  - sql
  - code
  - agent
  - agents
  - llm
  - rag
  - migration
  - snowflake
  - dbt
  - evaluation
  - feature-engineering
  - text-generation
datasets:
  - dgvj-work/vertica-snowflake-pairs
---

# SQLShiftAI — SQL Migration Agent

## Model card (hybrid agent + upcoming LoRA)

**SQLShiftAI** is an AI-powered **SQL Migration Agent** for warehouse modernization. It combines:

1. **Deterministic hybrid codegen** (rules + sqlglot) for trustworthy conversions  
2. **Behavior RAG** over a platform-difference knowledge base  
3. **Optional Hugging Face Inference LLM** copilot  
4. **Eval harness** (exact match, token F1, fuzzy) on a public pair dataset  
5. **dbt project emission** for architecture-ready outputs  
6. **ML feature SQL** path for DS/ML feature marts  

### Intended users
- ML / DS engineers migrating feature & label SQL  
- Data engineers modernizing Vertica / Oracle / Redshift / BigQuery → Snowflake / dbt  
- Researchers benchmarking SQL migration / code translation  

### Dataset
[`dgvj-work/vertica-snowflake-pairs`](https://huggingface.co/datasets/dgvj-work/vertica-snowflake-pairs) — curated + synthetic `source_sql` / `target_sql` pairs including `ml_feature` category.

### LoRA roadmap
The hybrid engine is production-default (high precision). A **Code LLM LoRA** fine-tuned on the pair dataset is the next Hub model release for soft / free-form SQL rewrites. Until then, this card documents the agent + eval stack.

### How to use (Space)
Open **Agent Demo** → Run agent. Or:

```bash
pip install sqlshift-ai
python app.py
```

### Eval
```python
from sqlshift.eval import run_eval, ensure_pairs_file
ensure_pairs_file()
results, summary = run_eval(limit=50)
print(summary["token_f1"], summary["pass_rate"])
```

### Citation
```bibtex
@software{sqlshiftai2026,
  title={SQLShiftAI: SQL Migration Agent},
  author={Digvijay Waghela},
  year={2026},
  url={https://github.com/dgvj-work/sql_shift_ai}
}
```
