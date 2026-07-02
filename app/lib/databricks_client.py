"""Databricks SDK access — the SHARED backend module.

Reused verbatim by the sibling Supervisor and Finance apps. Provides:
  - a process-wide WorkspaceClient singleton (auths via the app service principal
    in Databricks Apps, or via the CLI profile `DATABRICKS_CONFIG_PROFILE` locally),
  - `run_sql(...)`  — execute governed Spark SQL on the serverless SQL warehouse and
    return {columns, rows} with rows as list-of-dicts,
  - `chat(...)`     — query a Databricks Model Serving chat endpoint (OpenAI-style messages).

Nothing here is quote-specific, so the other two apps import it unchanged.
"""
from __future__ import annotations

import os
import threading
from functools import lru_cache
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

# Defaults for this workspace; override via env in app.yaml / .env.
SQL_WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "<your-warehouse-id>")
CHAT_ENDPOINT = os.environ.get("DATABRICKS_CHAT_ENDPOINT", "databricks-claude-opus-4-8")

_lock = threading.Lock()
_client: WorkspaceClient | None = None


def client() -> WorkspaceClient:
    """Return the process-wide WorkspaceClient singleton (thread-safe)."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = WorkspaceClient()
    return _client


@lru_cache(maxsize=1)
def current_user() -> str:
    """The identity the SDK is authenticating as (email)."""
    return client().current_user.me().user_name


def run_sql(statement: str, warehouse_id: str | None = None, wait_timeout: str = "50s") -> dict[str, Any]:
    """Execute governed SQL on the serverless warehouse.

    Returns {"columns": [..], "rows": [{col: val, ...}, ...], "row_count": n}.
    Raises RuntimeError on a non-SUCCEEDED terminal state.
    """
    resp = client().statement_execution.execute_statement(
        warehouse_id=warehouse_id or SQL_WAREHOUSE_ID,
        statement=statement,
        wait_timeout=wait_timeout,
    )
    state = resp.status.state.value if resp.status and resp.status.state else "UNKNOWN"
    if state != "SUCCEEDED":
        msg = resp.status.error.message if resp.status and resp.status.error else state
        raise RuntimeError(f"SQL execution {state}: {msg}")

    columns: list[str] = []
    if resp.manifest and resp.manifest.schema and resp.manifest.schema.columns:
        columns = [c.name for c in resp.manifest.schema.columns]

    data = (resp.result.data_array if resp.result else None) or []
    rows = [dict(zip(columns, raw)) for raw in data]
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def chat(messages: list[dict[str, str]], endpoint: str | None = None,
         max_tokens: int = 1024, temperature: float | None = None) -> str:
    """Query a Model Serving chat endpoint. `messages` is OpenAI-style
    [{"role": "system"|"user"|"assistant", "content": str}, ...]. Returns text.

    Note: some endpoints (e.g. databricks-claude-opus-4-8) reject the
    `temperature` parameter, so it is only sent when explicitly provided."""
    role_map = {
        "system": ChatMessageRole.SYSTEM,
        "user": ChatMessageRole.USER,
        "assistant": ChatMessageRole.ASSISTANT,
    }
    chat_messages = [
        ChatMessage(role=role_map[m["role"]], content=m["content"]) for m in messages
    ]
    kwargs = {"name": endpoint or CHAT_ENDPOINT, "messages": chat_messages,
              "max_tokens": max_tokens}
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = client().serving_endpoints.query(**kwargs)
    return resp.choices[0].message.content
