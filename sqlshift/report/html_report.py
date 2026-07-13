"""HTML migration report generation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Template

from sqlshift.models import MigrationReport

REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SQLShiftAI Report — {{ report.repository_path }}</title>
<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --accent: #38bdf8;
    --green: #4ade80; --yellow: #facc15; --red: #f87171; --border: #334155;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
  .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
  h1 { font-size: 2rem; margin-bottom: 0.5rem; color: var(--accent); }
  h2 { font-size: 1.4rem; margin: 2rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
  .subtitle { color: #94a3b8; margin-bottom: 2rem; }
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin: 1.5rem 0; }
  .metric { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.2rem; text-align: center; }
  .metric .value { font-size: 2rem; font-weight: 700; color: var(--accent); }
  .metric .label { font-size: 0.85rem; color: #94a3b8; margin-top: 0.3rem; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; }
  table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
  th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
  th { color: var(--accent); font-weight: 600; }
  .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 6px; font-size: 0.8rem; font-weight: 600; }
  .badge-low { background: #166534; color: var(--green); }
  .badge-medium { background: #854d0e; color: var(--yellow); }
  .badge-high { background: #991b1b; color: var(--red); }
  .badge-critical { background: #7f1d1d; color: #fca5a5; }
  .progress-bar { background: var(--border); border-radius: 8px; height: 8px; margin: 0.5rem 0; }
  .progress-fill { background: var(--accent); height: 100%; border-radius: 8px; }
  pre { background: #0c1222; padding: 1rem; border-radius: 8px; overflow-x: auto; font-size: 0.85rem; }
  .footer { text-align: center; color: #64748b; margin-top: 3rem; font-size: 0.85rem; }
</style>
</head>
<body>
<div class="container">
  <h1>SQLShiftAI Migration Report</h1>
  <p class="subtitle">{{ report.source_dialect.value | upper }} → {{ report.target_dialect.value | upper }} | {{ report.repository_path }} | Generated {{ timestamp }}</p>

  <div class="metrics">
    <div class="metric"><div class="value">{{ report.dashboard.total_objects }}</div><div class="label">Objects Discovered</div></div>
    <div class="metric"><div class="value">{{ report.dashboard.auto_migratable }}</div><div class="label">Auto-Migratable</div></div>
    <div class="metric"><div class="value">{{ report.dashboard.requires_review }}</div><div class="label">Requires Review</div></div>
    <div class="metric"><div class="value">{{ report.dashboard.requires_redesign }}</div><div class="label">Manual Redesign</div></div>
    <div class="metric"><div class="value">{{ report.dashboard.recommended_retirement }}</div><div class="label">Retire/Consolidate</div></div>
    <div class="metric"><div class="value">{{ "%.0f"|format(report.dashboard.migration_risk_score) }}</div><div class="label">Risk Score (/100)</div></div>
  </div>

  <h2>Migration Progress</h2>
  <div class="card">
    <p>Conversion Completed: {{ "%.0f"|format(report.dashboard.conversion_completed_pct) }}%</p>
    <div class="progress-bar"><div class="progress-fill" style="width: {{ report.dashboard.conversion_completed_pct }}%"></div></div>
    <p>Validation Passed: {{ "%.0f"|format(report.dashboard.validation_passed_pct) }}%</p>
    <div class="progress-bar"><div class="progress-fill" style="width: {{ report.dashboard.validation_passed_pct }}%"></div></div>
    <p>Lineage Coverage: {{ "%.0f"|format(report.dashboard.lineage_coverage_pct) }}%</p>
    <div class="progress-bar"><div class="progress-fill" style="width: {{ report.dashboard.lineage_coverage_pct }}%"></div></div>
    <p>Test Coverage: {{ "%.0f"|format(report.dashboard.test_coverage_pct) }}%</p>
    <div class="progress-bar"><div class="progress-fill" style="width: {{ report.dashboard.test_coverage_pct }}%"></div></div>
  </div>

  {% if report.dashboard.estimated_annual_savings_usd[1] > 0 %}
  <h2>Cost Estimate</h2>
  <div class="card">
    <p>Estimated annual savings: <strong>${{ "{:,.0f}".format(report.dashboard.estimated_annual_savings_usd[0]) }} – ${{ "{:,.0f}".format(report.dashboard.estimated_annual_savings_usd[1]) }}</strong></p>
  </div>
  {% endif %}

  <h2>Object Assessment</h2>
  <table>
    <tr><th>Object</th><th>Type</th><th>Complexity</th><th>Risk</th><th>Category</th><th>Confidence</th></tr>
    {% for obj in report.objects %}
    <tr>
      <td>{{ obj.name }}</td>
      <td>{{ obj.object_type.value }}</td>
      <td>{{ obj.complexity_score }}/100</td>
      <td><span class="badge badge-{{ obj.risk_level.value }}">{{ obj.risk_level.value | upper }}</span></td>
      <td>{{ obj.migration_category.value | replace('_', ' ') }}</td>
      <td>{{ "%.0f"|format(obj.conversion_confidence) }}%</td>
    </tr>
    {% endfor %}
  </table>

  {% if report.behavior_warnings %}
  <h2>Behavior Difference Warnings</h2>
  <div class="card">
    <ul>{% for w in report.behavior_warnings %}<li>{{ w }}</li>{% endfor %}</ul>
  </div>
  {% endif %}

  {% if report.retirement_candidates %}
  <h2>Retirement Candidates</h2>
  <div class="card">
    <ul>{% for r in report.retirement_candidates %}<li>{{ r }}</li>{% endfor %}</ul>
  </div>
  {% endif %}

  <h2>Object Details</h2>
  {% for obj in report.objects %}
  <div class="card">
    <h3>{{ obj.name }} <span class="badge badge-{{ obj.risk_level.value }}">{{ obj.risk_level.value }}</span></h3>
    <p><strong>Path:</strong> {{ obj.source_path }} | <strong>Complexity:</strong> {{ obj.complexity_score }}/100</p>
    {% if obj.risk_factors %}
    <p><strong>Risk Factors:</strong></p>
    <ul>{% for rf in obj.risk_factors %}<li>{{ rf.description }} (+{{ rf.score }})</li>{% endfor %}</ul>
    {% endif %}
    {% if obj.requires_review %}
    <p><strong>Requires Review:</strong> {{ obj.requires_review | join(', ') }}</p>
    {% endif %}
    {% if obj.business_rules %}
    <p><strong>Business Rules:</strong></p>
    <pre>{{ obj.business_rules | join('\\n') }}</pre>
    {% endif %}
    {% if obj.target_sql %}
    <p><strong>Converted SQL:</strong></p>
    <pre>{{ obj.target_sql[:2000] }}{% if obj.target_sql|length > 2000 %}...{% endif %}</pre>
    {% endif %}
  </div>
  {% endfor %}

  <div class="footer">
    Generated by <strong>SQLShiftAI</strong> v0.1.0 | Open-source migration intelligence
  </div>
</div>
</body>
</html>"""


def generate_html_report(report: MigrationReport) -> str:
    """Generate an HTML migration report."""
    template = Template(REPORT_TEMPLATE)
    return template.render(
        report=report,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
    )


def write_html_report(report: MigrationReport, output_path: str | Path) -> Path:
    """Write HTML report to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = generate_html_report(report)
    output_path.write_text(html, encoding="utf-8")
    return output_path
