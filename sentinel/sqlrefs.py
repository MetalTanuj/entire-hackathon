"""Extract table references from SQL.

This is the fact `entire graph` does not have: a .sql file currently yields zero
symbols, so a dashboard query reading a gold table is invisible to impact
analysis. Everything here is a pure function of the text — the same input always
gives the same output, no network, no state — which is the bar the graph's own
boundary doc sets for a fact belonging in the provider.

Deliberately not a SQL parser. It recognises the clauses that name a table and
ignores the rest of the grammar; a query whose shape we do not recognise yields
no reference rather than a wrong one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A table name: optionally catalog-qualified, dot-separated, backtick-tolerant.
_NAME = r"`?([A-Za-z_][\w]*(?:`?\.`?[A-Za-z_][\w]*){0,2})`?"

# Clauses that READ a table.
_READS = (
    re.compile(r"\bFROM\s+" + _NAME, re.I),
    re.compile(r"\bJOIN\s+" + _NAME, re.I),
)

# Clauses that WRITE a table. CREATE/INSERT/MERGE name their target directly.
_WRITES = (
    re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _NAME, re.I),
    re.compile(r"\bINSERT\s+(?:INTO|OVERWRITE)\s+(?:TABLE\s+)?" + _NAME, re.I),
    re.compile(r"\bMERGE\s+INTO\s+" + _NAME, re.I),
    re.compile(r"\bUPDATE\s+" + _NAME, re.I),
)

# Names that follow FROM/JOIN but are not tables.
_NOT_A_TABLE = frozenset({"select", "values", "lateral", "unnest", "table"})


def _strip_noise(sql: str) -> str:
    """Remove comments and string literals.

    A table name inside a quoted string is data, not a reference, and a name
    inside a comment is not a dependency — counting either is how an extractor
    reports a table nothing actually reads.
    """
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"'(?:[^']|'')*'", " ", sql)
    return sql


def _clean(name: str) -> str:
    return name.replace("`", "").strip()


@dataclass(frozen=True)
class TableRefs:
    """Tables a SQL text reads and writes."""

    reads: frozenset[str]
    writes: frozenset[str]

    def __bool__(self) -> bool:
        return bool(self.reads or self.writes)


def table_refs(sql: str) -> TableRefs:
    """Every table this SQL reads from and writes to."""
    text = _strip_noise(sql)

    def collect(patterns) -> set[str]:
        found = set()
        for pattern in patterns:
            for match in pattern.finditer(text):
                name = _clean(match.group(1))
                if name and name.lower() not in _NOT_A_TABLE:
                    found.add(name)
        return found

    writes = collect(_WRITES)
    # A CTE is defined and read inside the same statement; it is not a stored
    # table and must not surface as a dependency on one.
    ctes = {
        _clean(m.group(1))
        for m in re.finditer(r"\b(?:WITH|,)\s+`?(\w+)`?\s+AS\s*\(", text, re.I)
    }
    reads = collect(_READS) - ctes - writes
    return TableRefs(reads=frozenset(reads), writes=frozenset(writes - ctes))
