"""Live Bitcoin address investigation."""
import json

import pandas as pd
import streamlit as st

from src.live import bitcoin_live as btc
from src.live import flows, store
from views.common import (analyst, attach_to_case, band_badge, compact, lead_notice, need, open_case_button,
                          page_header, short, trace_dot)

page_header("Investigate · Bitcoin", "Bitcoin address investigation",
            "Enter any Bitcoin address to analyse its live activity, detect mixing (CoinJoin), score risk and "
            "follow the money. The graph model under Bitcoin transactions scores the Elliptic research dataset.",
            {"Source": "live Bitcoin (mempool.space)", "Values": "BTC and USD at the day's price"})


@st.cache_data(ttl=300, show_spinner=False)
def load(address, n):
    return btc.fetch_transfers(address, max_transfers=n), btc.fetch_account(address)


@st.cache_data(ttl=300, show_spinner=False)
def load_trace(address, hops, top_k, direction):
    G, errors = btc.trace(address, hops=hops, top_k=top_k, direction=direction)
    return {"nodes": dict(G.nodes(data=True)), "edges": list(G.edges(data=True))}, errors


with st.form("lookup"):
    c1, c2 = st.columns([4, 1])
    address = c1.text_input("Address", value=st.session_state.get("btc_addr", ""), placeholder="bc1… / 1… / 3…").strip()
    depth = c2.selectbox("History", [50, 100, 300], index=1, format_func=lambda n: f"last {n} transactions")
    go = st.form_submit_button("Investigate", type="primary", icon=":material/search:")
if go:
    st.session_state["btc_addr"] = address
address = st.session_state.get("btc_addr", "")
if not address:
    st.info("Enter a Bitcoin address. The platform fetches its transactions, values them in USD, checks for "
            "CoinJoin mixing and watchlisted counterparties, and traces funds forward and backward.")
    st.stop()
if not btc.valid_address(address):
    st.error("That is not a valid Bitcoin address.")
    st.stop()

with st.spinner("Fetching transactions from the Bitcoin blockchain…"):
    try:
        tx, account = load(address, depth)
    except btc.BtcError as e:
        st.error(str(e))
        st.stop()
coinjoins = tx.attrs.get("coinjoins", [])
s = flows.summarise(address, tx)
cp = flows.counterparties(tx)
ind = btc.risk_indicators(address, s, cp, coinjoins)
score = flows.risk_score(ind)
band = btc.band(score)
entity_id = store.eid("btc", address)
if go or store.entity(entity_id) is None:
    store.log(analyst(), "bitcoin address lookup", module="btc", subject=address, detail=f"{len(tx)} transfers")
    flows.record(analyst(), "btc", address, tx, score, band, ind, module="btc", asset="USD")

h1, h2 = st.columns([3, 1])
h1.subheader(address)
with h2:
    band_badge(band, score)
if not account["exists"]:
    st.warning("This address has no confirmed transactions.")
    st.stop()
m = st.columns(6)
m[0].metric("Risk score", f"{score}/100")
m[1].metric("In (USD)", compact(s.get("usdt_in", 0)), f"{s.get('in_count', 0):,} transfers", delta_color="off", delta_arrow="off")
m[2].metric("Out (USD)", compact(s.get("usdt_out", 0)), f"{s.get('out_count', 0):,} transfers", delta_color="off", delta_arrow="off")
m[3].metric("Transactions", f"{account['tx_count']:,}")
m[4].metric("CoinJoins", len(coinjoins))
m[5].metric("Balance", f"{account['balance_btc']:.4f} BTC")
if not tx.empty:
    st.caption(f"Analysed {len(set(tx['tx_id'])):,} transactions, {s['first_seen']:%d %b %Y} → {s['last_seen']:%d %b %Y} UTC.")
lead_notice()

