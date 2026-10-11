# Data quality findings

18 checks run against the raw landing layer at extract time
(`python etl/profile_source.py` → `reports/source_profile.json`), plus the
same guarantees re-asserted as dbt tests on every build
(`python -m dbt build`, currently **67/67 passing**).

Every finding in the JSON carries the SQL that produced it, so no number here
requires trusting this document - re-run the query and check.

## Severity policy

| tier | meaning | build behaviour |
|---|---|---|
| error | unresolvable FK - a fact row that cannot join to its dimension | blocks the build (`assert_no_unmapped_products`, `not_null` on `product_key`) |
| warning | null that is a real business state, not a defect | modelled explicitly, never imputed |
| info | vendor encoding choice or repaired spelling | documented, surfaced on the dashboard |

## Findings

### DQ-003 - `opportunity.product` resolves to `products.product` - ERROR at source

**1,480 of 8,800 rows (16.8%) carry the label `GTXPro`; the product master
says `GTX Pro`.** A verbatim join drops every one of those rows, taking 16.8%
of pipeline revenue with them from any product-level aggregate.

Treatment: a normalized join key (`lower(regexp_replace(name,
'[^A-Za-z0-9]', '', 'g'))`) in `int_opportunity_enriched` recovers all 1,480
rows. **Source bytes are never edited** - the raw label is preserved on every
row with `is_product_key_repaired`, so the repair is reversible and auditable.
After normalization, zero rows remain unmapped (verified; enforced by test).

Why normalize rather than fix the CSV: the pipeline must work on the vendor's
next extract, which will still contain `GTXPro`. Editing a file is a one-time
fix; the join is a permanent repair.

### DQ-004 - `sales_pipeline.account` completeness - WARNING

**1,425 rows (16.19%) have no account.** Null is kept as null; `account_key`
is null on those fact rows and the `relationships` test passes because dbt
skips null FKs by design - these rows join to the unknown member, not to
nothing. No default account is invented.

### DQ-005 - `engage_date` completeness - WARNING

**500 rows (5.68%) were never engaged.** These are the Prospecting rows - the
absence of engagement is the state, so it is not imputed and those rows are
excluded from cycle-time averages (a cycle needs both ends).

### DQ-006 / DQ-007 - `close_date` / `close_value` completeness - WARNING

**2,089 rows (23.74%) have neither.** The null count exactly equals
Prospecting (500) + Engaging (1,589) - it is **structural: it is the open
pipeline**. Imputing these would manufacture closures that never happened, so
the models treat `is_pipeline_open` as a first-class flag and every reporting
measure names open deals separately.

### DQ-008 - close-date nulls vs open opportunities - PASS by construction

The equality above (2,089 nulls = 2,089 open rows) is asserted, not assumed.
If a future extract closes a deal without a date, DQ-008 stops being
structural and becomes a defect.

### DQ-009 - Lost deals recorded at `close_value = 0` - INFO

All **2,473 Lost rows** carry `close_value = 0`, never null. Revenue is
therefore defined as **stage-filtered** (`case when is_won then close_value
else 0 end`), not as `close_value > 0`. The difference is invisible on this
extract and dangerous on the next one.

### DQ-015 - `accounts.sector` misspelling - INFO (repaired)

`technolgy` appears on **12 account rows**. Staging repairs it to `technology`
and keeps `sector_raw` plus `is_sector_repaired` on every row.

### DQ-016 - `accounts.office_location` misspelling - INFO (repaired)

`Philipines` appears on **1 account row**. Repaired to `Philippines` the same
way, with `office_country_raw` preserved.

### Passing checks (11)

- DQ-001 - opportunity → account referential integrity: **0 violations** (1,425
  nulls excluded as unattributed, not as broken refs).
- DQ-002 - opportunity → sales_agent: **0 orphans**, all 8,800 rows join.
- DQ-010 - `opportunity_id` uniqueness: **8,800 distinct / 8,800 rows**.
- DQ-011 - agent referential: managers resolve within the roster.
- DQ-012/013 - numeric ranges (`revenue`, `employees`, `sales_price`): no
  negatives, no non-numeric strings.
- DQ-014 - dates parse; all closes after their engagement.
- DQ-017 - `deal_stage` domain: exactly {Prospecting, Engaging, Won, Lost}.
- DQ-018 - snapshot consistency: open rows never carry a close date.

## Where the guarantees live

| finding | extract-time | warehouse-side enforcement |
|---|---|---|
| DQ-003 | `profile_source.py` | `assert_no_unmapped_products`, `not_null product_key`, `is_product_key_repaired` |
| DQ-004 | `profile_source.py` | `relationships` on `account_key` (null-tolerant by design) |
| DQ-006/007/008 | `profile_source.py` | `is_pipeline_open` flag, `assert_won_opportunities_have_close_date` |
| DQ-009 | `profile_source.py` | revenue defined in `stg_crm_opportunities` with stage filter |
| DQ-010 | `profile_source.py` | `unique opportunity_id` |
| DQ-014 | `profile_source.py` | `assert_no_negative_sales_cycle` |
| totals | `source_profile.json` | `assert_revenue_ties_to_source` (10,005,534 to the cent) |

`rpt_data_quality` re-computes the row-level findings from the modelled
warehouse on every build; the static JSON profiles the bytes as landed. Both
are shown on the dashboard Data Quality page because they answer different
questions: "what did the vendor send" vs "what does the warehouse believe".
