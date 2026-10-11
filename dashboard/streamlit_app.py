"""Sales Pipeline Analytics - Streamlit dashboard over the dbt warehouse.

Run from this directory:
    streamlit run streamlit_app.py

Every number on screen comes from a dbt-tested mart or reporting view; this
app never reads the raw schema. Filters are page-level, not global: only the
views that carry a regional_office column can honour one, so a control appears
only where it changes every figure beneath it.
"""

import streamlit as st

st.set_page_config(
    page_title="Sales Pipeline Analytics",
    page_icon=":material/dashboard:",
    layout="wide",
)

with st.sidebar:
    st.caption(
        "Source: Maven Analytics CRM Sales Opportunities (8,800 opportunities, "
        "2016-10 to 2017-12). Warehouse: dbt + DuckDB, 67 passing models/tests."
    )
    st.divider()
    st.caption(
        "Metric definitions: docs/METRIC_DEFINITIONS.md. Every figure on these "
        "pages is produced by a model or test that `dbt build` passes."
    )

page = st.navigation(
    [
        st.Page("app_pages/exec_overview.py", title="Exec Overview", icon=":material/dashboard:"),
        st.Page("app_pages/pipeline_health.py", title="Pipeline Health", icon=":material/query_stats:"),
        st.Page("app_pages/rep_scorecard.py", title="Rep Scorecard", icon=":material/groups:"),
        st.Page("app_pages/data_quality.py", title="Data Quality", icon=":material/fact_check:"),
    ],
    position="top",
)

st.title(page.title, icon=page.icon)

page.run()
