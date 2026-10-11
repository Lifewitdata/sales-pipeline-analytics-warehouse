{#
    The flagship DQ-003 repair: every opportunity must resolve to a product
    through the normalized join. Both sides are compared as normalized text
    (lowercase alphanumeric), never as surrogate hashes. Zero rows is the
    only passing state; the same guarantee is what makes
    fct_opportunity.product_key not_null-able.
#}

select
    opportunity_id,
    product_name_raw

from {{ ref('stg_crm_opportunities') }}

where lower(regexp_replace(product_name_raw, '[^A-Za-z0-9]', '', 'g'))
    not in (select product_name_normalized from {{ ref('stg_crm_products') }})
