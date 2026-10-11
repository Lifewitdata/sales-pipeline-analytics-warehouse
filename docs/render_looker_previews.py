"""Render the four Looker Studio pages as PNG previews from the built warehouse.

Why this exists: `docs/LOOKER_STUDIO_SPEC.md` is a build sheet, and a build sheet
nobody can picture is hard to review. These images are the layout rendered with
matplotlib against the real `reporting.*` views, so the spec can be read visually
without a Google account or a live BigQuery dataset.

They are NOT Looker Studio screenshots and must not be presented as such. Looker
Studio has no file format for a report - a report exists only inside a Google
account's UI - so the honest offline artefact is a preview of the same pages from
the same numbers. The acceptance check at the bottom of the spec is what ties the
two together: every figure drawn here is a figure the built report must reproduce.

    python docs/render_looker_previews.py

Reads `warehouse/crm_warehouse.duckdb` (run `python etl/load.py` and `dbt build`
first). Writes `docs/assets/looker_page{1..4}_*.png`.
"""

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "warehouse" / "crm_warehouse.duckdb"
ASSETS = ROOT / "docs" / "assets"

# Same theme as dashboard/.streamlit/config.toml and the spec's Layout section, so
# the two BI surfaces read as one product.
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
        "font.size": 8.5,
        "axes.edgecolor": LINE,
        "axes.labelcolor": GREY,
        "xtick.color": GREY,
        "ytick.color": GREY,
        "axes.titlecolor": "#1f2328",
        "axes.titlesize": 9.5,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "grid.color": LINE,
        "grid.linewidth": 0.6,
    }
)

CON = duckdb.connect(str(WAREHOUSE), read_only=True)


def q(sql):
    return CON.execute(sql).df()


def page_frame(title, subtitle, figsize, top=0.885, bottom=0.06):
    """A report page: title, one-line subtitle, an accent rule, then the chart grid.

    The subtitle sits above the rule and the grid starts below it. Both are placed
    in figure coordinates, so `top` has to leave room for them - that spacing is
    what keeps the header from overprinting the first row of titles.
    """
    fig = plt.figure(figsize=figsize)
    fig.text(0.085, 0.978, title, fontsize=13.5, fontweight="bold", color="#1f2328", va="top")
    fig.text(0.085, 0.949, subtitle, fontsize=7.2, color=GREY, va="top")
    fig.add_artist(
        plt.Line2D([0.085, 0.97], [0.933, 0.933], color=BLUE, lw=1.8, transform=fig.transFigure)
    )
    return fig


def grid(fig, nrows, ncols, top=0.885, bottom=0.06, hspace=0.62, wspace=0.22, ratios=None):
    return fig.add_gridspec(
        nrows, ncols, left=0.085, right=0.97, top=top, bottom=bottom,
        wspace=wspace, hspace=hspace, height_ratios=ratios,
    )


def scorecards(fig, rect, items):
    """Draw a row of KPI cards in the figure-fraction rectangle [l, b, w, h]."""
    n = len(items)
    left, bottom, width, height = rect
    gap = 0.008
    card_w = (width - gap * (n - 1)) / n
    for i, (label, value, note) in enumerate(items):
        x = left + i * (card_w + gap)
        box = FancyBboxPatch(
            (x, bottom),
            card_w,
            height,
            transform=fig.transFigure,
            boxstyle="round,pad=0.004,rounding_size=0.008",
            linewidth=1,
            edgecolor=LINE,
            facecolor=BG,
        )
        fig.add_artist(box)
        fig.text(x + card_w / 2, bottom + height * 0.63, value, ha="center", va="center",
                 fontsize=13, fontweight="bold", color="#1f2328")
        fig.text(x + card_w / 2, bottom + height * 0.27, label.upper(), ha="center", va="center",
                 fontsize=6.8, color=GREY)
        if note:
            fig.text(x + card_w / 2, bottom + height * 0.02, note, ha="center", va="center",
                     fontsize=6.2, color=BLUE)


