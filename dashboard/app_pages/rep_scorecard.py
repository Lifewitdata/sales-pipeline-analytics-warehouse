import streamlit as st

import db

all_offices = db.offices()
selected_offices = st.multiselect(
    "Regional office",
    all_offices,
    default=all_offices,
    key="rs_office_filter",
)
all_managers = db.managers()
selected_managers = st.multiselect(
    "Manager",
    all_managers,
    default=all_managers,
    key="manager_filter",
)
if not (selected_offices and selected_managers):
    st.caption("An empty selection applies no filter - the rows below span all offices or managers.")

score = db.rep_scorecard(tuple(selected_offices), tuple(selected_managers))

top = score[["agent_name", "total_revenue"]].sort_values(
    "total_revenue", ascending=False
).head(10)

col_left, col_right = st.columns(2)

with col_left, st.container(border=True):
    st.subheader("Top 10 agents by won revenue")
    st.bar_chart(top, x="agent_name", y="total_revenue", horizontal=True, alt="Top 10 agents by won revenue")

with col_right, st.container(border=True):
    st.subheader("Win rate vs volume")
    st.scatter_chart(
        score,
        x="total_opportunities",
        y="win_rate",
        color="regional_office",
        size="total_revenue",
        alt="Agent win rate against opportunity volume",
    )

with st.container(border=True):
    st.subheader("Full scorecard")
    score["win_rate_pct"] = 100 * score["win_rate"]
    st.dataframe(
        score.drop(columns=["win_rate", "sales_agent_key"]),
        hide_index=True,
        width="stretch",
        column_config={
            "revenue_rank": st.column_config.NumberColumn("Rank", format="%d"),
            "total_revenue": st.column_config.NumberColumn("Won revenue", format="$%.0f"),
            "win_rate_pct": st.column_config.NumberColumn("Win rate", format="%.1f%%"),
            "avg_won_deal_size": st.column_config.NumberColumn("Avg won deal", format="$%.0f"),
            "avg_won_cycle_days": st.column_config.NumberColumn("Avg cycle (days)", format="%.1f"),
            "open_pipeline_count": st.column_config.NumberColumn("Open pipeline", format="%d"),
        },
        alt="Sales agent scorecard",
    )

st.caption(
    "Revenue ranks agents on Won close_value only. Win rate is closed-deal "
    "(won / (won + lost)); open pipeline carried per agent is a count, not a "
    "value. Rank is computed company-wide in the reporting view, so filtering "
    "can leave gaps in the numbering. Definitions: docs/METRIC_DEFINITIONS.md."
)
