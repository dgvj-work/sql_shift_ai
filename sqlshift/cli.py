"""SQLShiftAI CLI — sqlshift command-line interface."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sqlshift import __product_name__, __version__
from sqlshift.models import Dialect
from sqlshift.pipeline import MigrationPipeline
from sqlshift.translator.engine import translate_sql

app = typer.Typer(
    name="sqlshift",
    help=f"{__product_name__} — AI-powered data platform migration intelligence",
    add_completion=False,
)
console = Console()


class SourceDialect(str, Enum):
    vertica = "vertica"
    oracle = "oracle"
    redshift = "redshift"
    bigquery = "bigquery"


class TargetDialect(str, Enum):
    snowflake = "snowflake"
    dbt_snowflake = "dbt-snowflake"
    bigquery = "bigquery"


def _to_dialect(d: SourceDialect | TargetDialect) -> Dialect:
    return Dialect(d.value)


@app.callback()
def main():
    """SQLShiftAI — migration intelligence toolkit."""
    pass


@app.command()
def analyze(
    path: str = typer.Argument(..., help="Path to SQL repository (directory or .zip)"),
    source: SourceDialect = typer.Option(SourceDialect.vertica, "--source", "-s"),
    target: TargetDialect = typer.Option(TargetDialect.snowflake, "--target", "-t"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output directory"),
):
    """Analyze a legacy SQL repository for migration complexity and risk."""
    console.print(Panel(f"[bold cyan]{__product_name__}[/] v{__version__} — Analyze", expand=False))

    pipeline = MigrationPipeline(source=_to_dialect(source), target=_to_dialect(target))
    report = pipeline.analyze(path)

    _print_dashboard(report)

    table = Table(title="Object Assessment")
    table.add_column("Object", style="cyan")
    table.add_column("Type")
    table.add_column("Complexity", justify="right")
    table.add_column("Risk")
    table.add_column("Category")

    for obj in report.objects:
        risk_color = {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}
        table.add_row(
            obj.name,
            obj.object_type.value,
            f"{obj.complexity_score}/100",
            f"[{risk_color.get(obj.risk_level.value, 'white')}]{obj.risk_level.value}[/]",
            obj.migration_category.value.replace("_", " "),
        )

    console.print(table)

    if output:
        out = Path(output)
        out.mkdir(parents=True, exist_ok=True)
        pipeline.generate_report(report, out / "migration_report.html")
        with open(out / "analysis.json", "w") as f:
            json.dump(report.model_dump(), f, indent=2, default=str)
        console.print(f"\n[green]✓[/] Report written to {out}")


@app.command()
def convert(
    path: str = typer.Argument(..., help="Path to SQL file or repository"),
    source: SourceDialect = typer.Option(SourceDialect.vertica, "--source", "-s"),
    target: TargetDialect = typer.Option(TargetDialect.snowflake, "--target", "-t"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    generate_tests: bool = typer.Option(False, "--generate-tests"),
    generate_lineage: bool = typer.Option(False, "--generate-lineage"),
    generate_dbt: bool = typer.Option(False, "--generate-dbt"),
):
    """Convert legacy SQL to target platform dialect."""
    pipeline = MigrationPipeline(source=_to_dialect(source), target=_to_dialect(target))

    path_obj = Path(path)
    if path_obj.is_file():
        sql = path_obj.read_text()
        translated, confidence, auto, review = translate_sql(sql, _to_dialect(source), _to_dialect(target))
        console.print(Panel(f"Conversion confidence: [bold]{confidence:.0f}%[/]", expand=False))
        if auto:
            console.print("[green]Auto-converted:[/] " + ", ".join(auto[:5]))
        if review:
            console.print("[yellow]Requires review:[/] " + ", ".join(review[:5]))
        console.print("\n[bold]Converted SQL:[/]\n")
        console.print(translated)
        if output:
            Path(output).write_text(translated)
    else:
        report = pipeline.analyze(path)
        report = pipeline.convert(report)
        if generate_tests:
            report = pipeline.validate(report)
        out = Path(output or "migration-output")
        out.mkdir(parents=True, exist_ok=True)
        pipeline.generate_report(report, out / "migration_report.html")
        if generate_dbt:
            pipeline.generate_dbt(report, out / "dbt")
        console.print(f"[green]✓[/] Converted {len(report.objects)} objects → {out}")


@app.command()
def validate(
    path: str = typer.Argument(..., help="Path to SQL repository"),
    source: SourceDialect = typer.Option(SourceDialect.vertica, "--source", "-s"),
    target: TargetDialect = typer.Option(TargetDialect.snowflake, "--target", "-t"),
    tolerance: float = typer.Option(0.01, "--tolerance"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
):
    """Generate validation and reconciliation tests."""
    pipeline = MigrationPipeline(source=_to_dialect(source), target=_to_dialect(target))
    report = pipeline.analyze(path)
    report = pipeline.convert(report)
    report = pipeline.validate(report)

    table = Table(title="Validation Results")
    table.add_column("Object")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")

    for result in report.validation_results:
        status = "[green]PASS[/]" if result.passed else "[red]FAIL[/]"
        detail = result.root_cause or result.recommendation or ""
        table.add_row(result.object_name, result.check_name, status, detail[:60])

    console.print(table)

    if output:
        out = Path(output)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "validation_results.json", "w") as f:
            json.dump([r.model_dump() for r in report.validation_results], f, indent=2)
        console.print(f"[green]✓[/] Validation results → {out}")


@app.command(name="migrate")
def migrate_cmd(
    path: str = typer.Argument(..., help="Path to SQL repository"),
    source: SourceDialect = typer.Option(SourceDialect.vertica, "--source", "-s"),
    target: TargetDialect = typer.Option(TargetDialect.snowflake, "--target", "-t"),
    output: str = typer.Option("migration-output", "--output", "-o"),
):
    """Run the complete migration pipeline: analyze → convert → validate → report."""
    console.print(Panel(
        f"[bold cyan]{__product_name__}[/] — Full Migration Pipeline\n"
        f"{source.value} → {target.value}",
        expand=False,
    ))

    pipeline = MigrationPipeline(source=_to_dialect(source), target=_to_dialect(target))
    report = pipeline.run_full_pipeline(path, output)
    _print_dashboard(report)
    console.print(f"\n[green]✓[/] Complete migration package → [bold]{output}[/]")


@app.command()
def version():
    """Show version information."""
    console.print(f"{__product_name__} v{__version__}")


def _print_dashboard(report) -> None:
    d = report.dashboard
    console.print(Panel(
        f"Objects: [bold]{d.total_objects}[/] | "
        f"Auto-migrate: [green]{d.auto_migratable}[/] | "
        f"Review: [yellow]{d.requires_review}[/] | "
        f"Redesign: [red]{d.requires_redesign}[/] | "
        f"Risk: [bold]{d.migration_risk_score:.0f}/100[/]",
        title="Migration Dashboard",
        expand=False,
    ))


if __name__ == "__main__":
    app()
