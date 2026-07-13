"""LLM-powered migration copilot with Hugging Face Inference API."""

from __future__ import annotations

import os
from typing import Any

from sqlshift.knowledge.behavior import BEHAVIOR_DIFFERENCES
from sqlshift.models import MigrationReport

DEFAULT_MODEL = os.getenv(
    "MIGRATIONIQ_MODEL",
    "Qwen/Qwen2.5-3B-Instruct",
)

SYSTEM_PROMPT = """You are MigrationIQ Copilot, an expert data platform migration advisor embedded in a migration intelligence product.

You help data engineers plan and execute warehouse migrations (Vertica, Oracle, Redshift → Snowflake, dbt, BigQuery).

Your expertise covers:
- Repository discovery, dependency lineage, and impact analysis
- Migration risk scoring and workload rationalization (migrate / rewrite / retire)
- Hybrid SQL translation and stored-procedure → dbt decomposition
- Semantic validation, reconciliation testing, and platform behavior differences
- Cutover planning, incremental strategies, and cost estimation

Rules:
- Answer concisely and professionally. Use markdown when helpful.
- Ground answers in the migration context provided below when available.
- If context is missing, give general best-practice guidance for enterprise migrations.
- Never claim automatic correctness — always note manual review for procedural SQL, dynamic SQL, and cursors.
- Do not mention being an AI model unless asked.
- Prefer actionable steps over generic advice.
"""


