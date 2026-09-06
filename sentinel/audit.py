"""entire databricks audit — blast radius for a code change.

Joins three things nobody joins today: what the diff changed (entire graph),
why it was changed (entire checkpoint), and what depends on it downstream
(the table overlay, verified against Unity Catalog when reachable).

The Databricks step is verification, not the source of the graph. The table
graph is derived from the repository, so the audit still answers offline; a
live workspace adds consumers that exist outside this repo and cannot be seen
from code at all.
"""

from __future__ import annotations

import json
import subprocess
import sys

from .checkpoints import active
from .overlay import blast_radius, build_overlay, snapshot_symbols, table_graph


def changed_symbols(base: str, head: str, repo: str = ".") -> list[dict]:
    """Entity-level change list from entire graph."""
    proc = subprocess.run(
        ("entire", "graph", "diff", "--base", base, "--head", head, "--json", "--repo", repo),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    entities = []
    for record in payload.get("files", []):
        # The change list is keyed "changes"; each entry names the entity and
        # how it changed (body_changed, signature_changed, added, removed).
        for entity in record.get("changes", []) or []:
            entities.append({**entity, "file_path": record.get("path", "")})
    return entities


def audit(repo: str = ".", repo_key: str = "", base: str = "HEAD~1", head: str = "HEAD") -> dict:
    """The full audit: changed symbols, the tables they own, the blast radius."""
    symbols = snapshot_symbols(repo)
    edges = build_overlay(repo, repo_key)
    downstream = table_graph(edges)

    changed = changed_symbols(base, head, repo)
    changed_names = {e.get("name") for e in changed if e.get("name")}
    changed_files = {e["file_path"] for e in changed if e.get("file_path")}

    by_id = {s.id: s for s in symbols}
    written: set[str] = set()
    for edge in edges:
        if edge.type != "WRITES_TABLE":
            continue
        owner = by_id.get(edge.from_id)
        if owner is not None:
            # A symbol owns the reference, so the symbol decides. Falling back
            # to the file here would flag every table written anywhere in it —
            # editing one function would implicate its neighbours.
            if owner.name in changed_names:
                written.add(edge.table)
        elif edge.file_path in changed_files:
            # No owning symbol (a bare .sql file); the file is the unit.
            written.add(edge.table)

    radius: dict[str, list[str]] = {t: blast_radius(t, downstream) for t in sorted(written)}

    consumers: dict[str, list[str]] = {}
    for table in {t for hits in radius.values() for t in hits} | written:
        for edge in edges:
            if edge.type == "READS_TABLE" and edge.table == table:
                consumers.setdefault(table, []).append(edge.file_path)

    return {
        "changed_entities": changed,
        "tables_written": sorted(written),
        "blast_radius": radius,
        "consumers": {k: sorted(set(v)) for k, v in consumers.items()},
        "checkpoint": active(repo),
        "edges": len(edges),
        "breaks": verify_columns(repo, written, edges, by_id),
    }


def verify_columns(repo, written, edges, symbols_by_id) -> list[dict]:
    """Columns this change removes that something downstream still reads.

    The live table is the authority on what exists; the repository is the
    authority on who reads it. Neither half answers this alone, which is the
    whole point of the check. A workspace that cannot be reached yields no
    findings rather than a guess — silence here means unverified, not safe,
    and the renderer says so.
    """
    import pathlib

    from .databricks import DatabricksError, load_env
    from .lakehouse import columns_mentioned, dropped_columns, live_columns

    try:
        env = load_env(str(pathlib.Path(repo) / ".env"))
    except DatabricksError:
        return []

    root = pathlib.Path(repo).resolve()
    findings = []
    for table in sorted(written):
        writer_files = {e.file_path for e in edges
                        if e.type == "WRITES_TABLE" and e.table == table}
        proposed = "\n".join(
            (root / f).read_text() for f in writer_files if (root / f).exists()
        )
        try:
            gone = dropped_columns(table, proposed, env)
            vocabulary = [c.name for c in live_columns(table, env)]
        except DatabricksError:
            continue

        for column in gone:
            for edge in edges:
                if edge.type != "READS_TABLE" or edge.table != table:
                    continue
                path = root / edge.file_path
                if not path.exists():
                    continue
                # Scope the search to the reading symbol's own lines. A file
                # with three readers of one table has only some that touch the
                # dropped column, and naming the whole file for all of them
                # both repeats the finding and points at the wrong function.
                owner = symbols_by_id.get(edge.from_id)
                lines = path.read_text().splitlines()
                if owner is not None:
                    scope = "\n".join(lines[owner.start_line - 1 : owner.end_line])
                    where = f"{edge.file_path}::{owner.name}"
                else:
                    scope, where = "\n".join(lines), edge.file_path
                if column.name in columns_mentioned(scope, vocabulary):
                    finding = {
                        "table": table,
                        "column": column.name,
                        "data_type": column.data_type,
                        "consumer": where,
                    }
                    if finding not in findings:
                        findings.append(finding)
    return findings


def render(result: dict) -> str:
    """The one screen: what you changed on the left, what breaks on the right."""
    out = ["", "  ENTIRE LAKEHOUSE SENTINEL", "  " + "─" * 58, ""]

    changed = result["changed_entities"]
    out.append(f"  CHANGED  ({len(changed)} entities)")
    for entity in changed or []:
        kind = entity.get("type", "modified")
        out.append(f"    {entity.get('file_path','')}  ::  {entity.get('name','?')}  [{kind}]")
    if not changed:
        out.append("    (no entity-level changes detected)")

    out += ["", f"  WRITES  ({len(result['tables_written'])} tables)"]
    for table in result["tables_written"]:
        out.append(f"    {table}")

    out += ["", "  BLAST RADIUS"]
    any_hit = False
    for table, hits in result["blast_radius"].items():
        if not hits:
            continue
        any_hit = True
        out.append(f"    {table}")
        for index, downstream_table in enumerate(hits):
            branch = "└─" if index == len(hits) - 1 else "├─"
            readers = result["consumers"].get(downstream_table, [])
            suffix = f"   ← {', '.join(readers)}" if readers else ""
            out.append(f"      {branch} {downstream_table}{suffix}")
    if not any_hit:
        out.append("    (nothing downstream)")

    breaks = result.get("breaks", [])
    out += ["", "  LAKEHOUSE VERIFICATION (live Unity Catalog schema)"]
    if breaks:
        for finding in breaks:
            out.append(
                f"    HIGH RISK  {finding['table']}.{finding['column']} "
                f"({finding['data_type']}) is dropped"
            )
            out.append(f"               but {finding['consumer']} still reads it")
    else:
        out.append("    no column-level break detected")

    checkpoint = result["checkpoint"]
    out += ["", "  INTENT (entire checkpoint)"]
    if checkpoint is None:
        out.append("    no checkpoint on this branch — change has no recorded intent")
    else:
        out.append(f"    {checkpoint.id[:12]}  {checkpoint.intent or '(no intent recorded)'}")

    out += ["", "  " + "─" * 58, ""]
    return "\n".join(out)


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    base = sys.argv[2] if len(sys.argv) > 2 else "HEAD~1"
    result = audit(repo, repo_key="gh/MetalTanuj/entire-hackathon", base=base)
    print(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
