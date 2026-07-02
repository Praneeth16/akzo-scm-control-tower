"""Text2SQL — natural-language-to-governed-SQL module.

Takes the SCM Genie space instructions (`scm_space.md`, bundled next to this
file) as the system prompt, asks the chat model to turn an NL question into a
single Spark SQL statement, executes it on the governed warehouse, and
returns {sql, columns, rows}.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

import databricks_client as dbx

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_GENIE = os.environ.get("GENIE_INSTRUCTIONS_PATH", os.path.join(_HERE, "scm_space.md"))

_SYSTEM_PREAMBLE = """You are a Spark SQL generator for a governed Databricks lakehouse.
Use ONLY the tables, columns, and business definitions described below. Never invent columns.
Return a SINGLE Spark SQL statement that answers the question — no commentary, no markdown
fences, no trailing semicolon explanation. If the question cannot be answered from these tables,
return exactly: SELECT 'out_of_scope' AS error.

Domain instructions:
---
{instructions}
---
Output ONLY the SQL.
"""


@lru_cache(maxsize=8)
def _instructions(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def _strip_sql(text: str) -> str:
    """Pull a clean SQL statement out of a model response (handles code fences)."""
    t = text.strip()
    fence = re.search(r"```(?:sql)?\s*(.+?)```", t, re.DOTALL | re.IGNORECASE)
    if fence:
        t = fence.group(1).strip()
    return t.rstrip(";").strip()


def generate_sql(question: str, genie_instructions_path: str | None = None) -> str:
    """NL question -> Spark SQL string, grounded in the domain Genie instructions."""
    path = genie_instructions_path or _DEFAULT_GENIE
    system = _SYSTEM_PREAMBLE.format(instructions=_instructions(path))
    raw = dbx.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        max_tokens=800,
    )
    return _strip_sql(raw)


def ask(question: str, genie_instructions_path: str | None = None) -> dict:
    """NL question -> {sql, columns, rows, row_count}. The full text2sql round trip."""
    sql = generate_sql(question, genie_instructions_path)
    result = dbx.run_sql(sql)
    return {"sql": sql, **result}
