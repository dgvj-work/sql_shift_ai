#!/usr/bin/env bash
# SQLShiftAI — Local setup, test, and run script
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "🔄 SQLShiftAI — Local Setup"
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
sqlshift analyze examples/vertica_legacy --source vertica --target snowflake --output ./migration-output

# 5. Run full migration pipeline
echo ""
echo "🚀 Running full migration pipeline..."
sqlshift migrate examples/vertica_legacy --output ./migration-output

# 6. Verify outputs
echo ""
echo "✅ Verifying outputs..."
test -f ./migration-output/migration_report.html && echo "   ✓ HTML report generated"
test -d ./migration-output/dbt && echo "   ✓ dbt projects generated"
DBT_COUNT=$(find ./migration-output/dbt -name "dbt_project.yml" | wc -l | tr -d ' ')
echo "   ✓ $DBT_COUNT dbt projects created"

# 7. Test app imports
echo ""
echo "🌐 Testing Gradio app..."
python -c "
from app import analyze_sql, analyze_repository, convert_sql
sql = open('examples/vertica_legacy/procedures/SP_BUILD_CUSTOMER_DAILY.sql').read()
s, d, f = analyze_sql(sql, 'vertica', 'snowflake')
t, m = convert_sql(sql, 'vertica', 'snowflake')
rs, rd, rc, rj = analyze_repository('vertica', 'snowflake')
assert 'Complexity' in s and len(t) > 0 and 'Total Objects' in rs
print('   ✓ All app functions working')
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
echo "     sqlshift analyze examples/vertica_legacy --source vertica --target snowflake"
echo "     sqlshift convert examples/vertica_legacy --source vertica --target dbt-snowflake --generate-dbt"
echo "     sqlshift migrate examples/vertica_legacy --output migration-output"
echo ""
echo "  3. Open the HTML report:"
echo "     open migration-output/migration_report.html"
echo ""
