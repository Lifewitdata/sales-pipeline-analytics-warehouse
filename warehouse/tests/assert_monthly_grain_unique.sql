{#
    fct_pipeline_monthly grain is one row per (month_start, regional_office).
    Any duplicate grain returned here fails the build.
#}

select
    month_start,
    regional_office,
    count(*) as row_count

from {{ ref('fct_pipeline_monthly') }}

group by
    month_start,
    regional_office

having count(*) > 1
