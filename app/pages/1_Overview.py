"""Overview page — 'OTIF, inventory, and service explained.'

Filters by region and month range, shows KPI deltas, OTIF/service trends,
current-month at-risk inventory, and lanes ranked by lead-time drift vs
their own mode average (surfaces the disrupted lane without hardcoding it).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import pandas as pd
import streamlit as st

import databricks_client as dbx

st.set_page_config(page_title="Overview — Akzo SCM Control Tower", layout="wide")

CATALOG = os.environ.get("AKZO_CATALOG", "<catalog>")
SCHEMA = os.environ.get("AKZO_SCHEMA", "<schema>")
FQ = f"{CATALOG}.{SCHEMA}"

# Same thresholds as app/lib/interventions.py — dashboard and rule engine must agree.
DAYS_OF_SUPPLY_MEDIUM = 3.0

st.title("Overview")
st.caption("OTIF, inventory, and service explained.")


@st.cache_data(ttl=300)
def _months() -> list[str]:
    rows = dbx.run_sql(f"SELECT DISTINCT month FROM {FQ}.otif ORDER BY month")["rows"]
    return [r["month"] for r in rows]


@st.cache_data(ttl=300)
def _regions() -> list[str]:
    rows = dbx.run_sql(f"SELECT DISTINCT region FROM {FQ}.otif ORDER BY region")["rows"]
    return [r["region"] for r in rows]


@st.cache_data(ttl=300)
def _otif_trend(region: str, start: str, end: str) -> pd.DataFrame:
    where_region = f"AND region = '{region}'" if region != "All regions" else ""
    rows = dbx.run_sql(
        f"""SELECT month, region,
                   ROUND(SUM(ROUND(otif_pct * orders)) / SUM(orders), 4) AS otif_pct
            FROM {FQ}.otif
            WHERE month BETWEEN DATE'{start}' AND DATE'{end}' {where_region}
            GROUP BY month, region
            ORDER BY month"""
    )["rows"]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["otif_pct"] = df["otif_pct"].astype(float)
    return df


@st.cache_data(ttl=300)
def _service_trend(region: str, start: str, end: str) -> pd.DataFrame:
    where_region = f"AND region = '{region}'" if region != "All regions" else ""
    rows = dbx.run_sql(
        f"""SELECT month, region, service_pct, backorder_units
            FROM {FQ}.service_levels
            WHERE month BETWEEN DATE'{start}' AND DATE'{end}' {where_region}
            ORDER BY month"""
    )["rows"]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["service_pct"] = df["service_pct"].astype(float)
        df["backorder_units"] = df["backorder_units"].astype(int)
    return df


@st.cache_data(ttl=300)
def _at_risk_inventory(month: str, region: str) -> pd.DataFrame:
    where_region = (
        f"AND o.region = '{region}'" if region != "All regions" else ""
    )
    rows = dbx.run_sql(
        f"""SELECT DISTINCT i.plant, i.sku, i.days_of_supply, i.stockout_flag, o.region
            FROM {FQ}.inventory i
            JOIN (SELECT DISTINCT plant, region FROM {FQ}.otif) o ON o.plant = i.plant
            WHERE i.month = DATE'{month}'
              AND (i.stockout_flag = 1 OR i.days_of_supply < {DAYS_OF_SUPPLY_MEDIUM})
              {where_region}
            ORDER BY i.days_of_supply ASC"""
    )["rows"]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["days_of_supply"] = df["days_of_supply"].astype(float)
        df["stockout_flag"] = df["stockout_flag"].astype(int)
    return df


@st.cache_data(ttl=300)
def _lane_drift(month: str) -> pd.DataFrame:
    rows = dbx.run_sql(
        f"""SELECT lane_id, origin_plant, dest_region, mode, lead_time_days,
                   ROUND(lead_time_days - AVG(lead_time_days) OVER (PARTITION BY mode), 1) AS drift_days
            FROM {FQ}.lanes
            ORDER BY drift_days DESC"""
    )["rows"]
    return pd.DataFrame(rows)


months = _months()
regions = ["All regions"] + _regions()

col_a, col_b, col_c = st.columns(3)
region = col_a.selectbox("Region", regions)
start_month = col_b.selectbox("From month", months, index=0)
end_month = col_c.selectbox("To month", months, index=len(months) - 1)

latest_month = months[-1]
prior_month = months[-2] if len(months) > 1 else months[-1]

otif_latest = _otif_trend(region, latest_month, latest_month)
otif_prior = _otif_trend(region, prior_month, prior_month)
service_latest = _service_trend(region, latest_month, latest_month)
service_prior = _service_trend(region, prior_month, prior_month)


def _weighted_or_mean(df: pd.DataFrame, col: str) -> float | None:
    if df.empty:
        return None
    return float(df[col].mean())


otif_now = _weighted_or_mean(otif_latest, "otif_pct")
otif_before = _weighted_or_mean(otif_prior, "otif_pct")
service_now = _weighted_or_mean(service_latest, "service_pct")
service_before = _weighted_or_mean(service_prior, "service_pct")
backorders_now = service_latest["backorder_units"].sum() if not service_latest.empty else 0
_at_risk_now = _at_risk_inventory(latest_month, region)
stockouts_now = (
    len(_at_risk_now[_at_risk_now["stockout_flag"] == 1]) if not _at_risk_now.empty else 0
)

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "OTIF %",
    f"{otif_now * 100:.1f}%" if otif_now is not None else "—",
    delta=f"{(otif_now - otif_before) * 100:.1f} pts" if otif_now and otif_before else None,
)
c2.metric(
    "Service level %",
    f"{service_now * 100:.1f}%" if service_now is not None else "—",
    delta=f"{(service_now - service_before) * 100:.1f} pts" if service_now and service_before else None,
)
c3.metric("Backorder units", int(backorders_now))
c4.metric("Active stockouts", int(stockouts_now))

st.divider()

st.subheader("OTIF by month" + (f" — {region}" if region != "All regions" else " by region"))
otif_df = _otif_trend(region, start_month, end_month)
if not otif_df.empty:
    pivot = otif_df.pivot(index="month", columns="region", values="otif_pct")
    st.line_chart(pivot)
else:
    st.info("No OTIF data for this selection.")

st.subheader("Service level by month" + (f" — {region}" if region != "All regions" else " by region"))
service_df = _service_trend(region, start_month, end_month)
if not service_df.empty:
    pivot_service = service_df.pivot(index="month", columns="region", values="service_pct")
    st.line_chart(pivot_service)
else:
    st.info("No service-level data for this selection.")

st.subheader("Backorder units by month" + (f" — {region}" if region != "All regions" else ""))
if not service_df.empty:
    if region != "All regions":
        bo = service_df.set_index("month")["backorder_units"]
    else:
        bo = service_df.groupby("month")["backorder_units"].sum()
    st.bar_chart(bo)
else:
    st.info("No backorder data for this selection.")

st.divider()

st.subheader(f"At-risk inventory — {latest_month}")
at_risk = _at_risk_inventory(latest_month, region)
if not at_risk.empty:
    st.dataframe(at_risk, use_container_width=True)
else:
    st.success("No plant/SKU pairs below the days-of-supply threshold this month.")

st.subheader("Lanes ranked by lead-time drift vs mode average")
st.dataframe(_lane_drift(latest_month), use_container_width=True)
