-- Native BigQuery DDL for the sales pipeline warehouse.
--
-- WHY THIS FILE EXISTS SEPARATELY FROM dbt
--   The dbt project (profile target `bigquery_prod`) materializes these same
--   models with dbt-duckdb-style dialect translation. This file is the
--   hand-written BigQuery-native version of the two tables where physical
--   layout actually matters - the partition/cluster clauses below cannot be
--   expressed in a dbt model's SQL body; they live in dbt config as
--   `+on_table_change` / partition_by metadata or, here, as plain DDL.
--   Running this file gives you the warehouse without dbt; running dbt gives
--   you the same tables plus the tests. Pick one - they target the same
--   dataset names.
--
-- WHY PARTITION + CLUSTER
--   optimization/RESULTS.md measured a 6.5x / 93%-less-I/O win from partition
--   pruning on 40M rows locally. On BigQuery the same lever is a cost lever:
--   bytes scanned is billed, and partition elimination is the only way to
--   keep a growing fact table cheap. The pattern below mirrors what was
--   measured: partition on the event date the filters use, cluster on the
--   low-cardinality filter column that follows.

#standardSQL

-- 1. Raw landing zone - the Python ELT layer appends here with _loaded_at,
--    exactly as it does into the DuckDB `raw` schema.
create schema if not exists analytics_raw;

create table if not exists analytics_raw.sales_pipeline (
    opportunity_id string,
    sales_agent    string,
    product        string,
    account        string,
    deal_stage     string,
    engage_date    date,
    close_date     date,
    close_value    numeric,
    _loaded_at     timestamp
)
partition by date_trunc(_loaded_at, day)
cluster by deal_stage;

create table if not exists analytics_raw._load_manifest (
    load_run_id     string,
    source_file     string,
    target_table    string,
    row_count       int64,
    column_count    int64,
    source_sha256   string,
    loaded_at       timestamp,
    load_duration_ms int64
);

-- 2. Opportunity fact: one row per opportunity_id.
--    PARTITION BY month(close_date) - the single most-filtered predicate in
--    every reporting view. Open deals have null close_date, and BigQuery
--    routes nulls into a __NULL__ partition, which is exactly right: they
--    are the open pipeline and should never be scanned by a closed-deal
--    query (DQ-008).
--    CLUSTER BY deal_stage, sales_agent_key - stage is the low-cardinality
--    filter that survives pruning of whole partitions; the agent key lets
--    scorecard queries skip row blocks inside a partition.
create schema if not exists analytics;

create table if not exists analytics.fct_opportunity (
    opportunity_id        string,
    sales_agent_key       string,
    product_key           string,
    account_key           string,
    engage_date           date,
    close_date            date,
    deal_stage            string,
    stage_order           int64,
    is_won                bool,
    is_lost               bool,
    is_closed             bool,
    is_open               bool,
    revenue               numeric,
    close_value_raw       numeric,
    sales_cycle_days      int64,
    snapshot_date         date,
    days_open_at_snapshot int64,
    is_account_missing    bool,
    is_pre_engagement     bool,
    _loaded_at            timestamp
)
partition by date_trunc(close_date, month)
cluster by deal_stage, sales_agent_key
options(description = 'Opportunity fact. revenue = Won close_value only; see docs/METRIC_DEFINITIONS.md');

-- 3. Monthly pipeline snapshot: small by construction (3 offices x 15 months
--    on this extract), so it is clustered, not partitioned - partitioning a
--    table this small would only fragment it.
create table if not exists analytics.fct_pipeline_monthly (
    month_start          date,
    regional_office      string,
    engaged_count        int64,
    won_count            int64,
    lost_count           int64,
    closed_count         int64,
    won_revenue          numeric,
    avg_won_cycle_days   float64,
    open_pipeline_count  int64
)
cluster by regional_office;

-- 4. Agent dimension - tiny (35 rows), no layout tuning; it exists so the
--    materialized view below has an office to group on.
create table if not exists analytics.dim_sales_agent (
    sales_agent_key string,
    agent_name      string,
    manager_name    string,
    manager_key     string,
    regional_office string
);

-- 5. Materialized view: the exec-overview aggregate. BigQuery materialized
--   views refresh automatically on underlying-table writes and are billed at
--   storage price, not query price, so a KPI strip that every dashboard load
--   re-runs is the right candidate.
create materialized view if not exists analytics.mv_monthly_office_revenue as
select
    date_trunc(close_date, month) as month_start,
    a.regional_office,
    sum(f.revenue)                as won_revenue,
    countif(f.is_won)             as won_count,
    countif(f.is_lost)            as lost_count,
    countif(f.is_open)            as open_pipeline_count
from analytics.fct_opportunity f
join analytics.dim_sales_agent a
  on a.sales_agent_key = f.sales_agent_key
group by 1, 2;

-- 6. Cost/usage monitoring - the BigQuery equivalent of the timing loop in
--    optimization/run_benchmark.py. total_bytes_processed is what a query
--    billed; compare a partition-filtered run against the same query without
--    the partition predicate to see elimination working.
--
-- select
--     job_id,
--     statement_type,
--     total_bytes_processed,
--     total_slot_ms,
--     timeline_duration_ms
-- from `analytics-region`.region-us.information_schema.jobs_by_project
-- where statement_type = 'SELECT'
--   and creation_time > timestamp_sub(current_timestamp(), interval 1 day)
-- order by total_bytes_processed desc
-- limit 25;
