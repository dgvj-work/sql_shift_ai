---
language: en
license: apache-2.0
tags:
  - sql
  - migration
  - vertica
  - snowflake
  - dbt
  - data-engineering
  - lineage
  - etl
  - code-generation
  - agent
  - sqlglot
  - data-warehouse
library_name: sqlshift-ai
pipeline_tag: text-generation
---

# SQLShiftAI

## Model Card

### Model Description

**SQLShiftAI** is an AI-powered data platform migration intelligence toolkit. It analyzes legacy SQL repositories, stored procedures, and ETL workflows to automate cloud data warehouse modernization.

Unlike simple SQL translators, SQLShiftAI provides:

- **Repository-level discovery** — scan entire codebases, not single queries
- **Column-level lineage** — dependency graphs before and after conversion
- **Migration risk scoring** — complexity, unsupported syntax, business criticality
- **Hybrid translation** — deterministic rules + sqlglot dialect transpilation
- **dbt decomposition** — stored procedures → modular dbt projects
- **Semantic validation** — reconciliation tests for source vs target equivalence
- **Behavior intelligence** — platform-specific NULL, timezone, merge differences

### Supported Migration Paths (v0.1)

| Source | Target | Status |
|--------|--------|--------|
| Vertica | Snowflake | ✅ Full support |
| Vertica | dbt + Snowflake | ✅ Full support |
| Oracle | Snowflake | 🟡 Beta |
| Redshift | Snowflake | 🟡 Beta |
| BigQuery | Snowflake | 🔜 Planned |

### Intended Use

- **Primary**: Data engineers migrating legacy warehouse SQL to Snowflake/dbt
- **Secondary**: Migration consultants assessing complexity and risk
- **Tertiary**: Engineering teams generating migration documentation and test suites

### Out-of-Scope

- Real-time database connectivity (v0.1 uses offline analysis)
- Production cutover orchestration
- Informatica/SSIS workflow migration (planned Phase 3)

### How to Use

```bash
pip install sqlshift-ai

# Analyze repository
sqlshift analyze ./legacy_sql --source vertica --target snowflake --output report/

# Convert with dbt generation
sqlshift convert ./legacy_sql --source vertica --target dbt-snowflake --generate-dbt

# Full pipeline
sqlshift migrate ./legacy_sql --output migration-package/
```

```python
from sqlshift.pipeline import MigrationPipeline
from sqlshift.models import Dialect

pipeline = MigrationPipeline(source=Dialect.VERTICA, target=Dialect.SNOWFLAKE)
report = pipeline.run_full_pipeline("./legacy_sql", "./output")
print(f"Objects: {report.dashboard.total_objects}, Risk: {report.dashboard.migration_risk_score}")
```

### Training Data

SQLShiftAI uses a hybrid architecture, not a fine-tuned LLM:

1. **sqlglot** — battle-tested SQL parser and dialect transpiler
2. **Deterministic rules** — Vertica/Oracle function mappings, syntax replacements
3. **Behavior knowledge base** — 12+ documented platform behavioral differences
4. **Heuristic risk model** — complexity metrics, dependency analysis, unsupported feature detection

### Evaluation

Tested against bundled Vertica legacy repository (procedures, views, tables, queries):

- Repository scanning: 100% object detection
- Translation confidence: 70-95% for standard SQL
- Risk scoring: correlates with manual assessment
- dbt decomposition: generates staging/intermediate/mart structure

### Limitations

- Dynamic SQL and cursor-based procedures require manual review
- Vertica-specific features (PROJECTION, TIMESERIES, SEGMENTED BY) flagged, not auto-converted
- Validation is simulated in v0.1 (execution-based validation planned)
- Cost estimates are heuristic, not based on actual query profiles

### Ethical Considerations

- Does not connect to production databases by default
- No data is sent to external APIs in the open-source core
- Migration recommendations should be reviewed by qualified engineers

### Citation

```bibtex
@software{sqlshiftai2026,
  title={SQLShiftAI: AI Data Platform Migration Intelligence},
  author={SQLShiftAI Contributors},
  year={2026},
  url={https://huggingface.co/migrationiq/sqlshift-ai}
}
```
