import streamlit as st

import db

row = db.exec_overview().iloc[0]

with st.container(horizontal=True):
    st.metric("Opportunities", f"{int(row.total_opportunities):,}", border=True)
    st.metric("Won revenue", f"${row.total_revenue:,.0f}", border=True)
    st.metric("Win rate", f"{row.win_rate * 100:.1f}%", border=True)
    st.metric("Open pipeline", f"{int(row.open_pipeline_count):,}", border=True)
    st.metric("Avg won deal", f"${row.avg_won_deal_size:,.0f}", border=True)
    st.metric("Avg cycle", f"{row.avg_won_cycle_days:.0f} days", border=True)

st.caption(
    "Whole-warehouse view: `reporting.rpt_exec_overview` has one row and no "
    "office dimension, so nothing on this page is office-filterable. "
    "Office-level cuts live on Pipeline Health and Rep Scorecard."
)

trend = db.monthly_trend(())

col_left, col_right = st.columns(2)

with col_left, st.container(border=True):
    st.subheader("Won revenue by month")
    st.line_chart(trend, x="month_start", y="won_revenue", alt="Won revenue by month")

with col_right, st.container(border=True):
    st.subheader("Pipeline funnel")
    funnel = db.stage_funnel()
    st.bar_chart(
        funnel,
        x="deal_stage",
        y="opportunities",
        horizontal=True,
        alt="Opportunities by deal stage",
    )

with st.container(border=True):
    st.subheader("Office breakdown")
    office_df = db.revenue_by_office()
    office_df["win_rate_pct"] = 100 * office_df["won_count"] / office_df["closed_count"]
    st.dataframe(
        office_df[["regional_office", "opportunities", "won_revenue", "win_rate_pct"]],
        hide_index=True,
        width="stretch",
        column_config={
            "regional_office": "Office",
            "opportunities": st.column_config.NumberColumn("Opportunities", format="%d"),
            "won_revenue": st.column_config.NumberColumn("Won revenue", format="$%.0f"),
            "win_rate_pct": st.column_config.NumberColumn("Win rate", format="%.1f%%"),
        },
        alt="Revenue and win rate by regional office",
    )

st.caption(
    f"Coverage: {str(row.first_engage_date)[:10]} engage through "
    f"{str(row.snapshot_date)[:10]} close - {int(row.active_agents)} agents "
    f"with activity, {int(row.attributed_accounts)} accounts attributed. "
    f"{int(row.unattributed_opportunities):,} opportunities carry no account "
    "(16.19%) - see the Data Quality page."
)
