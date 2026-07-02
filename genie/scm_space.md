# Genie Space — Akzo SCM Control Tower

> Paste the **Instructions** block into the Genie space's *Instructions* field, and add the
> **example SQL** pairs as *Sample / Trusted Questions*. All SQL is Spark SQL against
> `<catalog>.<schema>.*`. Every column below exists in the tables loaded by `data/load_to_uc.py` —
> do not invent columns.

---

## 1. Space title + description

**Title:** Akzo SCM Control Tower — OTIF, Inventory & Service

**Description:** Ask plain-English questions about AkzoNobel's coatings supply chain:
on-time-in-full (OTIF) delivery performance, inventory health and stockouts, lane lead
times and freight cost, and regional customer service levels — by plant, region, lane,
SKU, and month. This space is for supply chain planners and S&OP: it pinpoints *where*
and *why* service slipped (equipment failures, lead-time blowouts, stockouts,
backorders). Costs are in **EUR**; current month is **2026-06**.

---

## 2. Tables in scope

All tables fully-qualified under `<catalog>.<schema>`.

| Table | Purpose | Key columns | Grain |
|---|---|---|---|
| `<catalog>.<schema>.otif` | On-Time-In-Full delivery performance | `plant`, `region` (EMEA/Americas/APAC/China), `lane`, `sku`, `month` (DATE), `orders`, `on_time`, `in_full`, `otif_pct` | plant × region × lane × sku × month |
| `<catalog>.<schema>.inventory` | Inventory health & stockouts | `plant`, `sku`, `month`, `on_hand_units`, `safety_stock`, `days_of_supply`, `stockout_flag` (1=stockout) | plant × sku × month |
| `<catalog>.<schema>.lanes` | Lane master (current values) | `lane_id`, `origin_plant`, `dest_region`, `mode` (road/sea), `lead_time_days` (current), `cost_per_unit` (EUR) | one row per lane |
| `<catalog>.<schema>.service_levels` | Regional customer service | `region`, `month`, `service_pct`, `backorder_units` | region × month |

> SKUs are `DEC-####` (Decorative Paints) or `PFC-####` (Performance Coatings).
> Plants: Antwerp-BE, Ashington-UK (EMEA); Charlotte-US, Bahia-BR (Americas);
> Guangzhou-CN (China); Chonburi-TH (APAC).

---

## 3. Join hints / relationships

- `otif.lane = lanes.lane_id` — bring in `mode`, `lead_time_days`, `cost_per_unit`, `origin_plant`, `dest_region`.
- `otif.plant = inventory.plant` and `otif.sku = inventory.sku` (and `month`) — connect a service dip to a stockout.
- `service_levels` is region×month only — join to `otif`/`inventory` on `region` + `month` for the regional rollup.
- To scope **"Performance Coatings China"**, filter `otif.region = 'China'` and `otif.sku LIKE 'PFC-%'`.
- The narrative China lane is **`Guangzhou-CN->China-East`** (road). Guangzhou-CN also
  ships a stable sea lane, `Guangzhou-CN->China-South` — the disruption is lane-specific,
  not plant-wide, so region-level OTIF dilutes the lane-level severity. Always check both.

---

## 4. Certified metrics / business-term definitions (always use these)

- **OTIF (certified)** — perfect orders / total orders. When aggregating across rows compute it volume-weighted: `SUM(perfect) / SUM(orders)`, where per row `perfect = round(otif_pct * orders)`. **Do not average `otif_pct`** across rows; weight by `orders`.
- **service_pct** — order-fill / customer service level for a region-month (from `service_levels`); higher is better.
- **stockout** — a row in `inventory` with `stockout_flag = 1` (on-hand critically below safety stock; `days_of_supply` ~1).
- **"Performance Coatings China"** := `region = 'China'` AND `sku LIKE 'PFC-%'`.
- **Quarters (2026):** Q1 = `2026-01-01..2026-03-01`; Q2 = `2026-04-01..2026-06-01`.
- **Elevated lead time** — a lane whose `lead_time_days` is high relative to its mode's average (road lanes should be short; a road lane running near sea-lane length is the signal, not absolute days).
- > Narrative anchors (seed 7): `Guangzhou-CN->China-East` OTIF ~95.8% baseline → **84.3% March 2026** → 95.5% June. China region `service_pct` ~96% baseline → **87.0% March**; China `backorder_units` ~100 baseline → **2,101 March**. **2** Performance Coatings SKUs (`PFC-2000`, `PFC-2004`) stock out at Guangzhou-CN in Feb–Mar 2026 (`days_of_supply` ~1.2). Root cause: a curing-oven equipment failure at the Guangzhou-CN plant, not a freight/customs issue. All other regions/lanes hold ~95–96% OTIF throughout.

