"""Wallet watchlist: victim-reported, sanctioned or case-linked wallets."""
import pandas as pd
import streamlit as st

from src.live import store, tron
from views.common import analyst

st.title(":material/visibility: Watchlist")
st.caption("Wallets on this list raise the risk of every wallet that transacts with them, and are highlighted in traces.")

with st.form("add", clear_on_submit=True):
    c1, c2, c3 = st.columns([3, 2, 2])
    addr = c1.text_input("TRON address")
    label = c2.text_input("Reason", placeholder="victim-reported scam wallet")
    source = c3.text_input("Source / reference", placeholder="report or case number")
    if st.form_submit_button("Add", icon=":material/add:"):
        if not tron.valid_address(addr.strip()):
            st.error("Not a valid TRON address.")
        else:
            try:
                store.watch(analyst(), addr, label, source)
                st.cache_data.clear()
                st.success("Added.")
            except ValueError as e:
                st.error(str(e))

with st.expander("Bulk import (CSV with columns address, label, source)"):
    up = st.file_uploader("CSV", type=["csv"], label_visibility="collapsed")
    if up and st.button("Import"):
        df = pd.read_csv(up)
        ok = 0
        for r in df.itertuples():
            if tron.valid_address(str(r.address).strip()) and str(r.label).strip():
                store.watch(analyst(), str(r.address), str(r.label), str(getattr(r, "source", "") or ""))
                ok += 1
        st.cache_data.clear()
        st.success(f"Imported {ok} of {len(df)} rows.")

wl = store.watchlist()
st.metric("Watched wallets", len(wl))
if wl.empty:
    st.stop()
st.dataframe(wl, hide_index=True, width="stretch")
c1, c2 = st.columns(2)
pick = c1.selectbox("Wallet", wl["address"])
if c2.button("Investigate", icon=":material/arrow_forward:"):
    st.session_state["tron_addr"] = pick
    st.switch_page("views/tron.py")
if c2.button("Remove from watchlist", icon=":material/delete:"):
    store.unwatch(analyst(), pick)
    st.cache_data.clear()
    st.rerun()
