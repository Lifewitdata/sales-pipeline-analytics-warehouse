"""Render the three Power BI report pages as PNG previews from the model's own data.

Why this exists: `powerbi/README.md` describes a report that cannot be opened in
this build environment, and a description nobody can picture is hard to review.
This script draws each page from the artefacts that *are* committed:

  * layout - each visual's `visualType`, `position`, role fields and title come
    straight from `SalesPipeline.Report/definition/pages/<page>/visuals/*`;
  * numbers - every value is a measure from `dax_engine.py`, evaluated over
    `powerbi/data/*.csv`, the same files Power Query imports.

So the pictures show the authored layout filled with the model's real figures.

They are NOT Power BI Desktop screenshots and must not be presented as such.
Power BI has no file format for an unsaved report and Desktop cannot run here,
so the honest offline artefact is a preview of the same page from the same data.
Differences from Desktop are rendering-only: Desktop sorts table and bar rows by
their category and scrolls, these previews sort by the measure so a page is
readable at one glance; slicers are drawn unselected, which is the state the
report opens in; and fonts, themes and hover affordances are matplotlib's.

    python powerbi/render_report_previews.py

Writes `powerbi/assets/report_page{1..3}_*.png`. No warehouse, no credentials,
no Power BI required - only the committed CSVs.
"""

import datetime as dt
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dax_engine import Context, Model  # noqa: E402

PAGES_DIR = ROOT / "SalesPipeline.Report/definition/pages"
ASSETS = ROOT / "assets"
PAGE_W, PAGE_H = 1280, 720
HEADER = 0.085  # figure fraction kept clear above the report canvas for the page title

BLUE = "#0969da"
RED = "#cf222e"
ORANGE = "#bf8700"
GREEN = "#1a7f37"
GREY = "#57606a"
LINE = "#d0d7de"
BG = "#f6f8fa"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.edgecolor": LINE,
        "axes.labelcolor": GREY,
        "xtick.color": GREY,
        "ytick.color": GREY,
        "axes.titlecolor": "#1f2328",
        "axes.titlesize": 8.5,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "grid.color": LINE,
        "grid.linewidth": 0.6,
    }
)

def format_value(value, pattern):
    """Apply a measure's PBIR formatString, blank included."""
    if value is None:
        return "blank"
    percent = "%" in pattern
    section = pattern.split(";")[0].replace("%", "")
    decimals = len(section.split(".")[1]) if "." in section else 0
    money = "$" in section
    number = value * (100 if percent else 1)
    body = f"{abs(number):,.{decimals}f}"
    if money:
        return f"$({body})" if number < 0 else f"${body}"
    suffix = "%" if percent else ""
    return f"-{body}{suffix}" if number < 0 else f"{body}{suffix}"


# PBIR binds a visual's fields under named roles inside queryState; reading them
# from the JSON is what keeps this preview from drifting away from the report.
def fields_of(visual, role):
    state = visual["visual"]["query"]["queryState"]
    return [
        (
            next(iter(item["field"])),
            next(iter(item["field"].values()))["Expression"]["SourceRef"]["Entity"],
            next(iter(item["field"].values()))["Property"],
        )
        for item in state.get(role, {}).get("projections", [])
    ]


def title_of(visual):
    entry = visual["visual"]["visualContainerObjects"].get("title")
    if not entry:
        return ""
    literal = entry[0]["properties"]["text"]["expr"]["Literal"]["Value"]
    return literal.strip("'")


def category_axis(model, entity, prop):
    """(values, context-for-each-value) for a bar, line or table category."""
    column = {"regional_office": "office", "agent_name": "agent",
              "product_series": "series", "deal_stage": "stage"}.get(prop)
    if entity == "dim_date" and prop == "month_start":
        months = model.month_starts
        return list(months), [model.month_context(m) for m in months]
    if column is None:
        raise SystemExit(f"no relationship path implemented for {entity}[{prop}]")
    if entity == "fct_opportunity":
        values = sorted({r[prop] for r in model.fact})
    else:
        values = sorted({r[prop] for r in model.rows[entity]})
    contexts = [Context(**{column: frozenset({v})}) for v in values]
    return values, contexts


def label(value):
    return value.strftime("%b %Y") if isinstance(value, dt.date) else str(value)


