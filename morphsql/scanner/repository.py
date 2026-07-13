"""Repository-level SQL discovery and scanning."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from morphsql.models import MigrationObject, ObjectType

SQL_EXTENSIONS = {".sql", ".hql", ".ddl", ".dml"}
DBT_EXTENSIONS = {".sql", ".yml", ".yaml"}
AIRFLOW_EXTENSIONS = {".py"}
SKIP_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "target", "dbt_packages", ".dbt", "dist", "build",
}


def _classify_file(path: Path, content: str) -> ObjectType:
    name_lower = path.name.lower()
    content_upper = content.upper()

    if "CREATE OR REPLACE PROCEDURE" in content_upper or "CREATE PROCEDURE" in content_upper:
        return ObjectType.STORED_PROCEDURE
    if "CREATE OR REPLACE FUNCTION" in content_upper or "CREATE FUNCTION" in content_upper:
        return ObjectType.FUNCTION
    if "CREATE VIEW" in content_upper or "CREATE OR REPLACE VIEW" in content_upper:
        return ObjectType.VIEW
    if "CREATE TABLE" in content_upper or "CREATE LOCAL TEMP" in content_upper:
        if "TEMP" in content_upper or "TEMPORARY" in content_upper:
            return ObjectType.TEMP_TABLE
        return ObjectType.TABLE
    if path.suffix in {".yml", ".yaml"} and "models:" in content:
        return ObjectType.DBT_MODEL
    if path.suffix == ".py" and ("DAG(" in content or "airflow" in content.lower()):
        return ObjectType.AIRFLOW_DAG
    if name_lower.endswith(".sql"):
        return ObjectType.SQL_SCRIPT
    return ObjectType.UNKNOWN


def _extract_object_name(path: Path, content: str, obj_type: ObjectType) -> str:
    patterns = [
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+([\w.]+)",
        r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+([\w.]+)",
        r"CREATE\s+(?:LOCAL\s+TEMP|TEMP|TEMPORARY)?\s*TABLE\s+([\w.]+)",
        r"CREATE\s+TABLE\s+([\w.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    stem = path.stem.upper()
    if obj_type == ObjectType.DBT_MODEL:
        return stem
    return stem


def scan_directory(path: str | Path) -> list[MigrationObject]:
    """Scan a directory for SQL and migration-relevant artifacts."""
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    objects: list[MigrationObject] = []

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if any(part in SKIP_DIRS for part in file_path.parts):
            continue
        if file_path.suffix.lower() not in SQL_EXTENSIONS | DBT_EXTENSIONS | AIRFLOW_EXTENSIONS:
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if not content.strip():
            continue

        obj_type = _classify_file(file_path, content)
        name = _extract_object_name(file_path, content, obj_type)

        objects.append(
            MigrationObject(
                name=name,
                object_type=obj_type,
                source_path=str(file_path.relative_to(root)),
                source_sql=content,
                metadata={
                    "lines": content.count("\n") + 1,
                    "size_bytes": len(content.encode("utf-8")),
                },
            )
        )

    return objects


def scan_zip(zip_path: str | Path) -> list[MigrationObject]:
    """Scan a zip archive containing SQL artifacts."""
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip not found: {zip_path}")

    objects: list[MigrationObject] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if any(skip in name.split("/") for skip in SKIP_DIRS):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in SQL_EXTENSIONS | DBT_EXTENSIONS | AIRFLOW_EXTENSIONS:
                continue

            try:
                content = zf.read(info).decode("utf-8", errors="replace")
            except Exception:
                continue

            if not content.strip():
                continue

            obj_type = _classify_file(Path(name), content)
            obj_name = _extract_object_name(Path(name), content, obj_type)

            objects.append(
                MigrationObject(
                    name=obj_name,
                    object_type=obj_type,
                    source_path=name,
                    source_sql=content,
                    metadata={
                        "lines": content.count("\n") + 1,
                        "size_bytes": len(content.encode("utf-8")),
                        "from_zip": True,
                    },
                )
            )

    return objects


def scan_repository(path: str | Path) -> list[MigrationObject]:
    """Scan a repository path (directory or zip file)."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        return scan_zip(path)
    return scan_directory(path)
