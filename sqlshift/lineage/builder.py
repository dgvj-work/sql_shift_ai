"""Table and column-level lineage construction."""

from __future__ import annotations

import re
from collections import defaultdict

import networkx as nx

from sqlshift.models import ColumnLineage, Dialect, MigrationObject, TableLineage
from sqlshift.parser.sql_parser import extract_columns, extract_tables, parse_sql_multi


def build_lineage_graph(
    objects: list[MigrationObject],
    dialect: Dialect,
) -> nx.DiGraph:
    """Build a directed dependency graph from migration objects."""
    graph = nx.DiGraph()

    for obj in objects:
        graph.add_node(
            obj.name,
            object_type=obj.object_type.value,
            source_path=obj.source_path,
        )

        tables_read = extract_tables(obj.source_sql, dialect)
        tables_written = _extract_write_targets(obj.source_sql)

        for table in tables_read:
            graph.add_node(table, object_type="table")
            graph.add_edge(table, obj.name, relation="reads")

        for table in tables_written:
            graph.add_node(table, object_type="table")
            graph.add_edge(obj.name, table, relation="writes")

    return graph


def build_table_lineage(
    objects: list[MigrationObject],
    dialect: Dialect,
) -> list[TableLineage]:
    """Build table-level lineage with upstream/downstream relationships."""
    graph = build_lineage_graph(objects, dialect)
    lineages: list[TableLineage] = []

    table_nodes = [
        n for n, d in graph.nodes(data=True)
        if d.get("object_type") in ("table", "view", "temp_table")
    ]

    for table in sorted(set(table_nodes)):
        upstream = sorted(
            pred for pred in graph.predecessors(table)
            if graph.nodes[pred].get("object_type") != "table"
        )
        downstream = sorted(
            succ for succ in graph.successors(table)
            if graph.nodes[succ].get("object_type") != "table"
        )

        columns = _build_column_lineage(table, objects, dialect)

        lineages.append(
            TableLineage(
                table=table,
                upstream=upstream,
                downstream=downstream,
                columns=columns,
            )
        )

    return lineages


def build_column_lineage_for_object(
    obj: MigrationObject,
    dialect: Dialect,
) -> list[ColumnLineage]:
    """Extract column-level lineage for a single object."""
    columns_map = extract_columns(obj.source_sql, dialect)
    lineages: list[ColumnLineage] = []

    for table, cols in columns_map.items():
        for col in set(cols):
            lineages.append(
                ColumnLineage(
                    column=col,
                    table=table,
                    source_columns=[f"{table}.{col}"],
                    transformations=_detect_transformations(obj.source_sql, col),
                    downstream=[],
                )
            )

    return lineages


def get_lineage_chain(
    graph: nx.DiGraph,
    node: str,
    direction: str = "downstream",
    max_depth: int = 10,
) -> list[str]:
    """Get lineage chain for a node."""
    chain: list[str] = []
    visited: set[str] = set()

    def _walk(current: str, depth: int) -> None:
        if depth > max_depth or current in visited:
            return
        visited.add(current)
        neighbors = (
            list(graph.successors(current))
            if direction == "downstream"
            else list(graph.predecessors(current))
        )
        for neighbor in neighbors:
            chain.append(neighbor)
            _walk(neighbor, depth + 1)

    _walk(node, 0)
    return chain


def format_lineage_tree(
    graph: nx.DiGraph,
    root: str,
) -> str:
    """Format lineage as an ASCII tree."""
    lines: list[str] = [root]
    visited: set[str] = {root}

    def _render(node: str, prefix: str, depth: int) -> None:
        if depth > 8:
            return
        successors = list(graph.successors(node))
        for i, succ in enumerate(successors):
            if succ in visited:
                continue
            visited.add(succ)
            connector = "└── " if i == len(successors) - 1 else "├── "
            lines.append(f"{prefix}{connector}{succ}")
            extension = "    " if i == len(successors) - 1 else "│   "
            _render(succ, prefix + extension, depth + 1)

    _render(root, "", 0)
    return "\n".join(lines)


def detect_circular_dependencies(graph: nx.DiGraph) -> list[list[str]]:
    """Detect circular dependencies in the lineage graph."""
    try:
        cycles = list(nx.simple_cycles(graph))
        return cycles
    except nx.NetworkXError:
        return []


def find_orphaned_tables(
    graph: nx.DiGraph,
    objects: list[MigrationObject],
) -> list[str]:
    """Find tables with no downstream consumers."""
    all_tables = set()
    consumed = set()

    for obj in objects:
        for table in extract_tables(obj.source_sql, Dialect.VERTICA):
            all_tables.add(table)
        for table in _extract_write_targets(obj.source_sql):
            all_tables.add(table)
            if graph.out_degree(table) == 0:
                consumed.add(table)

    orphans = [t for t in all_tables if graph.out_degree(t) == 0 and t not in consumed]
    return sorted(orphans)


def _extract_write_targets(sql: str) -> set[str]:
    """Extract tables written to (INSERT/CREATE/MERGE targets)."""
    targets: set[str] = set()
    patterns = [
        r"INSERT\s+INTO\s+([\w.]+)",
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:LOCAL\s+TEMP\s+|TEMP\s+|TEMPORARY\s+)?TABLE\s+([\w.]+)",
        r"MERGE\s+INTO\s+([\w.]+)",
        r"UPDATE\s+([\w.]+)\s+SET",
        r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+([\w.]+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, sql, re.IGNORECASE):
            targets.add(match.group(1).upper())
    return targets


def _build_column_lineage(
    table: str,
    objects: list[MigrationObject],
    dialect: Dialect,
) -> list[ColumnLineage]:
    columns: dict[str, ColumnLineage] = {}

    for obj in objects:
        if table.upper() not in extract_tables(obj.source_sql, dialect):
            if table.upper() not in _extract_write_targets(obj.source_sql):
                continue

        for col_lineage in build_column_lineage_for_object(obj, dialect):
            key = f"{col_lineage.table}.{col_lineage.column}"
            if key not in columns:
                columns[key] = col_lineage
            else:
                columns[key].downstream.extend(col_lineage.source_columns)

    return list(columns.values())


def _detect_transformations(sql: str, column: str) -> list[str]:
    """Detect transformation patterns involving a column."""
    transformations: list[str] = []
    col_escaped = re.escape(column.upper())

    patterns = {
        "aggregation": rf"\b(SUM|COUNT|AVG|MIN|MAX)\s*\([^)]*{col_escaped}",
        "case_logic": rf"\bCASE\b[\s\S]*?{col_escaped}",
        "window_function": rf"{col_escaped}[^)]*\bOVER\s*\(",
        "cast": rf"CAST\s*\(\s*{col_escaped}",
        "coalesce": rf"\b(COALESCE|NVL|IFNULL|ZEROIFNULL)\s*\([^)]*{col_escaped}",
        "date_trunc": rf"\b(DATE_TRUNC|TRUNC)\s*\([^)]*{col_escaped}",
    }

    sql_upper = sql.upper()
    for name, pattern in patterns.items():
        try:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                transformations.append(name)
        except re.error:
            continue

    return transformations
