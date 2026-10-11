{#
    Mart revenue must equal the source's Won close_value total to the cent.
    This is the end-to-end tie-out: raw CSV -> raw schema -> staging ->
    intermediate -> mart, with the GTXPro repair (1,480 rows) included on
    both sides because the source side filters only on stage.
#}

with mart as (

    select
        round(sum(revenue), 2) as mart_revenue

    from {{ ref('fct_opportunity') }}

),

source_ as (

    select
        round(sum(close_value), 2) as source_revenue

    from {{ source('crm_raw', 'sales_pipeline') }}

    where deal_stage = 'Won'

)

select
    mart.mart_revenue,
    source_.source_revenue

from mart
cross join source_

where mart.mart_revenue <> source_.source_revenue