class MigrationCopilot:
    """Grounded migration copilot using HF Inference API with structured fallback."""

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            try:
                from huggingface_hub import InferenceClient

                token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
                self._client = InferenceClient(token=token) if token else InferenceClient()
            except ImportError:
                self._client = False
        return self._client

    def build_context(
        self,
        report: MigrationReport | None = None,
        sql_snippet: str = "",
        source: str = "vertica",
        target: str = "snowflake",
    ) -> str:
        """Build grounded context block for the LLM."""
        parts = [f"Migration route: {source} → {target}"]

        if sql_snippet.strip():
            snippet = sql_snippet.strip()[:3000]
            parts.append(f"\n### Active SQL (truncated)\n```sql\n{snippet}\n```")

        if report is None:
            parts.append("\nNo repository scan loaded. User may ask general migration questions.")
            return "\n".join(parts)

        d = report.dashboard
        parts.append(
            f"\n### Repository scan: {report.repository_path}\n"
            f"- Objects discovered: {d.total_objects}\n"
            f"- Auto-migratable: {d.auto_migratable}\n"
            f"- Needs review: {d.requires_review}\n"
            f"- Manual redesign: {d.requires_redesign}\n"
            f"- Retire/consolidate: {d.recommended_retirement}\n"
            f"- Avg risk score: {d.migration_risk_score:.0f}/100\n"
            f"- Lineage coverage: {d.lineage_coverage_pct:.0f}%\n"
            f"- Est. annual savings: ${d.estimated_annual_savings_usd[0]:,.0f}–"
            f"${d.estimated_annual_savings_usd[1]:,.0f}"
        )

        if report.objects:
            parts.append("\n### Top objects")
            for obj in sorted(report.objects, key=lambda o: o.complexity_score, reverse=True)[:8]:
                parts.append(
                    f"- **{obj.name}** ({obj.object_type.value}): "
                    f"complexity {obj.complexity_score}/100, "
                    f"risk {obj.risk_level.value}, "
                    f"confidence {obj.conversion_confidence:.0f}%"
                )
                if obj.requires_review[:2]:
                    parts.append(f"  Review: {', '.join(obj.requires_review[:2])}")

        if report.retirement_candidates:
            parts.append("\n### Retirement candidates")
            for r in report.retirement_candidates[:5]:
                parts.append(f"- {r}")

        if report.behavior_warnings:
            parts.append("\n### Behavior warnings")
            for w in report.behavior_warnings[:5]:
                parts.append(f"- {w[:200]}")

        return "\n".join(parts)

    def respond(
        self,
        message: str,
        history: list[dict[str, str]],
        report: MigrationReport | None = None,
        sql_snippet: str = "",
        source: str = "vertica",
        target: str = "snowflake",
    ) -> str:
        """Generate a copilot response."""
        if not message.strip():
            return "Ask a question about your migration — scope, risks, lineage, dbt strategy, or cutover planning."

        context = self.build_context(report, sql_snippet, source, target)
        full_system = f"{SYSTEM_PROMPT}\n\n## Current session context\n{context}"

        llm_reply = self._call_llm(full_system, history, message.strip())
        if llm_reply:
            return llm_reply

        return self._fallback(message.strip(), report, source, target)

    def _call_llm(
        self,
        system: str,
        history: list[dict[str, str]],
        message: str,
    ) -> str | None:
        if not self.client:
            return None

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for turn in history[-8:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})

        try:
            response = self.client.chat_completion(
                model=self.model,
                messages=messages,
                max_tokens=900,
                temperature=0.25,
            )
            content = response.choices[0].message.content
            return content.strip() if content else None
        except Exception:
            try:
                # Fallback: text generation API for older endpoints
                prompt = system + "\n\n"
                for turn in history[-4:]:
                    prompt += f"{turn.get('role', 'user').upper()}: {turn.get('content', '')}\n"
                prompt += f"USER: {message}\nASSISTANT:"
                text = self.client.text_generation(
                    prompt,
                    model=self.model,
                    max_new_tokens=600,
                    temperature=0.25,
                    return_full_text=False,
                )
                return text.strip() if text else None
            except Exception:
                return None

    def _fallback(
        self,
        message: str,
        report: MigrationReport | None,
        source: str,
        target: str,
    ) -> str:
        """Structured fallback when LLM API is unavailable."""
        msg = message.lower()
        lines = [
            "*LLM inference unavailable — using grounded knowledge base. "
            "Set `HF_TOKEN` on Hugging Face Spaces for full copilot responses.*\n"
        ]

        if report and ("scope" in msg or "summary" in msg or "overview" in msg):
            d = report.dashboard
            lines.append(
                f"**Migration scope:** {d.total_objects} objects scanned. "
                f"{d.auto_migratable} ready for automatic migration, "
                f"{d.requires_review} need review, "
                f"{d.requires_redesign} require redesign. "
                f"Average risk {d.migration_risk_score:.0f}/100."
            )
        elif report and ("retire" in msg or "rational" in msg or "consolidat" in msg):
            if report.retirement_candidates:
                lines.append("**Rationalization recommendations:**")
                for r in report.retirement_candidates[:6]:
                    lines.append(f"- {r}")
            else:
                lines.append("No retirement candidates detected in current scan.")
        elif "zeroifnull" in msg or "nvl" in msg:
            lines.append(
                "Map `ZEROIFNULL(x)` → `COALESCE(x, 0)`. "
                "`NVL`/`ISNULL` → `COALESCE`. Validate NULL semantics after conversion."
            )
        elif "lineage" in msg and report:
            lines.append(
                f"Lineage coverage is {report.dashboard.lineage_coverage_pct:.0f}%. "
                "Check the Lineage tab for dependency graph. "
                "High downstream count increases cutover risk."
            )
        elif "dbt" in msg:
            lines.append(
                "Decompose procedures into staging → intermediate → mart models. "
                "Use incremental strategies for delete+reload patterns. "
                "Generate schema tests from detected behavior risks."
            )
        elif "cutover" in msg or "plan" in msg:
            lines.append(
                "**Suggested cutover phases:**\n"
                "1. Discovery + lineage (current scan)\n"
                "2. Convert low-risk objects first\n"
                "3. Parallel run with reconciliation tests\n"
                "4. Migrate high-risk procedures with manual redesign\n"
                "5. Retire orphaned assets\n"
                "6. Production cutover with rollback window"
            )
        else:
            diffs = [d for d in BEHAVIOR_DIFFERENCES if d.source_platform == source][:3]
            lines.append(
                "I can help with migration scope, lineage impact, dbt architecture, "
                "validation strategy, workload rationalization, and cutover planning."
            )
            if diffs:
                lines.append("\n**Key platform behaviors:**")
                for d in diffs:
                    lines.append(f"- {d.name}: {d.description}")

        return "\n".join(lines)
