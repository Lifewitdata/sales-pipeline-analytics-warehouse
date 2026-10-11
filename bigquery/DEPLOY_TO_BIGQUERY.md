# Flipping the warehouse to BigQuery

**Status honesty first.** Every model in `warehouse/` was built and verified
against the DuckDB dev target - `dbt build` passes 67/67 there, and the
dashboard, benchmark and metric figures in this repo all come from that run.
The BigQuery target is **configured and dialect-reviewed but has not been
executed live** in this build: there is no GCP project behind it yet. This
document is the path to changing that in roughly 15 minutes, and the numbers
in the README stay DuckDB numbers until someone runs this.

Nothing in the repo contains credentials. The profile reads four environment
variables and fails loudly if they are missing - that is by design, so a
service-account key never ends up in git.

## Why the models should compile on BigQuery unchanged

`warehouse/macros/compat.sql` isolates every place the two dialects diverge:
`datediff_days`, `date_trunc_to`, `safe_cast`, `date_spine`, `surrogate_key`,
plus a `generate_schema_name` override so marts land in `marts`, not
`dev_marts`. Models themselves contain no adapter branching. Two deliberate
choices keep that true:

- counts use `sum(case when ... then 1 else 0 end)`, because the countif
  spelling differs between engines (DuckDB `count_if`, BigQuery `COUNTIF`);
- `dim_date` only uses date parts with identical semantics in both
  (`extract(year/quarter/month/day/doy/isodow)`); named parts that diverge
  (`monthname` vs `format_date`) were left out rather than bridged.

If `dbt compile --target bigquery_prod` fails, the failure is information: it
means something outside compat.sql grew a dialect dependency, and the fix
belongs in compat.sql.

## 1. Create the GCP side (5 minutes, free tier applies)

1. console.cloud.google.com → new project, e.g. `crm-sales-warehouse-lab`.
2. Enable the BigQuery API for it.
3. IAM → Service accounts → create one, e.g. `dbt-lab@...`, role
   **BigQuery User** (and Data Editor if you want dbt to create the dataset).
4. Keys → add key → JSON → download. Put the file **outside the repo** (e.g.
   `C:\Users\hp\gcp\dbt-lab.json`) and never commit it - `.gitignore` already
   blocks `service-account*.json` for the day someone tries.

BigQuery's free tier covers this project's scale outright: 1 TB of queries and
10 GB of storage per month, and the whole warehouse here is ~7 MB of source
CSV plus ~2 MB of marts.

## 2. Point the environment at it (2 minutes)

PowerShell:

```powershell
$env:BQ_PROJECT_ID     = "crm-sales-warehouse-lab"
$env:BQ_MARTS_DATASET  = "analytics"
$env:BQ_LOCATION       = "US"
$env:BQ_SA_KEYFILE     = "C:\Users\hp\gcp\dbt-lab.json"
```

Bash:

```bash
export BQ_PROJECT_ID=crm-sales-warehouse-lab
export BQ_MARTS_DATASET=analytics
export BQ_LOCATION=US
export BQ_SA_KEYFILE=/c/Users/hp/gcp/dbt-lab.json
```

The variable names above are the ones `warehouse/profiles.yml` actually reads,
so a missing one fails at connection time with a named env-var error rather
than silently pointing at the wrong project.

## 3. Load the same raw data into BigQuery (3 minutes)

The ELT layer stays the single loader - dbt does not extract in this project.
Two ways, pick one:

**a. bq CLI from the same CSVs already committed here** (recommended, it is
the faithful reproduction of the DuckDB raw layer):

```bash
bq --location=US mk --dataset crm-sales-warehouse-lab:analytics_raw
bq load --source_format=CSV --replace \
  crm-sales-warehouse-lab:analytics_raw.sales_pipeline \
  raw_data/sales_pipeline.csv schema_sales_pipeline.json
```

(Repeat for the other four files; a `--replace` load is what makes the
idempotent DuckDB loader's semantics match.)

**b. Hand-run the raw DDL in `ddl_warehouse.sql`** and stream rows with the
Python client. Use this if you want `_loaded_at` partitioning from day one.

## 4. Run the warehouse (5 minutes)

```bash
pip install dbt-bigquery            # the dev venv only ships dbt-duckdb
cd warehouse
dbt deps                            # none today; harmless
dbt --target bigquery_prod compile  # dialect check before spending anything
dbt --target bigquery_prod build    # models + all 51 tests
```

Expect the first `build` to take a few minutes (dataset creation, then 16
models). After it finishes, `analytics.mv_monthly_office_revenue` from
`ddl_warehouse.sql` is optional - the dbt `reporting` views already cover the
dashboard, and the materialized view exists to demonstrate the BigQuery cost
lever.

## 5. Prove the cost lever, not just the green check

This is the part worth doing, and it is the BigQuery version of
`optimization/RESULTS.md`:

```sql
-- same question, partition predicate present vs absent
select date_trunc(close_date, month) as m, sum(revenue)
from analytics.fct_opportunity
where close_date between '2017-10-01' and '2017-12-31'
group by 1;

select date_trunc(close_date, month) as m, sum(revenue)
from analytics.fct_opportunity
group by 1;
```

Run both in the console, open each job's "Performance" tab, and compare
bytes processed. The first should report a small multiple of the months it
touches; the second scans the full table. Record the two numbers in
`optimization/results.json`'s sibling doc or the PR description - that is the
evidence a reviewer on a data-eng panel actually looks for.

## If something breaks

- `Access Denied: BigQuery BigQuery` → the key file env var is unset or the
  service account lacks BigQuery User.
- `Not found: Dataset ...` → create it (`bq mk --dataset`) or grant Data
  Editor; dbt will not guess your project id.
- A model compiles on DuckDB and fails on BigQuery → the offending expression
  has escaped `compat.sql`; move it there rather than adding
  `{% if target.type == 'bigquery' %}` inside the model.
- `Syntax error: Unsupported statement type` on the DDL file → you pasted a
  `create schema` block into a query editor bound to a specific dataset; run
  DDL from the project level.

## What this repo claims, precisely

| claim | basis |
|---|---|
| 67/67 models + tests pass | executed, DuckDB, this machine |
| $10,005,534 revenue, 63.15% win rate, 1,480 repaired labels | executed warehouse output |
| 6.5x / 93% less I/O from partition pruning | executed benchmark, 40M rows |
| models are BigQuery-portable | dialect layer + review, **not executed** |
| `ddl_warehouse.sql` runs on BigQuery | written for it, **not executed** |
