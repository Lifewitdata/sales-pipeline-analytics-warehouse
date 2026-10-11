"""Load stage: land the verified source extract into the warehouse raw layer.

Idempotent by construction - every run drops and recreates the raw tables from
the committed CSVs, so a partial or repeated run cannot leave the warehouse in a
mixed state. Each table carries _loaded_at and every run appends to
raw._load_manifest so an auditor can tie any warehouse row back to the exact
source file bytes and the moment it landed.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "raw_data"
DEFAULT_DB = PROJECT_ROOT / "warehouse" / "crm_warehouse.duckdb"

# Explicit column types rather than read_csv_auto inference. Inference lets a
# single malformed value silently widen a column (or turn a numeric column into
# VARCHAR) and the breakage only surfaces three models downstream.
RAW_TABLES: dict[str, dict[str, object]] = {
    "accounts": {
        "file": "accounts.csv",
        "columns": {
            "account": "VARCHAR",
            "sector": "VARCHAR",
            "year_established": "INTEGER",
            "revenue": "DOUBLE",
            "employees": "INTEGER",
            "office_location": "VARCHAR",
            "subsidiary_of": "VARCHAR",
        },
    },
    "products": {
        "file": "products.csv",
        "columns": {
            "product": "VARCHAR",
            "series": "VARCHAR",
            "sales_price": "DOUBLE",
        },
    },
    "sales_teams": {
        "file": "sales_teams.csv",
        "columns": {
            "sales_agent": "VARCHAR",
            "manager": "VARCHAR",
            "regional_office": "VARCHAR",
        },
    },
    "sales_pipeline": {
        "file": "sales_pipeline.csv",
        "columns": {
            "opportunity_id": "VARCHAR",
            "sales_agent": "VARCHAR",
            "product": "VARCHAR",
            "account": "VARCHAR",
            "deal_stage": "VARCHAR",
            "engage_date": "DATE",
            "close_date": "DATE",
            "close_value": "DOUBLE",
        },
    },
    "data_dictionary": {
        "file": "data_dictionary.csv",
        "columns": {
            "source_table": "VARCHAR",
            "field": "VARCHAR",
            "description": "VARCHAR",
        },
    },
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def columns_literal(columns: dict[str, str]) -> str:
    return "{" + ", ".join(f"'{k}': '{v}'" for k, v in columns.items()) + "}"


def ensure_manifest(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw._load_manifest (
            load_run_id     VARCHAR,
            source_file     VARCHAR,
            target_table    VARCHAR,
            row_count       BIGINT,
            column_count    INTEGER,
            source_sha256   VARCHAR,
            loaded_at       TIMESTAMPTZ,
            load_duration_ms BIGINT
        )
        """
    )


def load_table(
    con: duckdb.DuckDBPyConnection, name: str, spec: dict, run_id: str, loaded_at: datetime
) -> dict:
    source_path = RAW_DIR / spec["file"]
    if not source_path.exists():
        raise FileNotFoundError(f"missing source file: {source_path}")

    started = time.perf_counter()
    columns = spec["columns"]
    source_literal = str(source_path).replace("'", "''")

    con.execute(f'DROP TABLE IF EXISTS raw."{name}"')
    con.execute(
        f"""
        CREATE TABLE raw."{name}" AS
        SELECT * FROM read_csv(
            '{source_literal}',
            header = true,
            nullstr = '',
            auto_detect = false,
            columns = {columns_literal(columns)}
        )
        """
    )
    con.execute(
        f'ALTER TABLE raw."{name}" ADD COLUMN _loaded_at TIMESTAMPTZ DEFAULT \'{loaded_at.isoformat()}\'::TIMESTAMPTZ'
    )
    con.execute(f'UPDATE raw."{name}" SET _loaded_at = \'{loaded_at.isoformat()}\'::TIMESTAMPTZ')
    duration_ms = int((time.perf_counter() - started) * 1000)

    row_count = con.execute(f'SELECT count(*) FROM raw."{name}"').fetchone()[0]

    con.execute(
        """
        INSERT INTO raw._load_manifest
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id,
            spec["file"],
            f"raw.{name}",
            row_count,
            len(columns),
            sha256_of(source_path),
            loaded_at,
            duration_ms,
        ],
    )

    return {
        "table": f"raw.{name}",
        "file": spec["file"],
        "rows": row_count,
        "cols": len(columns),
        "ms": duration_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB file path")
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    loaded_at = datetime.now(timezone.utc)

    print(f"loading into {db_path}")
    con = duckdb.connect(str(db_path))
    try:
        ensure_manifest(con)
        results = []
        for name, spec in RAW_TABLES.items():
            results.append(load_table(con, name, spec, run_id, loaded_at))

        print(f"\nrun_id {run_id}")
        print(f"{'table':<24}{'file':<22}{'rows':>8}{'cols':>6}{'ms':>7}")
        print("-" * 67)
        for row in results:
            print(
                f"{row['table']:<24}{row['file']:<22}{row['rows']:>8,}{row['cols']:>6}{row['ms']:>7}"
            )

        total_rows = con.execute(
            """
            SELECT sum(row_count) FROM raw._load_manifest WHERE load_run_id = ?
            """,
            [run_id],
        ).fetchone()[0]
        runs = con.execute(
            "SELECT count(DISTINCT load_run_id) FROM raw._load_manifest"
        ).fetchone()[0]
        print("-" * 67)
        print(f"total rows landed: {total_rows:,}   |   load runs recorded: {runs}")
    finally:
        con.close()

    print("\nload complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