def rect(position):
    """Map a PBIR canvas rectangle into figure fractions.

    The authored visuals start 10px from the top of a 720px canvas, so the page
    title and provenance line get a header band and the canvas is scaled into
    the space beneath it rather than being overprinted.
    """
    x, y, w, h = (position[k] for k in ("x", "y", "width", "height"))
    canvas = 1 - HEADER
    return x / PAGE_W, (1 - (y + h) / PAGE_H) * canvas, w / PAGE_W, h / PAGE_H * canvas


def money_scale(axis, pattern):
    """Desktop abbreviates currency; matplotlib's shared 1e6 offset does not read."""
    if "$" in pattern:
        axis.set_major_formatter(
            mticker.FuncFormatter(lambda v, _: f"${v / 1e6:.1f}M" if abs(v) >= 1e6 else f"${v:,.0f}"))


def box(fig, rect_of, edge=LINE, face=BG):
    left, bottom, width, height = rect_of
    patch = FancyBboxPatch(
        (left, bottom), width, height, transform=fig.transFigure,
        boxstyle="round,pad=0.0015,rounding_size=0.006",
        linewidth=1, edgecolor=edge, facecolor=face,
    )
    # Figure.draw sorts its draw list by zorder and a Patch defaults to 1, which
    # would paint this card background over the axes sitting on top of it.
    patch.set_zorder(-10)
    fig.add_artist(patch)


def draw_card(ax, model, formats, visual, title):
    measure = fields_of(visual, "Values")[0]
    if measure[0] != "Measure":
        raise SystemExit("card bound to a column, not a measure")
    value = model.measures(Context())[measure[2]]
    ax.set_axis_off()
    # Titles go inside the visual, as Desktop's header does, rather than above
    # the axes - these boxes abut the page edge and would collide with its title.
    ax.text(0.03, 0.82, title, ha="left", va="center", fontsize=7.5, fontweight="bold",
            color="#1f2328", transform=ax.transAxes)
    ax.text(0.5, 0.4, format_value(value, formats[measure[2]]), ha="center", va="center",
            fontsize=16, fontweight="bold", color="#1f2328", transform=ax.transAxes)


def draw_slicer(ax, model, formats, visual, title):
    _, entity, prop = fields_of(visual, "Values")[0]
    values = sorted({r[prop] for r in model.rows[entity]},
                    key=lambda v: (v is None, str(v) if not isinstance(v, dt.date) else v.isoformat()))
    ax.set_axis_off()
    ax.text(0.012, 0.82, title, ha="left", va="center", fontsize=7.5, fontweight="bold",
            color="#1f2328", transform=ax.transAxes)
    shown = " | ".join(label(v) for v in values[:6])
    ax.text(0.012, 0.38, shown + (f" | +{len(values) - 6} more" if len(values) > 6 else ""),
            ha="left", va="center", fontsize=6.2, color=GREY, transform=ax.transAxes, wrap=True)


def draw_bars(ax, model, formats, visual, title):
    category = fields_of(visual, "Category")[0]
    measure = fields_of(visual, "Y")[0]
    values, contexts = category_axis(model, category[1], category[2])
    pattern = formats[measure[2]]

    pairs = []
    for value, context in zip(values, contexts):
        raw = model.measures(context)[measure[2]]
        pairs.append((label(value), raw or 0, raw))
    pairs.sort(key=lambda p: p[1])

    ax.barh([p[0] for p in pairs], [p[1] for p in pairs], color=BLUE, height=0.62)
    ax.set_title(title, loc="left")
    ax.grid(axis="x", alpha=0.6)
    ax.tick_params(labelsize=6.8)
    money_scale(ax.xaxis, pattern)
    top = max(p[1] for p in pairs) or 1
    ax.set_xlim(0, top * 1.2)
    for i, (_, length, raw) in enumerate(pairs):
        ax.text(length + top * 0.015, i, format_value(raw, pattern), va="center",
                fontsize=6.4, color=GREY)


def draw_line(ax, model, formats, visual, title):
    category = fields_of(visual, "Category")[0]
    measure = fields_of(visual, "Y")[0]
    values, contexts = category_axis(model, category[1], category[2])
    series = [(v, model.measures(c)[measure[2]]) for v, c in zip(values, contexts)]
    ax.plot([v for v, _ in series], [x if x is not None else float("nan") for _, x in series],
            color=BLUE, lw=1.8, marker="o", ms=3)
    ax.set_title(title, loc="left")
    ax.set_ylabel(measure[2])
    ax.grid(axis="y", alpha=0.6)
    ax.tick_params(labelsize=6.8)
    if isinstance(values[0], dt.date):
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        # Desktop's axis spans the whole date dimension, empty months included, so
        # the pre-revenue start of dim_date reads as a gap rather than vanishing.
        edge = dt.timedelta(days=14)
        ax.set_xlim(values[0] - edge, values[-1] + edge)
    else:
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels([label(v) for v in values], rotation=45, ha="right")
    money_scale(ax.yaxis, formats[measure[2]])


