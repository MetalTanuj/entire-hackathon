"""Read Entire checkpoints — the agent's stated intent behind a change.

The CLI is the source of truth for its own output. We shell out rather than
reading .entire/ directly, so a checkpoint-format change is theirs to absorb,
not ours. Every accessor tolerates a missing key: the envelope is documented by
`entire agent-help checkpoint explain`, but its exact field names are only
confirmed against a real checkpoint, and a KeyError here would take down an
audit run over a field we merely hoped for.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


class CheckpointUnavailable(RuntimeError):
    """Entire is not enabled here, or has no checkpoints to read."""


def _entire(*args: str, cwd: str = ".") -> str:
    proc = subprocess.run(
        ("entire",) + args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise CheckpointUnavailable(
            f"entire {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _first_str(payload: dict, *names: str) -> str:
    """First present, non-empty string among `names`."""
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@dataclass
class Checkpoint:
    """One checkpoint, reduced to what the audit actually reasons about."""

    id: str
    session: str = ""
    intent: str = ""
    files: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_envelope(cls, payload: dict) -> "Checkpoint":
        files = payload.get("files") or payload.get("changed_files") or []
        # Files may arrive as bare paths or as objects carrying a path plus a
        # change kind; both shapes flatten to the paths we join on.
        paths = []
        for entry in files:
            if isinstance(entry, str):
                paths.append(entry)
            elif isinstance(entry, dict):
                path = _first_str(entry, "path", "file", "file_path")
                if path:
                    paths.append(path)
        return cls(
            id=_first_str(payload, "id", "checkpoint_id", "sha"),
            session=_first_str(payload, "session", "session_id"),
            intent=_first_str(payload, "intent", "summary", "description"),
            files=paths,
            raw=payload,
        )


def list_checkpoints(cwd: str = ".") -> list[Checkpoint]:
    """Every checkpoint on the current branch, newest first per the CLI."""
    payload = json.loads(_entire("checkpoint", "list", "--json", cwd=cwd) or "{}")
    # The list view has been seen as a bare array and as an object wrapping one;
    # accept either rather than pinning to whichever shipped today.
    entries = payload if isinstance(payload, list) else payload.get("checkpoints", [])
    return [Checkpoint.from_envelope(entry) for entry in entries]


def explain(checkpoint_id: str, cwd: str = ".") -> Checkpoint:
    """The full metadata envelope for one checkpoint."""
    payload = json.loads(
        _entire("checkpoint", "explain", checkpoint_id, "--json", cwd=cwd) or "{}"
    )
    if isinstance(payload, dict) and "checkpoint" in payload:
        payload = payload["checkpoint"]
    return Checkpoint.from_envelope(payload)


def active(cwd: str = ".") -> Checkpoint | None:
    """The checkpoint an audit should read: the most recent on this branch.

    Returns None rather than raising when the repo simply has no history yet —
    an audit in a fresh repo is a legitimate state, and should report "no
    recorded intent" rather than failing.
    """
    try:
        found = list_checkpoints(cwd=cwd)
    except CheckpointUnavailable:
        return None
    return found[0] if found else None
