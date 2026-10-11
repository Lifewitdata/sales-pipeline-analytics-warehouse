"""Data access for the dashboard.

One read-only DuckDB connection shared across pages (cache_resource) and
per-query caching (cache_data). All SQL here reads the dbt marts/reporting
schemas - pages never query raw or staging directly, so a page can only show
what the tested warehouse exposes.
"""

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

WAREHOUSE = Path(__file__).resolve().parent.parent / "warehouse" / "crm_warehouse.duckdb"


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE), read_only=True)


@st.cache_data(ttl="5m", show_spinner=False)
def query(sql: str) -> pd.DataFrame:
    return get_connection().execute(sql).df()


# --- reporting views -------------------------------------------------------

@st.cache_data(ttl="5m", show_spinner=False)
def exec_overview() -> pd.DataFrame:
    return query("select * from reporting.rpt_exec_overview")


@st.cache_data(ttl="5m", show_spinner=False)
def stage_funnel() -> pd.DataFrame:
    return query(
        """
        select
            deal_stage,
            stage_order,
            count(*)              as opportunities,
            sum(revenue)          as won_revenue
        from marts.fct_opportunity
        group by deal_stage, stage_order
        order by stage_order
        """
    )


@st.cache_data(ttl="5m", show_spinner=False)
def revenue_by_office() -> pd.DataFrame:
    return query(
        """
        select
            a.regional_office,
            count(*)                         as opportunities,
            sum(f.revenue)                   as won_revenue,
            sum(case when f.is_closed then 1 else 0 end) as closed_count,
            sum(case when f.is_won then 1 else 0 end)    as won_count
        from marts.fct_opportunity f
        join marts.dim_sales_agent a
          on a.sales_agent_key = f.sales_agent_key
        group by a.regional_office
        order by won_revenue desc
        """
    )


@st.cache_data(ttl="5m", show_spinner=False)
def monthly_trend(offices: tuple[str, ...]) -> pd.DataFrame:
    office_filter = office_sql_filter(offices)
    return query(
        f"""
        select
            month_start,
            sum(engaged_count)   as engaged,
            sum(won_count)       as won,
            sum(lost_count)      as lost,
            sum(won_revenue)     as won_revenue,
            sum(open_pipeline_count) as open_pipeline
        from marts.fct_pipeline_monthly
        where {office_filter}
        group by month_start
        order by month_start
        """
    )


@st.cache_data(ttl="5m", show_spinner=False)
def pipeline_health(offices: tuple[str, ...]) -> pd.DataFrame:
    office_filter = office_sql_filter(offices)
    return query(
        f"""
        select *
        from reporting.rpt_pipeline_health
        where {office_filter}
        order by month_start, regional_office
        """
    )


@st.cache_data(ttl="5m", show_spinner=False)
def rep_scorecard(offices: tuple[str, ...], managers: tuple[str, ...]) -> pd.DataFrame:
    filters = [office_sql_filter(offices, alias="rpt")]
    if managers:
        managers_list = ", ".join(f"'{m}'" for m in managers)
        filters.append(f"rpt.manager_name in ({managers_list})")
    where = " and ".join(filters)
    return query(
        f"""
        select *
        from reporting.rpt_rep_scorecard rpt
        where {where}
        order by total_revenue desc
        """
    )


@st.cache_data(ttl="5m", show_spinner=False)
def data_quality_flags() -> pd.DataFrame:
    return query(
        """
        select check_id, severity, finding, flagged_rows
        from reporting.rpt_data_quality
        order by check_id
        """
    )


@st.cache_data(ttl="5m", show_spinner=False)
def offices() -> list[str]:
    df = query(
        "select distinct regional_office from marts.dim_sales_agent order by regional_office"
    )
    return df["regional_office"].tolist()


@st.cache_data(ttl="5m", show_spinner=False)
def managers() -> list[str]:
    df = query(
        "select distinct manager_name from marts.dim_sales_agent order by manager_name"
    )
    return df["manager_name"].tolist()


@st.cache_data(ttl="5m", show_spinner=False)
def opportunity_completeness() -> pd.DataFrame:
    return query(
        """
        select
            count(*)                                            as total_opportunities,
            sum(case when account_key is null then 1 else 0 end) as missing_account,
            sum(case when engage_date is null then 1 else 0 end) as missing_engage_date,
            sum(case when close_date is null then 1 else 0 end)   as open_pipeline
        from marts.fct_opportunity
        """
    )


@st.cache_data(ttl="5m", show_spinner=False)
def product_repair_count() -> int:
    df = query(
        """
        select count(*) as repaired_rows
        from intermediate.int_opportunity_enriched
        where is_product_key_repaired
        """
    )
    return int(df["repaired_rows"].iloc[0])


def office_sql_filter(offices: tuple[str, ...], alias: str = "") -> str:
    column = f"{alias}.regional_office" if alias else "regional_office"
    if not offices:
        return "1 = 1"
    offices_list = ", ".join(f"'{o}'" for o in offices)
    return f"{column} in ({offices_list})"
