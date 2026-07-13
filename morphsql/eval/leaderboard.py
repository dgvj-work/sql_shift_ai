"""Simple local leaderboard for conversion quality scores."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LEADERBOARD_PATH = Path(__file__).resolve().parent.parent.parent / "datasets" / "leaderboard.json"


def load_leaderboard() -> list[dict]:
    if not LEADERBOARD_PATH.exists():
        return []
    try:
        return json.loads(LEADERBOARD_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def submit_score(
    name: str,
    exact_match: float,
    token_f1: float,
    fuzzy: float,
    pass_rate: float,
    n_pairs: int,
    notes: str = "",
) -> list[dict]:
    board = load_leaderboard()
    entry = {
        "name": (name or "anonymous").strip()[:64],
        "exact_match": round(float(exact_match), 4),
        "token_f1": round(float(token_f1), 4),
        "fuzzy": round(float(fuzzy), 4),
        "pass_rate": round(float(pass_rate), 4),
        "n_pairs": int(n_pairs),
        "notes": (notes or "").strip()[:200],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    board.append(entry)
    board.sort(key=lambda e: (e.get("pass_rate", 0), e.get("token_f1", 0)), reverse=True)
    board = board[:50]
    LEADERBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEADERBOARD_PATH.write_text(json.dumps(board, indent=2), encoding="utf-8")
    return board


def format_leaderboard_md(board: list[dict] | None = None) -> str:
    board = board if board is not None else load_leaderboard()
    if not board:
        return (
            "### Leaderboard\n\n"
            "No scores yet. Run **Eval Suite**, then submit a score."
        )
    lines = [
        "### Leaderboard",
        "",
        "| Rank | Name | Pass rate | Token F1 | Exact | Pairs |",
        "|------|------|-----------|----------|-------|-------|",
    ]
    for i, e in enumerate(board[:20], 1):
        lines.append(
            f"| {i} | {e.get('name', '?')} | {100 * e.get('pass_rate', 0):.1f}% "
            f"| {100 * e.get('token_f1', 0):.1f}% | {100 * e.get('exact_match', 0):.1f}% "
            f"| {e.get('n_pairs', 0)} |"
        )
    return "\n".join(lines)
