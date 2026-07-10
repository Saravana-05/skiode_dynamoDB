"""
SQL Generator — Query Definition JSON (+ resolved join plan) -> SQL text.

Design rules (deliberate, matches the earlier design discussion):
  - Only IDENTIFIERS (table/column/alias names) are ever placed directly
    into the SQL string, and only after passing a strict whitelist regex.
  - Every VALUE (filter/having values) is bound as an asyncpg $-parameter,
    never string-interpolated.
  - No SQLAlchemy / ORM — this builds a plain SELECT string.

Query Definition JSON shape:
{
  "objects": ["customers", "orders"],
  "fields": [
    {"dmo": "customers", "field": "name", "alias": "customer_name"},
    {"dmo": "orders", "field": "amount", "aggregation": "SUM", "alias": "total_sales"}
  ],
  "filters": [
    {"dmo": "customers", "field": "city", "operator": "=", "value": "Bangalore"}
  ],
  "groupBy": [{"dmo": "customers", "field": "name"}],
  "having": [{"dmo": "orders", "field": "amount", "aggregation": "SUM",
              "operator": ">", "value": 100000}],
  "sort": [{"alias": "total_sales", "direction": "DESC"}]
}
"""
import re

from .relationship_resolver import JoinEdge

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_ALLOWED_OPERATORS = {"=", "!=", "<>", ">", "<", ">=", "<=", "LIKE", "ILIKE", "IN", "NOT IN"}
_ALLOWED_AGGREGATIONS = {"SUM", "COUNT", "AVG", "MIN", "MAX", "COUNT DISTINCT"}


class SqlGenerationError(ValueError):
    pass


def _check_identifier(name: str, what: str) -> str:
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise SqlGenerationError(f"Invalid {what}: {name!r}")
    return name


def _quote(identifier: str) -> str:
    return f'"{identifier}"'


