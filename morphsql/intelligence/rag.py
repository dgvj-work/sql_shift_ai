"""RAG over platform behavior knowledge base (embeddings optional)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from morphsql.knowledge.behavior import BEHAVIOR_DIFFERENCES, BehaviorDifference


@dataclass
class RetrievedDoc:
    name: str
    score: float
    source_platform: str
    target_platform: str
    description: str
    recommendation: str
    severity: str


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 2}


def _keyword_score(query: str, doc: BehaviorDifference) -> float:
    q = _tokenize(query)
    if not q:
        return 0.0
    blob = " ".join(
        [
            doc.name,
            doc.description,
            doc.impact,
            doc.recommendation,
            doc.source_platform,
            doc.target_platform,
            doc.detection_pattern,
        ]
    )
    d = _tokenize(blob)
    if not d:
        return 0.0
    overlap = len(q & d)
    return overlap / math.sqrt(len(q) * len(d))


class BehaviorRAG:
    """Retrieve relevant behavior diffs for a natural-language or SQL query."""

    def __init__(self):
        self._embeddings = None
        self._matrix = None
        self._docs = list(BEHAVIOR_DIFFERENCES)
        self._backend = "keyword"

    def _try_load_embeddings(self) -> None:
        if self._embeddings is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np

            model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            texts = [
                f"{d.name}. {d.description}. {d.recommendation}. "
                f"{d.source_platform} to {d.target_platform}."
                for d in self._docs
            ]
            self._matrix = model.encode(texts, normalize_embeddings=True)
            self._embeddings = model
            self._backend = "sentence-transformers"
            _ = np  # silence unused if encode returns list
        except Exception:
            self._embeddings = False
            self._backend = "keyword"

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        source: str | None = None,
        target: str | None = None,
    ) -> list[RetrievedDoc]:
        query = (query or "").strip()
        if not query:
            return []

        self._try_load_embeddings()
        docs = self._docs
        if source:
            docs = [d for d in docs if d.source_platform == source]
        if target:
            # accept snowflake for dbt-snowflake
            tgt = "snowflake" if target.startswith("dbt") else target
            docs = [d for d in docs if d.target_platform == tgt]
        if not docs:
            docs = self._docs

        scored: list[tuple[float, BehaviorDifference]] = []
        if self._backend == "sentence-transformers" and self._embeddings and self._matrix is not None:
            import numpy as np

            q = self._embeddings.encode([query], normalize_embeddings=True)[0]
            # map filtered docs back to indices
            idx_map = {id(d): i for i, d in enumerate(self._docs)}
            for d in docs:
                i = idx_map.get(id(d))
                if i is None:
                    continue
                score = float(np.dot(self._matrix[i], q))
                scored.append((score, d))
        else:
            for d in docs:
                scored.append((_keyword_score(query, d), d))

        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[RetrievedDoc] = []
        for score, d in scored[:top_k]:
            if score <= 0 and self._backend == "keyword":
                continue
            out.append(
                RetrievedDoc(
                    name=d.name,
                    score=round(score, 4),
                    source_platform=d.source_platform,
                    target_platform=d.target_platform,
                    description=d.description,
                    recommendation=d.recommendation,
                    severity=d.severity,
                )
            )
        return out

    def answer(self, query: str, source: str = "vertica", target: str = "snowflake") -> str:
        hits = self.retrieve(query, top_k=5, source=source, target=target)
        if not hits:
            hits = self.retrieve(query, top_k=5)
        lines = [
            f"### Behavior RAG ({self._backend})",
            "",
            f"**Query:** {query}",
            f"**Route filter:** {source} → {target}",
            "",
        ]
        if not hits:
            lines.append("No matching behavior differences found. Try keywords like NULL, timezone, ROWNUM, MERGE.")
            return "\n".join(lines)
        for i, h in enumerate(hits, 1):
            lines.append(
                f"**{i}. [{h.severity.upper()}] {h.name}** "
                f"({h.source_platform}→{h.target_platform}) · score={h.score}"
            )
            lines.append(f"- {h.description}")
            lines.append(f"- Recommendation: {h.recommendation}")
            lines.append("")
        return "\n".join(lines)


_rag_singleton: BehaviorRAG | None = None


def get_rag() -> BehaviorRAG:
    global _rag_singleton
    if _rag_singleton is None:
        _rag_singleton = BehaviorRAG()
    return _rag_singleton
