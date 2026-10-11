"""Generate the benchmark dataset for the query-optimization module.

WHY THIS EXISTS
    The real fact table has 8,800 rows. On data that small every query is
    sub-100 ms and there is nothing meaningful to optimize, so this script
    deterministically amplifies the real distribution to ~4M rows to make
    engine behaviour visible and measurable.

WHAT IS REAL, WHAT IS SYNTHETIC
    Column names, value distributions, stage mix, office mix and revenue
    distribution all come from the real marts.fct_opportunity. Individual
    rows are synthetic copies: dates are deterministically re-spread across
    a 5-year window and revenue is jittered by +/- 0-4%. This dataset exists
    ONLY to benchmark the engine - no analytics in this repo reads it, and
    the README says so explicitly.

DETERMINISM
    Every transformation is a pure function of (row, copy_index) - no RNG.
    Re-running produces byte-identical logic (parquet bytes may differ).

OUTPUT (all under optimization/data/, all gitignored)
    big_fact_unpartitioned.parquet   single file, rows in source order
    big_fact_partitioned/            Hive layout year=YYYY/month=MM/
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "warehouse" / "crm_warehouse.duckdb"
DATA_DIR = PROJECT_ROOT / "optimization" / "data"

COPIES = 4550  # 8,800 * 4550 = 40,040,000 rows - 4M rows measured in
               # tens of milliseconds on modern hardware, which is noise;
               # 40M makes both engine time and I/O differences visible.
BASE_DATE = "date '2016-10-01'"
WINDOW_DAYS = 1900  # ~5.2 years of spread


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    unpartitioned = DATA_DIR / "big_fact_unpartitioned.parquet"
    partitioned_dir = DATA_DIR / "big_fact_partitioned"

    con = duckdb.connect(DB_PATH.as_posix(), read_only=True)

    build_sql = f"""
        with base as (
            select
                f.*,
                a.regional_office
            from marts.fct_opportunity f
            join marts.dim_sales_agent a
              on a.sales_agent_key = f.sales_agent_key
        ),
        copies as (
            select
                b.*,
                g.k,
                -- Deterministic date re-spread: every copy shifts dates by a
                -- fixed day stride inside one window, so each year/month
                -- slice ends up with a comparable row count. Offsets are
                -- cast to INTEGER because DuckDB has no DATE + BIGINT
                -- overload.
                cast(((b.engage_date - {BASE_DATE}) + g.k * 41)
                    % {WINDOW_DAYS} as integer)                  as engage_off,
                case
                    when b.close_date is not null then
                        cast(((b.close_date - {BASE_DATE}) + g.k * 37)
                            % {WINDOW_DAYS} as integer)
                end                                              as close_off
            from base b, generate_series(0, {COPIES - 1}) as g(k)
        ),
        final as (
            select
                opportunity_id || '-' || k                    as opportunity_id,
                sales_agent_key,
                product_key,
                account_key,
                deal_stage,
                is_won,
                is_closed,
                is_open,
                regional_office,
                {BASE_DATE} + engage_off                      as engage_date,
                {BASE_DATE} + close_off                       as close_date,
                round(revenue * (1 + ((k % 9) - 4) * 0.01), 2) as revenue,
                k                                             as load_seq,
                extract(year from {BASE_DATE} + close_off)    as year,
                extract(month from {BASE_DATE} + close_off)   as month
            from copies
        )
        select * from final
    """

    print(f"building {COPIES:,} copies of the fact -> ~40M rows ...")

    con.execute(
        f"copy ({build_sql}) to '{unpartitioned.as_posix()}' (format parquet)"
    )
    print(f"wrote {unpartitioned.name} ({unpartitioned.stat().st_size / 1e6:.1f} MB)")

    # Shuffle before the partitioned write so neither layout benefits from
    # accidental locality the other lacks.
    con.execute(
        f"""
        copy (
            select *
            from ({build_sql})
            order by md5(opportunity_id || cast(load_seq as varchar))
        )
        to '{partitioned_dir.as_posix()}'
        (format parquet, partition_by (year, month), overwrite_or_ignore)
        """
    )
    n_files = len(list(partitioned_dir.rglob("*.parquet")))
    p_size = sum(f.stat().st_size for f in partitioned_dir.rglob("*.parquet"))
    print(f"wrote {partitioned_dir.name}/ ({n_files} files, {p_size / 1e6:.1f} MB)")

    # Parity check: same row count, same revenue total (jitter averages out
    # only approximately, so compare counts exactly and revenue within 1%).
    glob_path = partitioned_dir.as_posix() + "/**/*.parquet"
    check = con.execute(
        f"""
        select
            (select count(*) from '{unpartitioned.as_posix()}'),
            (select count(*) from read_parquet('{glob_path}', hive_partitioning = true)),
            (select round(sum(revenue), 0) from '{unpartitioned.as_posix()}'),
            (select round(sum(revenue), 0) from read_parquet('{glob_path}', hive_partitioning = true))
        """
    ).fetchone()
    assert check[0] == check[1], f"row count mismatch: {check[0]} vs {check[1]}"
    assert abs(check[2] - check[3]) / check[2] < 0.01, f"revenue drift: {check}"
    print(f"parity OK: {check[0]:,} rows per layout, revenue {check[2]:,.0f} vs {check[3]:,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
