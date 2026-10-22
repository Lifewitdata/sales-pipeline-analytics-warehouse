# Sales Pipeline — Power BI + DAX

Editable **Power BI Project (PBIP)** source: three report pages, an import-mode
semantic model, four one-to-many relationships, Power Query CSV imports, and
13 DAX measures. The CSV snapshots are exported from the existing dbt marts;
they are included so opening the report does not require Python or DuckDB.

**Validation status:** the warehouse build and 51 dbt tests passed. Exported
KPIs reconcile to the SQL warehouse. Report JSON is checked against Microsoft
PBIR schemas. Power BI Desktop is not available in the build environment:
**Desktop opening, Power Query refresh, DAX execution, and visual rendering
still require the acceptance steps below.** This is authored project source,
not an already Desktop-validated `.pbix` or a published Power BI Service report.

## Open on Windows

1. Download the repository ZIP from GitHub (Code → Download ZIP) and extract it.
   Keep the complete `powerbi` folder together.
2. Open `SalesPipeline.pbip` in a current Power BI Desktop version supporting
   PBIP/PBIR. The project initially has no imported data cache.
3. In **Transform data → Edit parameters**, set `DataFolder` to the absolute
   path of the extracted `powerbi/data` directory, for example
   `C:/Users/YourName/Downloads/sales-pipeline-analytics-warehouse-main/powerbi/data`.
4. Apply changes and **Refresh**. Allow local-file access if prompted.
5. Check the three pages and run `SalesPipeline.SemanticModel/DAXQueries/Acceptance.dax`
   in DAX Query View. Compare the results below. Save a local `.pbix` after checks.

The model's editable Power Query parameter is in `model.bim`. There are no
credentials, cloud connectors, paid visuals, or online data dependencies.

## Pages and filter semantics

| Page | Contents | Date meaning |
|---|---|---|
| Sales performance | Revenue, win rate, average won deal, sales cycle, monthly trend, office revenue, representative table | Close-month slicer filters closed deals through the active date relationship |
| Pipeline snapshot | Open count, open age, stage counts, office and representative breakdowns | No date slicer; snapshot of the source extract, not historical pipeline movement |
| Data quality | Missing account counts and rates by office and stage | All source opportunities, including unclosed deals |

Office and product-series slicers are local to each page. They filter the
fact via single-direction relationships. Open-count and open-age measures
explicitly remove date-dimension filters: an open deal has no close date.
Stage charts show a snapshot, **not a sequential conversion funnel**.
Average open age excludes records without engagement dates (including
pre-engagement prospecting). The snapshot date comes from the source's max
close date, not today's date. Missing account rows remain in the fact.

## Model

`dim_sales_agent[sales_agent_key]`, `dim_product[product_key]`,
`dim_account[account_key]` each filter their matching fact key.
`dim_date[date_day]` filters `fct_opportunity[close_date]`.
All relationships are one-to-many, dimension to fact, single direction.
Raw numeric columns use “Do not summarize”; report visuals use explicit measures.

## DAX acceptance values (clear all filters)

| Measure | Expected |
|---|---:|
| Opportunities | 8,800 |
| Won Deals | 4,238 |
| Closed Deals | 6,711 |
| Won Revenue | $10,005,534 |
| Win Rate | 63.150052% |
| Average Won Deal | $2,360.909391 |
| Average Won Sales Cycle Days | 51.781973 |
| Open Opportunities | 2,089 |
| Missing Account Opportunities | 1,425 |
| Missing Account Rate | 16.193182% |

Win rate = Won / (Won + Lost), never Won / all opportunities.
Revenue is explicitly restricted to Won. Open pipeline has **no dollar value**
because the source does not provide one. `Revenue Previous Month` and
`Revenue MoM Change` should be inspected at **individual month grain**, not as
an all-time growth headline. A missing or zero prior-month denominator returns
blank. DAX uses KEEPFILTERS so stage selections intersect measure definitions.

Also verify: West office revenue = $3,568,647; Central = $3,346,293;
East = $3,090,594. Select an office and product series to check cross-filtering;
clear them to restore totals. On the executive page select a close month and
confirm revenue changes. Pipeline page remains a snapshot.

## Rebuild from refreshed warehouse data

Run the existing extract/load/dbt workflow first, then from repository root:

```sh
python powerbi/build_project.py
python -m pip install jsonschema
python powerbi/validate_project.py
```

`build_project.py` regenerates the CSV snapshots, PBIP/PBIR definitions,
semantic model, DAX reference and expected values. It overwrites authored
report files: commit Desktop edits before rebuilding and review the diff.
Current KPI assertions deliberately pin the public sample dataset; update them
with reviewed expectations when intentionally replacing the source.

Validation checks schemas, relationship uniqueness/referential integrity, and
independent CSV totals against SQL. It **does not run the Microsoft DAX or M
engines**. `measures.dax` is a readable reference; measures are already installed
in the model. The `.pbi` cache and local Desktop settings must not be committed.

## Format references

- https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report
- https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset
