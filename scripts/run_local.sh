#!/usr/bin/env bash
# MorphSQL — Local setup, test, and run script
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "🔄 MorphSQL — Local Setup"
echo "=========================================="
echo ""

# 1. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# 2. Install package with all extras
echo "📦 Installing dependencies..."
pip install -q -e ".[dev,demo]"

# 3. Run tests
echo ""
echo "🧪 Running tests..."
pytest tests/ -v --tb=short

# 4. Run CLI smoke test
echo ""
echo "🔍 Running CLI analyze on example repo..."
morphsql analyze examples/vertica_legacy --source vertica --target snowflake --output ./migration-output

# 5. Run full migration pipeline
echo ""
echo "🚀 Running full migration pipeline..."
morphsql migrate examples/vertica_legacy --source vertica --target snowflake --output ./migration-output

# 6. Verify outputs
echo ""
echo "✅ Verifying outputs..."
test -f ./migration-output/migration_report.html && echo "   ✓ HTML report generated"
test -d ./migration-output/dbt && echo "   ✓ dbt projects generated"
DBT_COUNT=$(find ./migration-output/dbt -name "dbt_project.yml" | wc -l | tr -d ' ')
echo "   ✓ $DBT_COUNT dbt projects created"

# 7. Test app + handler surfaces
echo ""
echo "🌐 Testing Gradio handlers..."
python -c "
from pathlib import Path
import pandas as pd
from demo.handlers import (
    convert_for_ui,
    analyze_sql_object,
    get_sample_workbench,
    run_feature_migration,
    run_behavior_rag,
)
from app import _build_demo

sql = Path('examples/vertica_legacy/procedures/SP_BUILD_CUSTOMER_DAILY.sql').read_text()
notes, output, status, share, preview, path, nb, api = convert_for_ui(sql, 'vertica', 'pandas')
assert output.strip() and isinstance(preview, pd.DataFrame)

analysis, fig, badge, out, notes2 = analyze_sql_object(sql, 'vertica', 'snowflake')
assert out.strip() and badge

wb = get_sample_workbench()
assert len(wb) == 12

md, feat = run_feature_migration('snowflake')
assert feat.strip()

rag = run_behavior_rag('ZEROIFNULL', 'vertica', 'snowflake')
assert 'ZEROIFNULL' in rag.upper() or len(rag) > 20

assert _build_demo() is not None
print('   ✓ Convert, assess, workbench, features, RAG, Gradio build OK')
"

echo ""
echo "=========================================="
echo "✅ All checks passed! Ready to test."
echo ""
echo "Next steps:"
echo "  1. Launch the Gradio demo:"
echo "     python app.py"
echo ""
echo "  2. Or use the CLI:"
echo "     morphsql analyze examples/vertica_legacy --source vertica --target snowflake"
echo "     morphsql convert examples/vertica_legacy --source vertica --target dbt-snowflake --generate-dbt"
echo "     morphsql migrate examples/vertica_legacy --output migration-output"
echo ""
echo "  3. Open the HTML report:"
echo "     open migration-output/migration_report.html"
echo ""
