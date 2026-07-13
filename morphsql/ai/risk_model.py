"""Train and load the SQL migration risk classifier (downloadable HF model artifact)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline as SkPipeline

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "model"
MODEL_PATH = MODEL_DIR / "risk_classifier.joblib"
CONFIG_PATH = MODEL_DIR / "config.json"

LABELS = ["low", "medium", "high"]


def _synthetic_corpus() -> tuple[list[str], list[str]]:
    """Build labeled SQL snippets for a lightweight risk classifier."""
    texts: list[str] = []
    labels: list[str] = []

    low = [
        "SELECT a, b FROM t",
        "SELECT COUNT(*) FROM orders WHERE dt = CURRENT_DATE",
        "SELECT COALESCE(x, 0) FROM staging.facts",
        "CREATE VIEW v AS SELECT id FROM customers",
        "SELECT * FROM users LIMIT 100",
    ]
    medium = [
        "SELECT ZEROIFNULL(amount) FROM t WHERE d >= CURRENT_DATE - 30",
        "WITH cte AS (SELECT * FROM a JOIN b ON a.id=b.id) SELECT * FROM cte",
        "SELECT STRING_AGG(name, ',') FROM users GROUP BY dept",
        "CREATE LOCAL TEMP TABLE tmp AS SELECT * FROM staging.x",
        "SELECT NVL(a,0), SYSDATE FROM dual",
    ]
    high = [
        "CREATE OR REPLACE PROCEDURE p(load_date DATE) AS $$ BEGIN "
        "EXECUTE IMMEDIATE 'SELECT 1'; OPEN cur FOR SELECT * FROM t; "
        "EXCEPTION WHEN OTHERS THEN NULL; END; $$;",
        "CREATE PACKAGE pkg AS PROCEDURE run; END;",
        "MERGE INTO tgt USING src ON tgt.id=src.id WHEN MATCHED THEN UPDATE "
        "WHEN NOT MATCHED THEN INSERT VALUES (src.id)",
        "SELECT * FROM t START WITH id=1 CONNECT BY PRIOR id = parent_id",
        "CREATE OR REPLACE PROCEDURE sp AS $$ BEGIN "
        "FOR r IN cur LOOP EXECUTE IMMEDIATE dyn; END LOOP; END; $$;",
    ]

    for i in range(40):
        for s in low:
            texts.append(f"{s} -- sample {i}")
            labels.append("low")
        for s in medium:
            texts.append(f"{s} /* var {i} */")
            labels.append("medium")
        for s in high:
            texts.append(f"{s}\n-- complexity {i}")
            labels.append("high")

    # Extra keyword-heavy highs
    for kw in ("CURSOR", "EXECUTE IMMEDIATE", "CONNECT BY", "PACKAGE", "EXCEPTION WHEN"):
        for i in range(20):
            texts.append(f"SELECT 1 FROM t -- {kw} marker {i}")
            labels.append("high" if kw != "SELECT" else "low")

    return texts, labels


def train_and_save(model_dir: Path | None = None, *, force: bool = False) -> Path:
    global _risk_singleton
    model_dir = Path(model_dir or MODEL_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)
    out = model_dir / "risk_classifier.joblib"
    if out.exists() and not force:
        return out
    texts, labels = _synthetic_corpus()
    clf = SkPipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=2,
                    max_features=12000,
                ),
            ),
            (
                "lr",
                LogisticRegression(
                    max_iter=400,
                    class_weight="balanced",
                ),
            ),
        ]
    )
    clf.fit(texts, labels)
    joblib.dump(clf, model_dir / "risk_classifier.joblib")

    # Export rewrite rule “weights” as a downloadable JSON artifact
    from morphsql.translator.engine import VERTICA_SYNTAX_REPLACEMENTS

    rules = {
        "model_type": "morphsql-agent",
        "product_name": "MorphSQL",
        "task": "text-classification",
        "labels": LABELS,
        "version": "0.4.0",
        "description": "TF-IDF + LogisticRegression risk classifier for MorphSQL",
        "vertica_syntax_patterns": [p for p, _ in VERTICA_SYNTAX_REPLACEMENTS],
        "supported_sources": ["vertica", "oracle", "redshift", "bigquery", "snowflake"],
        "supported_targets": ["pandas", "pyspark", "snowflake", "dbt-snowflake", "bigquery"],
    }
    (model_dir / "config.json").write_text(json.dumps(rules, indent=2), encoding="utf-8")
    (model_dir / "rewrite_vocabulary.json").write_text(
        json.dumps(
            {
                "ZEROIFNULL": "COALESCE(expr, 0)",
                "NVL": "COALESCE",
                "ISNULL": "COALESCE",
                "STRING_AGG": "LISTAGG",
                "APPROXIMATE_COUNT_DISTINCT": "APPROX_COUNT_DISTINCT",
                "GETDATE": "CURRENT_TIMESTAMP()",
                "SYSDATE": "CURRENT_TIMESTAMP()",
                "IFNULL": "COALESCE",
                "IFF": "IF",
                "LISTAGG": "STRING_AGG",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _risk_singleton = None
    return model_dir / "risk_classifier.joblib"


def _load_compatible_model(path: Path):
    """Load the classifier, retraining when sklearn pickle versions disagree."""
    if not path.exists():
        train_and_save(path.parent)
    try:
        model = joblib.load(path)
        model.predict_proba(["SELECT 1"])
        return model
    except Exception:
        train_and_save(path.parent, force=True)
        return joblib.load(path)


class MigrationRiskModel:
    """Loadable AI risk head used by the agent and HF model repo."""

    def __init__(self, model_path: Path | None = None):
        path = Path(model_path or MODEL_PATH)
        self.model = _load_compatible_model(path)
        self.labels = LABELS

    def predict(self, sql: str) -> dict:
        sql = sql or ""
        proba = self.model.predict_proba([sql])[0]
        classes = list(self.model.classes_)
        idx = int(np.argmax(proba))
        label = classes[idx]
        # Heuristic boost for known hard patterns
        hard = bool(
            re.search(
                r"EXECUTE\s+IMMEDIATE|\bCURSOR\b|CONNECT\s+BY|\bPACKAGE\b|EXCEPTION\s+WHEN",
                sql,
                re.I,
            )
        )
        if hard and label != "high":
            label = "high"
            proba = np.array([0.05, 0.15, 0.80])
            classes = LABELS
            idx = 2
        return {
            "label": str(label),
            "score": float(proba[idx]),
            "scores": {str(c): float(p) for c, p in zip(classes, proba)},
        }


_risk_singleton: MigrationRiskModel | None = None


def get_risk_model() -> MigrationRiskModel:
    global _risk_singleton
    if _risk_singleton is None:
        _risk_singleton = MigrationRiskModel()
    return _risk_singleton
