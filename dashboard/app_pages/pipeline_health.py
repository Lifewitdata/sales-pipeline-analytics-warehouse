import streamlit as st

import db

all_offices = db.offices()
selected_offices = st.multiselect(
    "Regional office",
    all_offices,
    default=all_offices,
    key="ph_office_filter",
)
if not selected_offices:
    st.caption("No office selected - every figure below shows all offices.")
offices = tuple(selected_offices)
trend = db.monthly_trend(offices)
detail = db.pipeline_health(offices)

st.caption(
    "Open pipeline is measured in counts, not value - the source records no "
    "amount on an opportunity until it closes, so a pipeline value would be "
    "fabricated (see docs/METRIC_DEFINITIONS.md)."
)

col_left, col_right = st.columns(2)

with col_left, st.container(border=True):
    st.subheader("Monthly closes")
    st.line_chart(
        trend,
        x="month_start",
        y=["won", "lost"],
        alt="Won and lost opportunities by month",
    )

with col_right, st.container(border=True):
    st.subheader("Open pipeline carried at month end")
    st.area_chart(trend, x="month_start", y="open_pipeline", alt="Open pipeline by month")

with st.container(border=True):
    st.subheader("Engagement vs revenue")
    st.bar_chart(trend, x="month_start", y="engaged", alt="Engaged opportunities by month")
    st.line_chart(trend, x="month_start", y="won_revenue", alt="Won revenue by month")

with st.container(border=True):
    st.subheader("Monthly detail")
    detail["win_rate_pct"] = 100 * detail["win_rate"]
    st.dataframe(
        detail.drop(columns=["win_rate", "closed_count"]),
        hide_index=True,
        width="stretch",
        column_config={
            "month_start": st.column_config.DateColumn("Month", format="YYYY-MM"),
            "regional_office": "Office",
            "engaged_count": st.column_config.NumberColumn("Engaged", format="%d"),
            "won_count": st.column_config.NumberColumn("Won", format="%d"),
            "lost_count": st.column_config.NumberColumn("Lost", format="%d"),
            "won_revenue": st.column_config.NumberColumn("Won revenue", format="$%.0f"),
            "win_rate_pct": st.column_config.NumberColumn("Win rate", format="%.1f%%"),
            "open_pipeline_count": st.column_config.NumberColumn("Open pipeline", format="%d"),
            "avg_won_cycle_days": st.column_config.NumberColumn("Avg cycle (days)", format="%.1f"),
        },
        alt="Monthly pipeline health by office",
    )
