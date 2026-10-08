"""Append-only audit trail of everything investigators do on the platform."""
import streamlit as st

from src.live import store
from views.common import page_header

page_header("Casework · Audit", "Audit log", "Every sign-in, lookup, scan, case change and decision, with who did it and when (UTC).")

log = store.audit(limit=2000)
c1, c2 = st.columns(2)
who = c1.multiselect("Analyst", sorted(log["analyst"].unique()))
what = c2.text_input("Filter action or subject")
if who:
    log = log[log["analyst"].isin(who)]
if what:
    m = log["action"].str.contains(what, case=False, na=False) | log["subject"].fillna("").str.contains(what, case=False)
    log = log[m]
st.dataframe(log, hide_index=True, width="stretch")
st.download_button("Download (CSV)", log.to_csv(index=False), "audit_log.csv", "text/csv", icon=":material/download:")
