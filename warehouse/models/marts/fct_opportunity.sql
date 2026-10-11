{#
    Opportunity fact table. One row per opportunity_id, grain preserved from
    source (DQ-010: ids verified unique).

    revenue is Won close_value only - Lost rows carry close_value = 0 by the
    vendor's encoding (DQ-009), so a close_value > 0 filter would silently
    count Lost rows as zero-revenue deals and a raw SUM would still be right
    by accident; the explicit stage filter makes the intent unambiguous.
    Open-pipeline deals have no amount in the source, so their revenue is 0
    and pipeline is measured in counts, not value (see METRIC_DEFINITIONS.md).
#}

with enriched as (

    select * from {{ ref('int_opportunity_enriched') }}

)

select
    opportunity_id,

    sales_agent_key,
    product_key,
    account_key,

    engage_date,
    close_date,

    deal_stage,
    stage_order,
    is_won,
    is_lost,
    is_closed,
    is_open,

    revenue,
    close_value_raw,
    sales_cycle_days,

    snapshot_date,
    case
        when is_open and engage_date is not null
            then {{ datediff_days('engage_date', 'snapshot_date') }}
    end                                                  as days_open_at_snapshot,

    is_account_missing,
    is_pre_engagement,
    _loaded_at

from enriched
