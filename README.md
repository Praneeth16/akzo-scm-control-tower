# Akzo SCM Control Tower

A Databricks Apps demo for **usecase #02** of the AkzoNobel Agent Bricks Workshop
catalog: *"OTIF, inventory, and service explained, then a recommended intervention."*

Streamlit frontend, deployed on **Databricks Free Edition** — Unity Catalog for governed
data, a SQL warehouse for queries, a Foundation Model endpoint for NL→SQL and
summarization, a Genie Space for ad hoc human exploration, and **Lakebase** for a
human-in-the-loop intervention audit trail.

This is a standalone repo — no dependency on any other project. It deliberately uses
**Streamlit**, not React+FastAPI, to demonstrate the alternate Databricks Apps pattern
(see [Tech stack](#tech-stack) below).

---

## Architecture

```
Streamlit (app/)
   │
   ├── databricks_client.py ──► WorkspaceClient ──► SQL Warehouse ──► 4 UC tables
   │                                             └─► Model Serving endpoint (chat / NL→SQL)
   │
   └── lakebase.py ───────────► Lakebase Postgres ──► scm_interventions (audit trail)

Genie Space (workspace UI) ──► same 4 UC tables, for humans exploring ad hoc
(NOT wired to the app's chat page — see SETUP.md step 7)
```

4 governed Unity Catalog tables back everything:

| Table | Grain | Purpose |
|---|---|---|
| `otif` | plant × region × lane × sku × month | On-time-in-full delivery performance |
| `inventory` | plant × sku × month | Stock levels, days of supply, stockout flag |
| `lanes` | one row per lane | Lane master — mode, lead time, cost |
| `service_levels` | region × month | Customer service %, backorder units |

**Certified metric rule** (enforced everywhere — dashboard, chat, rule engine): OTIF must
be volume-weighted `SUM(ROUND(otif_pct*orders))/SUM(orders)`, never the average of
`otif_pct`.

---

## The narrative

Synthetic data (`data/generate_scm_data.py`, deterministic, seed=7), 24 months
`2024-07-01..2026-06-01`, current month `2026-06-01`.

A curing-oven equipment failure at the **Guangzhou-CN** plant starts **February 2026**,
degrading dispatch reliability on the `Guangzhou-CN->China-East` road lane for ~4 months —
worst in **March 2026**, recovering by May. Two Performance Coatings SKUs at
Guangzhou-CN (`PFC-2000`, `PFC-2004`) stock out in Feb–Mar 2026 and rebuild through April.
All other regions and lanes hold ~95–96% OTIF throughout, as the control group.

| Month | Lane lead time | Lane OTIF | China OTIF | China service_pct | China backorders |
|---|---|---|---|---|---|
| Baseline (Q4'25) | 3d | ~95.5% | ~95.8% | ~96% | ~100 |
| 2026-02 | 8d | ~92% | — | ~93% | ~400 |
| **2026-03 (worst)** | **12d** | **~84.3%** | **~86%** | **~87.0%** | **~2,101** |
| 2026-04 | 7d | ~90% | ~91% | ~91% | ~900 |
| 2026-05 | 4d | ~94% | ~95% | ~95% | ~250 |
| 2026-06 | 3d | ~95.5% | ~95.8% | ~96% | ~100 |

Golden question: *"Why did OTIF for Performance Coatings China drop in March 2026?"*

---

## The 3 pages

### 1. Overview — *"OTIF, inventory, and service explained"*

Region + month-range filters, KPI row with deltas vs prior month, OTIF and service-level
trend charts by region, backorder-units bar chart, an at-risk-inventory table
(stockouts or days-of-supply below threshold), and lanes ranked by lead-time drift
against their own transport-mode average — surfaces the disrupted lane without
hardcoding its name.

### 2. Ask the Control Tower — NL→SQL chat

Plain-English questions answered against the governed tables via `lib/text2sql.py`:
the chat model turns the question into a single Spark SQL statement (grounded in
`lib/scm_space.md`'s table docs, join hints, and certified metric definitions), the SQL
runs on the warehouse, and a second short model call summarizes the result. Every
answer shows its SQL in an expander. Example-question buttons seed common queries.

This is **not** the Genie Conversation API — it's a direct, lighter NL→SQL round trip
against the same model endpoint. The workspace's own Genie Space (created via UI, see
SETUP.md step 7) is a separate surface for humans to explore ad hoc; the two are not
wired together.

### 3. Recommended Interventions — *"then a recommended intervention"*

A pure-Python rule engine (`lib/interventions.py`, no extra LLM call) scans the latest
month for 3 issue families:

- **A — OTIF breach (lane level).** Volume-weighted lane OTIF `< 0.93` → MEDIUM,
  `< 0.90` → HIGH. Recommendation depends on lane mode: road/sea lanes get an
  "expedite via air freight" recommendation at HIGH severity; air lanes escalate to the
  regional planner to investigate root cause at origin.
- **B — Inventory risk (plant × SKU).** An active stockout → HIGH ("trigger emergency
  safety-stock replenishment"); `days_of_supply < 3.0` without a stockout → MEDIUM
  ("trigger standard replenishment order").
- **C — Regional service risk.** `service_pct < 0.93` or backorders `> 3×` the trailing
  3-month average → MEDIUM, or HIGH if `service_pct < 0.91`.

Only HIGH/MEDIUM severities are surfaced. Candidates are synced idempotently (by a
natural key of issue type / region / plant / lane / sku / month) into a Lakebase table,
`scm_interventions`, so re-running the scan never duplicates rows. A human reviews each
pending row, sees the rationale and recommendation, and clicks **Accept** or **Reject** —
recorded with `decided_by` and `decided_at`, guarded so a decision can't double-apply.
Accepted/rejected rows move to a **Decision history** expander. This is an audit-ledger
write, not an action dispatcher — no downstream email/PO/CRM call is fired.

---

## Tech stack

- **Streamlit** — no React, no Vite, no FastAPI, no pydantic. One Python process serves
  both UI and backend calls.
- `databricks-sdk` — `WorkspaceClient`, SQL warehouse statement execution, Model Serving
  chat completions.
- `psycopg[binary]` — Lakebase (Postgres-compatible) connection, using a short-lived
  generated database credential.
- `pandas` — result-set shaping for `st.dataframe`/`st.line_chart`/`st.bar_chart`.

---

## Repo layout

```
akzo-scm-control-tower/
├── README.md
├── SETUP.md
├── .gitignore
├── data/
│   ├── generate_scm_data.py   # synthetic data generator (run locally)
│   ├── load_to_uc.py          # loads parquet -> Unity Catalog (run as a notebook)
│   └── output/                # generated parquet — gitignored
├── genie/
│   └── scm_space.md           # Genie Space instructions (paste into workspace UI)
└── app/
    ├── app.py                 # Streamlit entrypoint + landing KPIs
    ├── pages/
    │   ├── 1_Overview.py
    │   ├── 2_Ask_the_Control_Tower.py
    │   └── 3_Recommended_Interventions.py
    ├── lib/
    │   ├── databricks_client.py
    │   ├── lakebase.py
    │   ├── text2sql.py
    │   ├── interventions.py
    │   └── scm_space.md       # bundled copy — the app never reads outside its sync root
    ├── app.yaml
    ├── requirements.txt
    ├── .env.example
    └── run_local.sh
```

---

## Local development

See [SETUP.md](SETUP.md) for the full Free-Edition provisioning checklist. Once the
Databricks resources exist and `app/.env` is filled from `app/.env.example`:

```bash
cd app
cp .env.example .env   # fill in values from SETUP.md
./run_local.sh
```

`run_local.sh` runs against the **real workspace** via your local `databricks` CLI
profile — there is no mocked/local-only mode.

---

## Provenance

Infra plumbing (`databricks_client.py`, `lakebase.py`, the `text2sql.py` pattern) is
adapted from the sibling `agent-bricks-workshop` repo's shared Apps utilities — generic,
reusable plumbing, not narrative. The SCM data narrative, rule-engine thresholds, and
Genie Space instructions in this repo are original, written fresh for this demo.
