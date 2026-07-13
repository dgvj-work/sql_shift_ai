"""Translation quality metrics for SQL migration eval."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sqlshift.eval.pairs import load_pairs
from sqlshift.models import Dialect
from sqlshift.translator.engine import translate_sql


def _normalize_sql(sql: str) -> str:
    sql = sql.lower().strip()
    sql = re.sub(r"--.*?$", "", sql, flags=re.M)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    sql = re.sub(r"\s+", " ", sql)
    sql = sql.replace(";", "")
    return sql.strip()


def _tokens(sql: str) -> list[str]:
    return re.findall(r"[a-z_][a-z0-9_]*|\d+|[=<>!()*,.]", _normalize_sql(sql))


def exact_match(pred: str, gold: str) -> float:
    return 1.0 if _normalize_sql(pred) == _normalize_sql(gold) else 0.0


def token_f1(pred: str, gold: str) -> float:
    p, g = _tokens(pred), _tokens(gold)
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    from collections import Counter

    pc, gc = Counter(p), Counter(g)
    overlap = sum((pc & gc).values())
    precision = overlap / max(sum(pc.values()), 1)
    recall = overlap / max(sum(gc.values()), 1)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def fuzzy_ratio(pred: str, gold: str) -> float:
    """Character-level Dice coefficient on normalized SQL."""
    a, b = _normalize_sql(pred), _normalize_sql(gold)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # bigram Dice
    def bigrams(s: str) -> set[str]:
        if len(s) < 2:
            return {s}
        return {s[i : i + 2] for i in range(len(s) - 1)}

    ba, bb = bigrams(a), bigrams(b)
    return 2 * len(ba & bb) / max(len(ba) + len(bb), 1)


@dataclass
class EvalResult:
    pair_id: str
    category: str
    source_dialect: str
    target_dialect: str
    exact_match: float
    token_f1: float
    fuzzy: float
    passed: bool
    predicted: str
    gold: str


def llm_judge_optional(pred: str, gold: str, source_sql: str) -> float | None:
    """Optional LLM-as-judge via HF Inference when HF_TOKEN is set. Returns 0..1 or None."""
    import os

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if not token:
        return None
    try:
        from huggingface_hub import InferenceClient

        client = InferenceClient(token=token)
        prompt = (
            "Score SQL migration quality from 0 to 1. Reply with ONLY a number.\n"
            f"Source:\n{source_sql[:800]}\n\nGold:\n{gold[:800]}\n\nPred:\n{pred[:800]}\n"
        )
        text = client.text_generation(
            prompt,
            model=os.getenv(
                "MORPHSQL_MODEL",
                os.getenv("SQLSHIFTAI_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
            ),
            max_new_tokens=8,
        )
        import re

        m = re.search(r"0?\.\d+|1(?:\.0+)?|0", str(text))
        if not m:
            return None
        return max(0.0, min(1.0, float(m.group(0))))
    except Exception:
        return None


def run_eval(
    limit: int | None = None,
    categories: list[str] | None = None,
) -> tuple[list[EvalResult], dict]:
    """Run translator against gold pairs and return rows + aggregate metrics."""
    pairs = load_pairs(limit=limit)
    if categories:
        cats = {c.lower() for c in categories}
        pairs = [p for p in pairs if p.get("category", "").lower() in cats]

    results: list[EvalResult] = []
    for pair in pairs:
        try:
            source = Dialect(pair["source_dialect"])
            target = Dialect(pair["target_dialect"])
        except Exception:
            continue
        predicted, _, _, _ = translate_sql(pair["source_sql"], source, target)
        em = exact_match(predicted, pair["target_sql"])
        f1 = token_f1(predicted, pair["target_sql"])
        fuzzy = fuzzy_ratio(predicted, pair["target_sql"])
        # Pass if exact or strong fuzzy/token agreement
        passed = em >= 1.0 or (f1 >= 0.85 and fuzzy >= 0.75)
        results.append(
            EvalResult(
                pair_id=pair["id"],
                category=pair.get("category", "unknown"),
                source_dialect=pair["source_dialect"],
                target_dialect=pair["target_dialect"],
                exact_match=em,
                token_f1=f1,
                fuzzy=fuzzy,
                passed=passed,
                predicted=predicted,
                gold=pair["target_sql"],
            )
        )

    n = max(len(results), 1)
    summary = {
        "n_pairs": len(results),
        "exact_match": sum(r.exact_match for r in results) / n,
        "token_f1": sum(r.token_f1 for r in results) / n,
        "fuzzy": sum(r.fuzzy for r in results) / n,
        "pass_rate": sum(1 for r in results if r.passed) / n,
        "by_category": {},
    }
    cats: dict[str, list[EvalResult]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)
    for cat, rows in cats.items():
        m = max(len(rows), 1)
        summary["by_category"][cat] = {
            "n": len(rows),
            "exact_match": sum(x.exact_match for x in rows) / m,
            "token_f1": sum(x.token_f1 for x in rows) / m,
            "pass_rate": sum(1 for x in rows if x.passed) / m,
        }
    return results, summary


def results_to_dicts(results: list[EvalResult], limit: int = 40) -> list[dict]:
    return [asdict(r) for r in results[:limit]]
