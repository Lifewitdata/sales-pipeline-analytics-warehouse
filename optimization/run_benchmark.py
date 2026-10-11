"""Measure baseline vs optimized query patterns on the amplified dataset.

Two pairs are benchmarked, each on a separate question a business user would
actually ask:

PAIR 1 - layout + pruning (I/O bound)
    "Monthly Won revenue for one office over one quarter."
    baseline   : single unpartitioned parquet, filter only on office/date
                 columns - the engine must read the whole file.
    optimized  : Hive-partitioned dataset, filter includes the partition
                 columns year/month - the engine reads only the partitions
                 the filter touches.

PAIR 2 - SQL pattern (CPU bound)
    "Deduplicate to the latest record per opportunity" over a one-year
    window (close_date in 2018, ~7.7M rows). Scoped like a real refresh -
    analysts dedup an increment, not the full history - and the smaller
    working set keeps variance down: an unscaled 40M-row dedup drifted
    16 s -> 61 s across rounds under OS memory pressure, which measured
    the machine rather than the query pattern.
    baseline   : self-join against max(load_seq) per group.
    optimized  : QUALIFY row_number() over (partition by ... order by ...) = 1.

METHODOLOGY
    - 5 interleaved rounds per pair (baseline, optimized, baseline, ...), so
      OS file-cache warming affects both variants equally. Windows file-cache
      cannot be dropped portably; interleaving is the fair alternative.
    - Engine settings pinned per connection (threads = 4, memory_limit =
      '1GB') so both variants compete under an identical budget and the
      numbers are reproducible on a smaller machine.
    - Reported number is the MEDIAN of the 5 rounds; every round is kept in
      results.json so the variance is visible rather than hidden.
    - I/O proxy: sum of parquet file bytes each query's read touches
      (whole file for baseline; only matching year=/month= folders for the
      optimized variant). This is the DuckDB analogue of BigQuery bytes
      billed, and the same technique applies to INFORMATION_SCHEMA.JOBS on
      the BigQuery target.
    - One fresh connection per query so metadata cache never carries over.

OUTPUTS
    optimization/results.json   machine-readable timings + sizes
    optimization/RESULTS.md     human-readable summary, regenerated each run
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import duckdb

from generate_big_dataset import COPIES

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "optimization" / "data"
RESULTS_JSON = PROJECT_ROOT / "optimization" / "results.json"
RESULTS_MD = PROJECT_ROOT / "optimization" / "RESULTS.md"

DATASET_ROWS = 8_800 * COPIES  # copies of the 8,800-row fact

UNPARTITIONED = (DATA_DIR / "big_fact_unpartitioned.parquet").as_posix()
PARTITIONED_GLOB = (DATA_DIR / "big_fact_partitioned").as_posix() + "/**/*.parquet"
PARTITIONED_DIR = DATA_DIR / "big_fact_partitioned"

ROUNDS = 5

Q1_BASELINE = f"""
select
    date_trunc('month', close_date) as month_start,
    sum(revenue)                    as won_revenue
from '{UNPARTITIONED}'
where regional_office = 'West'
  and close_date between date '2017-10-01' and date '2017-12-31'
  and is_won
group by 1
order by 1
"""

Q1_OPTIMIZED = f"""
select
    month                              as month_num,
    sum(revenue)                       as won_revenue
from read_parquet('{PARTITIONED_GLOB}', hive_partitioning = true)
where year = 2017
  and month between 10 and 12
  and regional_office = 'West'
  and is_won
group by 1
order by 1
"""

DEDUP_WINDOW = "close_date between date '2018-01-01' and date '2018-12-31'"

Q2_BASELINE = f"""
with src as (
    select opportunity_id, load_seq, revenue
    from '{UNPARTITIONED}'
    where {DEDUP_WINDOW}
)
select count(*) as latest_rows
from src t
join (
    select opportunity_id, max(load_seq) as max_seq
    from src
    group by opportunity_id
) s
  on t.opportunity_id = s.opportunity_id
 and t.load_seq = s.max_seq
