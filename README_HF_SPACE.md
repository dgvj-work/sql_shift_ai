---
title: SQLShiftAI
emoji: robot
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: "4.44.0"
app_file: app.py
pinned: true
license: apache-2.0
short_description: SQL Migration Agent — LLM tools, hybrid codegen, RAG, evals, dbt
tags:
  - agent
  - agents
  - llm
  - code
  - text-generation
  - sql
  - migration
  - dbt
  - snowflake
  - rag
  - evaluation
  - data-science
  - machine-learning
  - feature-engineering
---

# SQLShiftAI — SQL Migration Agent

**Not a toy SQL converter.** Hybrid rules + sqlglot + behavior RAG + optional Hugging Face LLM that converts legacy warehouse SQL, scores risk, and can emit a **dbt project**.

## Try in 30 seconds
1. Open **Agent Demo**
2. Click **Run agent** on the sample Vertica SQL
3. See conversion, explanation, RAG hits, confidence

## Tabs
| Tab | What it is |
|-----|------------|
| Agent Demo | One-shot convert + explain + RAG |
| Eval & Leaderboard | Exact / token F1 / fuzzy on pair dataset |
| Behavior RAG | Retrieve NULL/timezone/MERGE diffs |
| ML Feature SQL | Feature/label SQL → Snowflake / dbt mart |
| Object Inspector | Deep single-object conversion |
| Migration Workbench | Repo scan, lineage, runbook |
| Migration Copilot | Grounded HF Inference advisor |

## Dataset
Bundled pairs: `datasets/vertica_snowflake_pairs.jsonl`  
Publish: `python scripts/publish_dataset.py --repo <user>/vertica-snowflake-pairs`

## Stack
- Hybrid deterministic translation (trustworthy codegen)
- sqlglot dialect matrix
- Behavior knowledge RAG (keyword; sentence-transformers optional)
- Eval harness for ML-style metrics
- Optional `HF_TOKEN` for Inference API copilot
