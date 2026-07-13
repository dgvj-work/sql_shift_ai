"""Convert warehouse SQL (any supported dialect) into runnable PySpark code."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from morphsql.models import Dialect
from morphsql.parser.sql_parser import get_sqlglot_dialect


def is_pyspark_target(target: str | Dialect) -> bool:
    value = target.value if isinstance(target, Dialect) else str(target)
    return value.lower() in {"pyspark", "spark", "python-pyspark", "spark-sql-df"}


def sql_to_pyspark(
    sql: str,
    source: Dialect,
) -> tuple[str, float, list[str], list[str]]:
    """
    Translate SQL from any supported warehouse dialect into PySpark DataFrame code.

    Returns: (python_code, confidence, auto_notes, review_notes)
    """
    from morphsql.translator.engine import (
        _apply_function_mappings,
        _apply_syntax_replacements,
    )

    auto: list[str] = []
    review: list[str] = []
    confidence = 90.0
    original = sql or ""
    working = original.strip()

    if not working:
        return (
            _wrap_module("# Empty SQL — nothing to convert.\nresult = spark.createDataFrame([], schema=None)\n", []),
            0.0,
            [],
            ["Empty SQL input"],
        )

    working, syn = _apply_syntax_replacements(working, source)
    auto.extend(syn)
    if source == Dialect.ORACLE and re.search(r"\bDUAL\b", original, re.I):
        if not re.search(r"\bFROM\b", working, re.I):
            working = working.rstrip().rstrip(";") + " FROM dual"
            auto.append("Restored FROM dual as one-row Spark stub")

    working, funcs = _apply_function_mappings(working, source, Dialect.SNOWFLAKE)
    auto.extend(funcs)
    auto.append(f"Source dialect normalized: {source.value} → portable SQL → pyspark")

    if re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b", working, re.I):
        review.append(
            "Stored procedures are not fully expressible in PySpark — extracting SELECT bodies"
        )
        confidence -= 25
        working = _extract_selects_from_procedure(working)

    if re.search(r"\bEXECUTE\s+IMMEDIATE\b|\bCURSOR\b|\bEXCEPTION\s+WHEN\b", original, re.I):
        review.append("Dynamic SQL / cursors / exceptions need manual Spark redesign")
        confidence -= 15

    statements: list[exp.Expression] = []
    read_dialect = get_sqlglot_dialect(source)
    try:
        statements = [s for s in sqlglot.parse(working, read=read_dialect) if s is not None]
    except (ParseError, ValueError):
        statements = []

    if not statements:
        for fallback in ("snowflake", "postgres", "oracle", "bigquery", "redshift"):
            try:
                statements = [s for s in sqlglot.parse(working, read=fallback) if s is not None]
                if statements:
                    auto.append(f"Parsed with fallback dialect: {fallback}")
                    break
            except (ParseError, ValueError):
                continue

    if not statements:
        confidence = max(20.0, confidence - 40)
        review.append("Could not parse SQL — emitted stub with original query")
        stub = (
            "from pyspark.sql import SparkSession, functions as F\n\n"
            "spark = SparkSession.builder.getOrCreate()\n"
            "# TODO: MorphSQL could not parse this SQL automatically.\n"
            f"sql = {original.strip()!r}\n"
            "result = spark.sql(sql)  # fallback: run as Spark SQL if dialect-compatible\n"
        )
        return stub, confidence, list(dict.fromkeys(auto)), list(dict.fromkeys(review))

    frames_needed: set[str] = set()
    blocks: list[str] = []
    converter = _SparkConverter(auto=auto, review=review)

    for i, stmt in enumerate(statements):
        result_name = "result" if len(statements) == 1 else f"result_{i + 1}"
        if isinstance(stmt, (exp.Select, exp.Union, exp.With)):
            code, used = converter.convert_query(stmt, result_name=result_name)
            blocks.append(code)
            frames_needed.update(used)
            continue

        if isinstance(stmt, (exp.Create, exp.Insert, exp.Drop, exp.Command)):
            review.append(f"Skipped non-SELECT statement: {stmt.__class__.__name__}")
            confidence -= 8
            for sel in stmt.find_all(exp.Select):
                code, used = converter.convert_query(sel, result_name=f"result_{len(blocks) + 1}")
                blocks.append(code)
                frames_needed.update(used)
            continue

        sel = stmt.find(exp.Select)
        if sel is not None:
            code, used = converter.convert_query(sel, result_name=result_name)
            blocks.append(code)
            frames_needed.update(used)
        else:
            review.append(f"Unsupported statement type for PySpark: {stmt.__class__.__name__}")
            confidence -= 10

    if not blocks:
        review.append("No convertible SELECT found")
        confidence = min(confidence, 35.0)
        blocks = ["result = spark.createDataFrame([], schema=None)  # no SELECT\n"]

    confidence = max(0.0, min(100.0, confidence - 3 * len(review)))
    body = "\n\n".join(blocks)
    if len(blocks) > 1:
        last = f"result_{len(blocks)}"
        if f"{last} =" in body and "\nresult =" not in f"\n{body}":
            body += f"\n\nresult = {last}\n"

    return (
        _wrap_module(body, sorted(frames_needed)),
        confidence,
        list(dict.fromkeys(auto)),
        list(dict.fromkeys(review)),
    )


def _wrap_module(body: str, frame_names: list[str]) -> str:
    lines = [
        "from pyspark.sql import SparkSession, functions as F, Window",
        "from pyspark.sql.types import *",
        "",
        "# MorphSQL — SQL → PySpark",
        "spark = SparkSession.builder.getOrCreate()",
        "",
        "# Provide input DataFrames (or replace with spark.table / spark.read).",
        "tables: dict = {}",
    ]
    if frame_names:
        lines.append("# Expected frames:")
        for name in frame_names:
            lines.append(f"#   tables[{name!r}] = spark.table({name!r})  # or spark.read.parquet(...)")
    else:
        lines.append("# Example: tables['my_table'] = spark.read.parquet('my_table')")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    lines.append("# result.show()  # optional")
    lines.append("")
    return "\n".join(lines)


def _extract_selects_from_procedure(sql: str) -> str:
    selects = re.findall(
        r"(SELECT\b.+?)(?:;|END\b|INSERT\b|UPDATE\b|DELETE\b|CREATE\b)",
        sql,
        flags=re.I | re.S,
    )
    if not selects:
        m = re.search(r"SELECT\b.+", sql, flags=re.I | re.S)
        return m.group(0) if m else sql
    return ";\n".join(s.strip().rstrip(";") for s in selects)


def _table_key(table: exp.Table) -> str:
    parts = [p for p in [table.catalog, table.db, table.name] if p]
    return ".".join(parts) if parts else (table.name or "table")


def _ident(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]", "_", name or "col")


class _SparkConverter:
    def __init__(self, auto: list[str], review: list[str]):
        self.auto = auto
        self.review = review
        self._cte_vars: dict[str, str] = {}
        self._dual_mode = False

    def convert_query(self, node: exp.Expression, result_name: str = "result") -> tuple[str, set[str]]:
        used: set[str] = set()
        lines: list[str] = []

        if isinstance(node, exp.With):
            for cte in node.expressions:
                alias = cte.alias_or_name
                var = f"cte_{_ident(alias)}"
                code, u = self.convert_query(cte.this, result_name=var)
                lines.append(code.rstrip())
                used.update(u)
                self._cte_vars[str(alias).lower()] = var
            node = node.this

        if isinstance(node, exp.Union):
            left_code, u1 = self.convert_query(node.this, result_name=f"{result_name}_left")
            right_code, u2 = self.convert_query(node.expression, result_name=f"{result_name}_right")
            used |= u1 | u2
            lines.append(left_code.rstrip())
            lines.append(right_code.rstrip())
            if node.args.get("distinct") is False:
                lines.append(f"{result_name} = {result_name}_left.unionAll({result_name}_right)")
                self.auto.append("UNION ALL → DataFrame.unionAll")
            else:
                lines.append(f"{result_name} = {result_name}_left.union({result_name}_right).distinct()")
                self.auto.append("UNION → DataFrame.union().distinct()")
            return "\n".join(lines) + "\n", used

        if not isinstance(node, exp.Select):
            sel = node.find(exp.Select)
            if sel is None:
                self.review.append(f"Cannot convert {node.__class__.__name__} to PySpark")
                return f"{result_name} = spark.createDataFrame([], schema=None)\n", used
            node = sel

        assert isinstance(node, exp.Select)

        from_ = node.args.get("from_")
        if from_ is None:
            cols: dict[str, str] = {}
            for i, e in enumerate(node.expressions):
                alias, expr_code = self._project_expr(e)
                cols[alias or f"col_{i}"] = expr_code
            select_args = ", ".join(f"{v}.alias({k!r})" for k, v in cols.items())
            lines.append(
                f"{result_name} = spark.range(1).select({select_args})"
            )
            self.auto.append("Scalar SELECT → spark.range(1).select(...)")
            return "\n".join(lines) + "\n", used

        df_var = f"{result_name}_df"
        base_code, base_used = self._from_item(from_.this, df_var)
        lines.append(base_code.rstrip())
        used.update(base_used)

        joins = node.args.get("joins") or []
        for j_i, join in enumerate(joins):
            right_var = f"{result_name}_r{j_i}"
            right_code, right_used = self._from_item(join.this, right_var)
            lines.append(right_code.rstrip())
            used.update(right_used)
            how = (join.args.get("side") or "inner").lower()
            if how not in {"left", "right", "inner", "outer", "full"}:
                how = "inner"
            if how == "full":
                how = "outer"
            on = join.args.get("on")
            if on is not None:
                left_on, right_on = self._join_on_keys(on)
                if left_on and right_on:
                    lines.append(
                        f"{df_var} = {df_var}.join({right_var}, "
                        f"{df_var}[{left_on!r}] == {right_var}[{right_on!r}], how={how!r})"
                    )
                else:
                    lines.append(
                        f"{df_var} = {df_var}.join({right_var}, how={how!r})  # TODO: join keys"
                    )
                    self.review.append("Complex JOIN ON — verify Spark join keys")
            else:
                using = join.args.get("using")
                if using:
                    cols = [e.name for e in using]
                    lines.append(
                        f"{df_var} = {df_var}.join({right_var}, on={cols!r}, how={how!r})"
                    )
                else:
                    lines.append(
                        f"{df_var} = {df_var}.join({right_var}, how={how!r})  # TODO: add ON"
                    )
                    self.review.append("JOIN without ON/USING")
            self.auto.append(f"{how.upper()} JOIN → DataFrame.join(how={how!r})")

        where = node.args.get("where")
        if where is not None:
            cond = self._bool_expr(where.this, df_var)
            lines.append(f"{df_var} = {df_var}.filter({cond})")
            self.auto.append("WHERE → DataFrame.filter")

        group = node.args.get("group")
        projections = list(node.expressions)
        has_agg = any(e.find(exp.AggFunc) for e in projections)

        if group is not None or has_agg:
            group_cols: list[str] = []
            if group is not None:
                for g in group.expressions:
                    group_cols.append(self._column_name(g))

            agg_exprs: list[str] = []
            for e in projections:
                alias = e.alias_or_name
                inner = e.this if isinstance(e, exp.Alias) else e
                if isinstance(inner, exp.AggFunc):
                    out_name = alias or f"agg_{len(agg_exprs)}"
                    agg_exprs.append(self._agg_expr(inner, out_name, df_var))
                else:
                    name = alias or self._column_name(inner)
                    if name not in group_cols:
                        group_cols.append(name)

            if group_cols and agg_exprs:
                gcols = ", ".join(repr(c) for c in group_cols)
                aggs = ", ".join(agg_exprs)
                lines.append(f"{result_name} = {df_var}.groupBy({gcols}).agg({aggs})")
                self.auto.append("GROUP BY + aggregates → groupBy().agg()")
            elif agg_exprs and not group_cols:
                aggs = ", ".join(agg_exprs)
                lines.append(f"{result_name} = {df_var}.agg({aggs})")
                self.auto.append("Aggregate without GROUP BY → DataFrame.agg()")
            else:
                gcols = ", ".join(repr(c) for c in group_cols)
                lines.append(f"{result_name} = {df_var}.select({gcols}).distinct()")
        else:
            select_parts: list[str] = []
            star = False
            for e in projections:
                if isinstance(e, exp.Star) or (
                    isinstance(e, exp.Column) and getattr(e, "name", None) == "*"
                ):
                    star = True
                    break
                alias = e.alias if isinstance(e, exp.Alias) else None
                inner = e.this if isinstance(e, exp.Alias) else e
                if isinstance(inner, exp.Column) and not alias:
                    select_parts.append(f"{df_var}[{inner.name!r}]")
                else:
                    name = alias or self._column_name(inner)
                    select_parts.append(f"({self._value_expr(inner, df_var)}).alias({name!r})")

            if star and not select_parts:
                lines.append(f"{result_name} = {df_var}")
                self.auto.append("SELECT * → DataFrame passthrough")
            elif star and select_parts:
                lines.append(
                    f"{result_name} = {df_var}.select('*', {', '.join(select_parts)})"
                )
            else:
                lines.append(f"{result_name} = {df_var}.select({', '.join(select_parts)})")
                self.auto.append("SELECT columns → DataFrame.select")

        if node.args.get("distinct"):
            lines.append(f"{result_name} = {result_name}.distinct()")
            self.auto.append("DISTINCT → distinct()")

        order = node.args.get("order")
        if order is not None:
            order_parts = []
            for o in order.expressions:
                col = o.this if isinstance(o, exp.Ordered) else o
                name = self._column_name(col)
                desc = bool(o.args.get("desc")) if isinstance(o, exp.Ordered) else False
                order_parts.append(f"F.col({name!r}).desc()" if desc else f"F.col({name!r}).asc()")
            lines.append(f"{result_name} = {result_name}.orderBy({', '.join(order_parts)})")
            self.auto.append("ORDER BY → orderBy()")

        limit = node.args.get("limit")
        if limit is not None:
            n = limit.expression if hasattr(limit, "expression") and limit.expression else limit.this
            try:
                if hasattr(n, "name") and n.name is not None:
                    n_val: int | str = int(n.name)
                elif hasattr(n, "this"):
                    n_val = int(n.this)
                else:
                    n_val = int(str(n))
            except Exception:
                n_val = 10
                self.review.append("Non-literal LIMIT — defaulted to limit(10)")
            lines.append(f"{result_name} = {result_name}.limit({n_val})")
            self.auto.append("LIMIT → limit()")

        return "\n".join(lines) + "\n", used

    def _from_item(self, node: exp.Expression, var: str) -> tuple[str, set[str]]:
        used: set[str] = set()
        if isinstance(node, exp.Alias) and isinstance(
            node.this, (exp.Table, exp.Subquery, exp.Select)
        ):
            return self._from_item(node.this, var)
        if isinstance(node, exp.Table):
            key = _table_key(node)
            if key.lower() in {"dual"}:
                self.auto.append("FROM dual → spark.range(1) stub")
                self._dual_mode = True
                return f"{var} = spark.range(1).withColumnRenamed('id', '_dual')\n", used
            self._dual_mode = False
            if key.lower() in self._cte_vars:
                return f"{var} = {self._cte_vars[key.lower()]}\n", used
            short = key.split(".")[-1]
            if short.lower() in self._cte_vars:
                return f"{var} = {self._cte_vars[short.lower()]}\n", used
            used.add(key)
            return (
                f"{var} = tables.get({key!r}) or spark.table({key!r})\n",
                used,
            )
        if isinstance(node, exp.Subquery):
            return self.convert_query(node.this, result_name=var)
        self.review.append(f"Unusual FROM clause: {node.__class__.__name__}")
        return f"{var} = spark.createDataFrame([], schema=None)  # TODO: FROM\n", used

    def _join_on_keys(self, on: exp.Expression) -> tuple[str | None, str | None]:
        if isinstance(on, exp.EQ):
            left, right = on.left, on.right
            if isinstance(left, exp.Column) and isinstance(right, exp.Column):
                return left.name, right.name
        return None, None

    def _column_name(self, node: exp.Expression) -> str:
        if isinstance(node, exp.Column):
            return node.name
        if isinstance(node, exp.Alias):
            return node.alias_or_name
        if isinstance(node, exp.Literal):
            return str(node.this)
        try:
            return _ident(node.sql())
        except Exception:
            return "col"

    def _agg_expr(self, node: exp.AggFunc, out_name: str, df_var: str) -> str:
        mapping = {
            exp.Count: "count",
            exp.Sum: "sum",
            exp.Avg: "avg",
            exp.Min: "min",
            exp.Max: "max",
        }
        func = "sum"
        for typ, name in mapping.items():
            if isinstance(node, typ):
                func = name
                break
        else:
            self.review.append(f"Aggregate {node.__class__.__name__} approximated")

        if isinstance(node, exp.Count) and (node.this is None or isinstance(node.this, exp.Star)):
            return f"F.count(F.lit(1)).alias({out_name!r})"
        arg = self._value_expr(node.this, df_var) if node.this is not None else "F.lit(1)"
        return f"F.{func}({arg}).alias({out_name!r})"

    def _bool_expr(self, node: exp.Expression, df_var: str) -> str:
        if isinstance(node, exp.And):
            return f"({self._bool_expr(node.left, df_var)}) & ({self._bool_expr(node.right, df_var)})"
        if isinstance(node, exp.Or):
            return f"({self._bool_expr(node.left, df_var)}) | ({self._bool_expr(node.right, df_var)})"
        if isinstance(node, exp.Not):
            return f"~({self._bool_expr(node.this, df_var)})"
        if isinstance(node, exp.EQ):
            return f"({self._value_expr(node.left, df_var)} == {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.NEQ):
            return f"({self._value_expr(node.left, df_var)} != {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.GT):
            return f"({self._value_expr(node.left, df_var)} > {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.GTE):
            return f"({self._value_expr(node.left, df_var)} >= {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.LT):
            return f"({self._value_expr(node.left, df_var)} < {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.LTE):
            return f"({self._value_expr(node.left, df_var)} <= {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.Is):
            left = self._value_expr(node.this, df_var)
            if node.args.get("not"):
                return f"({left}.isNotNull())"
            return f"({left}.isNull())"
        if isinstance(node, exp.In):
            left = self._value_expr(node.this, df_var)
            vals = ", ".join(self._value_expr(v, df_var) for v in node.expressions)
            return f"({left}.isin([{vals}]))"
        if isinstance(node, exp.Like):
            left = self._value_expr(node.this, df_var)
            pat = self._value_expr(node.expression, df_var)
            return f"({left}.like({pat}))"
        if isinstance(node, exp.Between):
            val = self._value_expr(node.this, df_var)
            low = self._value_expr(node.args["low"], df_var)
            high = self._value_expr(node.args["high"], df_var)
            return f"(({val}) >= ({low})) & (({val}) <= ({high}))"
        self.review.append(f"Complex predicate approximated: {node.__class__.__name__}")
        return f"(F.lit(True))  # TODO: {node.sql()}"

    def _value_expr(self, node: exp.Expression, df_var: str) -> str:
        if node is None:
            return "F.lit(None)"
        if isinstance(node, exp.Column):
            if self._dual_mode and node.name.lower() != "_dual":
                self.review.append(
                    f"Column `{node.name}` on DUAL treated as null — replace with a literal"
                )
                return "F.lit(None)"
            return f"F.col({node.name!r})"
        if isinstance(node, exp.Literal):
            if node.is_string:
                return f"F.lit({node.this!r})"
            return f"F.lit({node.this})"
        if isinstance(node, exp.Boolean):
            return f"F.lit({bool(node.this)})"
        if isinstance(node, exp.Null):
            return "F.lit(None)"
        if isinstance(node, exp.Paren):
            return f"({self._value_expr(node.this, df_var)})"
        if isinstance(node, exp.Sub):
            left = self._value_expr(node.left, df_var)
            right = self._value_expr(node.right, df_var)
            if isinstance(node.left, (exp.CurrentDate, exp.CurrentTimestamp)) and isinstance(
                node.right, exp.Literal
            ) and not node.right.is_string:
                return f"F.date_sub({left}, {node.right.this})"
            return f"({left} - {right})"
        if isinstance(node, exp.Add):
            left = self._value_expr(node.left, df_var)
            right = self._value_expr(node.right, df_var)
            if isinstance(node.left, (exp.CurrentDate, exp.CurrentTimestamp)) and isinstance(
                node.right, exp.Literal
            ) and not node.right.is_string:
                return f"F.date_add({left}, {node.right.this})"
            return f"({left} + {right})"
        if isinstance(node, exp.Mul):
            return f"({self._value_expr(node.left, df_var)} * {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.Div):
            return f"({self._value_expr(node.left, df_var)} / {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.Coalesce):
            parts = [self._value_expr(node.this, df_var)] if node.this is not None else []
            parts.extend(self._value_expr(x, df_var) for x in (node.expressions or []))
            if not parts:
                return "F.lit(None)"
            return f"F.coalesce({', '.join(parts)})"
        if isinstance(node, exp.Anonymous):
            name = (node.name or "").upper()
            args = node.expressions
            if name in {"NVL", "IFNULL", "ZEROIFNULL"} and args:
                base = self._value_expr(args[0], df_var)
                fill = self._value_expr(args[1], df_var) if len(args) > 1 else "F.lit(0)"
                if name == "ZEROIFNULL" and len(args) == 1:
                    fill = "F.lit(0)"
                return f"F.coalesce({base}, {fill})"
            if name == "GREATEST" and len(args) >= 2:
                return (
                    f"F.greatest({self._value_expr(args[0], df_var)}, "
                    f"{self._value_expr(args[1], df_var)})"
                )
            if name == "LEAST" and len(args) >= 2:
                return (
                    f"F.least({self._value_expr(args[0], df_var)}, "
                    f"{self._value_expr(args[1], df_var)})"
                )
            self.review.append(f"Function {name} needs review in PySpark output")
            return f"({self._value_expr(args[0], df_var) if args else 'F.lit(None)'})  # TODO:{name}"
        if isinstance(node, exp.Cast):
            return f"({self._value_expr(node.this, df_var)})"
        if isinstance(node, exp.CurrentDate):
            return "F.current_date()"
        if isinstance(node, exp.CurrentTimestamp):
            return "F.current_timestamp()"
        if isinstance(node, exp.Upper):
            return f"F.upper({self._value_expr(node.this, df_var)})"
        if isinstance(node, exp.Lower):
            return f"F.lower({self._value_expr(node.this, df_var)})"
        if isinstance(node, exp.Case):
            self.review.append("CASE expression approximated — review branching")
            ifs = node.args.get("ifs") or []
            default = node.args.get("default")
            if ifs:
                when = ifs[0]
                cond = self._bool_expr(when.this, df_var)
                tru = self._value_expr(when.args.get("true"), df_var)
                fal = self._value_expr(default, df_var) if default is not None else "F.lit(None)"
                return f"F.when({cond}, {tru}).otherwise({fal})"
            return "F.lit(None)"
        try:
            sql = node.sql()
        except Exception:
            sql = node.__class__.__name__
        self.review.append(f"Expression approximated: {node.__class__.__name__}")
        return f"F.lit(None)  # TODO: {sql}"

    def _project_expr(self, node: exp.Expression) -> tuple[str, str]:
        alias = node.alias if isinstance(node, exp.Alias) else None
        inner = node.this if isinstance(node, exp.Alias) else node
        name = alias or self._column_name(inner)
        return name, self._value_expr(inner, "df")
