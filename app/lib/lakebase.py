"""Lakebase (managed Postgres) access — the SHARED write-back module.

Reused verbatim by the sibling Supervisor and Finance apps for their own
write-back tables (forecast_overrides, scm_interventions, commercial_actions,
agent_sessions, ...). This is the *write* governance plane: a short-lived DB
credential (the app/service write identity) generated via the SDK, psycopg3,
sslmode=require, search_path set to the `akzo` schema.

The credential is short-lived (~1h), so we cache it and transparently refresh on
expiry. `query()` / `execute()` open a fresh autocommit connection per call —
simple and correct for an app's low write volume; swap in a pool later if needed.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql as psql
from psycopg.rows import dict_row

from databricks_client import client, current_user

INSTANCE_NAME = os.environ.get("LAKEBASE_INSTANCE", "<your-lakebase-instance>")
DB_NAME = os.environ.get("LAKEBASE_DBNAME", "databricks_postgres")
PG_SCHEMA = os.environ.get("LAKEBASE_SCHEMA", "akzo")

_lock = threading.Lock()
_host: str | None = None
_token: str | None = None
_token_exp: float = 0.0
# Refresh a little before the ~1h expiry to avoid mid-request failures.
_TOKEN_TTL_SECONDS = 45 * 60


def _read_write_host() -> str:
    global _host
    if _host is None:
        with _lock:
            if _host is None:
                inst = client().database.get_database_instance(name=INSTANCE_NAME)
                _host = inst.read_write_dns
    return _host


def _db_token() -> str:
    """Short-lived Lakebase credential — the app/service write identity. Cached + refreshed."""
    global _token, _token_exp
    now = time.time()
    if _token is None or now >= _token_exp:
        with _lock:
            # Re-check inside the lock (another thread may have just refreshed).
            if _token is None or time.time() >= _token_exp:
                cred = client().database.generate_database_credential(instance_names=[INSTANCE_NAME])
                _token = cred.token
                _token_exp = now + _TOKEN_TTL_SECONDS
    return _token


@contextmanager
def connection():
    """Open an autocommit psycopg connection with search_path set to the akzo schema.

    Rows come back as dicts. Transparently retries once with a fresh token if the
    cached credential has expired.
    """
    def _connect() -> psycopg.Connection:
        return psycopg.connect(
            host=_read_write_host(), port=5432, dbname=DB_NAME,
            user=current_user(), password=_db_token(), sslmode="require",
            autocommit=True, row_factory=dict_row,
        )

    try:
        conn = _connect()
    except psycopg.OperationalError:
        # Likely an expired token — force a refresh and retry once.
        global _token
        _token = None
        conn = _connect()

    try:
        with conn.cursor() as cur:
            cur.execute(
                psql.SQL("SET search_path TO {}").format(psql.Identifier(PG_SCHEMA))
            )
        yield conn
    finally:
        conn.close()


def query(sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """Run a read query, return list-of-dicts."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute(sql: str, params: tuple | None = None, returning: bool = False):
    """Run a write. If returning=True, fetch and return the first row (a dict)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        if returning:
            return cur.fetchone()
        return None
