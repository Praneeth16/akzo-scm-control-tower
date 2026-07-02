"""Synthetic SCM data for the Akzo Control Tower demo.

Deterministic (numpy default_rng, fixed seed). 24 monthly periods
2024-07-01..2026-06-01, current month 2026-06-01. Writes 4 parquet files
(otif, inventory, lanes, service_levels) under output/scm/.

Narrative: a curing-oven equipment failure at the Guangzhou-CN plant starts
Feb 2026, degrading dispatch reliability on lane Guangzhou-CN->China-East for
~4 months, worst in March 2026, recovering by May. Two Performance Coatings
SKUs at Guangzhou-CN stock out Feb-Mar. All other regions/lanes stay stable
throughout, as the control group.

Run: python3 data/generate_scm_data.py
"""
import os

import numpy as np
import pandas as pd

SEED = 7
rng = np.random.default_rng(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output", "scm")

MONTHS = pd.date_range("2024-07-01", "2026-06-01", freq="MS")
SHOCK_MONTHS = pd.date_range("2026-02-01", "2026-05-01", freq="MS")  # Feb-May 2026
WORST_MONTH = pd.Timestamp("2026-03-01")

PLANTS = {
    "Antwerp-BE": "EMEA",
    "Ashington-UK": "EMEA",
    "Charlotte-US": "Americas",
    "Bahia-BR": "Americas",
    "Guangzhou-CN": "China",
    "Chonburi-TH": "APAC",
}

# lane_id, origin_plant, dest_region, mode, base_lead_time_days, cost_per_unit_eur
LANE_DEFS = [
    ("Antwerp-BE->EMEA-West", "Antwerp-BE", "EMEA", "road", 2, 4.10),
    ("Antwerp-BE->EMEA-East", "Antwerp-BE", "EMEA", "road", 4, 5.30),
    ("Ashington-UK->EMEA-West", "Ashington-UK", "EMEA", "sea", 6, 3.60),
    ("Charlotte-US->Americas-North", "Charlotte-US", "Americas", "road", 3, 4.80),
    ("Charlotte-US->Americas-South", "Charlotte-US", "Americas", "sea", 9, 3.90),
    ("Bahia-BR->Americas-South", "Bahia-BR", "Americas", "road", 3, 4.20),
    ("Guangzhou-CN->China-East", "Guangzhou-CN", "China", "road", 3, 4.50),
    ("Guangzhou-CN->China-South", "Guangzhou-CN", "China", "sea", 5, 3.70),
    ("Chonburi-TH->APAC-SEA", "Chonburi-TH", "APAC", "road", 4, 4.00),
    ("Chonburi-TH->APAC-ANZ", "Chonburi-TH", "APAC", "sea", 11, 3.50),
]

SHOCK_LANE = "Guangzhou-CN->China-East"
SHOCK_PLANT = "Guangzhou-CN"

# Effective lead time (days) on the shock lane, by month offset. Others use base.
LANE_LEAD_TIME_OVERRIDE = {
    pd.Timestamp("2026-02-01"): 8,
    pd.Timestamp("2026-03-01"): 12,
    pd.Timestamp("2026-04-01"): 7,
    pd.Timestamp("2026-05-01"): 4,
}

# Lane-level OTIF target, by month, for the shock lane. Baseline ~0.955.
LANE_OTIF_OVERRIDE = {
    pd.Timestamp("2026-02-01"): 0.92,
    pd.Timestamp("2026-03-01"): 0.84,
    pd.Timestamp("2026-04-01"): 0.90,
    pd.Timestamp("2026-05-01"): 0.94,
}
LANE_OTIF_BASELINE = 0.955

# Region-level OTIF/service targets for China, by month (baseline ~0.958/0.96).
REGION_OTIF_OVERRIDE = {
    pd.Timestamp("2026-03-01"): 0.86,
    pd.Timestamp("2026-04-01"): 0.91,
    pd.Timestamp("2026-05-01"): 0.95,
}
REGION_SERVICE_OVERRIDE = {
    pd.Timestamp("2026-02-01"): 0.93,
    pd.Timestamp("2026-03-01"): 0.87,
    pd.Timestamp("2026-04-01"): 0.91,
    pd.Timestamp("2026-05-01"): 0.95,
}
REGION_BACKORDER_OVERRIDE = {
    pd.Timestamp("2026-02-01"): 400,
    pd.Timestamp("2026-03-01"): 2100,
    pd.Timestamp("2026-04-01"): 900,
    pd.Timestamp("2026-05-01"): 250,
}
REGION_BASELINE_OTIF = 0.958
REGION_BASELINE_SERVICE = 0.96
REGION_BASELINE_BACKORDERS = 100

DECORATIVE_SKUS = [f"DEC-{n}" for n in range(1000, 1024, 4)]  # 6 SKUs
PERFORMANCE_SKUS = [f"PFC-{n}" for n in range(2000, 2036, 4)]  # 9 SKUs
ALL_SKUS = DECORATIVE_SKUS + PERFORMANCE_SKUS

STOCKOUT_SKUS = ["PFC-2000", "PFC-2004"]  # the 2 key Guangzhou SKUs that stock out
STOCKOUT_MONTHS = [pd.Timestamp("2026-02-01"), pd.Timestamp("2026-03-01")]


def plant_sku_pairs():
    """Each plant stocks/ships a fixed subset of SKUs (Decorative + Performance mix)."""
    pairs = []
    for plant in PLANTS:
        n = rng.integers(6, 9)
        skus = rng.choice(ALL_SKUS, size=n, replace=False).tolist()
        if plant == SHOCK_PLANT:
            for s in STOCKOUT_SKUS:
                if s not in skus:
                    skus.append(s)
        pairs.append((plant, sorted(skus)))
    return pairs


def build_lanes():
    rows = []
    for lane_id, origin, dest_region, mode, base_lt, cost in LANE_DEFS:
        rows.append(
            {
                "lane_id": lane_id,
                "origin_plant": origin,
                "dest_region": dest_region,
                "mode": mode,
                "lead_time_days": LANE_LEAD_TIME_OVERRIDE.get(WORST_MONTH, base_lt)
                if lane_id == SHOCK_LANE
                else base_lt,
                "cost_per_unit": round(cost, 2),
            }
        )
    return pd.DataFrame(rows)


def _lane_for_plant(plant):
    """Pick the lane whose origin_plant matches; each plant has 1-2 lanes."""
    return [l[0] for l in LANE_DEFS if l[1] == plant]


def build_otif(pairs):
    rows = []
    for plant, skus in pairs:
        region = PLANTS[plant]
        lanes = _lane_for_plant(plant)
        for sku in skus:
            for month in MONTHS:
                for lane in lanes:
                    base_orders = int(rng.integers(40, 140))
                    otif_target = LANE_OTIF_BASELINE
                    if lane == SHOCK_LANE:
                        otif_target = LANE_OTIF_OVERRIDE.get(month, LANE_OTIF_BASELINE)
                    noise = rng.normal(0, 0.006)
                    otif_pct = float(np.clip(otif_target + noise, 0.75, 0.995))
                    perfect = round(otif_pct * base_orders)
                    on_time = min(base_orders, perfect + int(rng.integers(0, 3)))
                    in_full = min(base_orders, perfect + int(rng.integers(0, 3)))
                    rows.append(
                        {
                            "plant": plant,
                            "region": region,
                            "lane": lane,
                            "sku": sku,
                            "month": month,
                            "orders": base_orders,
                            "on_time": on_time,
                            "in_full": in_full,
                            "otif_pct": round(perfect / base_orders, 4),
                        }
                    )
    return pd.DataFrame(rows)


def build_inventory(pairs):
    rows = []
    for plant, skus in pairs:
        for sku in skus:
            safety_stock = int(rng.integers(200, 500))
            on_hand = safety_stock + int(rng.integers(100, 600))
            for month in MONTHS:
                is_stockout_window = (
                    plant == SHOCK_PLANT
                    and sku in STOCKOUT_SKUS
                    and month in STOCKOUT_MONTHS
                )
                if is_stockout_window:
                    on_hand_units = int(safety_stock * rng.uniform(0.05, 0.15))
                    days_of_supply = round(rng.uniform(0.6, 1.4), 1)
                    stockout_flag = 1
                elif plant == SHOCK_PLANT and sku in STOCKOUT_SKUS and month == pd.Timestamp("2026-04-01"):
                    # rebuilding
                    on_hand_units = int(safety_stock * rng.uniform(0.5, 0.8))
                    days_of_supply = round(rng.uniform(4.0, 7.0), 1)
                    stockout_flag = 0
                else:
                    drift = rng.normal(0, 40)
                    on_hand_units = max(50, int(on_hand + drift))
                    days_of_supply = round(on_hand_units / max(1, safety_stock) * rng.uniform(5.5, 7.5), 1)
                    stockout_flag = 0
                rows.append(
                    {
                        "plant": plant,
                        "sku": sku,
                        "month": month,
                        "on_hand_units": on_hand_units,
                        "safety_stock": safety_stock,
                        "days_of_supply": days_of_supply,
                        "stockout_flag": stockout_flag,
                    }
                )
    return pd.DataFrame(rows)


def build_service_levels():
    rows = []
    for region in sorted(set(PLANTS.values())):
        for month in MONTHS:
            if region == "China":
                service_pct = REGION_SERVICE_OVERRIDE.get(month, REGION_BASELINE_SERVICE)
                backorders = REGION_BACKORDER_OVERRIDE.get(month, REGION_BASELINE_BACKORDERS)
            else:
                service_pct = float(np.clip(REGION_BASELINE_SERVICE + rng.normal(0, 0.004), 0.93, 0.99))
                backorders = int(max(0, REGION_BASELINE_BACKORDERS + rng.normal(0, 25)))
            rows.append(
                {
                    "region": region,
                    "month": month,
                    "service_pct": round(service_pct, 4),
                    "backorder_units": int(backorders + rng.integers(-10, 10)),
                }
            )
    return pd.DataFrame(rows)


def verify(otif, inventory, lanes, service):
    print("== verification ==")

    def lane_otif(lane, month):
        sub = otif[(otif["lane"] == lane) & (otif["month"] == month)]
        return round((sub["otif_pct"] * sub["orders"]).sum() / sub["orders"].sum() * 100, 1)

    def region_otif(region, month):
        sub = otif[(otif["region"] == region) & (otif["month"] == month)]
        return round((sub["otif_pct"] * sub["orders"]).sum() / sub["orders"].sum() * 100, 1)

    baseline_month = pd.Timestamp("2025-10-01")
    print(f"  {SHOCK_LANE} OTIF baseline ({baseline_month.date()}): {lane_otif(SHOCK_LANE, baseline_month)}%")
    for m in [pd.Timestamp("2026-02-01"), WORST_MONTH, pd.Timestamp("2026-04-01"), pd.Timestamp("2026-05-01"), pd.Timestamp("2026-06-01")]:
        print(f"  {SHOCK_LANE} OTIF {m.date()}: {lane_otif(SHOCK_LANE, m)}%")

    print(f"  China region OTIF {WORST_MONTH.date()}: {region_otif('China', WORST_MONTH)}%")
    for region in ["EMEA", "Americas", "APAC"]:
        print(f"  {region} region OTIF {WORST_MONTH.date()} (control): {region_otif(region, WORST_MONTH)}%")

    svc_worst = service[(service["region"] == "China") & (service["month"] == WORST_MONTH)]
    print(f"  China service_pct {WORST_MONTH.date()}: {svc_worst['service_pct'].iloc[0] * 100:.1f}%  backorders={svc_worst['backorder_units'].iloc[0]}")

    stockouts = inventory[(inventory["month"].isin(STOCKOUT_MONTHS)) & (inventory["stockout_flag"] == 1)]
    print(f"  stockout rows Feb-Mar 2026: {len(stockouts)} (expect {len(STOCKOUT_SKUS) * len(STOCKOUT_MONTHS)})")
    print(stockouts[["plant", "sku", "month", "days_of_supply"]].to_string(index=False))

    other_region_stable = all(
        region_otif(r, WORST_MONTH) >= 94.0 for r in ["EMEA", "Americas", "APAC"]
    )
    print(f"  other regions stable in worst month: {other_region_stable}")


def main():
    os.makedirs(OUT, exist_ok=True)
    pairs = plant_sku_pairs()

    lanes = build_lanes()
    otif = build_otif(pairs)
    inventory = build_inventory(pairs)
    service = build_service_levels()

    lanes.to_parquet(os.path.join(OUT, "lanes.parquet"), index=False)
    otif.to_parquet(os.path.join(OUT, "otif.parquet"), index=False)
    inventory.to_parquet(os.path.join(OUT, "inventory.parquet"), index=False)
    service.to_parquet(os.path.join(OUT, "service_levels.parquet"), index=False)

    print("== row counts ==")
    print(f"  lanes: {len(lanes)}")
    print(f"  otif: {len(otif)}")
    print(f"  inventory: {len(inventory)}")
    print(f"  service_levels: {len(service)}")

    verify(otif, inventory, lanes, service)


if __name__ == "__main__":
    main()
