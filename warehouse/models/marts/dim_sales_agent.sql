with agents as (

    select * from {{ ref('stg_crm_sales_teams') }}

),

managers as (

    select
        agent_name,
        sales_agent_key as manager_key

    from agents

),

final as (

    select
        agents.sales_agent_key,
        agents.agent_name,
        agents.manager_name,
        managers.manager_key,
        agents.regional_office

    from agents

    left join managers
        on managers.agent_name = agents.manager_name

)

select * from final
