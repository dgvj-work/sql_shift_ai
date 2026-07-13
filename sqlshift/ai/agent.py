"""Tool-calling SQL Migration Agent (AI-first interface)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from sqlshift.ai.risk_model import get_risk_model
from sqlshift.dbt_generator.decomposer import decompose_to_dbt, format_dbt_project, is_dbt_target
from sqlshift.intelligence.rag import get_rag
from sqlshift.models import Dialect, MigrationObject, ObjectType
from sqlshift.translator.engine import translate_sql
from sqlshift.translator.pandas_codegen import is_pandas_target


@dataclass
class AgentMessage:
    role: str
    content: str
    tool: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    answer: str
    converted_sql: str = ""
    risk: dict[str, Any] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)
    messages: list[AgentMessage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "converted_sql": self.converted_sql,
            "risk": self.risk,
            "tools_used": self.tools_used,
            "messages": [asdict(m) for m in self.messages],
        }


class SQLMigrationAgent:
    """
    AI agent that plans tool calls for SQL migration.

    Tools: convert_sql, predict_risk, retrieve_behavior, emit_dbt, explain
    """

    def __init__(self):
        self.risk_model = get_risk_model()
        self.rag = get_rag()

    def run(
        self,
        prompt: str,
        sql: str = "",
        source: str = "snowflake",
        target: str = "pandas",
    ) -> AgentResult:
        prompt = (prompt or "").strip()
        sql = (sql or "").strip()
        messages: list[AgentMessage] = [
            AgentMessage(role="user", content=prompt or "Migrate this SQL", data={"sql": sql})
        ]
        tools_used: list[str] = []
        converted = ""
        risk: dict[str, Any] = {}

        intent = self._detect_intent(prompt, sql)

        if sql and intent in {"convert", "migrate", "dbt", "full", "auto"}:
            converted, conf, auto, review = self._tool_convert(sql, source, target)
            tools_used.append("convert_sql")
            messages.append(
                AgentMessage(
                    role="tool",
                    tool="convert_sql",
                    content=f"Converted with {conf:.0f}% confidence",
                    data={"auto": auto, "review": review, "sql": converted},
                )
            )

        if sql and intent in {"risk", "full", "auto", "convert", "migrate", "dbt"}:
            risk = self._tool_risk(sql)
            tools_used.append("predict_risk")
            messages.append(
                AgentMessage(
                    role="tool",
                    tool="predict_risk",
                    content=f"Risk={risk['label']} ({risk['score']:.2f})",
                    data=risk,
                )
            )

        if intent in {"rag", "behavior", "full", "auto", "explain"} or (
            not sql and prompt
        ):
            rag_q = prompt or sql
            hits = self.rag.retrieve(rag_q, top_k=4, source=source, target=target)
            tools_used.append("retrieve_behavior")
            messages.append(
                AgentMessage(
                    role="tool",
                    tool="retrieve_behavior",
                    content=f"Retrieved {len(hits)} behavior docs",
                    data={"hits": [asdict(h) if hasattr(h, "__dataclass_fields__") else h.__dict__ for h in hits]},
                )
            )

        dbt_out = ""
        if sql and (intent == "dbt" or is_dbt_target(target)):
            dbt_out = self._tool_dbt(sql, converted or sql, source)
            tools_used.append("emit_dbt")
            converted = dbt_out or converted
            messages.append(
                AgentMessage(
                    role="tool",
                    tool="emit_dbt",
                    content="Emitted dbt project scaffold",
                    data={"preview": dbt_out[:500]},
                )
            )

        answer = self._compose_answer(prompt, source, target, converted, risk, messages, intent)
        messages.append(AgentMessage(role="assistant", content=answer))
        return AgentResult(
            answer=answer,
            converted_sql=converted,
            risk=risk,
            tools_used=list(dict.fromkeys(tools_used)),
            messages=messages,
        )

    def _detect_intent(self, prompt: str, sql: str) -> str:
        p = (prompt or "").lower()
        wants_convert = bool(
            re.search(r"\bconvert\b|\bmigrate\b|\btranslate\b|\btransform\b", p) or sql
        )
        if re.search(r"\bpandas\b|\bdataframe\b|\bpython\b", p):
            # still convert; target dropdown should be pandas
            return "full"
        if re.search(r"\bdbt\b|feature mart", p):
            return "dbt"
        if wants_convert and re.search(r"\brisk\b|complex|score|explain|null|behavior", p):
            return "full"
        if re.search(r"\brisk\b|complex|score", p) and not wants_convert:
            return "risk"
        if re.search(r"\bnull\b|timezone|behavior|rag|difference", p) and not sql:
            return "rag"
        if re.search(r"\bexplain\b|why|how", p) and not wants_convert:
            return "explain"
        if wants_convert:
            return "full"
        return "auto" if sql else "rag"

    def _tool_convert(self, sql: str, source: str, target: str):
        source_d = Dialect(source)
        if is_pandas_target(target):
            target_d = Dialect.PANDAS
        elif is_dbt_target(target):
            target_d = Dialect.SNOWFLAKE
        else:
            target_d = Dialect(target)
        return translate_sql(sql, source_d, target_d)

    def _tool_risk(self, sql: str) -> dict[str, Any]:
        return self.risk_model.predict(sql)

    def _tool_dbt(self, source_sql: str, target_sql: str, source: str) -> str:
        obj = MigrationObject(
            name="agent_object",
            object_type=ObjectType.STORED_PROCEDURE
            if "PROCEDURE" in source_sql.upper()
            else ObjectType.SQL_SCRIPT,
            source_sql=source_sql,
            target_sql=target_sql,
        )
        files = decompose_to_dbt(obj, Dialect(source), project_name="ai_agent_project")
        return format_dbt_project(files, max_files=10)

    def _compose_answer(
        self,
        prompt: str,
        source: str,
        target: str,
        converted: str,
        risk: dict,
        messages: list[AgentMessage],
        intent: str,
    ) -> str:
        lines = [
            f"**MorphSQL Agent** · `{source}` → `{target}`",
            "",
        ]
        if risk:
            lines.append(
                f"**Risk model:** `{risk.get('label')}` "
                f"(score={risk.get('score', 0):.2f})"
            )
            scores = risk.get("scores") or {}
            if scores:
                parts = ", ".join(f"{k}={v:.2f}" for k, v in scores.items())
                lines.append(f"- class probs: {parts}")
            lines.append("")
        for m in messages:
            if m.tool == "retrieve_behavior" and m.data.get("hits"):
                lines.append("**Behavior RAG**")
                for h in m.data["hits"][:3]:
                    name = h.get("name", "?")
                    rec = h.get("recommendation", "")
                    lines.append(f"- **{name}**: {rec}")
                lines.append("")
            if m.tool == "convert_sql" and m.data.get("auto"):
                lines.append("**Transforms**")
                for a in m.data["auto"][:8]:
                    lines.append(f"- {a}")
                lines.append("")
        if converted:
            lines.append("**Converted output ready** in the panel (SQL or dbt project).")
        elif not converted and intent == "rag":
            lines.append("Ask a conversion question with SQL pasted, or use Convert mode.")
        if prompt:
            lines.append("")
            lines.append(f"_User intent:_ {prompt}")
        return "\n".join(lines)


def chat_agent(
    message: str,
    history: list | None,
    sql: str,
    source: str,
    target: str,
) -> tuple[list, str, str, str]:
    """Gradio chat adapter: returns history, cleared input, converted sql, risk badge."""
    history = list(history or [])
    agent = SQLMigrationAgent()
    result = agent.run(message, sql=sql, source=source, target=target)
    history.append({"role": "user", "content": message or "(run tools on SQL)"})
    history.append({"role": "assistant", "content": result.answer})
    badge = ""
    if result.risk:
        badge = f"{result.risk.get('label', '?')} · {result.risk.get('score', 0):.2f}"
    tools = ", ".join(result.tools_used) or "none"
    badge = f"{badge} · tools: {tools}".strip(" ·")
    return history, "", result.converted_sql, badge
