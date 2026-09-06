"""Extract table references from Python.

Two shapes carry a table name in Spark code: the DataFrame API names it in a
call argument (`spark.table("x")`, `df.write.saveAsTable("x")`), and raw SQL
arrives as a string handed to `spark.sql(...)`. Both are handled here; the SQL
case defers to `sqlrefs.table_refs` so there is one definition of "what a SQL
statement touches" rather than two that drift.

Names are not always literal. `f"{GOLD}.daily_revenue"` is a real reference that
a literal-only reader would miss, so module-level string constants are folded
first. Every reference records how it was obtained — a folded name is marked
`inferred`, and a caller that needs certainty can drop those rather than having
a guess silently presented as a fact.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .sqlrefs import table_refs

READ_METHODS = frozenset({"table"})
WRITE_METHODS = frozenset({"saveAsTable", "insertInto"})
SQL_METHODS = frozenset({"sql"})

LITERAL = "literal"
INFERRED = "inferred"


@dataclass(frozen=True)
class PyTableRef:
    """One table reference found in Python source."""

    table: str
    direction: str  # READS_TABLE | WRITES_TABLE
    line: int
    resolution: str  # literal | inferred


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level string constants, with f-strings folded against each other.

    `CATALOG = "main"` then `GOLD = f"{CATALOG}.gold"` only resolves if the first
    is known when the second is folded. Source order gives that for free in the
    common case; a second pass catches a forward reference without needing a
    dependency graph for what is, in practice, a handful of names.
    """
    constants: dict[str, str] = {}
    for _ in range(2):
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            value, _ = _resolve(node.value, constants)
            if value is not None:
                constants[target.id] = value
    return constants


def _resolve(node: ast.expr, constants: dict[str, str]) -> tuple[str | None, str]:
    """A node's string value and how certainly it was obtained."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, LITERAL

    if isinstance(node, ast.Name):
        value = constants.get(node.id)
        return (value, INFERRED) if value is not None else (None, INFERRED)

    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                inner, _ = _resolve(piece.value, constants)
                if inner is None:
                    # One unresolvable placeholder makes the whole name a guess.
                    # Half a table name is worse than no reference at all.
                    return None, INFERRED
                parts.append(inner)
            else:
                return None, INFERRED
        return "".join(parts), INFERRED

    return None, INFERRED


def _method_name(call: ast.Call) -> str:
    return call.func.attr if isinstance(call.func, ast.Attribute) else ""


def table_refs_in_python(source: str) -> list[PyTableRef]:
    """Every table this module reads or writes."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # An unparseable file yields nothing rather than falling back to a
        # regex over broken source, which would report references the code
        # does not actually make.
        return []

    constants = _module_constants(tree)
    found: list[PyTableRef] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        method = _method_name(node)

        if method in SQL_METHODS:
            statement, _ = _resolve(node.args[0], constants)
            if statement is None:
                continue
            # An interpolated SQL string is still literal about its table names:
            # the placeholders sit in predicates, not in the FROM clause. The
            # names below were read directly off the statement text.
            refs = table_refs(statement)
            for table in sorted(refs.reads):
                found.append(PyTableRef(table, "READS_TABLE", node.lineno, LITERAL))
            for table in sorted(refs.writes):
                found.append(PyTableRef(table, "WRITES_TABLE", node.lineno, LITERAL))
            continue

        if method in READ_METHODS or method in WRITE_METHODS:
            table, resolution = _resolve(node.args[0], constants)
            # A path is not a table. `.load("/Volumes/...")` and friends reach
            # storage directly, and reporting one as a Delta table would invent
            # a lineage node with nothing on the other end of it.
            if not table or "/" in table:
                continue
            direction = "READS_TABLE" if method in READ_METHODS else "WRITES_TABLE"
            found.append(PyTableRef(table, direction, node.lineno, resolution))

    return found
