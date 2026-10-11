{#
    Row-level data quality findings, one row per (check, flagged entity), in a
    long format the reporting layer can aggregate directly.

    Checks with zero current findings (DQ-002 agent orphans, DQ-010 duplicate
    opportunity ids, DQ-003b unmapped products after normalisation) are kept
    as deliberate left joins / empty branches: an absence of rows IS the
    result, and if the source ever regresses those branches start emitting
    rows without a code change here.
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

-- DQ-003a: rows whose raw product label did not match the master verbatim but
-- were recovered by the normalized join (1,480 rows, warning - repaired).
dq003_repaired as (

    select
        'DQ-003'                                            as check_id,
        'warning'                                           as severity,
        'product label repaired by normalized join'         as finding,
        opp.opportunity_id                                  as entity_id,
        opp.product_name_raw                                as detail

    from opportunities opp

    left join products
        on products.product_name = opp.product_name_raw

    where products.product_name is null

),

-- DQ-003b: rows that survive neither the verbatim nor the normalized join.
-- Must always return zero rows; anything here is an error.
dq003_unmapped as (

    select
        'DQ-003b'                                           as check_id,
        'error'                                             as severity,
        'product label unresolvable after normalized join'  as finding,
        opp.opportunity_id                                  as entity_id,
        opp.product_name_raw                                as detail

    from opportunities opp

    left join products
        on products.product_name_normalized
            = lower(regexp_replace(opp.product_name_raw, '[^A-Za-z0-9]', '', 'g'))

    where products.product_name is null

),

-- DQ-004: opportunity without an attributed account (1,425 rows / 16.19%).
dq004_missing_account as (

    select
        'DQ-004'                                            as check_id,
        'warning'                                           as severity,
        'opportunity missing account attribution'           as finding,
        opportunity_id                                      as entity_id,
        'account is null'                                   as detail

    from opportunities

    where account_name is null

),

-- DQ-005: never-engaged opportunity (500 rows / 5.68%).
dq005_pre_engagement as (

    select
        'DQ-005'                                            as check_id,
        'warning'                                           as severity,
        'opportunity has no engage_date'                    as finding,
        opportunity_id                                      as entity_id,
        'engage_date is null'                               as detail

    from opportunities

    where engage_date is null

),

-- DQ-008: null close_date on an open opportunity. Structural - this IS the
-- open pipeline (2,089 rows = 500 Prospecting + 1,589 Engaging).
dq008_open_pipeline as (

    select
        'DQ-008'                                            as check_id,
        'warning'                                           as severity,
        'open opportunity with null close_date'             as finding,
        opportunity_id                                      as entity_id,
        'deal_stage = ' || deal_stage                       as detail

    from opportunities

    where close_date is null

),

-- DQ-009: Lost deals recorded at close_value = 0 rather than null
-- (2,473 rows). Recorded as info because it is the vendor's chosen encoding.
dq009_lost_at_zero as (

    select
        'DQ-009'                                            as check_id,
        'info'                                              as severity,
        'lost deal recorded at close_value = 0'             as finding,
        opportunity_id                                      as entity_id,
        'close_value_raw = 0'                               as detail

    from opportunities

    where is_lost and close_value_raw = 0

),

-- DQ-015: account sector repaired 'technolgy' -> 'technology'.
dq015_sector_repair as (

    select
        'DQ-015'                                            as check_id,
        'info'                                              as severity,
        'account sector repaired'                           as finding,
        account_name                                        as entity_id,
        sector_raw || ' -> ' || sector                      as detail

    from accounts

    where is_sector_repaired

),

-- DQ-016: account office location repaired 'Philipines' -> 'Philippines'.
dq016_country_repair as (

    select
        'DQ-016'                                            as check_id,
        'info'                                              as severity,
        'account office_location repaired'                  as finding,
        account_name                                        as entity_id,
        office_country_raw || ' -> ' || office_country      as detail

    from accounts

    where is_country_repaired

)

select * from dq003_repaired
union all
select * from dq003_unmapped
union all
select * from dq004_missing_account
union all
select * from dq005_pre_engagement
union all
select * from dq008_open_pipeline
union all
select * from dq009_lost_at_zero
union all
select * from dq015_sector_repair
union all
select * from dq016_country_repair
