{#
    Data quality summary for the dashboard DQ page. Aggregates the row-level
    flags from int_data_quality_flags to one row per check, plus the
    opportunity-level null profile a reviewer usually wants next to it.

    The counts here are live aggregates of the same warehouse the business
    reads from - they are not the static extract-time numbers in
    reports/source_profile.json. Both exist on purpose: the JSON profiles the
    bytes as landed, this view profiles the warehouse as modelled.
#}

with flags as (

    select * from {{ ref('int_data_quality_flags') }}

),

flag_summary as (

    select
        check_id,
        severity,
        finding,
        count(*)                                as flagged_rows

    from flags

    group by
        check_id,
        severity,
        finding

),

final as (

    select
        check_id,
        severity,
        finding,
        flagged_rows

    from flag_summary

)

select * from final
