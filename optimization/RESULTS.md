# Query Optimization Benchmark

Measured on the amplified benchmark dataset (40,040,000 rows - 4,550
deterministic copies of the real `marts.fct_opportunity` distribution; see
`generate_big_dataset.py`). Benchmark-only: no analytics in this repo reads
this dataset. Engine: DuckDB 1.5.6, single node.

**Methodology.** 5 interleaved rounds per pair (baseline, optimized,
baseline, ...), one fresh connection per query with engine settings pinned
identically (threads = 4, memory_limit = 1 GB), median reported and every
round kept in `results.json`. Windows file cache cannot be dropped portably,
so interleaving keeps cache warming equal for both variants. "Bytes read" is
the sum of parquet file bytes each query's read touches - the DuckDB analogue
of BigQuery bytes billed. Re-run any time with
`python optimization/run_benchmark.py`.

## Pair 1 - Layout + partition pruning (I/O bound)

Question: monthly Won revenue for one office over one quarter.

| variant | storage | filter | median time | min time | bytes read |
|---|---|---|---|---|---|
| baseline | single 477 MB parquet | office + date range | 0.233 s | 0.222 s | 476.7 MB |
| optimized | Hive `year=/month=` parquet | + partition columns | 0.035 s | 0.034 s | 32.59 MB |

**Speedup: 6.5x** with **93.2% less I/O**
(32.59 MB of 821.4 MB dataset).

The same lever on the BigQuery target: partition tables by `close_date` and
cluster by `office`, then filter on the partition column - BigQuery bills only
scanned bytes, so the layout choice is directly a cost choice. See
`bigquery/ddl_warehouse.sql` and `INFORMATION_SCHEMA.JOBS_BY_PROJECT` for
measuring it there.

## Pair 2 - SQL pattern (CPU bound)

Question: keep only the latest record per opportunity within one year's
refresh window (`close_date` in 2018, ~7.7M of 40,040,000 rows). The
window is deliberate: deduping the entire 40M-row history drifted 16 s -> 61 s
across rounds under OS memory pressure, which measures the machine instead of
the pattern. An increment-sized working set keeps the comparison honest.

| variant | pattern | median time | min time |
|---|---|---|---|
| baseline | self-join on `max(load_seq)` per group | 2.061 s | 1.899 s |
| optimized | `qualify row_number() over (...)` | 1.196 s | 1.149 s |

**Speedup: 1.7x.** Identical result set by construction.
The `QUALIFY` form reads the source once instead of twice and replaces a
group-by plus hash join with a single sorted pass, but at this scale the
engine's join is already efficient - the measured win is modest, and that is
the honest result rather than a cherry-picked one. The lever that actually
moved the needle in this project is layout (Pair 1), not SQL style.

Machine-readable numbers: [`results.json`](results.json).
