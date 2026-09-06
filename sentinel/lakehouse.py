"""Live schema from Unity Catalog, and the column checks it makes possible.

Lineage system tables are empty on this workspace, so the downstream graph comes
from the repository. Schema does not: a medallion pipeline builds every table
with CREATE ... AS SELECT, so no column list is ever declared in code, and the
real one exists only in the Lakehouse. This module is the only source of it.

That inverts the usual matching problem. We do not need to parse SQL well enough
to know which columns a query uses; we ask Databricks for the table's real
columns and check which of those names the query actually mentions. The
authoritative vocabulary comes from the catalog, so a query shape we cannot
parse still yields a correct answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .databricks import DatabricksError, rows, run_sql


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str


def live_columns(table: str, env: dict | None = None) -> list[Column]:
    """The columns a table actually has right now, in ordinal order."""
    parts = table.split(".")
    if len(parts) != 3:
        raise DatabricksError(f"expected catalog.schema.table, got {table!r}")
    catalog, schema, name = parts
    payload = run_sql(
        "SELECT column_name, full_data_type FROM "
        f"{catalog}.information_schema.columns "
        f"WHERE table_catalog='{catalog}' AND table_schema='{schema}' "
        f"AND table_name='{name}' ORDER BY ordinal_position",
        env=env,
    )
    return [Column(row[0], row[1]) for row in rows(payload)]


def table_exists(table: str, env: dict | None = None) -> bool:
    try:
        return bool(live_columns(table, env))
    except DatabricksError:
        return False


def columns_mentioned(sql: str, vocabulary: list[str]) -> set[str]:
    """Which of `vocabulary` this SQL text refers to.

    Word-boundary matching against a known column list, not a parse. A column
    named in a SELECT list, a GROUP BY, or a predicate all count equally,
    because any of them breaks when the column disappears.
    """
    found = set()
    for column in vocabulary:
        if re.search(rf"\b{re.escape(column)}\b", sql, re.I):
            found.add(column)
    return found


@dataclass(frozen=True)
class ColumnRisk:
    """A column that a consumer needs and a change is removing."""

    table: str
    column: str
    data_type: str
    consumer: str

    def describe(self) -> str:
        return (
            f"{self.consumer} reads {self.column} ({self.data_type}) "
            f"from {self.table}"
        )


def dropped_columns(table: str, new_sql: str, env: dict | None = None) -> list[Column]:
    """Live columns the replacement statement no longer produces.

    The live table is the truth about what exists today; the new statement is
    the proposal. Anything present in the first and absent from the second is
    about to disappear from a table other code is already reading.
    """
    live = live_columns(table, env)
    produced = columns_mentioned(new_sql, [c.name for c in live])
    return [c for c in live if c.name not in produced]
