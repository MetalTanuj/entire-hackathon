"""Talk to Databricks over the SQL Statement Execution API.

One dependency-free client rather than the SDK: the audit needs to run in a
pre-commit hook on a developer's machine, and a `pip install databricks-sdk`
between a developer and their commit is a reason not to adopt the tool.

Credentials come from the environment or .env and are never logged. The caller
decides what runs; nothing here writes on its own.
"""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request

API = "/api/2.0/sql/statements"


class DatabricksError(RuntimeError):
    pass


def load_env(path: str = ".env") -> dict[str, str]:
    """Read credentials from the environment, falling back to a .env file."""
    values = {
        key: os.environ[key]
        for key in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID")
        if os.environ.get(key)
    }
    dotenv = pathlib.Path(path)
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values.setdefault(key.strip(), value.strip())
    missing = {"DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"} - values.keys()
    if missing:
        raise DatabricksError(f"missing credentials: {', '.join(sorted(missing))}")
    return values


def run_sql(statement: str, env: dict[str, str] | None = None, wait: str = "30s") -> dict:
    """Execute one SQL statement and return its result payload."""
    env = env or load_env()
    body = json.dumps(
        {
            "statement": statement,
            "warehouse_id": env["DATABRICKS_WAREHOUSE_ID"],
            "wait_timeout": wait,
        }
    ).encode()
    request = urllib.request.Request(
        env["DATABRICKS_HOST"].rstrip("/") + API,
        data=body,
        headers={
            "Authorization": f"Bearer {env['DATABRICKS_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # The body carries the actual reason; the status alone says little.
        raise DatabricksError(f"HTTP {exc.code}: {exc.read().decode()[:400]}") from exc

    state = payload.get("status", {}).get("state")
    if state not in ("SUCCEEDED", "PENDING", "RUNNING"):
        reason = payload.get("status", {}).get("error", {}).get("message", state)
        raise DatabricksError(f"statement {state}: {reason}")
    return payload


def rows(payload: dict) -> list[list]:
    """The data rows of a result payload, or an empty list."""
    return payload.get("result", {}).get("data_array") or []