---

## 5. General instructions for the space

- Current month is **2026-06**; "latest / now" = `2026-06-01`. `month` is a DATE at first-of-month — compare against `'YYYY-MM-01'` literals.
- Always compute OTIF as the **volume-weighted certified ratio** (`SUM(perfect)/SUM(orders)`), never the average of `otif_pct`.
- Express OTIF and service percentages to 1 decimal; costs in EUR.
- `lanes.lead_time_days` holds the *current* lead time; for historical lead-time trend infer from OTIF over `month`, since `otif` is the time series (the lane master table only reflects the latest value).
- A region can look only mildly affected if it has more than one lane and only one is disrupted — always break down by `lane` before concluding a region is fine.
- Decline politely if asked about gross margin / cost / FX (route to Akzo Finance) or accounts / churn / pipeline (route to Akzo Commercial).

---

## 6. Example NL question → SQL pairs

> ⭐ = golden question (must answer the embedded narrative).

### ⭐ Q1. "Why did OTIF for Performance Coatings China drop in March 2026?"

```sql
WITH o AS (
  SELECT month,
         SUM(ROUND(otif_pct * orders)) AS perfect,
         SUM(orders)                   AS orders
  FROM <catalog>.<schema>.otif
  WHERE region = 'China' AND sku LIKE 'PFC-%'
    AND month BETWEEN DATE'2026-01-01' AND DATE'2026-05-01'
  GROUP BY month
)
SELECT o.month,
       ROUND(o.perfect / o.orders * 100, 1) AS otif_pct,
       s.service_pct,
       s.backorder_units
FROM o
JOIN <catalog>.<schema>.service_levels s
  ON s.region = 'China' AND s.month = o.month
ORDER BY o.month;
```
*Answer:* OTIF and service_pct collapse in March 2026 while backorder_units spike (~2,101) —
driven by a curing-oven equipment failure at Guangzhou-CN degrading the
`Guangzhou-CN->China-East` lane, plus two key SKU stockouts (see Q3/Q6).

### ⭐ Q2. "Which lanes had elevated lead times in Q1 2026?"

```sql
-- Flag lanes whose current lead time is high RELATIVE TO THEIR MODE
-- (sea lanes are naturally long; the disruption shows as a road lane that's elevated).
WITH mode_norm AS (
  SELECT mode, AVG(lead_time_days) AS mode_avg_days
  FROM <catalog>.<schema>.lanes GROUP BY mode
)
SELECT l.lane_id, l.origin_plant, l.dest_region, l.mode,
       l.lead_time_days,
       ROUND(n.mode_avg_days, 1)                    AS mode_avg_days,
       ROUND(l.lead_time_days - n.mode_avg_days, 1)  AS days_above_mode_avg
FROM <catalog>.<schema>.lanes l
JOIN mode_norm n ON l.mode = n.mode
ORDER BY days_above_mode_avg DESC;
```
*Answer:* `Guangzhou-CN->China-East` (road) is the most-elevated lane vs its mode average —
the disrupted China lane. Sea lanes like `Chonburi-TH->APAC-ANZ` are longer in absolute
days but normal for sea, so they do not top this list. Corroborate with the lane's OTIF
time series in Q5.

### ⭐ Q3. "Which China SKUs stocked out in March 2026?"

