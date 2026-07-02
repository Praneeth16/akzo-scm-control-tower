# Setup — Databricks Free Edition

Ordered checklist. Free Edition, single-user workspace. Every step that needs manual UI
clicking is called out explicitly — this repo has no Terraform/DAB automation for
resource provisioning.

Fill in the values you collect as you go — you'll need most of them for `app/.env` and
`app/app.yaml` in step 13.

---

### 1. Workspace access

Log into your Free Edition workspace. Note the URL — you'll pass it as `--host` (or via a
CLI profile) in later steps.

### 2. Unity Catalog catalog + schema

**UI:** Catalog Explorer (left sidebar → Catalog) → **Create Catalog** (or use an
existing one) → inside it, **Create Schema**.

Note the names as `AKZO_CATALOG` / `AKZO_SCHEMA`.

### 3. Serverless SQL warehouse

**UI:** Compute → SQL Warehouses → **Create SQL Warehouse**. Any size works for this
demo's data volume — Free Edition serverless is fine.

Open the warehouse, copy the id from the URL (`.../sql/warehouses/<id>`) into
`DATABRICKS_WAREHOUSE_ID`.

### 4. Generate + load data

Locally:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install numpy pandas pyarrow
python3 data/generate_scm_data.py
```

Confirms 4 parquet files under `data/output/scm/` and prints a verification block —
check it shows the March 2026 China dip and stable other-region OTIF before continuing.

Then run `data/load_to_uc.py` **as a Databricks notebook** (it needs `spark`/`dbutils`,
which only exist in that context):

1. Workspace → Create → Notebook.
2. Paste the contents of `data/load_to_uc.py` into a cell (or upload the file and
   `%run` it).
3. At the top of the notebook, set the 3 required env vars before running, e.g.:
   ```python
   import os
   os.environ["AKZO_CATALOG"] = "<your catalog>"
   os.environ["AKZO_SCHEMA"] = "<your schema>"
   os.environ["AKZO_STAGING"] = "<a UC volume path for staging uploads>"
   ```
4. Attach the notebook to the SQL warehouse from step 3 (or any cluster with Spark).
5. Run All. The script uploads the 4 parquet files and creates 4 UC tables idempotently
   (`CREATE OR REPLACE TABLE ... AS SELECT * FROM read_files(...)`).

### 5. Verify the load

SQL editor:

```sql
SELECT COUNT(*) FROM <catalog>.<schema>.otif;
```

Should return a few thousand rows (24 months × plants × lanes × skus). Spot-check
`inventory`, `lanes`, `service_levels` too.

### 6. Foundation Model endpoint

**UI:** Serving (left sidebar) → confirm `databricks-claude-opus-4-8` (or whatever
chat-capable pay-per-token endpoint your workspace is entitled to) is listed and
queryable. Note the endpoint name into `DATABRICKS_CHAT_ENDPOINT`.

### 7. Genie Space (UI)

This step is for **human ad hoc exploration only** — the app's own "Ask the Control
Tower" page does NOT call this Space; it calls the model endpoint directly via
`text2sql.py`. Still worth creating so you (and anyone reviewing the demo) can explore
the data conversationally in the native Databricks UI.

1. Left sidebar → **New** → **Genie space**.
2. Name it "Akzo SCM Control Tower".
3. **Add data** → select the SQL warehouse from step 3 → attach `otif`, `inventory`,
   `lanes`, `service_levels` from your catalog/schema.
4. **Instructions** tab → paste the full body of `genie/scm_space.md` (fill in the
   `<catalog>.<schema>` placeholders in the table names first).
5. **Sample questions** tab → paste the example questions listed near the bottom of
   `genie/scm_space.md`.
6. Save / Publish. Note the Space id from the URL (`.../genie/rooms/<space_id>`) if you
   want to link it anywhere — not required by the app itself.

### 8. Lakebase instance (UI)

**UI:** Compute (or "Lakebase" if it has its own sidebar entry) → Database Instances →
**Create** → name it `scm-control-tower` → wait for status `AVAILABLE`.

Note the instance name into `LAKEBASE_INSTANCE`.

### 9. Postgres schema

Free Edition is single-user, so there's no separate role-provisioning step — your own
identity already has access to the instance. The app creates the `akzo` schema itself
on first run via `CREATE SCHEMA IF NOT EXISTS akzo` (see `app/lib/lakebase.py`), so no
manual `psql` step is required here. `LAKEBASE_SCHEMA` is already `akzo` in
`.env.example`/`app.yaml` — leave it as-is unless you have a reason to change it.

### 10. Push the repo to GitHub

```bash
gh repo create Praneeth16/akzo-scm-control-tower --public --source=. --push
```

### 11. Create the Databricks App resource (UI)

**UI:** Compute → Apps → **Create app** → **Custom app** → name it
`akzo-scm-control-tower` → **Create**. Wait for status `ACTIVE`.

Open the app's detail page and note its **service principal client ID** — you'll grant
permissions to it in the next step, since the app runs as that SP, not as you.

### 12. Grant the app's service principal access

**Unity Catalog** (SQL editor, as yourself):

```sql
GRANT USE CATALOG ON CATALOG <catalog> TO `<app-sp-client-id>`;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<app-sp-client-id>`;
GRANT SELECT ON SCHEMA <catalog>.<schema> TO `<app-sp-client-id>`;
```

**SQL warehouse:** warehouse detail page → Permissions tab → add the SP → **Can Use**.

**Model Serving endpoint:** Serving → endpoint → Permissions tab → add the SP →
**Can Query** (only needed if the endpoint isn't already open to all workspace users).

**Lakebase:** Database Instance detail page → Roles/Permissions → add the SP's client ID
as a role, then grant it schema access — either via the UI's grant dialog, or a one-off
local script using `psycopg` and your own short-lived credential:

```python
# one-off, run locally with your own Databricks auth
GRANT USAGE, CREATE ON SCHEMA akzo TO "<app-sp-client-id>";
```

### 13. Fill in `app.yaml`

Edit `app/app.yaml`'s `env` block with the values collected in steps 2, 3, 6, 8:

- `DATABRICKS_WAREHOUSE_ID` — step 3
- `AKZO_CATALOG` / `AKZO_SCHEMA` — step 2
- `DATABRICKS_CHAT_ENDPOINT` — step 6
- `LAKEBASE_INSTANCE` — step 8
- `LAKEBASE_DBNAME` / `LAKEBASE_SCHEMA` — leave as `databricks_postgres` / `akzo`
  unless you changed them

### 14. Deploy

```bash
databricks sync ./app /Workspace/Users/<you>/akzo-scm-control-tower --profile <profile>
databricks apps deploy akzo-scm-control-tower \
  --source-code-path /Workspace/Users/<you>/akzo-scm-control-tower \
  --profile <profile>
```

Wait for status `SUCCEEDED`, then open the app URL from the Apps UI.

### 15. Verify

Walk all 3 pages as the deployed app (not just locally):

- **Overview** — charts and KPIs render, no exceptions.
- **Ask the Control Tower** — ask *"Why did OTIF for Performance Coatings China drop in
  March 2026?"*, confirm it returns a real result with SQL shown in the expander.
- **Recommended Interventions** — confirm HIGH-severity rows appear for the disrupted
  lane/SKUs/China region, Accept one, refresh the page, confirm it now shows in
  **Decision history** (proves the write landed in Lakebase, not just session state).

If any step fails with a permissions error, it's almost always a missed grant in
step 12 — the app runs as its service principal, not as you.