def add_table(ax, rows, col_labels, col_widths=None, fontsize=7.2):
    """A table that fills its axes exactly.

    `bbox` is the whole point: without it matplotlib sizes the table from its own
    text metrics and the last row runs off the bottom of the page.
    """
    ax.axis("off")
    tbl = ax.table(
        cellText=rows, colLabels=col_labels, cellLoc="center", loc="center",
        colWidths=col_widths, bbox=[0, 0, 1, 1],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(fontsize)
    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor(LINE)
        if row == 0:
            cell.set_facecolor(BG)
            cell.set_text_props(fontweight="bold", color="#1f2328")
    return tbl


def office_palette(values):
    """Stable office -> colour mapping, so an office reads the same on every page."""
    cycle = [BLUE, GREEN, ORANGE, RED, "#8250df", "#0d9488", "#e16f24"]
    return {v: cycle[i % len(cycle)] for i, v in enumerate(sorted(values))}


def style_dates(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.grid(axis="y", alpha=0.6)
    ax.tick_params(labelsize=7)


def save(fig, name):
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / name
    fig.savefig(out, dpi=140)
    plt.close(fig)
    print(f"wrote {out.relative_to(ROOT)}  {out.stat().st_size/1024:.0f} KB")


# ---------------------------------------------------------------- page 1
def page1():
    ov = q("select * from reporting.rpt_exec_overview").iloc[0]
    trend = q(
        """
        select month_start, sum(won_revenue) as won_revenue
        from marts.fct_pipeline_monthly group by month_start order by month_start
        """
    )
    funnel = q(
        """
        select deal_stage, stage_order, count(*) as opportunities, sum(revenue) as won_revenue
        from marts.fct_opportunity group by deal_stage, stage_order order by stage_order
        """
    )
    office = q(
        """
        select a.regional_office,
               count(*)                              as opportunities,
               sum(f.revenue)                        as won_revenue,
               sum(case when f.is_won then 1 else 0 end) * 100.0
                 / nullif(sum(case when f.is_closed then 1 else 0 end), 0) as win_rate
        from marts.fct_opportunity f
        join marts.dim_sales_agent a on a.sales_agent_key = f.sales_agent_key
        group by a.regional_office order by won_revenue desc
        """
    )

    fig = page_frame(
        "Sales Pipeline - Executive Overview",
        "Page 1 of 4   |   sources: reporting.rpt_exec_overview, marts.fct_pipeline_monthly, "
        "marts.fct_opportunity, rpt_rep_scorecard   |   no page filter by design (whole warehouse)",
        (11.0, 7.0),
    )
    scorecards(
        fig,
        [0.085, 0.80, 0.885, 0.078],
        [
            ("Opportunities", f"{int(ov.total_opportunities):,}", None),
            ("Won revenue", f"${ov.total_revenue:,.0f}", None),
            ("Win rate", f"{ov.win_rate * 100:.2f}%", "closed-deal"),
            ("Open pipeline", f"{int(ov.open_pipeline_count):,}", "count, not value"),
            ("Avg won deal", f"${ov.avg_won_deal_size:,.2f}", None),
            ("Avg cycle", f"{ov.avg_won_cycle_days:.2f} days", "won deals"),
        ],
    )
    gs = grid(fig, 2, 3, top=0.755, bottom=0.06, ratios=[1.3, 0.7], hspace=0.5)

    ax = fig.add_subplot(gs[0, 0:2])
    ax.plot(trend.month_start, trend.won_revenue / 1e6, color=BLUE, lw=1.8)
    ax.fill_between(trend.month_start, trend.won_revenue / 1e6, color=BLUE, alpha=0.12)
    ax.set_title("Won revenue by month", loc="left")
    ax.set_ylabel("$M")
    style_dates(ax)

    ax = fig.add_subplot(gs[0, 2])
    order = funnel.sort_values("opportunities")
    ax.barh(order.deal_stage, order.opportunities, color=[GREY, GREY, BLUE, GREEN][: len(order)])
    for y, count in enumerate(order.opportunities):
        ax.text(count + 60, y, f"{count:,}", va="center", fontsize=7, color=GREY)
    ax.set_title("Pipeline funnel", loc="left")
    ax.set_xlim(0, order.opportunities.max() * 1.22)
    ax.grid(axis="x", alpha=0.6)
    ax.tick_params(labelsize=7.5)

    ax = fig.add_subplot(gs[1, :])
    add_table(
        ax,
        [
            [
                r.regional_office,
                f"{int(r.opportunities):,}",
                f"${r.won_revenue:,.0f}",
                f"{r.win_rate:.1f}%",
            ]
            for r in office.itertuples()
        ],
        ["Regional office", "Opportunities", "Won revenue", "Win rate"],
        col_widths=[0.34, 0.22, 0.24, 0.20],
        fontsize=7.8,
    )
    ax.set_title("Office breakdown", loc="left", pad=9)
    save(fig, "looker_page1_exec_overview.png")


# ---------------------------------------------------------------- page 2
def page2():
    health = q(
        """
        select month_start, sum(engaged_count) as engaged, sum(won_count) as won,
               sum(lost_count) as lost, sum(won_revenue) as won_revenue,
               sum(open_pipeline_count) as open_pipeline
        from marts.fct_pipeline_monthly group by month_start order by month_start
        """
    )
    detail = q("select * from reporting.rpt_pipeline_health order by month_start desc limit 6")

    fig = page_frame(
        "Sales Pipeline - Pipeline Health",
        "Page 2 of 4   |   source: reporting.rpt_pipeline_health (grain: month x regional office)"
        "   |   page filter: regional_office drives every element below",
        (11.0, 7.0),
    )
    gs = grid(fig, 3, 2, top=0.885, bottom=0.06, ratios=[1, 1, 0.72], hspace=0.62)

    ax = fig.add_subplot(gs[0, 0])
    ax.plot(health.month_start, health.won, color=GREEN, lw=1.7, label="won")
    ax.plot(health.month_start, health.lost, color=RED, lw=1.7, label="lost")
    ax.set_title("Monthly closes", loc="left")
    ax.legend(frameon=False, fontsize=7)
    style_dates(ax)

    ax = fig.add_subplot(gs[0, 1])
    ax.fill_between(health.month_start, health.open_pipeline, color=BLUE, alpha=0.25)
    ax.plot(health.month_start, health.open_pipeline, color=BLUE, lw=1.5)
    ax.set_title("Open pipeline carried", loc="left")
    ax.set_ylabel("opportunities")
    style_dates(ax)

    ax = fig.add_subplot(gs[1, 0])
    ax.bar(health.month_start, health.engaged, color=GREY, width=20)
    ax.set_title("Engagement volume", loc="left")
    style_dates(ax)

    ax = fig.add_subplot(gs[1, 1])
    ax.plot(health.month_start, health.won_revenue / 1e6, color=BLUE, lw=1.7)
    ax.set_title("Won revenue trend", loc="left")
    ax.set_ylabel("$M")
    style_dates(ax)

    ax = fig.add_subplot(gs[2, :])
    add_table(
        ax,
        [
            [
                r.month_start.strftime("%b %y"),
                r.regional_office,
                f"{int(r.engaged_count):,}",
                f"{int(r.won_count):,}",
                f"{int(r.lost_count):,}",
                f"${r.won_revenue:,.0f}",
                f"{r.win_rate * 100:.1f}%",
            ]
            for r in detail.itertuples()
        ],
        ["Month", "Office", "Engaged", "Won", "Lost", "Won revenue", "Win rate"],
        fontsize=7.8,
    )
    ax.set_title("Monthly detail (latest 6 rows)", loc="left", pad=9)
    save(fig, "looker_page2_pipeline_health.png")


# ---------------------------------------------------------------- page 3
def page3():
    reps = q("select * from reporting.rpt_rep_scorecard order by total_revenue desc")
    top = reps.head(10).sort_values("total_revenue")

    fig = page_frame(
        "Sales Pipeline - Rep Scorecard",
        "Page 3 of 4   |   source: reporting.rpt_rep_scorecard (30 agents)   |   page filters: "
        "regional_office, manager_name   |   bubble size = won revenue",
        (11.0, 7.0),
    )
    gs = grid(fig, 2, 2, top=0.885, bottom=0.06, ratios=[1.15, 0.85], hspace=0.55)
    palette = office_palette(reps.regional_office.unique())

    ax = fig.add_subplot(gs[0, 0])
    short = [f"{n.split()[0][0]}. {n.split()[1]}" for n in top.agent_name]
    ax.barh(short, top.total_revenue / 1000, color=[palette[o] for o in top.regional_office])
    ax.set_title("Top 10 agents by won revenue", loc="left")
    ax.set_xlabel("$K")
    ax.grid(axis="x", alpha=0.6)
    ax.tick_params(labelsize=7.5)

    ax = fig.add_subplot(gs[0, 1])
    for office, group in reps.groupby("regional_office"):
        ax.scatter(
            group.total_opportunities,
            group.win_rate * 100,
            s=group.total_revenue / 6000,
            alpha=0.75,
            color=palette[office],
            label=office,
            edgecolor="white",
            linewidth=0.6,
        )
    pooled = reps.won_count.sum() / (reps.won_count.sum() + reps.lost_count.sum()) * 100
    ax.axhline(pooled, color=GREY, ls="--", lw=1)
    ax.set_title(f"Win rate vs volume  (dashed = pooled {pooled:.2f}%)", loc="left")
    ax.set_xlabel("opportunities")
    ax.set_ylabel("win rate %")
    ax.legend(frameon=False, fontsize=7)
    ax.grid(alpha=0.4)
    ax.tick_params(labelsize=7.5)

    ax = fig.add_subplot(gs[1, :])
    add_table(
        ax,
        [
            [
                f"{int(r.revenue_rank)}",
                r.agent_name,
                r.manager_name,
                r.regional_office,
                f"{int(r.total_opportunities):,}",
                f"{int(r.won_count):,}",
                f"{r.win_rate * 100:.1f}%",
                f"{int(r.open_pipeline_count):,}",
                f"${r.total_revenue:,.0f}",
                f"${r.avg_won_deal_size:,.0f}",
                f"{r.avg_won_cycle_days:.1f}",
            ]
            for r in reps.head(11).itertuples()
        ],
        ["#", "Agent", "Manager", "Office", "Opps", "Won", "Win %", "Open",
         "Won revenue", "Avg deal", "Avg days"],
        col_widths=[0.04, 0.15, 0.15, 0.09, 0.07, 0.07, 0.08, 0.07, 0.12, 0.08, 0.08],
        fontsize=7.2,
    )
    ax.set_title("Full scorecard (top 11 of 30 shown)", loc="left", pad=9)
    save(fig, "looker_page3_rep_scorecard.png")


# ---------------------------------------------------------------- page 4
def page4():
    dq = q("select * from reporting.rpt_data_quality order by flagged_rows desc")
    completeness = q(
        """
        -- The spec's Null profile element reads the two flag columns, not raw
        -- null tests; they agree exactly (1,425 / 500 / 2,089), and the flags are
        -- what a Looker Studio connector would actually see.
        select count(*)                          as total,
               sum(is_account_missing)            as missing_account,
               sum(is_pre_engagement)             as pre_engagement,
               sum(case when close_date is null then 1 else 0 end) as open_pipeline
        from marts.fct_opportunity
        """
    ).iloc[0]
    repaired = q(
        "select count(*) as n from intermediate.int_opportunity_enriched "
        "where is_product_key_repaired"
    ).iloc[0]["n"]

    fig = page_frame(
        "Sales Pipeline - Data Quality",
        f"Page 4 of 4   |   source: reporting.rpt_data_quality ({len(dq)} findings from the "
        "dbt tests)   |   every figure here is a row the warehouse refused to hide",
        (11.0, 7.0),
    )
    cmap = {"error": RED, "warning": ORANGE, "info": BLUE, "ok": GREEN}
    scorecards(
        fig,
        [0.085, 0.80, 0.885, 0.072],
        [
            ("Checks firing", f"{len(dq):,}", "4 warning, 3 info"),
            ("Error-severity rows",
             f"{int(dq[dq.severity == 'error'].flagged_rows.sum()):,}",
             "DQ-003b - must be 0"),
            ("Missing account", f"{int(completeness.missing_account):,}", "never imputed"),
            ("Repaired product", f"{int(repaired):,}", "normalized join"),
        ],
    )
    gs = grid(fig, 2, 2, top=0.755, bottom=0.06, ratios=[1.05, 0.95], hspace=0.55)

    ax = fig.add_subplot(gs[0, 0])
    counts = dq.groupby("severity").flagged_rows.sum().sort_values()
    ax.bar(counts.index, counts.values, color=[cmap.get(s, GREY) for s in counts.index])
    for i, v in enumerate(counts.values):
        ax.text(i, v * 1.1, f"{v:,}", ha="center", fontsize=7.5, color=GREY)
    ax.set_title("Severity mix (flagged rows, log scale)", loc="left")
    ax.set_yscale("log")
    ax.grid(axis="y", alpha=0.5)
    ax.tick_params(labelsize=7.5)

    ax = fig.add_subplot(gs[0, 1])
    labels = ["missing account", "pre-engagement", "open pipeline"]
    values = [completeness.missing_account, completeness.pre_engagement,
              completeness.open_pipeline]
    ax.barh(labels, values, color=[RED, ORANGE, BLUE])
    for i, v in enumerate(values):
        ax.text(v + 25, i, f"{int(v):,}", va="center", fontsize=7.5, color=GREY)
    ax.set_title(f"Null profile of {int(completeness.total):,} opportunities", loc="left")
    ax.set_xlim(0, max(values) * 1.28)
    ax.grid(axis="x", alpha=0.6)
    ax.tick_params(labelsize=7.5)

    ax = fig.add_subplot(gs[1, :])
    rows = [[r.check_id, r.severity, r.finding, f"{int(r.flagged_rows):,}"] for r in dq.itertuples()]
    tbl = add_table(
        ax, rows, ["Check", "Severity", "Finding", "Rows"],
        col_widths=[0.09, 0.1, 0.69, 0.08], fontsize=7.2,
    )
    for (row, col), cell in tbl.get_celld().items():
        if row > 0 and col == 2:
            cell.set_text_props(ha="left")
        elif row > 0 and col == 1:
            cell.set_text_props(color=cmap.get(rows[row - 1][1], "#1f2328"), fontweight="bold")
    ax.set_title("Findings by check", loc="left", pad=9)
    save(fig, "looker_page4_data_quality.png")


if __name__ == "__main__":
    if not WAREHOUSE.exists():
        raise SystemExit(
            f"no warehouse at {WAREHOUSE} - run `python etl/load.py` then `dbt build` "
            "in warehouse/ first"
        )
    page1()
    page2()
    page3()
    page4()