def draw_table(ax, model, formats, visual, title, limit=8):
    columns = fields_of(visual, "Values")
    category = next((c for c in columns if c[0] == "Column"), columns[0])
    measures = [c for c in columns if c[0] == "Measure"]
    values, contexts = category_axis(model, category[1], category[2])

    entries = []
    for value, context in zip(values, contexts):
        computed = model.measures(context)
        cells = [format_value(computed[m[2]], formats[m[2]]) for m in measures]
        rank = computed[measures[0][2]] if measures else None
        entries.append((-(rank if rank is not None else float("-inf")), [label(value)] + cells))
    entries.sort(key=lambda e: e[0])
    rows = [e[1] for e in entries]
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit] + [["…"] + [""] * len(measures)]

    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=[c[2] for c in columns], cellLoc="center",
                     loc="center", bbox=[0, 0, 1, 1])
    table.auto_set_font_size(False)
    table.set_fontsize(6.6)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor(LINE)
        if row == 0:
            cell.set_facecolor(BG)
            cell.set_text_props(fontweight="bold", color="#1f2328")
    note = f"top {limit} of {len(values)} by {measures[0][2]}" if truncated else "all rows"
    if measures and truncated:
        note += f"; Desktop sorts by {category[2]} and the visual scrolls"
    elif measures:
        note += f"; sorted by {measures[0][2]}"
    ax.set_title(f"{title}  ({note})", loc="left", pad=6, fontsize=7.5)


def draw(visual, model, formats, fig, page_dir):
    left, bottom, width, height = rect(visual["position"])
    kind = visual["visual"]["visualType"]
    title = title_of(visual)
    if kind == "card":
        box(fig, (left, bottom, width, height))
        ax = fig.add_axes([left, bottom, width, height])
        draw_card(ax, model, formats, visual, title)
    elif kind == "slicer":
        box(fig, (left, bottom, width, height), face="white")
        ax = fig.add_axes([left, bottom, width, height])
        draw_slicer(ax, model, formats, visual, title)
    else:
        # The authored boxes sit 20px from the canvas edge; tick labels need a
        # gutter there, so charts lose a little width rather than losing digits.
        gutter = 0.032 if kind == "lineChart" else 0.055 if kind == "clusteredBarChart" else 0.0
        ax = fig.add_axes([left + gutter, bottom, width - gutter, height - 0.035])
        if kind == "clusteredBarChart":
            draw_bars(ax, model, formats, visual, title)
        elif kind == "lineChart":
            draw_line(ax, model, formats, visual, title)
        elif kind == "tableEx":
            draw_table(ax, model, formats, visual, title)
        else:
            raise SystemExit(f"unhandled visualType {kind} in {page_dir}")


def render(page, out):
    model = Model()
    formats = {m["name"]: m["formatString"]
               for t in model.bim["model"]["tables"] for m in t.get("measures", [])}
    layout = json.loads((PAGES_DIR / page / "page.json").read_text())
    fig = plt.figure(figsize=(PAGE_W / 100, PAGE_H / 100))
    fig.text(0.012, 0.988, layout["displayName"], fontsize=11, fontweight="bold",
             color="#1f2328", va="top")
    fig.add_artist(plt.Line2D([0.01, 0.99], [0.962, 0.962], color=BLUE, lw=1.4,
                              transform=fig.transFigure))
    fig.text(0.012, 0.952,
             "matplotlib preview of the authored PBIR layout - not a Power BI Desktop screenshot; "
             "values from dax_engine.py over powerbi/data/*.csv, slicers unselected",
             fontsize=6.2, color=GREY, va="top")
    for path in sorted((PAGES_DIR / page / "visuals").glob("*/visual.json")):
        draw(json.loads(path.read_text()), model, formats, fig, path.parent)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(ASSETS / out, dpi=150)
    plt.close(fig)
    print(f"wrote powerbi/assets/{out}  {(ASSETS / out).stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    render("executive", "report_page1_sales_performance.png")
    render("pipeline", "report_page2_pipeline_snapshot.png")
    render("quality", "report_page3_data_quality.png")
