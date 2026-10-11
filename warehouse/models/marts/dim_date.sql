{#
    Conformed date dimension spanning the full observed fact range
    (engage 2016-10-20 .. close 2017-12-31, verified against source). Bounds
    are derived from the staging fact, not hardcoded, so a refreshed extract
    that widens the range widens the dim automatically.

    Only date parts whose semantics are identical in DuckDB and BigQuery are
    used (extract year/quarter/month/day/doy/isodow/isoweek). Named parts with
    divergent functions (monthname, dayofweek 0- vs 1-based) are deliberately
    excluded and can be added per-dialect in the BI layer.
#}

with bounds as (

    select
        min(engage_date) as spine_start,
        max(close_date)  as spine_end

    from {{ ref('stg_crm_opportunities') }}

),

spine as (

    select cast(date_day as date) as date_day

    from bounds
    {{ date_spine('bounds.spine_start', 'bounds.spine_end') }}

),

final as (

    select
        extract(year from date_day) * 10000
            + extract(month from date_day) * 100
            + extract(day from date_day)                  as date_key,

        date_day,
        extract(year from date_day)                        as year,
        extract(quarter from date_day)                     as quarter,
        extract(month from date_day)                       as month_num,
        {{ date_trunc_to('month', 'date_day') }}           as month_start,
        extract(week from date_day)                        as iso_week,
        extract(isodow from date_day)                      as iso_day_of_week,
        extract(dayofyear from date_day)                   as day_of_year,

        extract(isodow from date_day) in (6, 7)            as is_weekend

    from spine

)

select * from final
