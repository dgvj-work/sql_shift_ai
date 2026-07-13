"""LLM-powered migration copilot with Hugging Face Inference API."""

from __future__ import annotations

import os
import re

from sqlshift.knowledge.behavior import BEHAVIOR_DIFFERENCES
from sqlshift.models import MigrationReport
from sqlshift.risk.scorer import recommend_workload_action

DEFAULT_MODEL = os.getenv(
    "SQLSHIFTAI_MODEL",
    os.getenv("MIGRATIONIQ_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
)

SYSTEM_PROMPT = """You are SQLShiftAI Copilot, an expert data platform migration advisor.

You help data engineers plan warehouse migrations (Vertica, Oracle, Redshift → Snowflake, dbt, BigQuery).

Expertise:
- Repository discovery, dependency lineage, impact analysis
- Migration risk scoring and workload rationalization (migrate / rewrite / retire)
- Hybrid SQL translation and stored-procedure → dbt decomposition
- Semantic validation, reconciliation testing, platform behavior differences
- Cutover planning, incremental strategies, cost estimation

Rules:
- Answer like a senior migration consultant: clear, structured, actionable.
- Ground answers in the migration context when provided.
- Never claim automatic correctness for procedural SQL, dynamic SQL, or cursors.
- Prefer numbered steps and short tables over fluff.
"""


class MigrationCopilot:
    """Grounded migration copilot using HF Inference API with structured fallback."""

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL
        self._client = None
        self._client_checked = False

    @property
    def client(self):
        if self._client_checked:
            return self._client
        self._client_checked = True
        token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
        if not token:
            self._client = False
            return self._client
        try:
            from huggingface_hub import InferenceClient

            self._client = InferenceClient(token=token)
        except Exception:
            self._client = False
        return self._client

    def build_context(
        self,
        report: MigrationReport | None = None,
        sql_snippet: str = "",
        source: str = "vertica",
        target: str = "snowflake",
    ) -> str:
        parts = [f"Migration route: {source} → {target}"]

        if sql_snippet.strip():
            snippet = sql_snippet.strip()[:3000]
            parts.append(f"\n### Active SQL (truncated)\n```sql\n{snippet}\n```")

        if report is None:
            parts.append("\nNo repository scan loaded.")
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
            f"- Validation pass: {d.validation_passed_pct:.0f}%\n"
            f"- Est. annual savings: ${d.estimated_annual_savings_usd[0]:,.0f}–"
            f"${d.estimated_annual_savings_usd[1]:,.0f}"
        )

        if report.objects:
            parts.append("\n### Top objects by complexity")
            for obj in sorted(report.objects, key=lambda o: o.complexity_score, reverse=True)[:10]:
                action = recommend_workload_action(obj)
                parts.append(
                    f"- **{obj.name}** ({obj.object_type.value}): "
                    f"complexity {obj.complexity_score}/100, "
                    f"risk {obj.risk_level.value}, "
                    f"confidence {obj.conversion_confidence:.0f}%, "
                    f"action={action}"
                )

        if report.retirement_candidates:
            parts.append("\n### Retirement candidates")
            for r in report.retirement_candidates[:8]:
                parts.append(f"- {r}")

        if report.behavior_warnings:
            parts.append("\n### Behavior warnings")
            for w in report.behavior_warnings[:6]:
                parts.append(f"- {w[:220]}")

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
        if not message.strip():
            return (
                "Ask about migration scope, what to migrate first, lineage risk, "
                "dbt strategy, validation, or cutover planning."
            )

        context = self.build_context(report, sql_snippet, source, target)
        full_system = f"{SYSTEM_PROMPT}\n\n## Current session context\n{context}"

        llm_reply = self._call_llm(full_system, history, message.strip())
        if llm_reply:
            return llm_reply

        return self._fallback(message.strip(), report, sql_snippet, source, target)

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
                temperature=0.2,
            )
            content = response.choices[0].message.content
            return content.strip() if content else None
        except Exception:
            return None

    def _fallback(
        self,
        message: str,
        report: MigrationReport | None,
        sql_snippet: str,
        source: str,
        target: str,
    ) -> str:
        """Grounded consultant-style answers when HF token is not available."""
        msg = message.lower()
        sections: list[str] = []

        # Always acknowledge route
        sections.append(f"Looking at **{source} → {target}**.")

        if report:
            d = report.dashboard
            ranked = sorted(report.objects, key=lambda o: o.complexity_score, reverse=True)

            if any(k in msg for k in ("first", "priority", "start", "order", "sequence")):
                low = [o for o in ranked if o.complexity_score < 30][::-1] or ranked[::-1]
                high = [o for o in ranked if o.complexity_score >= 50]
                sections.append(
                    f"\n**Recommended order** based on your scan of {d.total_objects} objects:\n"
                    "1. Convert low-risk objects first (build confidence and pipeline)\n"
                    "2. Parallel-run with reconciliation tests\n"
                    "3. Redesign high-complexity procedures last\n"
                )
                if low:
                    sections.append("**Start with:**")
                    for o in low[:4]:
                        sections.append(
                            f"- `{o.name}` — complexity {o.complexity_score}/100, "
                            f"{o.risk_level.value} risk"
                        )
                if high:
                    sections.append("\n**Defer / redesign:**")
                    for o in high[:4]:
                        sections.append(
                            f"- `{o.name}` — complexity {o.complexity_score}/100 "
                            f"({recommend_workload_action(o).replace('_', ' ')})"
                        )
                return "\n".join(sections)

            if any(k in msg for k in ("scope", "summary", "overview", "dashboard", "status")):
                sections.append(
                    f"\n**Current portfolio**\n"
                    f"- Objects: **{d.total_objects}**\n"
                    f"- Auto-migratable: **{d.auto_migratable}**\n"
                    f"- Needs review: **{d.requires_review}**\n"
                    f"- Redesign: **{d.requires_redesign}**\n"
                    f"- Retire/consolidate: **{d.recommended_retirement}**\n"
                    f"- Avg risk: **{d.migration_risk_score:.0f}/100**\n"
                    f"- Est. savings: **${d.estimated_annual_savings_usd[0]:,.0f}–"
                    f"${d.estimated_annual_savings_usd[1]:,.0f}/yr**"
                )
                if ranked:
                    sections.append("\n**Highest complexity objects:**")
                    for o in ranked[:5]:
                        sections.append(
                            f"- `{o.name}` ({o.object_type.value}) — "
                            f"{o.complexity_score}/100, confidence {o.conversion_confidence:.0f}%"
                        )
                return "\n".join(sections)

            if any(k in msg for k in ("retire", "rational", "consolidat", "unused", "orphan")):
                sections.append("\n**Workload rationalization**")
                for o in ranked:
                    action = recommend_workload_action(o)
                    if action in ("retire", "manual_redesign", "rewrite"):
                        sections.append(
                            f"- `{o.name}` → **{action.replace('_', ' ')}** "
                            f"(complexity {o.complexity_score})"
                        )
                if report.retirement_candidates:
                    sections.append("\n**Retirement candidates from lineage:**")
                    for r in report.retirement_candidates[:6]:
                        sections.append(f"- {r}")
                if len(sections) == 2:
                    sections.append("No strong retirement candidates in this sample. Focus on rewrite candidates.")
                return "\n".join(sections)

            if "lineage" in msg or "depend" in msg or "impact" in msg:
                sections.append(
                    f"\nLineage coverage is **{d.lineage_coverage_pct:.0f}%**. "
                    "Use the Workbench → Lineage tab for the interactive graph.\n\n"
                    "**Cutover risk tip:** migrate objects with few downstream dependents first; "
                    "leave hubs (high fan-out) for later phases with extra validation."
                )
                return "\n".join(sections)

            if any(k in msg for k in ("validat", "reconcil", "test", "checksum")):
                sections.append(
                    f"\nValidation pass rate in last scan: **{d.validation_passed_pct:.0f}%**.\n\n"
                    "**Minimum reconciliation suite:**\n"
                    "1. Row counts (source vs target)\n"
                    "2. Null rates on string columns (empty-string vs NULL)\n"
                    "3. Aggregate metric tolerance for financial columns\n"
                    "4. Incremental replay for delete+reload patterns\n"
                    "5. Spot-check business-rule CASE classifications"
                )
                return "\n".join(sections)

        # SQL / dialect questions
        if re.search(r"zeroifnull|nvl|isnull", msg):
            sections.append(
                "\n**Function mapping**\n"
                "- `ZEROIFNULL(x)` → `COALESCE(x, 0)`\n"
                "- `NVL(x, y)` / `ISNULL(x, y)` → `COALESCE(x, y)`\n\n"
                "After conversion, validate NULL rates — Vertica/Oracle empty-string "
                "semantics can differ from Snowflake."
            )
            return "\n".join(sections)

        if any(k in msg for k in ("datediff", "dateadd", "date arithmetic", "timezone")):
            sections.append(
                "\n**Date handling**\n"
                "- Vertica `DATEDIFF('day', a, b)` → Snowflake `DATEDIFF(day, a, b)`\n"
                "- `col - 90` → `DATEADD(day, -90, col)`\n"
                "- Normalize timestamps to UTC before period aggregations"
            )
            return "\n".join(sections)

        if any(k in msg for k in ("procedure", "stored proc", "pl/sql")):
            sections.append(
                "\n**Procedure migration**\n"
                "1. Convert wrapper to Snowflake `LANGUAGE SQL` with `:PARAM` bindings\n"
                "2. Replace `LOCAL TEMP` with `CREATE OR REPLACE TEMPORARY TABLE`\n"
                "3. Prefer decomposing into dbt staging → intermediate → mart\n"
                "4. Manually review cursors, dynamic SQL, and exception handlers"
            )
            return "\n".join(sections)

        if "dbt" in msg:
            sections.append(
                "\n**dbt architecture approach**\n"
                "1. Sources for landing/staging tables\n"
                "2. Staging models = 1:1 cleansed sources\n"
                "3. Intermediate models = business transforms (CTEs)\n"
                "4. Marts = consumer-facing tables\n"
                "5. Incremental strategy: delete+insert for day-reload patterns; merge for CDC\n"
                "6. Add schema tests (`unique`, `not_null`) on keys"
            )
            return "\n".join(sections)

        if any(k in msg for k in ("cutover", "plan", "roadmap", "phase")):
            sections.append(
                "\n**Suggested cutover plan**\n"
                "1. Discovery + lineage (Workbench scan)\n"
                "2. Migrate low-risk objects + generate dbt scaffold\n"
                "3. Parallel run with reconciliation tests\n"
                "4. Redesign high-risk procedures\n"
                "5. Retire orphaned / unused assets\n"
                "6. Production cutover with rollback window"
            )
            if report:
                d = report.dashboard
                sections.append(
                    f"\nWith your current scan: start with **{d.auto_migratable}** auto-migratable "
                    f"objects, then schedule **{d.requires_review + d.requires_redesign}** for engineering."
                )
            return "\n".join(sections)

        if sql_snippet.strip() and any(k in msg for k in ("this", "sql", "convert", "what", "explain")):
            sections.append(
                "\nI see SQL loaded in context. Use **Object Inspector → Assess & Convert** "
                "for dialect output and risk score. Ask specifically about functions, "
                "incremental strategy, or dbt decomposition for this object."
            )
            return "\n".join(sections)

        # Default helpful response
        diffs = [d for d in BEHAVIOR_DIFFERENCES if d.source_platform == source][:3]
        sections.append(
            "\nI can answer like a migration consultant on:\n"
            "- What to migrate first / portfolio risk\n"
            "- Lineage impact and retirement candidates\n"
            "- ZEROIFNULL / dates / procedures / dbt strategy\n"
            "- Validation and cutover planning\n"
        )
        if report:
            sections.append(
                f"A scan is loaded ({report.dashboard.total_objects} objects). "
                "Try: *What should we migrate first?*"
            )
        else:
            sections.append(
                "No scan loaded yet — run **Migration Workbench** first for grounded answers, "
                "or ask a dialect/process question."
            )
        if diffs:
            sections.append("\n**Platform behaviors to watch:**")
            for d in diffs:
                sections.append(f"- {d.description}")

        if not (os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")):
            sections.append(
                "\n_Tip: set `HF_TOKEN` for full LLM responses via Hugging Face Inference._"
            )

        return "\n".join(sections)
