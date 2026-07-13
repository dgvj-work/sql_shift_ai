"""Workload rationalization recommendations."""

from __future__ import annotations

from sqlshift.models import MigrationCategory, MigrationReport
from sqlshift.risk.scorer import recommend_workload_action


def generate_rationalization(report: MigrationReport) -> str:
    """Generate workload rationalization analysis."""
    migrate: list[str] = []
    review: list[str] = []
    rewrite: list[str] = []
    retire: list[str] = []

    for obj in report.objects:
        action = recommend_workload_action(obj)
        entry = f"**{obj.name}** ({obj.object_type.value}, complexity {obj.complexity_score}/100)"
        if action == "retire" or obj.migration_category == MigrationCategory.RETIRE:
            retire.append(entry)
        elif action in ("manual_redesign", "rewrite"):
            rewrite.append(entry)
        elif action == "review_and_migrate":
            review.append(entry)
        else:
            migrate.append(entry)

    lines = [
        "### Workload rationalization",
        "",
        "Enterprise migrations often fail by moving everything. "
        "This analysis categorizes each object by recommended action.",
        "",
        f"| Action | Count |",
        f"|--------|-------|",
        f"| Migrate as-is | {len(migrate)} |",
        f"| Review then migrate | {len(review)} |",
        f"| Rewrite / redesign | {len(rewrite)} |",
        f"| Retire / consolidate | {len(retire) + len(report.retirement_candidates)} |",
        "",
    ]

    if migrate:
        lines += ["#### Migrate", ""] + [f"- {e}" for e in migrate[:10]] + [""]
    if review:
        lines += ["#### Review required", ""] + [f"- {e}" for e in review[:10]] + [""]
    if rewrite:
        lines += ["#### Rewrite", ""] + [f"- {e}" for e in rewrite[:10]] + [""]
    if retire or report.retirement_candidates:
        lines += ["#### Retire / consolidate", ""]
        for e in retire[:8]:
            lines.append(f"- {e}")
        for r in report.retirement_candidates[:5]:
            lines.append(f"- {r}")

    scope_reduction = len(retire) + len(report.retirement_candidates)
    if scope_reduction:
        lines += [
            "",
            f"**Scope reduction opportunity:** {scope_reduction} objects can be "
            f"retired or consolidated, reducing migration effort by approximately "
            f"{scope_reduction / max(len(report.objects), 1) * 100:.0f}%.",
        ]

    return "\n".join(lines)
