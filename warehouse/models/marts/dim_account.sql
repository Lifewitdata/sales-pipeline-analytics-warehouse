with accounts as (

    select * from {{ ref('stg_crm_accounts') }}

),

parent as (

    select
        account_name,
        account_key as parent_account_key

    from accounts

),

final as (

    select
        accounts.account_key,
        accounts.account_name,
        accounts.sector,
        accounts.year_established,
        accounts.annual_revenue,
        accounts.employee_count,
        accounts.office_country,
        accounts.is_domestic,
        accounts.parent_account_name,
        parent.parent_account_key,
        accounts.is_subsidiary

    from accounts

    left join parent
        on parent.account_name = accounts.parent_account_name

)

select * from final
