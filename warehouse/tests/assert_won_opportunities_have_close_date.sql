{#
    A Won opportunity must carry both close_date and close_value. Any row
    returned here fails the build.
#}

select
    opportunity_id,
    deal_stage,
    close_date,
    close_value_raw

from {{ ref('fct_opportunity') }}

where is_won
    and (close_date is null or close_value_raw is null)
