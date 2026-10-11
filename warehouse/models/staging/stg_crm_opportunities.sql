with source as (

    select * from {{ source('crm_raw', 'sales_pipeline') }}

),

cleaned as (

    select
        trim(source.opportunity_id)                          as opportunity_id,
        trim(source.sales_agent)                             as sales_agent_name,
        trim(source.product)                                 as product_name_raw,
        trim(source.account)                                 as account_name,
        trim(source.deal_stage)                              as deal_stage,

        {#- DQ-009: Lost deals are recorded at close_value = 0, not null - so
            revenue is a stage-filtered measure, never a close_value > 0
            filter. Raw columns are qualified with the CTE name because
            `deal_stage` is also an output alias of this select. -#}
        source.deal_stage = 'Won'                            as is_won,
        source.deal_stage = 'Lost'                           as is_lost,
        source.deal_stage in ('Won', 'Lost')                 as is_closed,
        source.deal_stage in ('Prospecting', 'Engaging')     as is_open,

        case source.deal_stage
            when 'Prospecting' then 1
            when 'Engaging'    then 2
            when 'Won'         then 3
            when 'Lost'        then 3
        end                                                  as stage_order,

        case when source.deal_stage = 'Won' then source.close_value else 0 end
                                                             as revenue,
        source.close_value                                   as close_value_raw,

        source.engage_date,
        source.close_date,

        {#- DQ-008: null close_date is exactly the open pipeline (2,089 rows =
            500 Prospecting + 1,589 Engaging) and is never imputed. -#}
        source.close_date is null                          as is_pipeline_open,

        {#- DQ-004/005: account and engage_date nulls stay null; they mark
            never-engaged and never-attributed opportunities. -#}
        trim(source.account) is null                       as is_account_missing,
        source.engage_date is null                         as is_pre_engagement,

        source._loaded_at

    from source

)

select
    opportunity_id,
    {{ surrogate_key(['sales_agent_name']) }}                as sales_agent_key,
    sales_agent_name,
    product_name_raw,
    account_name,
    deal_stage,
    stage_order,
    is_won,
    is_lost,
    is_closed,
    is_open,
    revenue,
    close_value_raw,
    engage_date,
    close_date,
    is_pipeline_open,
    is_account_missing,
    is_pre_engagement,
    _loaded_at
from cleaned
