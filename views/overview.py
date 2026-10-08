"""Landing page: workload across modules and quick entry points."""
import json

import pandas as pd
import streamlit as st

from src import config
from src.live import store, tron
from views.common import analyst

st.title(":material/policy: Blockchain Forensics Platform")
st.caption(f"Signed in as **{analyst()}** · Tracing illicit crypto flows across Bitcoin, TRON/USDT, "
           "smart contracts and mobile money")

cases = store.cases()
open_cases = cases[cases["status"].isin(["Open", "Escalated"])]
meta_f = config.OUTPUT_DIR / "meta.json"
alerts = None
if meta_f.exists():
    scored = pd.read_csv(config.OUTPUT_DIR / "scored_test.csv", usecols=["band"])
    alerts = int((scored["band"] == "High").sum())

m = st.columns(4)
m[0].metric("Open cases", len(open_cases))
m[1].metric("High-risk open cases", int((open_cases["risk_band"] == "High").sum()))
m[2].metric("Watched wallets", len(store.watchlist()))
m[3].metric("Bitcoin high-risk alerts", alerts if alerts is not None else "-")

st.subheader("Start an investigation")
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("**:material/account_balance_wallet: TRON / USDT wallet**")
    with st.form("quick_tron", border=False):
        addr = st.text_input("Wallet address", placeholder="T…", label_visibility="collapsed")
        if st.form_submit_button("Investigate", type="primary"):
            if tron.valid_address(addr.strip()):
                st.session_state["tron_addr"] = addr.strip()
                st.switch_page("views/tron.py")
            st.error("Not a valid TRON address.")
with c2, st.container(border=True):
    st.markdown("**:material/data_object: Smart contract**")
    st.caption("Upload Solidity source and get a vulnerability report in seconds.")
    if st.button("Audit a contract"):
        st.switch_page("views/contracts.py")
c3, c4 = st.columns(2)
with c3, st.container(border=True):
    st.markdown("**:material/currency_bitcoin: Bitcoin alerts**")
    if meta_f.exists():
        meta = json.load(open(meta_f))
        st.caption(f"{meta['model']} graph model · alert precision target {meta['precision_target']:.0%}")
    if st.button("Review alerts"):
        st.switch_page("views/bitcoin.py")
with c4, st.container(border=True):
    st.markdown("**:material/phone_android: Mobile-money attribution**")
    st.caption("Match a P2P trader's statement to their on-chain cash-outs.")
    if st.button("Import a statement"):
        st.switch_page("views/mobile_money.py")

st.subheader("Recent activity")
recent = store.audit(limit=12)
if recent.empty:
    st.caption("Nothing yet.")
else:
    st.dataframe(recent[["ts_utc", "analyst", "action", "subject"]], hide_index=True, width="stretch")
