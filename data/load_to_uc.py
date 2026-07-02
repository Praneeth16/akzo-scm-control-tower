"""Load the synthetic SCM parquet files into Unity Catalog.

Uses spark.sql() and dbutils.fs — no CLI or SQL warehouse required.
Idempotent: safe to re-run.

Configure with environment variables:
  AKZO_CATALOG   Unity Catalog name  (required)
  AKZO_SCHEMA    Target schema       (required)
  AKZO_STAGING   Staging volume path (required, e.g. /Volumes/<catalog>/<schema>/staging)

Run as a Databricks notebook cell (paste the file, or %run), not from a local
terminal — it needs `spark` and `dbutils`, which only exist inside a notebook.
"""
import os
import sys

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.getcwd()  # cwd is the data/ folder when run interactively

OUT = os.path.join(_here, "output")

CATALOG = os.environ.get("AKZO_CATALOG")
SCHEMA = os.environ.get("AKZO_SCHEMA")
STAGING = os.environ.get("AKZO_STAGING")

if not CATALOG:
    sys.exit("Set AKZO_CATALOG env var.")
if not SCHEMA:
    sys.exit("Set AKZO_SCHEMA env var.")
if not STAGING:
    sys.exit("Set AKZO_STAGING env var, e.g. /Volumes/<catalog>/<schema>/staging")

TABLES = ["otif", "inventory", "lanes", "service_levels"]

FAILURES = []  # (label, message) accumulated across the run


def run_sql(stmt, label=None):
    tag = label or stmt[:60]
    try:
        spark.sql(stmt)
        print(f"  ok  {tag}")
        return True
    except Exception as e:
        msg = str(e)[:300]
        print(f"  FAIL {tag}: {msg}")
        FAILURES.append((tag, msg))
        return False


def upload(local, dest):
    try:
        dbutils.fs.cp(f"file://{local}", dest)
        print(f"  ok  upload {os.path.basename(local)} -> {dest}")
        return True
    except Exception as e:
        msg = str(e)[:200]
        print(f"  FAIL upload {os.path.basename(local)}: {msg}")
        FAILURES.append((f"upload {os.path.basename(local)}", msg))
        return False


def main():
    print("== config ==")
    print(f"  catalog : {CATALOG}")
    print(f"  schema  : {SCHEMA}")
    print(f"  staging : {STAGING}")

    print("\n== schema + volume ==")
    run_sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
    run_sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.staging")

    print("== upload parquet ==")
    for t in TABLES:
        local = os.path.join(OUT, "scm", f"{t}.parquet")
        if not os.path.exists(local):
            print(f"  SKIP missing {local}")
            continue
        upload(local, f"{STAGING}/{t}.parquet")

    print("== create tables ==")
    for t in TABLES:
        path = f"{STAGING}/{t}.parquet"
        run_sql(
            f"CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.{t} AS "
            f"SELECT * FROM read_files('{path}', format => 'parquet')",
            label=f"{SCHEMA}.{t}",
        )

    print("== row counts ==")
    for t in TABLES:
        try:
            n = spark.sql(f"SELECT count(*) AS n FROM {CATALOG}.{SCHEMA}.{t}").collect()[0]["n"]
            print(f"  ok  count {SCHEMA}.{t}: {n:,}")
        except Exception as e:
            msg = str(e)[:200]
            print(f"  FAIL count {SCHEMA}.{t}: {msg}")
            FAILURES.append((f"count {SCHEMA}.{t}", msg))

    if FAILURES:
        summary = "\n".join(f"  - {tag}: {msg}" for tag, msg in FAILURES)
        raise RuntimeError(f"{len(FAILURES)} step(s) failed:\n{summary}")
    print("\n== all steps succeeded ==")


if __name__ == "__main__":
    main()
