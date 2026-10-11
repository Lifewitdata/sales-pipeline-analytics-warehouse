{#
    Per-agent scorecard. One row per agent with closed-deal win rate,
    Won revenue, deal size and cycle times, and the open pipeline the agent
    is carrying at the snapshot date. Ranked by Won revenue.
#}

with fct as (

    select * from {{ ref('fct_opportunity') }}

),

agents as (

    select * from {{ ref('dim_sales_agent') }}

),

scored as (

    select
        fct.sales_agent_key,

        count(*)                                            as total_opportunities,
        sum(case when fct.is_won then 1 else 0 end)         as won_count,
        sum(case when fct.is_lost then 1 else 0 end)        as lost_count,
        sum(case when fct.is_open then 1 else 0 end)        as open_pipeline_count,

        round(
            sum(case when fct.is_won then 1 else 0 end)
            / nullif(sum(case when fct.is_closed then 1 else 0 end), 0),
        4)                                                  as win_rate,

        sum(fct.revenue)                                    as total_revenue,
        avg(case when fct.is_won then fct.revenue end)      as avg_won_deal_size,
        avg(case when fct.is_won then fct.sales_cycle_days end)
                                                            as avg_won_cycle_days

    from fct

    group by fct.sales_agent_key

)

select
    agents.sales_agent_key,
    agents.agent_name,
    agents.manager_name,
    agents.regional_office,

    scored.total_opportunities,
    scored.won_count,
    scored.lost_count,
    scored.open_pipeline_count,
    scored.win_rate,
    scored.total_revenue,
    scored.avg_won_deal_size,
    scored.avg_won_cycle_days,

    rank() over (order by scored.total_revenue desc)        as revenue_rank

from scored

join agents
    on agents.sales_agent_key = scored.sales_agent_key

order by scored.total_revenue desc
