"""Agent-based migration workflow orchestration."""

from __future__ import annotations

from pathlib import Path

from morphsql.dbt_generator.decomposer import decompose_to_dbt, write_dbt_project
from morphsql.knowledge.behavior import format_behavior_warning, get_behavior_warnings
from morphsql.lineage.builder import (
    build_lineage_graph,
    build_table_lineage,
    detect_circular_dependencies,
    find_orphaned_tables,
)
from morphsql.models import (
    DashboardMetrics,
    Dialect,
    MigrationCategory,
    MigrationReport,
)
from morphsql.report.html_report import write_html_report
from morphsql.risk.scorer import extract_business_rules, score_objects
from morphsql.scanner.repository import scan_repository
from morphsql.translator.engine import translate_objects
from morphsql.validation.reconciliation import generate_dbt_tests, simulate_validation


class MigrationPipeline:
    """Orchestrates the full migration intelligence pipeline."""

    def __init__(
        self,
        source: Dialect = Dialect.VERTICA,
        target: Dialect = Dialect.SNOWFLAKE,
    ):
        self.source = source
        self.target = target

    def analyze(self, repository_path: str | Path) -> MigrationReport:
        """Run full discovery + assessment pipeline."""
        # Discovery Agent
        objects = scan_repository(repository_path)

        # Lineage Agent
        graph = build_lineage_graph(objects, self.source)
        lineage = build_table_lineage(objects, self.source)

        downstream_map: dict[str, int] = {}
        for obj in objects:
            downstream_map[obj.name] = graph.out_degree(obj.name) if obj.name in graph else 0

        # Risk scoring
        objects = score_objects(objects, self.source, self.target, downstream_map=downstream_map)

        # Business rule extraction
        for obj in objects:
            obj.business_rules = extract_business_rules(obj.source_sql)

        # Behavior warnings
        behavior_warnings: list[str] = []
        for obj in objects:
            warnings = get_behavior_warnings(obj.source_sql, self.source.value, self.target.value)
            for w in warnings:
                msg = format_behavior_warning(w)
                if msg not in behavior_warnings:
                    behavior_warnings.append(msg)

        # Retirement candidates
        orphans = find_orphaned_tables(graph, objects)
        retirement = [
            f"{t} — orphaned table with no downstream consumers"
            for t in orphans
        ]

        # Circular dependencies
        cycles = detect_circular_dependencies(graph)
        for cycle in cycles:
            behavior_warnings.append(f"Circular dependency detected: {' → '.join(cycle)}")

        dashboard = self._compute_dashboard(objects, lineage)

        return MigrationReport(
            source_dialect=self.source,
            target_dialect=self.target,
            repository_path=str(repository_path),
            objects=objects,
            lineage=lineage,
            dashboard=dashboard,
            behavior_warnings=behavior_warnings,
            retirement_candidates=retirement,
        )

    def convert(self, report: MigrationReport) -> MigrationReport:
        """Translation Agent — convert all objects."""
        report.objects = translate_objects(report.objects, self.source, self.target)
        report.dashboard.conversion_completed_pct = (
            sum(1 for o in report.objects if o.target_sql) / max(len(report.objects), 1) * 100
        )
        return report

    def validate(self, report: MigrationReport) -> MigrationReport:
        """Validation Agent — generate tests and simulate validation."""
        all_results = []
        for obj in report.objects:
            generate_dbt_tests(obj)
            results = simulate_validation(obj)
            all_results.extend(results)

        report.validation_results = all_results
        passed = sum(1 for r in all_results if r.passed)
        report.dashboard.validation_passed_pct = passed / max(len(all_results), 1) * 100
        report.dashboard.test_coverage_pct = (
            sum(1 for o in report.objects if o.tests_generated) / max(len(report.objects), 1) * 100
        )
        return report

    def generate_dbt(self, report: MigrationReport, output_dir: str | Path) -> MigrationReport:
        """Architecture Agent — decompose to dbt project."""
        output_dir = Path(output_dir)
        for obj in report.objects:
            if obj.object_type.value in ("stored_procedure", "sql_script", "view"):
                files = decompose_to_dbt(obj, self.source)
                obj_dir = output_dir / obj.name.lower()
                write_dbt_project(files, obj_dir)
        return report

    def generate_report(self, report: MigrationReport, output_path: str | Path) -> Path:
        """Documentation Agent — generate HTML report."""
        return write_html_report(report, output_path)

    def run_full_pipeline(
        self,
        repository_path: str | Path,
        output_dir: str | Path,
    ) -> MigrationReport:
        """Run the complete migration intelligence pipeline."""
        report = self.analyze(repository_path)
        report = self.convert(report)
        report = self.validate(report)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        self.generate_dbt(report, output_dir / "dbt")
        self.generate_report(report, output_dir / "migration_report.html")

        return report

    def _compute_dashboard(self, objects, lineage) -> DashboardMetrics:
        total = len(objects)
        if total == 0:
            return DashboardMetrics()

        auto = sum(1 for o in objects if o.migration_category == MigrationCategory.AUTO_MIGRATE)
        review = sum(1 for o in objects if o.migration_category == MigrationCategory.AUTO_WITH_REVIEW)
        redesign = sum(1 for o in objects if o.migration_category in (
            MigrationCategory.MANUAL_REDESIGN, MigrationCategory.PARTIAL
        ))
        retire = sum(1 for o in objects if o.migration_category == MigrationCategory.RETIRE)

        avg_risk = sum(o.complexity_score for o in objects) / total
        lineage_pct = min(100, len(lineage) / max(total, 1) * 100)

        # Cost estimate heuristic
        savings_low = total * 500
        savings_high = total * 1500

        return DashboardMetrics(
            total_objects=total,
            auto_migratable=auto,
            requires_review=review,
            requires_redesign=redesign,
            recommended_retirement=retire,
            lineage_coverage_pct=lineage_pct,
            migration_risk_score=avg_risk,
            estimated_annual_savings_usd=(savings_low, savings_high),
        )
