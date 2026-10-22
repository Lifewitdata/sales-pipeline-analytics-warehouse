"""Evaluate the semantic model's 13 DAX measures in Python over the CSV snapshots.

This is NOT the Microsoft DAX engine and does not pretend to be. It is a
deliberate re-implementation of the measure definitions in
`SalesPipeline.SemanticModel/model.bim`, run against the same CSV files Power
Query imports. `validate_project.py` compares its output to the SQL baseline in
`expected_kpis.json`, which proves each measure's *definition* - its stage
intersection, its blank handling, its date-filter removal - rather than only
the fact table's totals. Power BI Desktop is not available in this environment,
so the real engine is still never invoked.

Semantics reproduced on purpose:

* `KEEPFILTERS` intersects the measure's stage restriction with any stage
  filter already in context instead of replacing it, so a Won measure under a
  Lost selection is empty.
* `COUNTROWS` over an empty selection is 0, but `SUM`/`AVERAGE` are blank.
  `AVERAGE` ignores blanks; `DIVIDE` is blank on a zero or blank denominator.
* `REMOVEFILTERS(dim_date)` drops the filter that a slicer on
  `dim_date[month_start]` propagates to `fct_opportunity[close_date]` through
  the single-direction relationship - which is why open-deal measures still see
  deals that have no close date.
* `DATEADD(dim_date[date_day], -1, MONTH)` shifts the actual filtered day set
  and clamps to the end of the shorter month, so at month grain it is *not*
  always the whole previous calendar month. See `revenue_previous_month`.
* A dimension filter reaches the fact only through the relationship key, so a
  fact row whose key is absent from the dimension is excluded.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import json
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WON = frozenset({"Won"})
CLOSED = frozenset({"Won", "Lost"})
OPEN = frozenset({"Prospecting", "Engaging"})
BLANK = None


def minus_one_month(day: dt.date) -> dt.date:
    """DAX DATEADD(..., -1, MONTH): clamp 31 -> last day of a shorter month."""
    year, month = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Context:
    """A report filter context. `None` means "no filter on that field".

    `days` holds the surviving `dim_date[date_day]` values, which is how both a
    month slicer and a DATEADD result reach the fact.
    """

    stage: frozenset | None = None
    office: frozenset | None = None
    agent: frozenset | None = None
    series: frozenset | None = None
    days: frozenset | None = None


def _sum(values):
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else BLANK


def _avg(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else BLANK


def _divide(numerator, denominator):
    if denominator is None or denominator == 0:
        return BLANK
    return (numerator or 0) / denominator


class Model:
    def __init__(self, root: Path = ROOT):
        bim = json.loads((root / "SalesPipeline.SemanticModel/model.bim").read_text())
        self.bim = bim
        self.data_dir = root / "data"
        self.types = {}
        self.measure_names = []
        for table in bim["model"]["tables"]:
            self.types[table["name"]] = {c["name"]: c["dataType"] for c in table["columns"]}
            self.measure_names += [m["name"] for m in table.get("measures", [])]
        self.rows = {
            name: self._read(self.data_dir / f"{name}.csv", types)
            for name, types in self.types.items()
        }
        self.fact = self.rows["fct_opportunity"]
        self.agents = self.rows["dim_sales_agent"]
        self.products = self.rows["dim_product"]
        self.dates = self.rows["dim_date"]
        self.office_of = {r["sales_agent_key"]: r["regional_office"] for r in self.agents}
        self.agent_of = {r["sales_agent_key"]: r["agent_name"] for r in self.agents}
        self.series_of = {r["product_key"]: r["product_series"] for r in self.products}
        self.all_days = frozenset(r["date_day"] for r in self.dates)
        self.month_starts = sorted({r["month_start"] for r in self.dates})
        self.days_by_month = {
            m: frozenset(r["date_day"] for r in self.dates if r["month_start"] == m)
            for m in self.month_starts
        }

    def _read(self, path, types):
        with path.open(newline="", encoding="utf-8") as handle:
            out = []
            for raw in csv.DictReader(handle):
                row = {}
                for column, value in raw.items():
                    row[column] = self._cell(value, types[column])
                out.append(row)
        return out

    @staticmethod
    def _cell(value, dtype):
        if value == "":
            return None
        if dtype == "boolean":
            return value == "true"
        if dtype == "dateTime":
            return dt.date.fromisoformat(value[:10])
        if dtype == "int64":
            return int(value)
        if dtype == "double":
            return float(value)
        return value

    # ------------------------------------------------------------- context
    def month_context(self, month_start, **filters):
        return Context(days=self.days_by_month[month_start], **filters)

    def dateadd_month(self, context: Context) -> Context:
        """CALCULATE(..., DATEADD(dim_date[date_day], -1, MONTH)).

        With no date filter in context the shift runs over every day in
        dim_date, exactly as DAX does - which is why the all-time reading of the
        two MoM measures is meaningless rather than absent. Shifted values that
        are not in dim_date drop out, because the filter lands on dim_date.
        """
        source = context.days if context.days is not None else self.all_days
        shifted = frozenset(minus_one_month(day) for day in source)
        return replace(context, days=shifted & self.all_days)

    def scan(self, context: Context, *, stage_keep=None, ignore_date=False):
        """Fact rows surviving the filter context, then the measure's own stage.

        `stage_keep` uses KEEPFILTERS intersection, not CALCULATE's default
        overwrite.
        """
        rows = self.fact
        if context.office:
            rows = [r for r in rows if self.office_of.get(r["sales_agent_key"]) in context.office]
        if context.agent:
            rows = [r for r in rows if self.agent_of.get(r["sales_agent_key"]) in context.agent]
        if context.series:
            rows = [r for r in rows if self.series_of.get(r["product_key"]) in context.series]
        if context.days is not None and not ignore_date:
            rows = [r for r in rows if r["close_date"] in context.days]
        stages = context.stage
        if stage_keep is not None:
            stages = stage_keep if stages is None else stages & frozenset(stage_keep)
        if stages is not None:
            rows = [r for r in rows if r["deal_stage"] in stages]
        return rows

    # ------------------------------------------------------------- measures
    def won_rows(self, context):
        return self.scan(context, stage_keep=WON)

    def revenue_previous_month(self, context):
        return _sum(r["revenue"] for r in self.won_rows(self.dateadd_month(context)))

    def measures(self, context: Context):
        """All 13 measures, keyed by their model names, for one filter context."""
        rows = self.scan(context)
        won = self.won_rows(context)
        open_rows = self.scan(context, stage_keep=OPEN, ignore_date=True)
        missing = [r for r in rows if r["is_account_missing"] is True]
        won_revenue = _sum(r["revenue"] for r in won)
        previous = self.revenue_previous_month(context)
        return {
            "Opportunities": len(rows),
            "Won Deals": len(won),
            "Closed Deals": len(self.scan(context, stage_keep=CLOSED)),
            "Won Revenue": won_revenue,
            "Win Rate": _divide(len(won), len(self.scan(context, stage_keep=CLOSED))),
            "Average Won Deal": _divide(won_revenue, len(won)),
            "Average Won Sales Cycle Days": _avg(r["sales_cycle_days"] for r in won),
            "Open Opportunities": len(open_rows),
            "Average Open Age Days": _avg(r["days_open_at_snapshot"] for r in open_rows),
            "Missing Account Opportunities": len(missing),
            "Missing Account Rate": _divide(len(missing), len(rows)),
            "Revenue Previous Month": previous,
            "Revenue MoM Change": BLANK
            if previous is None
            else _divide((won_revenue or 0) - previous, previous),
        }
