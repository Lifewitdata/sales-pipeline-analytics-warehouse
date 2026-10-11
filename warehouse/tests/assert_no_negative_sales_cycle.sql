{#
    Close can never precede engagement. Only closed deals are checked; open
    deals have a legitimately null close_date (DQ-008). Any row returned
    here fails the build.
#}

select
    opportunity_id,
    engage_date,
    close_date,
    sales_cycle_days

from {{ ref('fct_opportunity') }}

where is_closed
    and engage_date is not null
    and close_date < engage_date
