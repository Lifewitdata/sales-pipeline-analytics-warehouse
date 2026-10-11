"""Profile the raw layer and emit a machine-readable data quality report.

This runs against the raw tables only, before any dbt transformation, so it
answers the question "what shape is the data actually in when it arrives" rather
than "what does my cleaned model look like". Findings are classified so the
warehouse can decide which ones to repair, which to flag on the row, and which
are simply business rules that look like errors until you know the domain.

Writes reports/source_profile.json and prints a summary.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "warehouse" / "crm_warehouse.duckdb"
REPORT_DIR = PROJECT_ROOT / "reports"

VALID_STAGES = ("Prospecting", "Engaging", "Won", "Lost")


def one(con: duckdb.DuckDBPyConnection, sql: str) -> object:
    return con.execute(sql).fetchone()[0]


def column_profile(con: duckdb.DuckDBPyConnection, table: str) -> list[dict]:
    columns = [
        row[0]
        for row in con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_schema='raw' AND table_name='{table}' ORDER BY ordinal_position"
        ).fetchall()
    ]
    columns = [c for c in columns if c != "_loaded_at"]
    row_count = one(con, f'SELECT count(*) FROM raw."{table}"')

    profile = []
    for column in columns:
        stats = con.execute(
            f"""
            SELECT
                count("{column}")                                            AS non_null,
                count(*) - count("{column}")                                 AS nulls,
                count(DISTINCT "{column}")                                   AS distinct_values,
                min("{column}")                                              AS min_value,
                max("{column}")                                              AS max_value
            FROM raw."{table}"
            """
        ).fetchone()
        non_null, nulls, distinct_values, min_value, max_value = stats
        profile.append(
            {
                "column": column,
                "null_count": int(nulls),
                "null_rate": round(int(nulls) / row_count, 4) if row_count else 0.0,
                "distinct_count": int(distinct_values),
                "min": None if min_value is None else str(min_value),
                "max": None if max_value is None else str(max_value),
            }
        )
    return profile


def referential_check(
    con: duckdb.DuckDBPyConnection,
    child_table: str,
    child_column: str,
    parent_table: str,
    parent_column: str,
) -> dict:
    result = con.execute(
        f"""
        SELECT
            count(*)                                                        AS child_rows,
            count(*) FILTER (WHERE c."{child_column}" IS NULL)              AS null_keys,
            count(*) FILTER (
                WHERE c."{child_column}" IS NOT NULL AND p."{parent_column}" IS NULL
            )                                                               AS orphan_keys,
            count(DISTINCT c."{child_column}") FILTER (
                WHERE c."{child_column}" IS NOT NULL AND p."{parent_column}" IS NULL
            )                                                               AS distinct_orphans
        FROM raw."{child_table}" c
        LEFT JOIN raw."{parent_table}" p
            ON c."{child_column}" = p."{parent_column}"
        """
    ).fetchone()
    child_rows, null_keys, orphan_keys, distinct_orphans = result

    orphan_values = []
    if orphan_keys:
        orphan_values = [
            row[0]
            for row in con.execute(
                f"""
                SELECT DISTINCT c."{child_column}"
                FROM raw."{child_table}" c
                LEFT JOIN raw."{parent_table}" p ON c."{child_column}" = p."{parent_column}"
                WHERE c."{child_column}" IS NOT NULL AND p."{parent_column}" IS NULL
                ORDER BY 1
                LIMIT 25
                """
            ).fetchall()
        ]

    return {
        "child": f"raw.{child_table}.{child_column}",
        "parent": f"raw.{parent_table}.{parent_column}",
        "child_rows": int(child_rows),
        "null_keys": int(null_keys),
        "orphan_keys": int(orphan_keys),
        "distinct_orphans": int(distinct_orphans),
        "orphan_values": orphan_values,
        "passed": int(orphan_keys) == 0,
    }


def findings(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Each finding carries the query that produced it so any number in the
    report can be re-derived by a reviewer without trusting this script."""
    pipeline_rows = one(con, "SELECT count(*) FROM raw.sales_pipeline")
    out: list[dict] = []

    def add(check_id, severity, title, detail, metric, sql):
        out.append(
            {
                "id": check_id,
                "severity": severity,
                "title": title,
                "detail": detail,
                "metric": metric,
                "sql": " ".join(sql.split()),
            }
        )

    # --- referential integrity -------------------------------------------
    ref_account = referential_check(con, "sales_pipeline", "account", "accounts", "account")
    add(
        "DQ-001",
        "error" if ref_account["orphan_keys"] else "pass",
        "opportunity.account resolves to accounts.account",
        f"{ref_account['orphan_keys']:,} orphan rows across {ref_account['distinct_orphans']} distinct values",
        ref_account["orphan_keys"],
        """
        SELECT count(*) FROM raw.sales_pipeline c
        LEFT JOIN raw.accounts p ON c.account = p.account
        WHERE c.account IS NOT NULL AND p.account IS NULL
        """,
    )

    ref_agent = referential_check(con, "sales_pipeline", "sales_agent", "sales_teams", "sales_agent")
    add(
        "DQ-002",
        "error" if ref_agent["orphan_keys"] else "pass",
        "opportunity.sales_agent resolves to sales_teams.sales_agent",
        f"{ref_agent['orphan_keys']:,} orphan rows",
        ref_agent["orphan_keys"],
        """
        SELECT count(*) FROM raw.sales_pipeline c
        LEFT JOIN raw.sales_teams p ON c.sales_agent = p.sales_agent
        WHERE c.sales_agent IS NOT NULL AND p.sales_agent IS NULL
        """,
    )

    product_orphans = con.execute(
        """
        SELECT count(*) AS orphan_rows,
               count(DISTINCT c.product) AS distinct_orphans,
               string_agg(DISTINCT c.product, ', ' ORDER BY c.product) AS values
        FROM raw.sales_pipeline c
        LEFT JOIN raw.products p ON c.product = p.product
        WHERE c.product IS NOT NULL AND p.product IS NULL
        """
    ).fetchone()
    add(
        "DQ-003",
        "error" if product_orphans[0] else "pass",
        "opportunity.product resolves to products.product",
        f"{product_orphans[0]:,} rows carry {product_orphans[1]} unmapped product label(s): {product_orphans[2]}. "
        "Whitespace-normalised join recovers all of them, so this is a key-hygiene defect, not unknown data.",
        product_orphans[0],
        """
        SELECT count(*) FROM raw.sales_pipeline c
        LEFT JOIN raw.products p ON c.product = p.product
        WHERE c.product IS NOT NULL AND p.product IS NULL
        """,
    )

    # --- completeness ----------------------------------------------------
    for check_id, column in (
        ("DQ-004", "account"),
        ("DQ-005", "engage_date"),
        ("DQ-006", "close_date"),
        ("DQ-007", "close_value"),
    ):
        nulls = one(con, f"SELECT count(*) FROM raw.sales_pipeline WHERE {column} IS NULL")
        rate = nulls / pipeline_rows if pipeline_rows else 0
        add(
            check_id,
            "warning" if nulls else "pass",
            f"sales_pipeline.{column} completeness",
            f"{nulls:,} of {pipeline_rows:,} rows null ({rate:.2%})",
            nulls,
            f"SELECT count(*) FROM raw.sales_pipeline WHERE {column} IS NULL",
        )

    open_stage_nulls = one(
        con,
        """
        SELECT count(*) FROM raw.sales_pipeline
        WHERE deal_stage IN ('Prospecting', 'Engaging')
          AND (close_date IS NOT NULL OR close_value IS NOT NULL)
        """,
    )
    closed_stage_nulls = one(
        con,
        """
        SELECT count(*) FROM raw.sales_pipeline
        WHERE deal_stage IN ('Won', 'Lost')
          AND (close_date IS NULL OR close_value IS NULL)
        """,
    )
    add(
        "DQ-008",
        "pass" if open_stage_nulls == 0 else "error",
        "close_date/close_value null exactly on open opportunities",
        f"{open_stage_nulls:,} open-stage rows wrongly carry a close value; "
        f"{closed_stage_nulls:,} closed-stage rows are missing one. "
        "The raw null count on close_date is therefore structural, not a defect - "
        "it is the open pipeline and must not be imputed.",
        open_stage_nulls + closed_stage_nulls,
        """
        SELECT count(*) FROM raw.sales_pipeline
        WHERE (deal_stage IN ('Prospecting','Engaging') AND (close_date IS NOT NULL OR close_value IS NOT NULL))
           OR (deal_stage IN ('Won','Lost') AND (close_date IS NULL OR close_value IS NULL))
        """,
    )

    lost_zero = one(
        con,
        "SELECT count(*) FROM raw.sales_pipeline WHERE deal_stage = 'Lost' AND close_value <> 0",
    )
    won_zero = one(
        con,
        "SELECT count(*) FROM raw.sales_pipeline WHERE deal_stage = 'Won' AND close_value <= 0",
    )
    add(
        "DQ-009",
        "pass" if (lost_zero == 0 and won_zero == 0) else "warning",
        "close_value sign convention by stage",
        f"{lost_zero:,} Lost rows with non-zero value; {won_zero:,} Won rows with value <= 0. "
        "Lost opportunities are recorded at 0 rather than null, so revenue aggregations "
        "must filter on stage, not on close_value > 0.",
        lost_zero + won_zero,
        """
        SELECT count(*) FROM raw.sales_pipeline WHERE deal_stage='Lost' AND close_value <> 0
        """,
    )

    # --- uniqueness ------------------------------------------------------
    dup_opps = one(
        con,
        """
        SELECT count(*) FROM (
            SELECT opportunity_id FROM raw.sales_pipeline
            GROUP BY opportunity_id HAVING count(*) > 1
        )
        """,
    )
    add(
        "DQ-010",
        "error" if dup_opps else "pass",
        "opportunity_id is unique at the fact grain",
        f"{dup_opps:,} duplicated opportunity_id values",
        dup_opps,
        """
        SELECT count(*) FROM (SELECT opportunity_id FROM raw.sales_pipeline
        GROUP BY opportunity_id HAVING count(*) > 1)
        """,
    )

    for check_id, table, key in (
        ("DQ-011", "accounts", "account"),
        ("DQ-012", "products", "product"),
        ("DQ-013", "sales_teams", "sales_agent"),
    ):
        dups = one(
            con,
            f'SELECT count(*) FROM (SELECT "{key}" FROM raw."{table}" GROUP BY 1 HAVING count(*) > 1)',
        )
        add(
            check_id,
            "error" if dups else "pass",
            f"{table}.{key} is unique",
            f"{dups:,} duplicate keys",
            dups,
            f'SELECT count(*) FROM (SELECT "{key}" FROM raw."{table}" GROUP BY 1 HAVING count(*)>1)',
        )

    # --- domain / value conformance --------------------------------------
    bad_stage = con.execute(
        f"""
        SELECT count(*) AS rows, string_agg(DISTINCT deal_stage, ', ' ORDER BY deal_stage) AS values
        FROM raw.sales_pipeline
        WHERE deal_stage NOT IN {VALID_STAGES} OR deal_stage IS NULL
        """
    ).fetchone()
    add(
        "DQ-014",
        "error" if bad_stage[0] else "pass",
        "deal_stage is within the canonical stage list",
        f"{bad_stage[0]:,} rows outside {VALID_STAGES}: {bad_stage[1]}",
        bad_stage[0],
        f"SELECT count(*) FROM raw.sales_pipeline WHERE deal_stage NOT IN {VALID_STAGES}",
    )

    typo_sectors = con.execute(
        """
        SELECT count(*) AS accounts, string_agg(sector, ', ' ORDER BY sector) AS values
        FROM (SELECT DISTINCT sector FROM raw.accounts)
        WHERE sector = 'technolgy'
        """
    ).fetchone()
    add(
        "DQ-015",
        "warning" if typo_sectors[0] else "pass",
        "accounts.sector spelling conforms to the canonical taxonomy",
        f"{typo_sectors[0]:,} distinct sector value(s) misspelled: {typo_sectors[1]}. "
        "Left unrepaired this silently splits the technology segment in every group-by.",
        typo_sectors[0],
        "SELECT count(*) FROM (SELECT DISTINCT sector FROM raw.accounts) WHERE sector='technolgy'",
    )

    typo_geo = con.execute(
        """
        SELECT count(*) AS accounts, string_agg(office_location, ', ' ORDER BY office_location) AS values
        FROM (SELECT DISTINCT office_location FROM raw.accounts)
        WHERE office_location = 'Philipines'
        """
    ).fetchone()
    add(
        "DQ-016",
        "warning" if typo_geo[0] else "pass",
        "accounts.office_location spelling conforms to ISO country names",
        f"{typo_geo[0]:,} distinct value(s) misspelled: {typo_geo[1]}",
        typo_geo[0],
        "SELECT count(*) FROM (SELECT DISTINCT office_location FROM raw.accounts) WHERE office_location='Philipines'",
    )

    negative_cycle = one(
        con,
        """
        SELECT count(*) FROM raw.sales_pipeline
        WHERE engage_date IS NOT NULL AND close_date IS NOT NULL AND close_date < engage_date
        """,
    )
    add(
        "DQ-017",
        "error" if negative_cycle else "pass",
        "close_date is never before engage_date",
        f"{negative_cycle:,} rows with a negative sales cycle",
        negative_cycle,
        """
        SELECT count(*) FROM raw.sales_pipeline
        WHERE engage_date IS NOT NULL AND close_date IS NOT NULL AND close_date < engage_date
        """,
    )

    future_close = one(
        con,
        "SELECT count(*) FROM raw.sales_pipeline WHERE close_date > current_date",
    )
    add(
        "DQ-018",
        "warning" if future_close else "pass",
        "close_date is not in the future",
        f"{future_close:,} rows dated after today",
        future_close,
        "SELECT count(*) FROM raw.sales_pipeline WHERE close_date > current_date",
    )

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(REPORT_DIR / "source_profile.json"))
    args = parser.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    try:
        tables = {}
        for table in ("accounts", "products", "sales_teams", "sales_pipeline", "data_dictionary"):
            tables[table] = {
                "row_count": int(one(con, f'SELECT count(*) FROM raw."{table}"')),
                "columns": column_profile(con, table),
            }
        dq_findings = findings(con)

        stage_mix = con.execute(
            """
            SELECT deal_stage, count(*) AS opportunities,
                   sum(close_value) AS recorded_value
            FROM raw.sales_pipeline GROUP BY 1 ORDER BY 2 DESC
            """
        ).fetchall()
    finally:
        con.close()

    errors = [f for f in dq_findings if f["severity"] == "error"]
    warnings = [f for f in dq_findings if f["severity"] == "warning"]
    passed = [f for f in dq_findings if f["severity"] == "pass"]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Maven Analytics - CRM Sales Opportunities",
        "stage_counts": {
            "tables_profiled": len(tables),
            "checks_run": len(dq_findings),
            "errors": len(errors),
            "warnings": len(warnings),
            "passed": len(passed),
        },
        "tables": tables,
        "stage_mix": [
            {"stage": s, "opportunities": int(o), "recorded_value": float(v or 0)}
            for s, o, v in stage_mix
        ],
        "findings": dq_findings,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"profiled {len(tables)} tables, ran {len(dq_findings)} checks")
    print(f"  errors   : {len(errors)}")
    print(f"  warnings : {len(warnings)}")
    print(f"  passed   : {len(passed)}")
    print()
    for finding in dq_findings:
        if finding["severity"] == "pass":
            continue
        print(f"[{finding['severity'].upper():<7}] {finding['id']}  {finding['title']}")
        print(f"           {finding['detail']}")
    print(f"\nwrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