t_risk, t_flow, t_cp, t_tx = st.tabs(["Risk indicators", "Fund flow trace", "Counterparties", "Transfers"])
with t_risk:
    if not ind:
        st.success("No risk indicators triggered on the analysed activity.")
    for pts, name, why in sorted(ind, key=lambda x: -x[0]):
        st.markdown(f"**{name}**  ·  +{pts}" if pts else f"**{name}**  ·  context")
        st.caption(why)
    if coinjoins:
        st.markdown("**CoinJoin transactions**")
        st.dataframe(pd.DataFrame({"txid": coinjoins, "link": ["https://mempool.space/tx/" + c for c in coinjoins]}),
                     hide_index=True, column_config={"link": st.column_config.LinkColumn("Explorer")})
    c1, c2, c3 = st.columns(3)
    with c1:
        open_case_button("btc", address, f"Bitcoin address {short(address)}", score, band,
                         summary="; ".join(n for _, n, _ in ind), evidence={"summary": s, "indicators": ind},
                         entity_id=entity_id)
    with c2:
        with st.popover("Add to watchlist", icon=":material/visibility:", disabled=not need("watch", "edit the watchlist")):
            label = st.text_input("Reason", key="bwl_label")
            source = st.text_input("Source / reference", key="bwl_src")
            if st.button("Save to watchlist", key="bwl_save"):
                try:
                    store.watch(analyst(), address, label, source)
                    st.cache_data.clear()
                    st.success("Added.")
                except ValueError as e:
                    st.error(str(e))
    with c3:
        report = {"address": address, "risk_score": score, "risk_band": band, "summary": s, "coinjoins": coinjoins,
                  "indicators": [{"points": p, "name": n, "reason": w} for p, n, w in ind], "analyst": analyst()}
        st.download_button("Export report (JSON)", json.dumps(report, default=str, indent=1), f"btc_{address}.json",
                           "application/json", icon=":material/download:")

with t_flow:
    c1, c2, c3 = st.columns(3)
    direction = c1.radio("Follow funds", ["out", "in"], horizontal=True, key="btc_dir",
                         format_func=lambda d: "Forward (where it went)" if d == "out" else "Backward (where it came from)")
    hops = c2.slider("Hops", 1, 3, 2, key="btc_hops")
    top_k = c3.slider("Largest counterparties per address", 2, 5, 3, key="btc_topk")
    if st.button("Trace", icon=":material/account_tree:", key="btc_trace_btn"):
        with st.spinner("Following the money…"):
            st.session_state["btc_trace"] = (address, direction, *load_trace(address, hops, top_k, direction))
        store.log(analyst(), f"bitcoin trace {direction} {hops} hops", module="btc", subject=address)
        flows.record_trace(analyst(), "btc", st.session_state["btc_trace"][2], asset="USD", module="btc")
    t = st.session_state.get("btc_trace")
    if t and t[0] == address and t[1] == direction:
        graph, errors = t[2], t[3]
        st.graphviz_chart(trace_dot(graph, address, unit="USD"), width="content")
        for e in errors:
            st.caption(f"Could not fetch {e}")
        st.caption("Yellow = likely exchange or service: not traced through.")
        attach_to_case([store.eid("btc", n) for n in graph["nodes"] if n != address], key="btc-trace",
                       label="Attach traced addresses")
    else:
        st.caption("Press Trace to follow the largest flows across addresses.")

with t_cp:
    st.dataframe(cp, hide_index=True, width="stretch", column_config={
        "sent_to_it": st.column_config.NumberColumn("Sent to it (USD)", format="%.2f"),
        "received_from_it": st.column_config.NumberColumn("Received from it (USD)", format="%.2f"),
        "volume": st.column_config.NumberColumn("Total (USD)", format="%.2f")})
    pick = st.selectbox("Investigate a counterparty", [""] + list(cp["counterparty"].head(50)), key="btc_pick")
    if pick and st.button("Open this address", icon=":material/arrow_forward:", key="btc_open"):
        st.session_state["btc_addr"] = pick
        st.rerun()

with t_tx:
    view = tx.assign(link="https://mempool.space/tx/" + tx["tx_id"])
    st.dataframe(view[["ts", "direction", "amount_native", "amount", "counterparty", "link"]], hide_index=True, width="stretch",
                 column_config={"ts": st.column_config.DatetimeColumn("Time (UTC)"),
                                "amount_native": st.column_config.NumberColumn("BTC", format="%.8f"),
                                "amount": st.column_config.NumberColumn("USD", format="%.2f"),
                                "link": st.column_config.LinkColumn("Transaction", display_text=r".*/tx/(.{12}).*")})
    st.download_button("Download transfers (CSV)", tx.to_csv(index=False), f"btc_{address}_transfers.csv", "text/csv")
