"""Recommended Interventions — 'then a recommended intervention.'

Rule engine (lib.interventions) flags issues for the latest month, syncs
them to the scm_interventions Lakebase table (idempotent), and this page
renders the pending queue with an Accept/Reject human-in-the-loop form.
Every decision is an audit-ledger write — no downstream action dispatch.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

import pandas as pd
import streamlit as st

import databricks_client as dbx
import interventions as iv

st.set_page_config(page_title="Recommended Interventions — Akzo SCM", layout="wide")

st.title("Recommended Interventions")
st.caption("Rule-flagged issues for the latest month — review, then accept or reject.")

try:
    candidates = iv.scan_latest_month()
    inserted = iv.sync_to_lakebase(candidates)
    if inserted:
        st.toast(f"{inserted} new intervention(s) added to the queue.")
except Exception as e:
    st.error(f"Could not run the rule scan: {e}")

st.subheader("Pending queue")
try:
    pending = iv.list_interventions(status="pending")
except Exception as e:
    st.error(f"Could not load the pending queue: {e}")
    pending = []

if not pending:
    st.success("No pending interventions — all clear.")
else:
    default_user = dbx.current_user()
    for row in pending:
        severity = row["severity"]
        header = f"{severity} — {row['issue_type']} — {row['month']}"
        if row.get("lane"):
            header += f" — {row['lane']}"
        if row.get("plant"):
            header += f" — {row['plant']}"
        if row.get("sku"):
            header += f" / {row['sku']}"
        if row.get("region") and not row.get("lane"):
            header += f" — {row['region']}"

        with st.container(border=True):
            st.markdown(f"**{header}**")
            st.write(row["rationale"])
            st.markdown(f"*Recommendation:* {row['recommendation']}")

            with st.form(key=f"intervention_{row['intervention_id']}"):
                decided_by = st.text_input("Decided by", value=default_user, key=f"by_{row['intervention_id']}")
                col_accept, col_reject = st.columns(2)
                accept = col_accept.form_submit_button("Accept")
                reject = col_reject.form_submit_button("Reject")

                if accept or reject:
                    status = "accepted" if accept else "rejected"
                    try:
                        iv.decide(row["intervention_id"], status, decided_by)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not record decision: {e}")

st.divider()

with st.expander("Decision history"):
    try:
        history = [
            r for r in iv.list_interventions() if r["status"] in ("accepted", "rejected")
        ]
    except Exception as e:
        st.error(f"Could not load history: {e}")
        history = []
    if history:
        st.dataframe(pd.DataFrame(history), use_container_width=True)
    else:
        st.write("No decisions recorded yet.")
