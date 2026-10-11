{#
    Executive KPI strip. One row. Every figure here is defined in
    docs/METRIC_DEFINITIONS.md - win rate is won / (won + lost), the closed-
    deal rate; revenue is Won close_value only (DQ-009); open pipeline is a
    count because the source carries no pre-close amounts.
#}

with fct as (

    select * from {{ ref('fct_opportunity') }}

),

final as (

    select
        count(*)                                                          as total_opportunities,

        sum(case when is_open then 1 else 0 end)                          as open_pipeline_count,
        sum(case when deal_stage = 'Prospecting' then 1 else 0 end)       as prospecting_count,
        sum(case when deal_stage = 'Engaging' then 1 else 0 end)          as engaging_count,
        sum(case when is_won then 1 else 0 end)                           as won_count,
        sum(case when is_lost then 1 else 0 end)                          as lost_count,

        round(
            sum(case when is_won then 1 else 0 end)
            / nullif(sum(case when is_closed then 1 else 0 end), 0),
        4)                                                                as win_rate,

        sum(revenue)                                                      as total_revenue,

        avg(case when is_won then revenue end)                            as avg_won_deal_size,
        avg(case when is_won then sales_cycle_days end)                   as avg_won_cycle_days,
        avg(case when is_closed then sales_cycle_days end)                as avg_closed_cycle_days,

        count(distinct sales_agent_key)                                   as active_agents,
        count(distinct account_key)                                       as attributed_accounts,

        sum(case when is_account_missing then 1 else 0 end)               as unattributed_opportunities,

        min(engage_date)                                                  as first_engage_date,
        max(close_date)                                                   as snapshot_date

    from fct

)

select * from final