"""

Q2_OPTIMIZED = f"""
select count(*) as latest_rows
from (
    select opportunity_id
    from '{UNPARTITIONED}'
    where {DEDUP_WINDOW}
    qualify row_number() over (
        partition by opportunity_id
        order by load_seq desc
    ) = 1
)
"""


def timed(query: str) -> float:
    """Run a query on a fresh, identically-configured connection."""
    con = duckdb.connect(":memory:")
    con.execute("set threads = 4")
    con.execute("set memory_limit = '1GB'")
    start = time.perf_counter()
    con.execute(query).fetchall()
    elapsed = time.perf_counter() - start
    con.close()
    return elapsed


def bench(name: str, baseline_sql: str, optimized_sql: str) -> dict:
    baseline_rounds, optimized_rounds = [], []
    for _ in range(ROUNDS):
        baseline_rounds.append(timed(baseline_sql))
        optimized_rounds.append(timed(optimized_sql))
    b_med = statistics.median(baseline_rounds)
    o_med = statistics.median(optimized_rounds)
    print(f"{name}: baseline {b_med:.3f}s | optimized {o_med:.3f}s "
          f"| speedup {b_med / o_med:.1f}x")
    return {
        "benchmark": name,
        "rounds": ROUNDS,
        "baseline_seconds": {
            "median": round(b_med, 4),
            "min": round(min(baseline_rounds), 4),
            "all": [round(x, 4) for x in baseline_rounds],
        },
        "optimized_seconds": {
            "median": round(o_med, 4),
            "min": round(min(optimized_rounds), 4),
            "all": [round(x, 4) for x in optimized_rounds],
        },
        "speedup_median": round(b_med / o_med, 2),
    }


def dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*.parquet"))


def io_bytes_for_q1() -> dict:
    total_partitioned = dir_bytes(PARTITIONED_DIR)
    touched = 0
    for month in (10, 11, 12):
        folder = PARTITIONED_DIR / f"year=2017" / f"month={month}"
        touched += dir_bytes(folder)
    return {
        "baseline_file_bytes": Path(UNPARTITIONED).stat().st_size,
        "optimized_file_bytes": touched,
        "dataset_total_bytes": total_partitioned,
        "bytes_reduction": round(
            1 - touched / Path(UNPARTITIONED).stat().st_size, 4
        ),
    }


def main() -> int:
    results = {
        "dataset": {
            "rows": DATASET_ROWS,
            "source": f"marts.fct_opportunity amplified {COPIES}x, deterministic",
            "note": "benchmark-only synthetic copies of a real distribution",
        },
        "environment": {
            "engine": f"duckdb {duckdb.__version__}",
            "platform": "local single node, Windows",
            "rounds": ROUNDS,
            "ordering": "interleaved per round, fresh connection per query",
            "engine_settings": "threads = 4, memory_limit = 1GB (pinned for every query)",
            "dedup_window": "close_date in 2018 (~7.7M of 40M rows)",
            "reported": "median of rounds; all rounds kept",
        },
        "benchmarks": [
            bench("pair1_partition_pruning", Q1_BASELINE, Q1_OPTIMIZED),
            bench("pair2_dedup_pattern", Q2_BASELINE, Q2_OPTIMIZED),
        ],
        "io_proxy_pair1": io_bytes_for_q1(),
    }

    RESULTS_JSON.write_text(json.dumps(results, indent=2))

    p1, p2 = results["benchmarks"]
    io = results["io_proxy_pair1"]

    RESULTS_MD.write_text(f"""# Query Optimization Benchmark

Measured on the amplified benchmark dataset ({DATASET_ROWS:,} rows - {COPIES:,}
deterministic copies of the real `marts.fct_opportunity` distribution; see
`generate_big_dataset.py`). Benchmark-only: no analytics in this repo reads
this dataset. Engine: DuckDB {duckdb.__version__}, single node.

**Methodology.** {ROUNDS} interleaved rounds per pair (baseline, optimized,
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
| baseline | single {io['baseline_file_bytes'] / 1e6:.0f} MB parquet | office + date range | {p1['baseline_seconds']['median']:.3f} s | {p1['baseline_seconds']['min']:.3f} s | {io['baseline_file_bytes'] / 1e6:.1f} MB |
| optimized | Hive `year=/month=` parquet | + partition columns | {p1['optimized_seconds']['median']:.3f} s | {p1['optimized_seconds']['min']:.3f} s | {io['optimized_file_bytes'] / 1e6:.2f} MB |

**Speedup: {p1['speedup_median']:.1f}x** with **{io['bytes_reduction'] * 100:.1f}% less I/O**
({io['optimized_file_bytes'] / 1e6:.2f} MB of {io['dataset_total_bytes'] / 1e6:.1f} MB dataset).

The same lever on the BigQuery target: partition tables by `close_date` and
cluster by `office`, then filter on the partition column - BigQuery bills only
scanned bytes, so the layout choice is directly a cost choice. See
`bigquery/ddl_warehouse.sql` and `INFORMATION_SCHEMA.JOBS_BY_PROJECT` for
measuring it there.

## Pair 2 - SQL pattern (CPU bound)

Question: keep only the latest record per opportunity within one year's
refresh window (`close_date` in 2018, ~7.7M of {DATASET_ROWS:,} rows). The
window is deliberate: deduping the entire 40M-row history drifted 16 s -> 61 s
across rounds under OS memory pressure, which measures the machine instead of
the pattern. An increment-sized working set keeps the comparison honest.

| variant | pattern | median time | min time |
|---|---|---|---|
| baseline | self-join on `max(load_seq)` per group | {p2['baseline_seconds']['median']:.3f} s | {p2['baseline_seconds']['min']:.3f} s |
| optimized | `qualify row_number() over (...)` | {p2['optimized_seconds']['median']:.3f} s | {p2['optimized_seconds']['min']:.3f} s |

**Speedup: {p2['speedup_median']:.1f}x.** Identical result set by construction.
The `QUALIFY` form reads the source once instead of twice and replaces a
group-by plus hash join with a single sorted pass, but at this scale the
engine's join is already efficient - the measured win is modest, and that is
the honest result rather than a cherry-picked one. The lever that actually
moved the needle in this project is layout (Pair 1), not SQL style.

Machine-readable numbers: [`results.json`](results.json).
""")

    print(f"wrote {RESULTS_JSON.relative_to(PROJECT_ROOT)}")
    print(f"wrote {RESULTS_MD.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
