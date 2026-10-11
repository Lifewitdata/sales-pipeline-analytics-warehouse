{#
    Monthly pipeline snapshot by regional office. Grain: one row per
    (month, regional_office).

    Open-pipeline-at-month-end is a count, not a value: the source carries no
    pre-close amount on an opportunity (close_value lands only at close, and
    is null while open - DQ-006/007), so any "pipeline value" figure would be
    fabricated. Engaged-in-month uses engage_date; the 500 never-engaged
    Prospecting rows enter only through the open-pipeline measure.

    Counts are sum(case ...) rather than countif: the function name differs
    between DuckDB (count_if) and BigQuery (COUNTIF), and sum(case) is
    identical in both, so the compat layer stays small.
#}

with opportunities as (

    select * from {{ ref('int_opportunity_enriched') }}

),

months as (

    select distinct
        {{ date_trunc_to('month', 'engage_date') }}       as month_start

    from opportunities

    where engage_date is not null

    union

    select distinct
        {{ date_trunc_to('month', 'close_date') }}

    from opportunities

    where close_date is not null

),

offices as (

    select distinct regional_office from opportunities

),

grid as (

    select
        months.month_start,
        offices.regional_office

    from months
    cross join offices

),

scored as (

    select
        grid.month_start,
        grid.regional_office,

        sum(case
            when opp.engage_date is not null
                and {{ date_trunc_to('month', 'opp.engage_date') }} = grid.month_start
            then 1 else 0
        end)                                             as engaged_count,

        sum(case
            when opp.is_won
                and {{ date_trunc_to('month', 'opp.close_date') }} = grid.month_start
            then 1 else 0
        end)                                             as won_count,

        sum(case
            when opp.is_lost
                and {{ date_trunc_to('month', 'opp.close_date') }} = grid.month_start
            then 1 else 0
        end)                                             as lost_count,

        sum(case
            when opp.is_closed
                and {{ date_trunc_to('month', 'opp.close_date') }} = grid.month_start
            then 1 else 0
        end)                                             as closed_count,

        sum(case
            when opp.is_won
                and {{ date_trunc_to('month', 'opp.close_date') }} = grid.month_start
            then opp.revenue
            else 0
        end)                                             as won_revenue,

        avg(case
            when opp.is_won
                and {{ date_trunc_to('month', 'opp.close_date') }} = grid.month_start
            then opp.sales_cycle_days
        end)                                             as avg_won_cycle_days,

        -- Open pipeline at month end: engaged (or never-engaged, so the
        -- pre-engagement Prospecting rows are visible) and not yet closed.
        sum(case
            when (opp.engage_date is null or opp.engage_date <= grid.month_start)
                and (opp.close_date is null or opp.close_date > grid.month_start)
            then 1 else 0
        end)                                             as open_pipeline_count

    from grid

    left join opportunities as opp
        on opp.regional_office = grid.regional_office

    group by
        grid.month_start,
        grid.regional_office

)

select * from scored
