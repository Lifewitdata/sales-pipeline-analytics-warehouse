{#
    Monthly pipeline health by regional office, built on fct_pipeline_monthly
    so the definitions stay in one place. Win rate and cycle figures inherit
    from the mart; see METRIC_DEFINITIONS.md.
#}

with monthly as (

    select * from {{ ref('fct_pipeline_monthly') }}

),

final as (

    select
        month_start,
        regional_office,

        engaged_count,
        won_count,
        lost_count,
        closed_count,
        won_revenue,

        round(
            won_count / nullif(won_count + lost_count, 0),
        4)                                                as win_rate,

        open_pipeline_count,
        avg_won_cycle_days

    from monthly

)

select * from final
