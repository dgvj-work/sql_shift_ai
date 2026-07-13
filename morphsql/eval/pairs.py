"""Generate and load Vertica ↔ Snowflake SQL migration pairs for HF dataset + evals."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "datasets"
PAIRS_PATH = DATA_DIR / "vertica_snowflake_pairs.jsonl"


TEMPLATES: list[dict] = [
    {
        "id": "zeroifnull_basic",
        "category": "function",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": "SELECT ZEROIFNULL(amount) AS amount FROM staging.orders",
        "target_sql": "SELECT COALESCE(amount, 0) AS amount FROM staging.orders",
        "notes": "ZEROIFNULL → COALESCE(expr, 0)",
    },
    {
        "id": "nvl_basic",
        "category": "function",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": "SELECT NVL(discount, 0) AS discount FROM staging.orders",
        "target_sql": "SELECT COALESCE(discount, 0) AS discount FROM staging.orders",
        "notes": "NVL → COALESCE",
    },
    {
        "id": "date_sub_days",
        "category": "date",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": "SELECT * FROM t WHERE order_date >= CURRENT_DATE - 30",
        "target_sql": "SELECT * FROM t WHERE order_date >= DATEADD(day, -30, CURRENT_DATE)",
        "notes": "Date arithmetic → DATEADD",
    },
    {
        "id": "local_temp",
        "category": "ddl",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": "CREATE LOCAL TEMP TABLE tmp_x ON COMMIT PRESERVE ROWS AS SELECT 1 AS id",
        "target_sql": "CREATE OR REPLACE TEMPORARY TABLE tmp_x AS SELECT 1 AS id",
        "notes": "LOCAL TEMP → TEMPORARY TABLE",
    },
    {
        "id": "string_agg",
        "category": "aggregate",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": "SELECT STRING_AGG(name, ',') FROM users",
        "target_sql": "SELECT LISTAGG(name, ',') FROM users",
        "notes": "STRING_AGG → LISTAGG",
    },
    {
        "id": "approx_distinct",
        "category": "aggregate",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": "SELECT APPROXIMATE_COUNT_DISTINCT(user_id) FROM events",
        "target_sql": "SELECT APPROX_COUNT_DISTINCT(user_id) FROM events",
        "notes": "APPROXIMATE_COUNT_DISTINCT → APPROX_COUNT_DISTINCT",
    },
    {
        "id": "datediff_quoted",
        "category": "date",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": "SELECT DATEDIFF('day', start_dt, end_dt) FROM t",
        "target_sql": "SELECT DATEDIFF(day, start_dt, end_dt) FROM t",
        "notes": "Quoted DATEDIFF unit → unquoted",
    },
    {
        "id": "sysdate",
        "category": "function",
        "source_dialect": "oracle",
        "target_dialect": "snowflake",
        "source_sql": "SELECT SYSDATE FROM dual",
        "target_sql": "SELECT CURRENT_TIMESTAMP()",
        "notes": "SYSDATE + drop DUAL",
    },
    {
        "id": "getdate_redshift",
        "category": "function",
        "source_dialect": "redshift",
        "target_dialect": "snowflake",
        "source_sql": "SELECT GETDATE(), NVL(x, 0) FROM t",
        "target_sql": "SELECT CURRENT_TIMESTAMP(), COALESCE(x, 0) FROM t",
        "notes": "GETDATE/NVL mappings",
    },
    {
        "id": "bigquery_ifnull",
        "category": "function",
        "source_dialect": "bigquery",
        "target_dialect": "snowflake",
        "source_sql": "SELECT IFNULL(a, 0), STRING_AGG(b, ',') FROM t GROUP BY a",
        "target_sql": "SELECT COALESCE(a, 0), LISTAGG(b, ',') FROM t GROUP BY a",
        "notes": "IFNULL/STRING_AGG → COALESCE/LISTAGG",
    },
    {
        "id": "feature_rfm",
        "category": "ml_feature",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": (
            "SELECT customer_id, "
            "ZEROIFNULL(SUM(order_amount)) AS monetary, "
            "COUNT(DISTINCT order_id) AS frequency, "
            "DATEDIFF('day', MAX(order_date), CURRENT_DATE) AS recency "
            "FROM staging.orders GROUP BY customer_id"
        ),
        "target_sql": (
            "SELECT customer_id, "
            "COALESCE(SUM(order_amount), 0) AS monetary, "
            "COUNT(DISTINCT order_id) AS frequency, "
            "DATEDIFF(day, MAX(order_date), CURRENT_DATE) AS recency "
            "FROM staging.orders GROUP BY customer_id"
        ),
        "notes": "ML RFM feature SQL migration",
    },
    {
        "id": "feature_label",
        "category": "ml_feature",
        "source_dialect": "vertica",
        "target_dialect": "snowflake",
        "source_sql": (
            "SELECT user_id, "
            "CASE WHEN ZEROIFNULL(churn_score) > 0.7 THEN 1 ELSE 0 END AS churn_label "
            "FROM ml.user_scores"
        ),
        "target_sql": (
            "SELECT user_id, "
            "CASE WHEN COALESCE(churn_score, 0) > 0.7 THEN 1 ELSE 0 END AS churn_label "
            "FROM ml.user_scores"
        ),
        "notes": "Training label feature SQL",
    },
]


def _expand_pairs() -> list[dict]:
    """Expand templates into a larger eval/dataset corpus."""
    pairs = [dict(p) for p in TEMPLATES]
    # Parametric expansions for volume (HF dataset appeal)
    for days in (7, 14, 30, 60, 90, 180, 365):
        pairs.append(
            {
                "id": f"date_sub_{days}",
                "category": "date",
                "source_dialect": "vertica",
                "target_dialect": "snowflake",
                "source_sql": f"SELECT * FROM events WHERE event_date >= CURRENT_DATE - {days}",
                "target_sql": (
                    f"SELECT * FROM events WHERE event_date >= DATEADD(day, -{days}, CURRENT_DATE)"
                ),
                "notes": f"CURRENT_DATE - {days} → DATEADD",
            }
        )
    for col in ("amount", "revenue", "fee", "tax", "balance", "score", "qty"):
        pairs.append(
            {
                "id": f"zeroifnull_{col}",
                "category": "function",
                "source_dialect": "vertica",
                "target_dialect": "snowflake",
                "source_sql": f"SELECT ZEROIFNULL({col}) AS {col} FROM staging.facts",
                "target_sql": f"SELECT COALESCE({col}, 0) AS {col} FROM staging.facts",
                "notes": "ZEROIFNULL expansion",
            }
        )
    for i in range(1, 81):
        pairs.append(
            {
                "id": f"agg_mix_{i}",
                "category": "aggregate",
                "source_dialect": "vertica",
                "target_dialect": "snowflake",
                "source_sql": (
                    f"SELECT dim_{i % 5}, ZEROIFNULL(SUM(metric_{i})), "
                    f"APPROXIMATE_COUNT_DISTINCT(user_id) "
                    f"FROM fact_{i % 3} GROUP BY 1"
                ),
                "target_sql": (
                    f"SELECT dim_{i % 5}, COALESCE(SUM(metric_{i}), 0), "
                    f"APPROX_COUNT_DISTINCT(user_id) "
                    f"FROM fact_{i % 3} GROUP BY 1"
                ),
                "notes": "Synthetic aggregate pair",
            }
        )
    for i in range(1, 61):
        pairs.append(
            {
                "id": f"oracle_nvl_{i}",
                "category": "function",
                "source_dialect": "oracle",
                "target_dialect": "snowflake",
                "source_sql": f"SELECT NVL(col_{i}, 0) FROM dual",
                "target_sql": f"SELECT COALESCE(col_{i}, 0)",
                "notes": "Oracle NVL expansion",
            }
        )
    for i in range(1, 51):
        pairs.append(
            {
                "id": f"ml_feature_{i}",
                "category": "ml_feature",
                "source_dialect": "vertica",
                "target_dialect": "snowflake",
                "source_sql": (
                    f"SELECT entity_id, ZEROIFNULL(AVG(feature_{i})) AS f_{i} "
                    f"FROM ml.training_window WHERE ds >= CURRENT_DATE - {7 + i} "
                    f"GROUP BY 1"
                ),
                "target_sql": (
                    f"SELECT entity_id, COALESCE(AVG(feature_{i}), 0) AS f_{i} "
                    f"FROM ml.training_window WHERE ds >= DATEADD(day, -{7 + i}, CURRENT_DATE) "
                    f"GROUP BY 1"
                ),
                "notes": "ML feature window SQL",
            }
        )
    # AI / LLM-eval oriented paraphrases
    for i in range(1, 41):
        pairs.append(
            {
                "id": f"ai_codegen_{i}",
                "category": "function",
                "source_dialect": "vertica",
                "target_dialect": "snowflake",
                "source_sql": (
                    f"SELECT ZEROIFNULL(score_{i}), NVL(flag_{i}, 0) "
                    f"FROM ml.inference_logs WHERE run_id = {i}"
                ),
                "target_sql": (
                    f"SELECT COALESCE(score_{i}, 0), COALESCE(flag_{i}, 0) "
                    f"FROM ml.inference_logs WHERE run_id = {i}"
                ),
                "notes": "AI inference-log SQL pair",
            }
        )
    return pairs


def ensure_pairs_file() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pairs = _expand_pairs()
    with PAIRS_PATH.open("w", encoding="utf-8") as fh:
        for row in pairs:
            fh.write(json.dumps(row) + "\n")
    return PAIRS_PATH


def load_pairs(limit: int | None = None) -> list[dict]:
    if not PAIRS_PATH.exists():
        ensure_pairs_file()
    rows: list[dict] = []
    with PAIRS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


if __name__ == "__main__":
    path = ensure_pairs_file()
    print(f"Wrote {len(load_pairs())} pairs → {path}")
