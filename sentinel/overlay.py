"""Bind data facts to code symbols, producing the edges the graph lacks.

entire-graph knows functions; it has no node kind for a table and no edge kind
for "writes to". Rather than fork its parser, we consume its NDJSON snapshot and
emit an overlay in the same shape: the union is a graph that spans code and data.

The join is interval containment. A symbol record carries file_path, start_line
and end_line; an extracted table reference carries a file and a line. The symbol
whose range encloses that line owns the reference. Where several enclose it
(a method inside a class), the innermost wins — the narrowest range is the one a
developer would name as the thing they changed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .sqlrefs import table_refs


@dataclass(frozen=True)
class Symbol:
    """A code symbol as entire-graph reported it."""

    id: str
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int

    def contains(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line

    @property
    def span(self) -> int:
        return self.end_line - self.start_line


@dataclass(frozen=True)
class TableEdge:
    """One overlay relation: a symbol reads or writes a table."""

    from_id: str
    table: str
    type: str  # READS_TABLE | WRITES_TABLE
    file_path: str
    line: int

    def as_relation(self, repo_key: str) -> dict:
        """The graph's own NDJSON relation shape, so the two merge cleanly."""
        return {
            "record_type": "relation",
            "type": self.type,
            "from_id": self.from_id,
            "to_id": f"{repo_key}:Table:{self.table}",
            "to_kind": "table",
            "resolution": "literal",
            "evidence": {"file_path": self.file_path, "line": self.line},
        }


def snapshot_symbols(repo: str = ".") -> list[Symbol]:
    """Every symbol entire-graph knows about, via its NDJSON contract."""
    proc = subprocess.run(
        ("entire", "graph", "symbols", "--repo", repo),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"entire graph symbols failed: {proc.stderr.strip()}")

    symbols = []
    for line in proc.stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("record_type") != "symbol":
            continue
        symbols.append(
            Symbol(
                id=record["id"],
                name=record.get("name", ""),
                kind=record.get("kind", ""),
                file_path=record.get("file_path", ""),
                start_line=record.get("start_line", 0),
                end_line=record.get("end_line", 0),
            )
        )
    return symbols


def owner_of(symbols: list[Symbol], file_path: str, line: int) -> Symbol | None:
    """The innermost symbol enclosing a line, or None for file-level code.

    A reference outside every symbol is real and common — a bare SQL file, or a
    module-level constant. It gets no owner rather than being misattributed to
    whichever function happens to sit nearest.
    """
    enclosing = [
        symbol
        for symbol in symbols
        if symbol.file_path == file_path and symbol.contains(line)
    ]
    return min(enclosing, key=lambda s: s.span) if enclosing else None


def _line_of(text: str, needle: str, start: int = 0) -> int:
    index = text.find(needle, start)
    return text.count("\n", 0, index) + 1 if index >= 0 else 1


def edges_for_sql_file(
    path: str, text: str, symbols: list[Symbol], repo_key: str
) -> list[TableEdge]:
    """Overlay edges for a standalone .sql file.

    These are the ones entire-graph currently misses entirely: a .sql file
    produces no symbols at all, so a dashboard query reading a gold table is
    invisible to impact analysis. With no enclosing symbol, the file itself is
    the owner — which is the honest attribution for a query that is its own unit.
    """
    refs = table_refs(text)
    edges = []
    for table, relation in (
        *((t, "READS_TABLE") for t in sorted(refs.reads)),
        *((t, "WRITES_TABLE") for t in sorted(refs.writes)),
    ):
        line = _line_of(text, table.split(".")[-1])
        owner = owner_of(symbols, path, line)
        edges.append(
            TableEdge(
                from_id=owner.id if owner else f"{repo_key}:file:{path}",
                table=table,
                type=relation,
                file_path=path,
                line=line,
            )
        )
    return edges
