#!/usr/bin/env bash
# Deploy SQLShiftAI to Hugging Face Hub
set -euo pipefail

SPACE_ID="${1:-migrationiq/sqlshift-ai}"
MODEL_ID="${2:-migrationiq/sqlshift-ai}"

echo "🔄 Deploying SQLShiftAI to Hugging Face..."
echo ""

# Deploy Gradio Space
echo "📦 Uploading Space: $SPACE_ID"
huggingface-cli upload "$SPACE_ID" . \
  --repo-type=space \
  --exclude=".git/*" \
  --exclude=".venv/*" \
  --exclude="__pycache__/*" \
  --exclude="*.egg-info/*" \
  --exclude="migration-output/*" \
  --exclude="/tmp/*"

echo ""
echo "📦 Uploading Model/Dataset repo: $MODEL_ID"
huggingface-cli upload "$MODEL_ID" . \
  --repo-type=model \
  --exclude=".git/*" \
  --exclude=".venv/*" \
  --exclude="__pycache__/*" \
  --exclude="*.egg-info/*" \
  --exclude="migration-output/*"

echo ""
echo "✅ Deployment complete!"
echo "   Space:  https://huggingface.co/spaces/$SPACE_ID"
echo "   Model:  https://huggingface.co/$MODEL_ID"
