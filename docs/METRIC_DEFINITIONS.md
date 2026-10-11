# Metric definitions

Every figure shown by the dashboard or written in the README is defined here.
Definitions match the SQL in `warehouse/models/` exactly - if a number in the
app cannot be reproduced from this file plus a model, that is a bug.

Source data: Maven Analytics "CRM Sales Opportunities" - 8,800 opportunities,
85 accounts, 35 agents, 7 products. Engagements span 2016-10-20 to 2017-12-27;
closes span 2017-03-01 to 2017-12-31.

## Counts and funnel

| metric | definition | source |
|---|---|---|
| `total_opportunities` | rows in `fct_opportunity`; grain is `opportunity_id`, verified unique at extract (DQ-010) | `rpt_exec_overview` |
| `prospecting_count` / `engaging_count` | opportunities whose `deal_stage` is Prospecting / Engaging | `rpt_exec_overview` |
| `won_count` / `lost_count` | opportunities whose `deal_stage` is Won / Lost | `rpt_exec_overview` |
| `open_pipeline_count` | Prospecting + Engaging = 500 + 1,589 = **2,089** | `rpt_exec_overview` |

The funnel is **not** sequential: a row's `deal_stage` is its state at the
extract snapshot. Prospecting 500 and Engaging 1,589 are separate populations
of open deals, not a conversion path from one to the other. Any funnel
"conversion rate" between Prospecting and Engaging would be fabricated and is
deliberately absent from every model.

## Revenue

| metric | definition |
|---|---|
| `revenue` (per opportunity) | `case when deal_stage = 'Won' then close_value else 0 end` |
| `total_revenue` | `sum(revenue)` = **10,005,534** across 4,238 won deals |
| `avg_won_deal_size` | `avg(revenue)` over won rows = **2,360.91** |

Why stage-filtered and not `close_value > 0`: the vendor records every Lost
deal at `close_value = 0`, never null (DQ-009, 2,473 rows). `sum(close_value)`
happens to equal `sum(revenue)` on this extract, but it is right by accident -
it silently includes Lost deals as zeros and would break the day a vendor
switches to nulls. The stage filter is the definition.

## Win rate

`win_rate = won_count / (won_count + lost_count)` = 4,238 / 6,711 = **0.6315**.

Closed-deal rate only. Open opportunities are excluded from both numerator and
denominator - including them would understate the rate by mixing unfinished
deals into a finished-deal ratio. Monthly and per-agent rates use the same
formula at their own grain.

## Cycle times

| metric | definition |
|---|---|
| `sales_cycle_days` | `date_diff('day', engage_date, close_date)` per closed opportunity |
| `avg_won_cycle_days` | mean over won closed rows = **51.78** |
| `avg_closed_cycle_days` | mean over all closed rows (Won + Lost) = **47.99** |
| `days_open_at_snapshot` | `date_diff('day', engage_date, snapshot_date)` for open rows only |

`snapshot_date` is the data's own `max(close_date)` = **2017-12-31**, never
`current_date`. Every build is therefore deterministic: two runs on the same
extract produce identical figures, which is what makes the tests meaningful.

Closed rows with a null `engage_date` are excluded from cycle averages; the
500 pre-engagement rows are all open, so no closed row loses its cycle.
Negative cycles are impossible by test (`assert_no_negative_sales_cycle`).

## Pipeline measures

| metric | definition |
|---|---|
| `engaged_count` (month, office) | opportunities whose `engage_date` falls in that month |
| `won_revenue` (month, office) | `sum(revenue)` where close month = that month |
| `open_pipeline_count` (month, office) | engaged on or before month end **and** not closed by month end; the 500 never-engaged rows qualify because their engagement never happened, not because they were closed |

Pipeline is a **count, never a value**. `close_value` is null while an
opportunity is open (DQ-006/007 - 2,089 rows), so there is no amount to
aggregate; any "pipeline value" or weighted-forecast number would require an
amount column this source does not have.

## Coverage

| metric | value | note |
|---|---|---|
| `attributed_accounts` | 85 | every account appears in at least one opportunity |
| `active_agents` | 30 | 30 of the 35 rostered agents carry opportunities |
| `unattributed_opportunities` | 1,425 | 16.19% have null `account` (DQ-004) - real missingness, kept null |

## Repair-affected measures

The 1,480 opportunities labelled `GTXPro` (DQ-003) are recovered by a
normalized join, not by editing source rows. Consequences:

- `fct_opportunity.product_key` is not null on every row, so product-level
  revenue aggregates are complete;
- the raw label survives on `int_opportunity_enriched.product_name_raw` and
  `is_product_key_repaired`, so the repair is auditable row by row;
- `assert_no_unmapped_products` fails the build if any label stops resolving.
