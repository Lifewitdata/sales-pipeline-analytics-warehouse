with source as (

    select * from {{ source('crm_raw', 'accounts') }}

),

cleaned as (

    select
        trim(account)                                   as account_name,
        trim(account)                                   as account_name_raw,

        {#- DQ-015: 'technolgy' is repaired to 'technology'. The raw value is
            kept on every row so the repair is auditable and reversible.
            Raw columns are qualified with the CTE name because `sector` is
            also an output alias of this select. -#}
        case lower(trim(source.sector))
            when 'technolgy' then 'technology'
            else lower(trim(source.sector))
        end                                             as sector,
        source.sector                                   as sector_raw,
        lower(trim(source.sector)) = 'technolgy'        as is_sector_repaired,

        source.year_established,
        source.revenue                                  as annual_revenue,
        source.employees                                as employee_count,

        {#- DQ-016: 'Philipines' -> 'Philippines'. -#}
        case lower(trim(source.office_location))
            when 'philipines' then 'Philippines'
            when 'united states' then 'United States'
            else trim(source.office_location)
        end                                             as office_country,
        source.office_location                          as office_country_raw,
        lower(trim(source.office_location)) = 'philipines'
                                                        as is_country_repaired,

        trim(source.office_location) = 'United States'  as is_domestic,

        {#- Null means the account is independent, not that the parent is
            unknown - 70 of 85 rows are independent by design. -#}
        trim(source.subsidiary_of)                      as parent_account_name,
        source.subsidiary_of is not null                as is_subsidiary,

        source._loaded_at

    from source

)

select
    {{ surrogate_key(['account_name']) }}               as account_key,
    account_name,
    account_name_raw,
    sector,
    sector_raw,
    is_sector_repaired,
    year_established,
    annual_revenue,
    employee_count,
    office_country,
    office_country_raw,
    is_country_repaired,
    is_domestic,
    parent_account_name,
    is_subsidiary,
    _loaded_at
from cleaned
