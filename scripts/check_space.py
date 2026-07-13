#!/usr/bin/env python3
"""Preflight checks before Hugging Face Space deploy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    errors: list[str] = []

    for rel in (
        "app.py",
        "requirements.txt",
        "README_HF_SPACE.md",
        "demo/handlers.py",
        "demo/theme.py",
        "morphsql/__init__.py",
        "model/risk_classifier.joblib",
        "examples/vertica_legacy",
    ):
        if not (ROOT / rel).exists():
            errors.append(f"missing required path: {rel}")

    try:
        import app as space_app  # noqa: F401
        from app import _build_demo, demo

        assert demo is not None
        built = _build_demo()
        assert built is not None
    except Exception as exc:
        errors.append(f"app import/build failed: {exc}")

    try:
        from demo.handlers import convert_for_ui, convert_upload_for_ui
        import tempfile
        from pathlib import Path as P

        notes, output, status, share, preview, path, nb, api = convert_for_ui(
            "SELECT COALESCE(a, 0) AS a FROM t",
            "snowflake",
            "pandas",
        )
        assert "import pandas" in output and path.endswith(".py")

        with tempfile.TemporaryDirectory() as td:
            sql = P(td) / "sample.sql"
            sql.write_text("SELECT COALESCE(x, 0) AS x FROM t", encoding="utf-8")
            batch = convert_upload_for_ui(str(sql), "", "snowflake", "pyspark")
            assert batch[6].endswith(".py")
    except Exception as exc:
        errors.append(f"convert smoke failed: {exc}")

    if errors:
        print("Space preflight FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("Space preflight OK — ready to deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
