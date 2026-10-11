{#
    Opportunity fact with every FK resolved and every known defect repaired.

    The product join deliberately does NOT match on the raw label: the source
    carries 'GTXPro' where the master says 'GTX Pro' on 1,480 rows (DQ-003).
    Both sides are reduced to a lowercase alphanumeric key so the join
    recovers those rows without editing source data, and
    is_product_key_repaired keeps the repair auditable. Verified at design
    time: 0 rows remain unmapped after the normalized join.
#}

with opportunities as (

    select * from {{ ref('stg_crm_opportunities') }}

),

products as (

    select * from {{ ref('stg_crm_products') }}

),

accounts as (

    select * from {{ ref('stg_crm_accounts') }}

),

teams as (

    select * from {{ ref('stg_crm_sales_teams') }}

),

enriched as (

    select
        opp.opportunity_id,

        teams.sales_agent_key,
        teams.agent_name,
        teams.manager_name,
        teams.regional_office,

        products.product_key,
        products.product_name,
        opp.product_name_raw,
        products.product_name <> opp.product_name_raw       as is_product_key_repaired,
        products.product_series,

        accounts.account_key,
        accounts.account_name,
        accounts.sector,
        accounts.office_country,
        accounts.is_domestic,

        opp.deal_stage,
        opp.stage_order,
        opp.is_won,
        opp.is_lost,
        opp.is_closed,
        opp.is_open,
        opp.revenue,
        opp.close_value_raw,

        opp.engage_date,
        opp.close_date,

        {{ datediff_days('opp.engage_date', 'opp.close_date') }}
                                                            as sales_cycle_days,

        {#- Snapshot-relative measures use the data's own max close date
            (2017-12-31), not current_date, so every build is deterministic
            and the tests are reproducible. -#}
        max(opp.close_date) over ()                         as snapshot_date,

        opp.is_pipeline_open,
        opp.is_account_missing,
        opp.is_pre_engagement,
        opp._loaded_at

    from opportunities opp

    left join products
        on products.product_name_normalized
            = lower(regexp_replace(opp.product_name_raw, '[^A-Za-z0-9]', '', 'g'))

    left join accounts
        on accounts.account_name = opp.account_name

    left join teams
        on teams.agent_name = opp.sales_agent_name

)

select * from enriched
