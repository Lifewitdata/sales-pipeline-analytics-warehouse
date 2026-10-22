"""Validate the Power BI project: PBIR schemas, model references, and all 13 DAX measures.

Run after `python powerbi/build_project.py`:

    python -m pip install jsonschema
    python powerbi/validate_project.py

Seven independent layers, each comparing two artefacts produced by different
code that could disagree:

1.  Report JSON against Microsoft's published PBIR schemas (fetched live).
2.  The semantic model itself - relationships, key uniqueness, `summarizeBy`.
3.  `measures.dax` and `Acceptance.dax` against the measures installed in
    `model.bim`, including every column and measure each expression references.
4.  Every field reference in every visual against the model's tables.
5.  The fact table's stage labels against its boolean flags, so a SQL baseline
    written `FILTER (WHERE is_won)` and a DAX filter written `deal_stage = "Won"`
    cannot silently diverge.
6.  `dax_engine.py` - a Python re-implementation of the 13 measures - against
    `expected_kpis.json`, which `build_project.py` derives in SQL from the dbt
    marts: all-time, per office, per product series, per close month.
7.  The published acceptance table in `README.md` against that same baseline, so
    the document cannot drift away from the model.

What this still does NOT prove: the Microsoft DAX engine and the Power Query (M)
engine were never executed, and no visual was rendered by Power BI Desktop.
`dax_engine.py` re-implements the measure definitions; it does not re-execute
them. Opening the project in Desktop and refreshing remains the acceptance step.
"""

import csv
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dax_engine import CLOSED, OPEN, Context, Model  # noqa: E402

BASELINE_TO_MEASURE = {
    "opportunities": "Opportunities",
    "won_deals": "Won Deals",
    "closed_deals": "Closed Deals",
    "won_revenue": "Won Revenue",
    "win_rate": "Win Rate",
    "average_won_deal": "Average Won Deal",
    "average_won_sales_cycle_days": "Average Won Sales Cycle Days",
    "open_opportunities": "Open Opportunities",
    "average_open_age_days": "Average Open Age Days",
    "missing_account_opportunities": "Missing Account Opportunities",
    "missing_account_rate": "Missing Account Rate",
}


@lru_cache(None)
def fetch(url):
    # Some Microsoft embedded schemas identify themselves with .embedded
    # while their published URL uses -embedded. Resolve that URL alias.
    url = url.replace("schema.embedded.json", "schema-embedded.json")
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


class Report:
    def __init__(self):
        self.passes = 0
        self.skips = []
        self.notes = []
        self.failures = []

    def true(self, condition, label, detail=""):
        if condition:
            self.passes += 1
        else:
            self.failures.append(f"{label} - {detail}" if detail else label)

    def note(self, label):
        self.notes.append(label)

    def value(self, label, actual, expected, tol=1e-9):
        if actual is None or expected is None:
            self.true(actual is expected, label,
                      "expected blank, got %r" % (actual,) if expected is None
                      else "expected %r, got blank" % (expected,))
        elif isinstance(actual, int) and isinstance(expected, int):
            self.true(actual == expected, label, f"{actual} != {expected}")
        else:
            scale = max(abs(expected), 1.0)
            self.true(abs(actual - expected) <= tol * scale, label, f"{actual!r} != {expected!r}")

    def skip(self, label, reason):
        self.skips.append(f"{label} ({reason})")