```sql
SELECT i.plant, i.sku, i.on_hand_units, i.safety_stock,
       ROUND(i.days_of_supply, 1) AS days_of_supply
FROM <catalog>.<schema>.inventory i
WHERE i.month = DATE'2026-03-01'
  AND i.stockout_flag = 1
  AND i.plant = 'Guangzhou-CN'
ORDER BY i.days_of_supply ASC;
```
*Answer:* Two Performance Coatings SKUs (`PFC-2000`, `PFC-2004`) stock out at Guangzhou-CN
in March, `days_of_supply` ~1.2 — consistent with the equipment-failure narrative
constraining inbound supply.

### Q4. "Show China service level and backorders by month for 2026."

```sql
SELECT month, service_pct, backorder_units
FROM <catalog>.<schema>.service_levels
WHERE region = 'China' AND month >= DATE'2026-01-01'
ORDER BY month;
```
*Answer:* Steady ~96% in January, collapses to ~87.0% in March with backorders spiking
to ~2,101, recovering through April-May, back to baseline by June.

### Q5. "Show monthly OTIF for the Guangzhou-CN->China-East lane in 2026."

```sql
SELECT month,
       ROUND(SUM(ROUND(otif_pct * orders)) / SUM(orders) * 100, 1) AS lane_otif_pct,
       SUM(orders) AS orders
FROM <catalog>.<schema>.otif
WHERE lane = 'Guangzhou-CN->China-East' AND month >= DATE'2026-01-01'
GROUP BY month
ORDER BY month;
```
*Answer:* ~95.8% in January, down to ~84.3% in March, recovering to ~95.5% by June.

### Q6. "Compare China OTIF to the other regions in March 2026."

```sql
SELECT region,
       ROUND(SUM(ROUND(otif_pct * orders)) / SUM(orders) * 100, 1) AS otif_pct,
       SUM(orders) AS orders
FROM <catalog>.<schema>.otif
WHERE month = DATE'2026-03-01'
GROUP BY region
ORDER BY otif_pct;
```
*Answer:* China is the clear outlier in March (region-level ~90%, diluted by its stable
sea lane); EMEA/Americas/APAC sit ~95.4–95.7%. The lane-level gap is starker — see Q5.

### Q7. "List China lanes with their lead time and cost per unit, slowest first."

```sql
SELECT lane_id, mode, lead_time_days, cost_per_unit
FROM <catalog>.<schema>.lanes
WHERE dest_region = 'China'
ORDER BY lead_time_days DESC, cost_per_unit DESC;
```

### Q8. "Which plant × SKU had the most stockout-months in 2026?"

```sql
SELECT plant, sku, SUM(stockout_flag) AS stockout_months
FROM <catalog>.<schema>.inventory
WHERE month >= DATE'2026-01-01'
GROUP BY plant, sku
HAVING SUM(stockout_flag) > 0
ORDER BY stockout_months DESC, plant, sku
LIMIT 20;
```

### Q9. "What were days of supply for PFC-2000 at Guangzhou-CN through 2026?"

```sql
SELECT month, on_hand_units, safety_stock,
       ROUND(days_of_supply, 1) AS days_of_supply, stockout_flag
FROM <catalog>.<schema>.inventory
WHERE plant = 'Guangzhou-CN' AND sku = 'PFC-2000'
  AND month >= DATE'2026-01-01'
ORDER BY month;
```
*Answer:* Days of supply craters to ~1.2 in Feb-March 2026 with `stockout_flag = 1`,
rebuilding through April, fully restocked by May.

### Q10. "How many Performance Coatings China orders were affected (not perfect) in March 2026?"

```sql
SELECT
  SUM(orders)                                 AS total_orders,
  SUM(ROUND(otif_pct * orders))               AS perfect_orders,
  SUM(orders) - SUM(ROUND(otif_pct * orders)) AS non_perfect_orders
FROM <catalog>.<schema>.otif
WHERE region = 'China' AND sku LIKE 'PFC-%' AND month = DATE'2026-03-01';
```
*Answer:* Quantifies the March service gap that fed backorders and the downstream
stockout risk at Guangzhou-CN.
