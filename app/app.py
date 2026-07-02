"""Akzo SCM Control Tower — Streamlit entrypoint.

Landing page: short intro + one KPI row so the app isn't empty before a
user picks a page. The 3 real pages live under pages/.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

import pandas as pd
import streamlit as st

import databricks_client as dbx

st.set_page_config(page_title="Akzo SCM Control Tower", layout="wide")

CATALOG = os.environ.get("AKZO_CATALOG", "<catalog>")
SCHEMA = os.environ.get("AKZO_SCHEMA", "<schema>")
FQ = f"{CATALOG}.{SCHEMA}"

st.title("Akzo SCM Control Tower")
st.caption(
    "OTIF, inventory, and service explained — then a recommended intervention. "
    "Usecase #02 of the AkzoNobel Agent Bricks Workshop catalog."
)

st.markdown(
    """
Use the sidebar to navigate:
- **Overview** — OTIF, inventory, and service KPIs and trends.
- **Ask the Control Tower** — ask supply-chain questions in plain English, grounded in governed tables.
- **Recommended Interventions** — rule-flagged issues with a human accept/reject workflow, written back to Lakebase.
"""
)


@st.cache_data(ttl=300)
def _latest_kpis() -> dict:
    month_row = dbx.run_sql(f"SELECT MAX(month) AS m FROM {FQ}.otif")["rows"][0]
    month = month_row["m"]

    otif_row = dbx.run_sql(
        f"""SELECT ROUND(SUM(ROUND(otif_pct * orders)) / SUM(orders), 4) AS otif
            FROM {FQ}.otif WHERE month = DATE'{month}'"""
    )["rows"][0]

    china_row = dbx.run_sql(
        f"""SELECT ROUND(SUM(ROUND(otif_pct * orders)) / SUM(orders), 4) AS otif
            FROM {FQ}.otif WHERE month = DATE'{month}' AND region = 'China'"""
    )["rows"][0]

    service_row = dbx.run_sql(
        f"""SELECT ROUND(AVG(service_pct), 4) AS service_pct, SUM(backorder_units) AS backorders
            FROM {FQ}.service_levels WHERE month = DATE'{month}'"""
    )["rows"][0]

    stockout_row = dbx.run_sql(
        f"""SELECT COUNT(*) AS n FROM {FQ}.inventory
            WHERE month = DATE'{month}' AND stockout_flag = 1"""
    )["rows"][0]

    return {
        "month": month,
        "otif": otif_row["otif"],
        "china_otif": china_row["otif"],
        "service_pct": service_row["service_pct"],
        "backorders": service_row["backorders"],
        "stockouts": stockout_row["n"],
    }


try:
    kpis = _latest_kpis()
    st.subheader(f"Latest month: {kpis['month']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overall OTIF", f"{kpis['otif'] * 100:.1f}%")
    c2.metric("China OTIF", f"{kpis['china_otif'] * 100:.1f}%")
    c3.metric("Avg service level", f"{kpis['service_pct'] * 100:.1f}%")
    c4.metric("Active stockouts", int(kpis["stockouts"]))
except Exception as e:
    st.warning(f"Could not load KPIs — check warehouse/catalog config. ({e})")