class SqlGenerator:
    def __init__(self, query_json: dict, join_plan: list[JoinEdge]):
        self.q = query_json
        self.join_plan = join_plan
        self._alias_by_dmo: dict[str, str] = {}
        self._params: list = []

    # ── alias assignment ────────────────────────────────────────

    def _assign_aliases(self) -> None:
        objects = self.q.get("objects") or []
        if not objects:
            raise SqlGenerationError("query.objects must contain at least one domain object")

        root = _check_identifier(objects[0], "domain object")
        self._alias_by_dmo[root] = "t0"
        i = 1
        for edge in self.join_plan:
            for dmo in (edge.left_dmo, edge.right_dmo):
                _check_identifier(dmo, "domain object")
                if dmo not in self._alias_by_dmo:
                    self._alias_by_dmo[dmo] = f"t{i}"
                    i += 1

    def _alias(self, dmo: str) -> str:
        _check_identifier(dmo, "domain object")
        alias = self._alias_by_dmo.get(dmo)
        if alias is None:
            raise SqlGenerationError(
                f"'{dmo}' is not part of the resolved join plan — "
                f"add it to query.objects or define a relationship for it."
            )
        return alias

    # ── expression builders ─────────────────────────────────────

    def _column_expr(self, dmo: str, field: str) -> str:
        _check_identifier(field, "field")
        return f"{self._alias(dmo)}.{_quote(field)}"

    def _aggregate_expr(self, dmo: str, field: str, aggregation: str) -> str:
        agg = aggregation.upper()
        if agg not in _ALLOWED_AGGREGATIONS:
            raise SqlGenerationError(f"Unsupported aggregation: {aggregation!r}")
        col = self._column_expr(dmo, field)
        if agg == "COUNT DISTINCT":
            return f"COUNT(DISTINCT {col})"
        return f"{agg}({col})"

    def _field_expr(self, f: dict) -> str:
        dmo, field = f["dmo"], f["field"]
        if f.get("aggregation"):
            return self._aggregate_expr(dmo, field, f["aggregation"])
        return self._column_expr(dmo, field)

    # ── clause builders ──────────────────────────────────────────

    def _build_select(self) -> str:
        fields = self.q.get("fields") or []
        if not fields:
            raise SqlGenerationError("query.fields must not be empty")
        parts = []
        for f in fields:
            expr = self._field_expr(f)
            alias = f.get("alias")
            if alias:
                _check_identifier(alias, "field alias")
                parts.append(f"{expr} AS {_quote(alias)}")
            else:
                parts.append(expr)
        return "SELECT " + ", ".join(parts)

    def _build_from_join(self) -> str:
        root_dmo = self.q["objects"][0]
        sql = f'FROM {_quote(root_dmo)} {self._alias(root_dmo)}'
        for edge in self.join_plan:
            left_alias = self._alias(edge.left_dmo)
            right_alias = self._alias(edge.right_dmo)
            # whichever side wasn't already joined is the one we're introducing
            if edge.right_dmo not in self._joined_so_far:
                new_dmo, new_alias = edge.right_dmo, right_alias
                on_left = f"{left_alias}.{_quote(edge.left_field)}"
                on_right = f"{right_alias}.{_quote(edge.right_field)}"
            else:
                new_dmo, new_alias = edge.left_dmo, left_alias
                on_left = f"{right_alias}.{_quote(edge.right_field)}"
                on_right = f"{left_alias}.{_quote(edge.left_field)}"
            self._joined_so_far.add(new_dmo)
            sql += f'\nJOIN {_quote(new_dmo)} {new_alias} ON {on_left} = {on_right}'
        return sql

    def _build_condition_clause(self, dmo: str, field: str, operator: str, value) -> str:
        """Builds a single `column OP $n` (or `column OP ($n, $n+1, ...)`)
        clause and appends the bound value(s) to self._params. Shared by
        both the legacy flat-filter path and the nested filter_tree path,
        so they can never drift apart on operator whitelisting or param
        binding behavior."""
        expr = self._column_expr(dmo, field)
        op = (operator or "=").upper()
        if op not in _ALLOWED_OPERATORS:
            raise SqlGenerationError(f"Unsupported operator: {operator!r}")
        if op in ("IN", "NOT IN"):
            values = value if isinstance(value, list) else [value]
            placeholders = []
            for v in values:
                self._params.append(v)
                placeholders.append(f"${len(self._params)}")
            return f"{expr} {op} ({', '.join(placeholders)})"
        self._params.append(value)
        return f"{expr} {op} ${len(self._params)}"

    def _build_filter_tree_clause(self, node: dict) -> str:
        """Recursively renders a filter_tree node (leaf condition or
        AND/OR group) into a parenthesized SQL boolean expression."""
        node_type = node.get("type", "condition")

        if node_type == "group":
            children = node.get("children") or []
            if not children:
                return "TRUE"  # empty group is a no-op, never "filter everything out"
            operator = node.get("operator", "AND").upper()
            if operator not in ("AND", "OR"):
                raise SqlGenerationError(f"Unsupported group operator: {node.get('operator')!r}")
            rendered = [self._build_filter_tree_clause(c) for c in children]
            return "(" + f" {operator} ".join(rendered) + ")"

        # leaf condition
        if "dmo" not in node or "field" not in node:
            raise SqlGenerationError(f"filter_tree condition missing dmo/field: {node!r}")
        return self._build_condition_clause(
            node["dmo"], node["field"], node.get("operator", "="), node.get("value")
        )

    def _build_where(self) -> str:
        # `filter_tree` (nested AND/OR) takes precedence over the legacy
        # flat `filters` list when both are present, so old callers that
        # only ever send `filters` are completely unaffected.
        filter_tree = self.q.get("filter_tree")
        if filter_tree:
            clause = self._build_filter_tree_clause(filter_tree)
            return "" if clause == "TRUE" else f"WHERE {clause}"

        filters = self.q.get("filters") or []
        if not filters:
            return ""
        clauses = [
            self._build_condition_clause(flt["dmo"], flt["field"], flt.get("operator", "="), flt["value"])
            for flt in filters
        ]
        return "WHERE " + " AND ".join(clauses)

    def _build_group_by(self) -> str:
        group_by = self.q.get("groupBy") or []
        if not group_by:
            return ""
        exprs = [self._column_expr(g["dmo"], g["field"]) for g in group_by]
        return "GROUP BY " + ", ".join(exprs)

    def _build_having(self) -> str:
        having = self.q.get("having") or []
        if not having:
            return ""
        clauses = []
        for h in having:
            if h.get("aggregation"):
                expr = self._aggregate_expr(h["dmo"], h["field"], h["aggregation"])
            else:
                expr = self._column_expr(h["dmo"], h["field"])
            op = h.get("operator", ">").upper()
            if op not in _ALLOWED_OPERATORS:
                raise SqlGenerationError(f"Unsupported operator: {h.get('operator')!r}")
            self._params.append(h["value"])
            clauses.append(f"{expr} {op} ${len(self._params)}")
        return "HAVING " + " AND ".join(clauses)

    def _build_order_by(self) -> str:
        sort = self.q.get("sort") or []
        if not sort:
            return ""
        parts = []
        for s in sort:
            direction = s.get("direction", "ASC").upper()
            if direction not in ("ASC", "DESC"):
                raise SqlGenerationError(f"Invalid sort direction: {s.get('direction')!r}")
            if s.get("alias"):
                # ORDER BY output-column-name is valid in PostgreSQL
                parts.append(f'{_quote(_check_identifier(s["alias"], "sort alias"))} {direction}')
            else:
                parts.append(f'{self._column_expr(s["dmo"], s["field"])} {direction}')
        return "ORDER BY " + ", ".join(parts)

    # ── public API ────────────────────────────────────────────────

    def generate(self) -> tuple[str, list]:
        """Returns (sql_text, params)."""
        self._assign_aliases()
        self._joined_so_far = {self.q["objects"][0]}

        clauses = [
            self._build_select(),
            self._build_from_join(),
            self._build_where(),
            self._build_group_by(),
            self._build_having(),
            self._build_order_by(),
        ]
        sql_text = "\n".join(c for c in clauses if c)
        return sql_text, self._params