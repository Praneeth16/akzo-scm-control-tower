"""Recommended-intervention rule engine + Lakebase write-back.

Pure Python over run_sql() results — no UC function, no extra LLM call.
Deterministic and auditable: every recommendation traces back to a threshold
and a metric value, not a black box.

Rule families (evaluated against MAX(month), never hardcoded to a date):
  A — OTIF breach (lane level)
  B — Inventory risk (plant x SKU)
  C — Regional service risk

Two severities only (HIGH/MEDIUM) — anything milder isn't surfaced.
"""
from __future__ import annotations

import os
from typing import Any

import databricks_client as dbx
import lakebase as lb

CATALOG = os.environ.get("AKZO_CATALOG", "<catalog>")
SCHEMA = os.environ.get("AKZO_SCHEMA", "<schema>")
FQ = f"{CATALOG}.{SCHEMA}"

OTIF_HIGH = 0.90
OTIF_MEDIUM = 0.93
DAYS_OF_SUPPLY_MEDIUM = 3.0
SERVICE_HIGH = 0.91
SERVICE_MEDIUM = 0.93

CREATED_BY = "scm-control-tower@service"


def _ensure_table() -> None:
    lb.execute(
        """
        CREATE TABLE IF NOT EXISTS scm_interventions (
            intervention_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            issue_type      TEXT NOT NULL,
            severity        TEXT NOT NULL,
            region          TEXT,
            plant           TEXT,
            lane            TEXT,
            sku             TEXT,
            month           DATE NOT NULL,
            metric_value    NUMERIC,
            rationale       TEXT NOT NULL,
            recommendation  TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            decided_by      TEXT,
            decided_at      TIMESTAMPTZ,
            created_by      TEXT NOT NULL DEFAULT 'scm-control-tower@service',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _latest_month() -> str:
    res = dbx.run_sql(f"SELECT MAX(month) AS m FROM {FQ}.otif")
    return res["rows"][0]["m"]


# ---------------------------------------------------------------------------
# Rule A — OTIF breach, lane level (volume-weighted, certified metric)
# ---------------------------------------------------------------------------
def _scan_otif_breaches(month: str) -> list[dict[str, Any]]:
    sql = f"""
        SELECT o.lane, o.region,
               l.mode,
               ROUND(SUM(ROUND(o.otif_pct * o.orders)) / SUM(o.orders), 4) AS lane_otif
        FROM {FQ}.otif o
        JOIN {FQ}.lanes l ON l.lane_id = o.lane
        WHERE o.month = DATE'{month}'
        GROUP BY o.lane, o.region, l.mode
        HAVING SUM(o.orders) > 0
        ORDER BY lane_otif ASC
    """
    rows = dbx.run_sql(sql)["rows"]
    out = []
    for r in rows:
        otif = float(r["lane_otif"])
        if otif >= OTIF_MEDIUM:
            continue
        severity = "HIGH" if otif < OTIF_HIGH else "MEDIUM"
        mode = r["mode"]
        if severity == "HIGH":
            rec = (
                "Expedite via air freight for the current cycle; investigate lane lead-time root cause."
                if mode in ("road", "sea")
                else "Escalate to regional planner — lane is already air; investigate root cause at origin plant."
            )
        else:
            rec = "Escalate to regional planner for lane monitoring."
        out.append(
            {
                "issue_type": "otif_breach",
                "severity": severity,
                "region": r["region"],
                "plant": None,
                "lane": r["lane"],
                "sku": None,
                "month": month,
                "metric_value": round(otif * 100, 1),
                "rationale": f"Lane {r['lane']} OTIF at {otif * 100:.1f}% for {month}, below the {OTIF_MEDIUM * 100:.0f}% target.",
                "recommendation": rec,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Rule B — Inventory risk, plant x SKU
# ---------------------------------------------------------------------------
def _scan_inventory_risk(month: str) -> list[dict[str, Any]]:
    sql = f"""
        SELECT i.plant, i.sku, i.days_of_supply, i.stockout_flag, o.region
        FROM {FQ}.inventory i
        JOIN (SELECT DISTINCT plant, region FROM {FQ}.otif) o ON o.plant = i.plant
        WHERE i.month = DATE'{month}'
          AND (i.stockout_flag = 1 OR i.days_of_supply < {DAYS_OF_SUPPLY_MEDIUM})
        ORDER BY i.days_of_supply ASC
    """
    rows = dbx.run_sql(sql)["rows"]
    out = []
    for r in rows:
        dos = float(r["days_of_supply"])
        stockout = int(r["stockout_flag"]) == 1
        severity = "HIGH" if stockout else "MEDIUM"
        rec = (
            f"Trigger emergency safety-stock replenishment; expedite inbound supply to {r['plant']} for {r['sku']}."
            if stockout
            else "Trigger standard safety-stock replenishment order; monitor weekly."
        )
        out.append(
            {
                "issue_type": "inventory_risk",
                "severity": severity,
                "region": r["region"],
                "plant": r["plant"],
                "lane": None,
                "sku": r["sku"],
                "month": month,
                "metric_value": round(dos, 1),
                "rationale": f"{r['plant']} / {r['sku']} days_of_supply at {dos:.1f}"
                + (" with an active stockout." if stockout else "."),
                "recommendation": rec,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Rule C — Regional service risk
# ---------------------------------------------------------------------------
def _scan_service_risk(month: str) -> list[dict[str, Any]]:
    sql = f"""
        WITH trailing AS (
            SELECT region, AVG(backorder_units) AS baseline_backorders
            FROM {FQ}.service_levels
            WHERE month < DATE'{month}'
              AND month >= DATE'{month}' - INTERVAL 3 MONTH
            GROUP BY region
        )
        SELECT s.region, s.service_pct, s.backorder_units, t.baseline_backorders
        FROM {FQ}.service_levels s
        JOIN trailing t ON t.region = s.region
        WHERE s.month = DATE'{month}'
    """
    rows = dbx.run_sql(sql)["rows"]
    out = []
    for r in rows:
        service_pct = float(r["service_pct"])
        backorders = float(r["backorder_units"])
        baseline = float(r["baseline_backorders"] or 0)
        breached = service_pct < SERVICE_MEDIUM or (baseline > 0 and backorders > 3 * baseline)
        if not breached:
            continue
        severity = "HIGH" if service_pct < SERVICE_HIGH else "MEDIUM"
        out.append(
            {
                "issue_type": "service_level_risk",
                "severity": severity,
                "region": r["region"],
                "plant": None,
                "lane": None,
                "sku": None,
                "month": month,
                "metric_value": round(service_pct * 100, 1),
                "rationale": f"{r['region']} service level at {service_pct * 100:.1f}%, backorders at {int(backorders)} vs baseline ~{int(baseline)}.",
                "recommendation": f"Escalate to regional planner — {r['region']} service level at {service_pct * 100:.1f}%, backorders at {int(backorders)} vs baseline ~{int(baseline)}.",
            }
        )
    return out


def scan_latest_month() -> list[dict[str, Any]]:
    """Run all 3 rule families against MAX(month). Returns candidate issues, HIGH first."""
    month = _latest_month()
    candidates = (
        _scan_otif_breaches(month) + _scan_inventory_risk(month) + _scan_service_risk(month)
    )
    candidates.sort(key=lambda c: 0 if c["severity"] == "HIGH" else 1)
    return candidates


def _exists(c: dict[str, Any]) -> bool:
    _ensure_table()
    rows = lb.query(
        """SELECT 1 FROM scm_interventions
           WHERE issue_type=%s AND month=%s
             AND COALESCE(region,'')=COALESCE(%s,'')
             AND COALESCE(plant,'')=COALESCE(%s,'')
             AND COALESCE(lane,'')=COALESCE(%s,'')
             AND COALESCE(sku,'')=COALESCE(%s,'')""",
        (c["issue_type"], c["month"], c["region"], c["plant"], c["lane"], c["sku"]),
    )
    return len(rows) > 0


def sync_to_lakebase(candidates: list[dict[str, Any]]) -> int:
    """Idempotent insert of new candidates (natural key: issue_type/region/plant/lane/sku/month)."""
    _ensure_table()
    inserted = 0
    for c in candidates:
        if _exists(c):
            continue
        lb.execute(
            """INSERT INTO scm_interventions
               (issue_type, severity, region, plant, lane, sku, month, metric_value,
                rationale, recommendation, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                c["issue_type"], c["severity"], c["region"], c["plant"], c["lane"], c["sku"],
                c["month"], c["metric_value"], c["rationale"], c["recommendation"], CREATED_BY,
            ),
        )
        inserted += 1
    return inserted


def list_interventions(status: str | None = None) -> list[dict[str, Any]]:
    _ensure_table()
    if status:
        return lb.query(
            "SELECT * FROM scm_interventions WHERE status=%s ORDER BY severity, month DESC",
            (status,),
        )
    return lb.query("SELECT * FROM scm_interventions ORDER BY status, severity, month DESC")


def decide(intervention_id: int, status: str, decided_by: str) -> dict[str, Any] | None:
    assert status in ("accepted", "rejected")
    return lb.execute(
        """UPDATE scm_interventions
           SET status=%s, decided_by=%s, decided_at=now()
           WHERE intervention_id=%s AND status='pending'
           RETURNING intervention_id, status""",
        (status, decided_by, intervention_id),
        returning=True,
    )
