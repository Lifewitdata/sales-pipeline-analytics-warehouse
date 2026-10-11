"""Data quality page.

Two sources of truth, shown side by side on purpose:
- live warehouse checks (reporting.rpt_data_quality) - what the tested models
  find on the data as modelled, this build;
- extract-time profile (reports/source_profile.json) - the 18 static checks
  etl/profile_source.py ran against the bytes as landed, each with the SQL
  that produced it so any number can be re-derived.
"""

import json
from pathlib import Path

import streamlit as st

import db

PROFILE_JSON = Path(__file__).resolve().parent.parent.parent / "reports" / "source_profile.json"

flags = db.data_quality_flags()
completeness = db.opportunity_completeness().iloc[0]
repaired = db.product_repair_count()

with st.container(horizontal=True):
    st.metric("Checks firing", len(flags), border=True)
    st.metric("Error-severity rows", int(flags["severity"].eq("error").sum()), border=True)
    st.metric("Product labels repaired", f"{repaired:,}", border=True)
    st.metric("Missing account", f"{100 * completeness.missing_account / completeness.total_opportunities:.1f}%", border=True)
    st.metric("Open pipeline nulls", f"{int(completeness.open_pipeline):,}", border=True)

SEVERITY_COLOR = {"error": "red", "warning": "orange", "info": "blue"}

st.caption(
    "Warehouse-wide findings: they describe the source data as landed, so "
    "they carry no office dimension and are not filterable."
)

with st.container(border=True):
    st.subheader("Live warehouse findings")
    display = flags.copy()
    display["severity"] = display["severity"].map(
        lambda s: f":{SEVERITY_COLOR[s]}[{s}]"
    )
    st.markdown(
        "| Check | Severity | Finding | Rows |\n|---|---|---|---|\n"
        + "\n".join(
            f"| `{r.check_id}` | {r.severity} | {r.finding} | {r.flagged_rows:,} |"
            for r in display.itertuples()
        )
    )
    st.caption(
        "DQ-008 nulls are the open pipeline (2,089 = 500 Prospecting + 1,589 "
        "Engaging) and are never imputed. DQ-003 rows are repaired by a "
        "normalized join in the warehouse, not by editing source data."
    )

with st.container(border=True):
    st.subheader("Opportunity completeness")
    st.dataframe(
        {
            "field": ["account", "engage_date", "close_date"],
            "null_rows": [
                int(completeness.missing_account),
                int(completeness.missing_engage_date),
                int(completeness.open_pipeline),
            ],
            "share_of_8800": [
                100 * completeness.missing_account / completeness.total_opportunities,
                100 * completeness.missing_engage_date / completeness.total_opportunities,
                100 * completeness.open_pipeline / completeness.total_opportunities,
            ],
        },
        hide_index=True,
        width="stretch",
        column_config={
            "null_rows": st.column_config.NumberColumn("Null rows", format="%d"),
            "share_of_8800": st.column_config.NumberColumn("Share of rows", format="%.2f%%"),
        },
        alt="Null profile of the opportunity fact",
    )

with st.container(border=True):
    st.subheader("Extract-time profile")
    if PROFILE_JSON.exists():
        profile = json.loads(PROFILE_JSON.read_text())
        counts = profile["stage_counts"]
        st.markdown(
            f"{counts['checks_run']} checks run at extract time on "
            f"{counts['tables_profiled']} tables: "
            f":red[{counts['errors']} error], "
            f":orange[{counts['warnings']} warning], "
            f":green[{counts['passed']} pass]. "
            f"Generated {profile['generated_at'][:10]}."
        )
        for finding in profile["findings"]:
            if finding["severity"] in ("error", "warning"):
                with st.expander(
                    f":{SEVERITY_COLOR.get(finding['severity'], 'blue')}"
                    f"[{finding['severity']}] {finding['id']} - {finding['title']}"
                ):
                    st.markdown(finding["detail"])
                    st.code(finding["sql"], language="sql")
        st.caption(
            "Every finding carries the SQL that produced it, so the numbers "
            "on this page can be re-derived without trusting this app."
        )
    else:
        st.warning("reports/source_profile.json not found - run `python etl/profile_source.py`.")
