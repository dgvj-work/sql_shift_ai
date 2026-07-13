"""Convert warehouse SQL (any supported dialect) into runnable pandas Python."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from sqlshift.models import Dialect
from sqlshift.parser.sql_parser import get_sqlglot_dialect


def is_pandas_target(target: str | Dialect) -> bool:
    value = target.value if isinstance(target, Dialect) else str(target)
    return value.lower() in {"pandas", "python", "python-pandas", "dataframe"}


def sql_to_pandas(
    sql: str,
    source: Dialect,
) -> tuple[str, float, list[str], list[str]]:
    """
    Translate SQL from any supported warehouse dialect into pandas code.

    Returns: (python_code, confidence, auto_notes, review_notes)
    """
    from sqlshift.translator.engine import (
        _apply_function_mappings,
        _apply_syntax_replacements,
    )

    auto: list[str] = []
    review: list[str] = []
    confidence = 92.0
    original = sql or ""
    working = original.strip()

    if not working:
        return (
            _wrap_module("# Empty SQL — nothing to convert.\nresult = pd.DataFrame()\n", []),
            0.0,
            [],
            ["Empty SQL input"],
        )

    working, syn = _apply_syntax_replacements(working, source)
    auto.extend(syn)
    # Oracle often strips FROM DUAL — restore a one-row dual for pandas
    if source == Dialect.ORACLE and re.search(r"\bDUAL\b", original, re.I):
        if not re.search(r"\bFROM\b", working, re.I):
            working = working.rstrip().rstrip(";") + " FROM dual"
            auto.append("Restored FROM dual as one-row pandas stub")
    # Portable intermediate via Snowflake-oriented function maps
    working, funcs = _apply_function_mappings(working, source, Dialect.SNOWFLAKE)
    auto.extend(funcs)
    auto.append(f"Source dialect normalized: {source.value} → portable SQL → pandas")

    if re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\b", working, re.I):
        review.append(
            "Stored procedures are not fully expressible in pandas — extracting SELECT bodies"
        )
        confidence -= 25
        working = _extract_selects_from_procedure(working)

    if re.search(r"\bEXECUTE\s+IMMEDIATE\b|\bCURSOR\b|\bEXCEPTION\s+WHEN\b", original, re.I):
        review.append("Dynamic SQL / cursors / exceptions need manual pandas redesign")
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
            "import pandas as pd\n\n"
            "# TODO: MorphSQL could not parse this SQL automatically.\n"
            f"sql = {original.strip()!r}\n"
            "result = pd.DataFrame()  # replace with your load + transform\n"
        )
        return stub, confidence, list(dict.fromkeys(auto)), list(dict.fromkeys(review))

    frames_needed: set[str] = set()
    blocks: list[str] = []
    converter = _PandasConverter(auto=auto, review=review)

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
            for j, sel in enumerate(stmt.find_all(exp.Select)):
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
            review.append(f"Unsupported statement type for pandas: {stmt.__class__.__name__}")
            confidence -= 10

    if not blocks:
        review.append("No convertible SELECT found")
        confidence = min(confidence, 35.0)
        blocks = ["result = pd.DataFrame()  # no SELECT to convert\n"]

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
        "import pandas as pd",
        "import numpy as np",
        "",
        "# MorphSQL — SQL → pandas",
        "# Provide a `tables` dict before running (table name → DataFrame).",
        "tables = globals().get('tables', {})",
        "",
        "def _coalesce(value, *defaults):",
        "    cur = value",
        "    for default in defaults:",
        "        if hasattr(cur, 'fillna'):",
        "            cur = cur.fillna(default)",
        "        else:",
        "            cur = default if pd.isna(cur) else cur",
        "    return cur",
    ]
    if frame_names:
        lines.append("# Expected frames:")
        for name in frame_names:
            lines.append(f"#   tables[{name!r}] = ...")
    else:
        lines.append("# Example: tables['my_table'] = pd.read_csv('my_table.csv')")
    lines.append("")
    lines.append(body.rstrip())
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


class _PandasConverter:
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
            distinct = node.args.get("distinct")
            if distinct is False:
                lines.append(
                    f"{result_name} = pd.concat("
                    f"[{result_name}_left, {result_name}_right], ignore_index=True)"
                )
                self.auto.append("UNION ALL → pd.concat")
            else:
                lines.append(
                    f"{result_name} = pd.concat("
                    f"[{result_name}_left, {result_name}_right], ignore_index=True)"
                    f".drop_duplicates()"
                )
                self.auto.append("UNION → pd.concat + drop_duplicates")
            return "\n".join(lines) + "\n", used

        if not isinstance(node, exp.Select):
            sel = node.find(exp.Select)
            if sel is None:
                self.review.append(f"Cannot convert {node.__class__.__name__} to pandas")
                return f"{result_name} = pd.DataFrame()\n", used
            node = sel

        assert isinstance(node, exp.Select)

        from_ = node.args.get("from_")
        if from_ is None:
            cols: dict[str, str] = {}
            for i, e in enumerate(node.expressions):
                alias, expr_code = self._project_expr(e, "pd.DataFrame()")
                cols[alias or f"col_{i}"] = expr_code
            assign = ", ".join(f"{k!r}: [{v}]" for k, v in cols.items())
            lines.append(f"{result_name} = pd.DataFrame({{{assign}}})")
            self.auto.append("Scalar SELECT → one-row DataFrame")
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
                        f"{df_var} = {df_var}.merge({right_var}, how={how!r}, "
                        f"left_on={left_on!r}, right_on={right_on!r})"
                    )
                else:
                    lines.append(
                        f"{df_var} = {df_var}.merge({right_var}, how={how!r})  "
                        f"# TODO: verify join keys"
                    )
                    self.review.append("Complex JOIN ON — verify merge keys")
            else:
                using = join.args.get("using")
                if using:
                    cols = [e.name for e in using]
                    lines.append(
                        f"{df_var} = {df_var}.merge({right_var}, how={how!r}, on={cols!r})"
                    )
                else:
                    lines.append(
                        f"{df_var} = {df_var}.merge({right_var}, how={how!r})  # TODO: add ON keys"
                    )
                    self.review.append("JOIN without ON/USING")
            self.auto.append(f"{how.upper()} JOIN → DataFrame.merge(how={how!r})")

        where = node.args.get("where")
        if where is not None:
            cond = self._bool_expr(where.this, df_var)
            lines.append(f"{df_var} = {df_var}.loc[{cond}]")
            self.auto.append("WHERE → DataFrame.loc[mask]")

        group = node.args.get("group")
        projections = list(node.expressions)
        has_agg = any(e.find(exp.AggFunc) for e in projections)

        if group is not None or has_agg:
            group_cols: list[str] = []
            if group is not None:
                for g in group.expressions:
                    group_cols.append(self._column_name(g))

            rename_map: dict[str, tuple[str, str]] = {}
            for e in projections:
                alias = e.alias_or_name
                inner = e.this if isinstance(e, exp.Alias) else e
                if isinstance(inner, exp.AggFunc):
                    out_name = alias or f"agg_{len(rename_map)}"
                    # Materialize non-column aggregate inputs as helper columns
                    arg = inner.this
                    if isinstance(inner, exp.Count) and (
                        arg is None or isinstance(arg, exp.Star)
                    ):
                        rename_map[out_name] = (group_cols[0] if group_cols else "__all__", "size")
                    elif isinstance(arg, exp.Column):
                        col, func = self._agg(inner, df_var)
                        rename_map[out_name] = (col, func)
                    else:
                        helper = f"__agg_{_ident(out_name)}"
                        expr_code = self._value_expr(arg, df_var) if arg is not None else "pd.NA"
                        lines.append(f"{df_var}[{helper!r}] = {expr_code}")
                        _, func = self._agg(inner, df_var)
                        if func == "size":
                            func = "count"
                        rename_map[out_name] = (helper, func)
                        self.auto.append(f"Aggregate expression → helper column {helper}")
                else:
                    name = alias or self._column_name(inner)
                    if name not in group_cols:
                        group_cols.append(name)

            if group_cols and rename_map:
                named_parts = []
                for out, (col, func) in rename_map.items():
                    if func == "size":
                        named_parts.append(f"{out}=({group_cols[0]!r}, 'size')")
                    else:
                        named_parts.append(f"{out}=({col!r}, {func!r})")
                named = ", ".join(named_parts)
                lines.append(
                    f"{result_name} = {df_var}.groupby({group_cols!r}, as_index=False).agg({named})"
                )
                self.auto.append("GROUP BY + aggregates → groupby().agg()")
            elif rename_map and not group_cols:
                parts = []
                for out, (col, func) in rename_map.items():
                    if func == "size":
                        parts.append(f"{out!r}: [len({df_var})]")
                    else:
                        parts.append(f"{out!r}: [{df_var}[{col!r}].{func}()]")
                lines.append(f"{result_name} = pd.DataFrame({{{', '.join(parts)}}})")
                self.auto.append("Aggregate without GROUP BY → scalar DataFrame")
            else:
                lines.append(f"{result_name} = {df_var}[{group_cols!r}].drop_duplicates()")
        else:
            col_exprs: list[tuple[str, str]] = []
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
                    col_exprs.append((inner.name, f"{df_var}[{inner.name!r}]"))
                else:
                    name = alias or self._column_name(inner)
                    col_exprs.append((name, self._value_expr(inner, df_var)))

            if star and not col_exprs:
                lines.append(f"{result_name} = {df_var}.copy()")
                self.auto.append("SELECT * → DataFrame.copy()")
            elif star and col_exprs:
                assigns = ", ".join(f"{n!r}: ({ex})" for n, ex in col_exprs)
                lines.append(f"_extra = pd.DataFrame({{{assigns}}}, index={df_var}.index)")
                lines.append(f"{result_name} = pd.concat([{df_var}, _extra], axis=1)")
            else:
                assigns = ", ".join(f"{n!r}: ({ex})" for n, ex in col_exprs)
                lines.append(f"{result_name} = pd.DataFrame({{{assigns}}}, index={df_var}.index)")
                self.auto.append("SELECT columns → DataFrame projection")

        if node.args.get("distinct"):
            lines.append(f"{result_name} = {result_name}.drop_duplicates()")
            self.auto.append("DISTINCT → drop_duplicates()")

        order = node.args.get("order")
        if order is not None:
            by = []
            ascending = []
            for o in order.expressions:
                col = o.this if isinstance(o, exp.Ordered) else o
                by.append(self._column_name(col))
                desc = bool(o.args.get("desc")) if isinstance(o, exp.Ordered) else False
                ascending.append(not desc)
            lines.append(
                f"{result_name} = {result_name}.sort_values({by!r}, ascending={ascending!r})"
            )
            self.auto.append("ORDER BY → sort_values()")

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
                self.review.append("Non-literal LIMIT — defaulted to head(10)")
            lines.append(f"{result_name} = {result_name}.head({n_val})")
            self.auto.append("LIMIT → head()")

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
                # Oracle DUAL → one-row stub (no external tables entry required)
                self.auto.append("FROM dual → one-row stub DataFrame")
                self._dual_mode = True
                return f"{var} = pd.DataFrame({{'_dual': [0]}})\n", used
            self._dual_mode = False
            if key.lower() in self._cte_vars:
                return f"{var} = {self._cte_vars[key.lower()]}.copy()\n", used
            short = key.split(".")[-1]
            if short.lower() in self._cte_vars:
                return f"{var} = {self._cte_vars[short.lower()]}.copy()\n", used
            used.add(key)
            return f"{var} = tables[{key!r}].copy()\n", used
        if isinstance(node, exp.Subquery):
            return self.convert_query(node.this, result_name=var)
        self.review.append(f"Unusual FROM clause: {node.__class__.__name__}")
        return f"{var} = pd.DataFrame()  # TODO: FROM {node.sql()}\n", used

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

    def _agg(self, node: exp.AggFunc, df_var: str) -> tuple[str, str]:
        mapping = {
            exp.Count: "count",
            exp.Sum: "sum",
            exp.Avg: "mean",
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

        if isinstance(node, exp.Count) and (
            node.this is None or isinstance(node.this, exp.Star)
        ):
            return "__all__", "size"
        col = self._column_name(node.this) if node.this is not None else "__all__"
        return col, func

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
                return f"({left}.notna())"
            return f"({left}.isna())"
        if isinstance(node, exp.In):
            left = self._value_expr(node.this, df_var)
            vals = ", ".join(self._value_expr(v, df_var) for v in node.expressions)
            return f"({left}.isin([{vals}]))"
        if isinstance(node, exp.Like):
            left = self._value_expr(node.this, df_var)
            pat = self._value_expr(node.expression, df_var)
            self.review.append("LIKE approximated with pandas str.contains")
            return f"({left}.astype(str).str.contains(str({pat}).replace('%', ''), na=False))"
        if isinstance(node, exp.Between):
            val = self._value_expr(node.this, df_var)
            low = self._value_expr(node.args["low"], df_var)
            high = self._value_expr(node.args["high"], df_var)
            return f"(({val}) >= ({low})) & (({val}) <= ({high}))"
        self.review.append(f"Complex predicate approximated: {node.__class__.__name__}")
        return f"(True)  # TODO: {node.sql()}"

    def _value_expr(self, node: exp.Expression, df_var: str) -> str:
        if node is None:
            return "None"
        if isinstance(node, exp.Column):
            if self._dual_mode and node.name.lower() != "_dual":
                # Unqualified names on DUAL are constants / binds, not table columns
                self.review.append(
                    f"Column `{node.name}` on DUAL treated as null constant — replace with a real value"
                )
                return "pd.NA"
            return f"{df_var}[{node.name!r}]"
        if isinstance(node, exp.Literal):
            if node.is_string:
                return repr(node.this)
            return str(node.this)
        if isinstance(node, exp.Boolean):
            return "True" if node.this else "False"
        if isinstance(node, exp.Null):
            return "pd.NA"
        if isinstance(node, exp.Paren):
            return f"({self._value_expr(node.this, df_var)})"
        if isinstance(node, exp.Sub):
            left = self._value_expr(node.left, df_var)
            right = self._value_expr(node.right, df_var)
            if isinstance(node.left, (exp.CurrentDate, exp.CurrentTimestamp)) and isinstance(
                node.right, exp.Literal
            ) and not node.right.is_string:
                return f"({left} - pd.Timedelta(days={node.right.this}))"
            return f"({left} - {right})"
        if isinstance(node, exp.Add):
            left = self._value_expr(node.left, df_var)
            right = self._value_expr(node.right, df_var)
            if isinstance(node.left, (exp.CurrentDate, exp.CurrentTimestamp)) and isinstance(
                node.right, exp.Literal
            ) and not node.right.is_string:
                return f"({left} + pd.Timedelta(days={node.right.this}))"
            return f"({left} + {right})"
        if isinstance(node, exp.Mul):
            return f"({self._value_expr(node.left, df_var)} * {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.Div):
            return f"({self._value_expr(node.left, df_var)} / {self._value_expr(node.right, df_var)})"
        if isinstance(node, exp.Coalesce):
            parts = [self._value_expr(node.this, df_var)] if node.this is not None else []
            parts.extend(self._value_expr(x, df_var) for x in (node.expressions or []))
            if not parts:
                return "pd.NA"
            if len(parts) == 1:
                return parts[0]
            return f"_coalesce({', '.join(parts)})"
        if isinstance(node, exp.Anonymous):
            name = (node.name or "").upper()
            args = node.expressions
            if name in {"NVL", "IFNULL", "ZEROIFNULL"} and args:
                base = self._value_expr(args[0], df_var)
                fill = self._value_expr(args[1], df_var) if len(args) > 1 else "0"
                if name == "ZEROIFNULL" and len(args) == 1:
                    fill = "0"
                return f"_coalesce({base}, {fill})"
            if name == "GREATEST" and len(args) >= 2:
                return (
                    f"np.maximum({self._value_expr(args[0], df_var)}, "
                    f"{self._value_expr(args[1], df_var)})"
                )
            if name == "LEAST" and len(args) >= 2:
                return (
                    f"np.minimum({self._value_expr(args[0], df_var)}, "
                    f"{self._value_expr(args[1], df_var)})"
                )
            self.review.append(f"Function {name} needs review in pandas output")
            return f"({self._value_expr(args[0], df_var) if args else 'pd.NA'})  # TODO:{name}"
        if isinstance(node, exp.Cast):
            return f"({self._value_expr(node.this, df_var)})"
        if isinstance(node, exp.CurrentDate):
            return "pd.Timestamp.today().normalize()"
        if isinstance(node, exp.CurrentTimestamp):
            return "pd.Timestamp.now()"
        if isinstance(node, (exp.Upper, exp.Lower)):
            fn = "upper" if isinstance(node, exp.Upper) else "lower"
            return f"({self._value_expr(node.this, df_var)}).astype(str).str.{fn}()"
        if isinstance(node, exp.Case):
            self.review.append("CASE expression approximated — review branching")
            ifs = node.args.get("ifs") or []
            default = node.args.get("default")
            if ifs:
                when = ifs[0]
                cond = self._bool_expr(when.this, df_var)
                tru = self._value_expr(when.args.get("true"), df_var)
                fal = self._value_expr(default, df_var) if default is not None else "pd.NA"
                return f"np.where({cond}, {tru}, {fal})"
            return "pd.NA"
        try:
            sql = node.sql()
        except Exception:
            sql = node.__class__.__name__
        self.review.append(f"Expression approximated: {node.__class__.__name__}")
        return f"(pd.NA)  # TODO: {sql}"

    def _project_expr(self, node: exp.Expression, df_var: str) -> tuple[str, str]:
        alias = node.alias if isinstance(node, exp.Alias) else None
        inner = node.this if isinstance(node, exp.Alias) else node
        name = alias or self._column_name(inner)
        return name, self._value_expr(inner, df_var)
