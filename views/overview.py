"""Landing page: workload across modules and quick entry points."""
import json

import pandas as pd
import streamlit as st

from src import config
from src.live import store
from views.common import analyst, page_header, role

page_header("Investigation platform", "Tracing illicit crypto flows to the people behind them",
            "Live wallet tracing on TRON, Ethereum and Bitcoin, cross-chain links, smart-contract audit and mobile-money "
            "attribution, all feeding one entity graph, one case workspace and a tamper-evident audit trail.",
            {"Signed in as": f"{analyst()} ({role()})", "Chains": "TRON · Ethereum · Bitcoin",
             "Assets": "USDT · USDC · ETH · BTC"})

cases = store.cases()
open_cases = cases[cases["status"].isin(["Open", "Escalated"])]
meta_f = config.OUTPUT_DIR / "meta.json"
alerts = None
if meta_f.exists():
    scored = pd.read_csv(config.OUTPUT_DIR / "scored_test.csv", usecols=["band"])
    alerts = int((scored["band"] == "High").sum())

n_ent, n_link = store.graph_stats()
m = st.columns(5)
m[0].metric("Open cases", len(open_cases))
m[1].metric("High-risk open cases", int((open_cases["risk_band"] == "High").sum()))
m[2].metric("Entities in graph", f"{sum(n_ent.values()):,}", f"{sum(n_link.values()):,} links", delta_color="off", delta_arrow="off")
m[3].metric("Watched wallets", len(store.watchlist()))
m[4].metric("Bitcoin model alerts", alerts if alerts is not None else "-")

with st.form("quick_any"):
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    addr = c1.text_input("Investigate any address", key="any_addr", placeholder="TRON T…, Ethereum 0x… or Bitcoin bc1… / 1… / 3…")
    if c2.form_submit_button("Investigate", type="primary", icon=":material/search:"):
        chain = store.chain_of(addr)
        if chain:
            key, page = {"tron": ("tron_addr", "views/tron.py"), "eth": ("eth_addr", "views/ethereum.py"),
                         "btc": ("btc_addr", "views/btc_live.py")}[chain]
            st.session_state[key] = addr.strip()
            st.switch_page(page)
        st.error("Not a TRON, Ethereum or Bitcoin address.")

st.subheader("Start an investigation")
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("**:material/swap_horiz: Cross-chain tracing**")
    st.caption("Same-key twins on TRON and Ethereum, and funds hopping between TRON, Ethereum and Bitcoin.")
    if st.button("Trace across chains"):
        st.switch_page("views/crosschain.py")
with c2, st.container(border=True):
    st.markdown("**:material/data_object: Smart contract**")
    st.caption("Upload Solidity source or give a deployed Ethereum contract address; findings in seconds.")
    if st.button("Audit a contract"):
        st.switch_page("views/contracts.py")
c3, c4 = st.columns(2)
with c3, st.container(border=True):
    st.markdown("**:material/hub: Bitcoin graph model**")
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
    recent = recent.assign(ts_utc=pd.to_datetime(recent["ts_utc"]), subject=recent["subject"].fillna(""))
    st.dataframe(recent[["ts_utc", "analyst", "action", "subject"]], hide_index=True, width="stretch",
                 column_config={"ts_utc": st.column_config.DatetimeColumn("Time (UTC)", format="D MMM YYYY, HH:mm"),
                                "analyst": "Analyst", "action": "Action", "subject": "Subject"})