def validate_schemas(report):
    try:
        from jsonschema import Draft7Validator, RefResolver
    except ImportError:
        report.skip("PBIR schema validation", "jsonschema not installed")
        return
    paths = sorted((ROOT / "SalesPipeline.Report").rglob("*.json")) + [
        ROOT / "SalesPipeline.Report/definition.pbir"
    ]
    checked = 0
    for path in paths:
        obj = json.loads(path.read_text())
        url = obj.get("$schema")
        if not url:
            continue
        try:
            schema = fetch(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            report.skip("PBIR schema validation", f"Microsoft schemas unreachable: {exc}")
            return
        Draft7Validator(schema, resolver=RefResolver(url, schema, handlers={"https": fetch})).validate(obj)
        checked += 1
    report.true(checked > 0, f"{checked} PBIR documents conform to Microsoft's published schemas")


def validate_model(model, rows, report):
    tables = {t["name"]: t for t in model["tables"]}
    measures = {m["name"] for t in tables.values() for m in t.get("measures", [])}

    for rel in model["relationships"]:
        for side in ("fromTable", "toTable"):
            report.true(rel[side] in tables, f"relationship {rel['name']} names a real table: {rel[side]}")
        keys = [r[rel["toColumn"]] for r in rows[rel["toTable"]]]
        report.true(len(keys) == len(set(keys)) and all(keys),
                    f"{rel['name']}: {rel['toTable']}[{rel['toColumn']}] is unique and non-null")
        lookup = set(keys)
        orphans = [r[rel["fromColumn"]] for r in rows[rel["fromTable"]]
                   if r[rel["fromColumn"]] and r[rel["fromColumn"]] not in lookup]
        report.true(not orphans, f"{rel['name']}: every fact key resolves in its dimension",
                    f"{len(orphans)} orphan rows")
        report.true(rel["crossFilteringBehavior"] == "oneDirection" and rel["isActive"]
                    and rel["toCardinality"] == "one" and rel["fromCardinality"] == "many",
                    f"{rel['name']}: active one-to-many, single direction, as documented")

    numeric = [c["name"] for t in tables.values() for c in t["columns"]
               if c["dataType"] in ("int64", "double") and c["name"] != "date_key"]
    report.true(all(c["summarizeBy"] == "none" for t in tables.values() for c in t["columns"]
                    if c["dataType"] in ("int64", "double") and c["name"] != "date_key"),
                f"all {len(numeric)} numeric columns are Do-not-summarize, so visuals can only use measures")
    return tables, measures


def validate_measure_source(model, tables, measures, engine, report):
    """model.bim is what runs; measures.dax and Acceptance.dax are the paperwork."""
    installed = {m["name"]: m["expression"] for t in model["tables"] for m in t.get("measures", [])}
    report.true(set(engine.measures(Context())) == set(installed),
                "dax_engine.py implements exactly the measures installed in model.bim")

    text = (ROOT / "measures.dax").read_text()
    documented = dict(re.findall(r"^([A-Z][A-Za-z ]*?) =\n(.+?)(?=\n\n|\Z)", text, re.M | re.S))
    report.true(set(documented) == set(installed),
                f"measures.dax lists all {len(installed)} measures and nothing else",
                f"extra={sorted(set(documented) - set(installed))} "
                f"missing={sorted(set(installed) - set(documented))}")
    for name, expression in installed.items():
        report.true(name not in documented
                    or " ".join(documented[name].split()) == " ".join(expression.split()),
                    f"measures.dax is byte-faithful to model.bim for [{name}]")

    qualified = re.compile(r"([A-Za-z_]\w*)\[([^\]]+)\]")
    for name, expression in installed.items():
        for table, column in qualified.findall(expression):
            report.true(table in tables and column in {c["name"] for c in tables[table]["columns"]},
                        f"[{name}] references a real column: {table}[{column}]")
        for reference in re.findall(r"\[([^`\]]+)\]", qualified.sub("", expression)):
            report.true(reference in measures, f"[{name}] references a defined measure: [{reference}]")

    acceptance = (ROOT / "SalesPipeline.SemanticModel/DAXQueries/Acceptance.dax").read_text()
    for reference in re.findall(r"\[([^\]\n]+)\]", acceptance):
        report.true(reference in measures, f"Acceptance.dax references a defined measure: [{reference}]")
    report.true(acceptance.count("EVALUATE ROW") == 1
                and len(re.findall(r'^\s+"', acceptance, re.M)) == len(BASELINE_TO_MEASURE),
                f"Acceptance.dax evaluates the {len(BASELINE_TO_MEASURE)} whole-number measures in one row")


def validate_visuals(tables, measures, report):
    count = 0
    for path in sorted((ROOT / "SalesPipeline.Report/definition/pages").glob("*/visuals/*/visual.json")):
        visual = json.loads(path.read_text())["visual"]
        count += 1
        for projections in visual["query"]["queryState"].values():
            for item in projections["projections"]:
                kind, payload = next(iter(item["field"].items()))
                entity, prop = payload["Expression"]["SourceRef"]["Entity"], payload["Property"]
                report.true(entity in tables, f"{path.parent.name}: source {entity} exists")
                if kind == "Measure":
                    report.true(prop in measures, f"{path.parent.name}: measure [{prop}] exists")
                else:
                    report.true(prop in {c["name"] for c in tables[entity]["columns"]},
                                f"{path.parent.name}: column {entity}[{prop}] exists")
    report.true(count > 0, f"the report defines {count} visuals to check")


def validate_invariants(fact, report):
    """The data facts the SQL baseline and the DAX filters both lean on."""
    equivalent = {"is_won": {"Won"}, "is_lost": {"Lost"},
                  "is_closed": set(CLOSED), "is_open": set(OPEN)}
    for flag, stages in equivalent.items():
        mismatched = [r["deal_stage"] for r in fact if bool(r[flag]) != (r["deal_stage"] in stages)]
        report.true(not mismatched, f"{flag} is exactly deal_stage in {sorted(stages)}",
                    f"{len(mismatched)} rows disagree, e.g. {mismatched[:3]}")
    report.true(sum(1 for r in fact if r["is_account_missing"])
                == sum(1 for r in fact if not r["account_key"]),
                "is_account_missing is exactly a null account_key")
    report.true(all(r["revenue"] in (None, 0.0) for r in fact if r["deal_stage"] not in CLOSED),
                "no open deal carries revenue, so sum(revenue) and won-only revenue cannot diverge")
    report.true(all(r["close_date"] is None for r in fact if r["deal_stage"] in OPEN)
                and all(r["close_date"] for r in fact if r["deal_stage"] in CLOSED),
                "open deals have no close date and closed deals always do")

    aged = {id(r) for r in fact if r["days_open_at_snapshot"] is not None}
    engaged_open = {id(r) for r in fact if r["is_open"] and not r["is_pre_engagement"]}
    report.true(aged == engaged_open,
                f"days_open_at_snapshot is populated for exactly the {len(engaged_open)} open, "
                "engaged rows - AVERAGE ignores the rest, it does not treat them as zero")


def validate_measures(engine, baseline, report):
    values, prior = baseline["values"], baseline["all_time_mom"]
    actual = engine.measures(Context())
    for key, name in BASELINE_TO_MEASURE.items():
        report.value(f"all-time {name}", actual[name], values[key])
    report.value("all-time Revenue Previous Month", actual["Revenue Previous Month"],
                 prior["revenue_previous_month"])
    report.value("all-time Revenue MoM Change", actual["Revenue MoM Change"], prior["revenue_mom_change"])

    for group, dimension in (("by_office", "office"), ("by_series", "series")):
        for name, expected in baseline[group].items():
            filtered = engine.measures(Context(**{dimension: frozenset({name})}))
            for key, measure in BASELINE_TO_MEASURE.items():
                if key in expected:
                    report.value(f"{group} {name} - {measure}", filtered[measure], expected[key])

    truncated = []
    for month_start, expected in baseline["by_close_month"].items():
        filtered = engine.measures(engine.month_context(dt.date.fromisoformat(month_start)))
        for column, measure in (("won_revenue", "Won Revenue"),
                                ("revenue_previous_month", "Revenue Previous Month"),
                                ("revenue_mom_change", "Revenue MoM Change")):
            report.value(f"{month_start} - {measure}", filtered[measure], expected[column])
        if expected["revenue_previous_calendar_month"] != expected["revenue_previous_month"]:
            truncated.append((month_start,
                              expected["revenue_previous_calendar_month"]
                              - expected["revenue_previous_month"]))
        else:
            report.value(f"{month_start}: DATEADD(day) equals the calendar month",
                         filtered["Revenue Previous Month"], expected["revenue_previous_calendar_month"])
    if truncated:
        report.note("DATEADD shifts dim_date[date_day], so a 30-day month cannot reach day 31 of the "
                    "month before it: " + ", ".join(f"{m[:7]} is short ${d:,.0f}" for m, d in truncated)
                    + ". Pinned in expected_kpis.json, not papered over.")

    lost = engine.measures(Context(stage=frozenset({"Lost"})))
    report.true(lost["Won Deals"] == 0 and lost["Won Revenue"] is None
                and lost["Average Won Deal"] is None and lost["Win Rate"] == 0.0
                and lost["Closed Deals"] > 0,
                "KEEPFILTERS intersects rather than overwrites: 0 won deals inside a Lost "
                "selection, blank SUM, blank on a zero denominator, but 0/n is a real 0")
    won = engine.measures(Context(stage=frozenset({"Won"})))
    report.true(won["Opportunities"] == values["won_deals"] == actual["Won Deals"],
                "a Won stage selection and the Won Deals measure agree")
    prospecting = engine.measures(Context(stage=frozenset({"Prospecting"})))
    report.true(prospecting["Closed Deals"] == 0 and prospecting["Average Won Deal"] is None,
                "a stage with no closed deals returns blank ratios, not ZeroDivision or 0.0%")

    december = engine.month_context(dt.date(2017, 12, 1))
    in_december = engine.measures(december)
    report.true(in_december["Open Opportunities"] == actual["Open Opportunities"]
                == values["open_opportunities"],
                "REMOVEFILTERS(dim_date): the close-month slicer does not reach open-deal measures")
    report.true(in_december["Opportunities"] < actual["Opportunities"]
                and in_december["Won Revenue"] != actual["Won Revenue"],
                "the same slicer does reach the measures that keep the date filter")


def validate_readme(baseline, report):
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    values = baseline["values"]
    rows = dict(re.findall(r"^\|\s*([A-Z][^|]*?)\s*\|\s*\$?([\d,]+(?:\.\d+)?%?)\s*\|", text, re.M))
    pinned = 0
    for name, displayed in rows.items():
        key = next((k for k, v in BASELINE_TO_MEASURE.items() if v == name), None)
        if key is None:
            continue
        cleaned = displayed.replace(",", "").rstrip("%")
        shown = float(cleaned) / (100 if displayed.endswith("%") else 1)
        decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
        unit = 0.01 if displayed.endswith("%") else 10 ** -decimals
        report.value(f"README acceptance row {name}", shown, values[key], tol=unit / 2 + 1e-12)
        pinned += 1
    report.true(pinned == len(BASELINE_TO_MEASURE),
                f"all {pinned} acceptance-table rows re-checked against the SQL baseline",
                f"parsed {pinned} of {len(BASELINE_TO_MEASURE)} pinned measures from README.md")
    checked = 0
    for office, revenue in re.findall(r"(West|Central|East)(?: office revenue)? = \$([\d,]+)", text):
        report.value(f"README prose {office} revenue", float(revenue.replace(",", "")),
                     baseline["by_office"][office]["won_revenue"], tol=0.5)
        checked += 1
    report.true(checked == len(baseline["by_office"]),
                "every office in the baseline has a matching README acceptance figure")


def validate():
    report = Report()
    engine = Model()
    model = engine.bim["model"]
    raw = {p.stem: list(csv.DictReader((engine.data_dir / p.name).open()))
           for p in sorted(engine.data_dir.glob("*.csv"))}
    baseline = json.loads((ROOT / "expected_kpis.json").read_text())

    validate_schemas(report)
    tables, measures = validate_model(model, raw, report)
    validate_measure_source(model, tables, measures, engine, report)
    validate_visuals(tables, measures, report)
    validate_invariants(engine.fact, report)
    validate_measures(engine, baseline, report)
    validate_readme(baseline, report)

    for failure in report.failures:
        print("FAIL ", failure)
    for skip in report.skips:
        print("SKIP ", skip)
    for note in report.notes:
        print("NOTE ", note)
    if report.failures:
        print(f"\nFAILED: {len(report.failures)} of "
              f"{report.passes + len(report.failures)} checks.")
        return 1
    print(f"PASS: {report.passes} checks over schema, model, DAX definitions, SQL baseline "
          "and README - see the module docstring for what is not covered.")
    return 0


if __name__ == "__main__":
    sys.exit(validate())
