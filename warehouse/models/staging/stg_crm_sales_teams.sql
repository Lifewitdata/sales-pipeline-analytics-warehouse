with source as (

    select * from {{ source('crm_raw', 'sales_teams') }}

),

cleaned as (

    select
        trim(sales_agent)                                    as agent_name,
        trim(manager)                                        as manager_name,
        trim(regional_office)                                as regional_office,

        _loaded_at

    from source

)

select
    {{ surrogate_key(['agent_name']) }}                      as sales_agent_key,
    agent_name,
    manager_name,
    regional_office,
    _loaded_at
from cleaned
