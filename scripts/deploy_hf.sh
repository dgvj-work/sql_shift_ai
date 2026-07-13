#!/usr/bin/env bash
# Deploy SQLShiftAI Space + optional dataset to Hugging Face Hub
set -euo pipefail

SPACE_ID="${1:-dgvj-work/sqlshift-ai}"
DATASET_ID="${2:-dgvj-work/vertica-snowflake-pairs}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Deploying SQLShiftAI SQL Migration Agent to Hugging Face..."
echo "  Space:   $SPACE_ID"
echo "  Dataset: $DATASET_ID"
echo ""

# Ensure pair dataset exists
python -c "from sqlshift.eval.pairs import ensure_pairs_file; print(ensure_pairs_file())"

# Space README must be the HF metadata card
cp README_HF_SPACE.md /tmp/sqlshiftai_space_README.md
# Keep project README for GitHub; Space upload uses HF card as README.md via include pattern

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.egg-info' \
  --exclude 'migration-output' \
  --exclude '.pytest_cache' \
  --exclude 'canvases' \
  "$ROOT/" "$STAGE/"

cp README_HF_SPACE.md "$STAGE/README.md"

echo "Uploading Space: $SPACE_ID"
hf upload "$SPACE_ID" "$STAGE" . --repo-type=space

echo ""
echo "Publishing dataset: $DATASET_ID"
python scripts/publish_dataset.py --repo "$DATASET_ID" || {
  echo "Dataset publish failed (login required). Space upload may still have succeeded."
}

echo ""
echo "Deployment complete"
echo "  Space:   https://huggingface.co/spaces/$SPACE_ID"
echo "  Dataset: https://huggingface.co/datasets/$DATASET_ID"
