"""Live Ethereum wallet and contract investigation."""
import json

import pandas as pd
import streamlit as st

from src.live import contracts, crosschain, ethereum, flows, store
from views.common import (analyst, attach_to_case, band_badge, compact, lead_notice, need, open_case_button,
                          page_header, short, trace_dot)

page_header("Investigate · Ethereum", "Ethereum wallet investigation",
            "Enter any Ethereum address to analyse its USDT, USDC and ETH activity, check public labels "
            "(sanctions, mixers, frozen addresses, exchanges), follow the money and audit deployed contracts.",
            {"Source": "live Ethereum (Blockscout)", "Assets": "USDT · USDC · ETH"})


@st.cache_data(ttl=300, show_spinner=False)
def load(address, n):
    return ethereum.fetch_transfers(address, max_transfers=n), ethereum.fetch_account(address)


@st.cache_data(ttl=300, show_spinner=False)
def load_trace(address, hops, top_k, direction, labels):
    G, errors = ethereum.trace(address, hops=hops, top_k=top_k, direction=direction, labels=labels)
    return {"nodes": dict(G.nodes(data=True)), "edges": list(G.edges(data=True))}, errors


@st.cache_data(ttl=3600, show_spinner=False)
def twin(address):
    return crosschain.same_key(address)


with st.form("lookup"):
    c1, c2 = st.columns([4, 1])
    address = c1.text_input("Address", value=st.session_state.get("eth_addr", ""), placeholder="0x… (42 characters)").strip()
    depth = c2.selectbox("History", [100, 300, 1000], index=1, format_func=lambda n: f"last {n:,} transfers")
    go = st.form_submit_button("Investigate", type="primary", icon=":material/search:")
if go:
    st.session_state["eth_addr"] = address
address = st.session_state.get("eth_addr", "").lower()
if not address:
    st.info("Enter an Ethereum address. Try a public sanctioned example: the Tornado Cash donation address "
            "`0x8589427373D6D84E98730D7795D8f6f8731FDA16`.")
    st.stop()
if not ethereum.valid_address(address):
    st.error("That is not a valid Ethereum address (0x followed by 40 hex characters).")
    st.stop()

with st.spinner("Fetching transfers from Ethereum…"):
    try:
        tx, account = load(address, depth)
    except ethereum.EthError as e:
        st.error(str(e))
        st.stop()
labels = tx.attrs.get("labels", {})
s = flows.summarise(address, tx)
cp = flows.counterparties(tx)
cp["labels"] = cp["counterparty"].map(lambda a: ", ".join(labels.get(a, [])[:3]))
ind = ethereum.risk_indicators(address, s, cp, account, labels)
score = flows.risk_score(ind)
band = ethereum.band(score)
kind = "contract" if account["is_contract"] else "wallet"
entity_id = store.eid("eth", address)
if go or store.entity(entity_id) is None:
    store.log(analyst(), "ethereum lookup", module="eth", subject=address, detail=f"{len(tx)} transfers")
    flows.record(analyst(), "eth", address, tx, score, band, ind, module="eth", asset="USD", kind=kind,
                 label=", ".join(account["labels"][:2]) or None)

h1, h2 = st.columns([3, 1])
h1.subheader(address)
with h2:
    band_badge(band, score)
if account["labels"]:
    st.markdown(" ".join(f":orange-badge[{l}]" if any(w in l.lower() for w in ("ofac", "sanction", "blocked", "tornado", "mixer"))
                         else f":gray-badge[{l}]" for l in account["labels"][:8]))
if not account["exists"]:
    st.warning("This address has no activity on Ethereum.")

m = st.columns(6)
m[0].metric("Risk score", f"{score}/100")
m[1].metric("In (USD)", compact(s.get("usdt_in", 0)), f"{s.get('in_count', 0):,} transfers", delta_color="off", delta_arrow="off")
m[2].metric("Out (USD)", compact(s.get("usdt_out", 0)), f"{s.get('out_count', 0):,} transfers", delta_color="off", delta_arrow="off")
m[3].metric("Counterparties", f"{s.get('senders', 0) + s.get('receivers', 0):,}")
m[4].metric("Pass-through", f"{s.get('pass_through', 0):.0%}")
m[5].metric("ETH", compact(account["eth_balance"]), help=f"{account['eth_balance']:,.4f} ETH")
try:
    t = twin(address)
    if t and t["active"]:
        st.info(f":material/link: **Same key on TRON:** `{t['twin']}` is {t['activity']}. One private key controls both "
                "addresses, so the same owner holds them.", icon=":material/key:")
except Exception:
    pass
if not tx.empty:
    st.caption(f"Analysed {s['transfers']:,} stablecoin and ETH transfers, {s['first_seen']:%d %b %Y} → "
               f"{s['last_seen']:%d %b %Y} UTC. USD values: stablecoins at face value, ETH at today's price.")
lead_notice()

tabs = st.tabs(["Risk indicators", "Fund flow trace", "Counterparties", "Transfers"] + (["Contract audit"] if account["is_contract"] else []))
with tabs[0]:
    if not ind:
        st.success("No risk indicators triggered on the analysed activity.")
    for pts, name, why in sorted(ind, key=lambda x: -x[0]):
        st.markdown(f"**{name}**  ·  +{pts}" if pts else f"**{name}**  ·  context")
        st.caption(why)
    c1, c2, c3 = st.columns(3)
    with c1:
        open_case_button("eth", address, f"Ethereum {kind} {short(address)}", score, band,
                         summary="; ".join(n for _, n, _ in ind), evidence={"summary": s, "indicators": ind,
                                                                            "labels": account["labels"]},
                         entity_id=entity_id)
    with c2:
        with st.popover("Add to watchlist", icon=":material/visibility:", disabled=not need("watch", "edit the watchlist")):
            label = st.text_input("Reason", key="ewl_label")
            source = st.text_input("Source / reference", key="ewl_src")
            if st.button("Save to watchlist", key="ewl_save"):
                try:
                    store.watch(analyst(), address, label, source)
                    st.cache_data.clear()
                    st.success("Added.")
                except ValueError as e:
                    st.error(str(e))
    with c3:
        report = {"address": address, "risk_score": score, "risk_band": band, "labels": account["labels"], "summary": s,
                  "indicators": [{"points": p, "name": n, "reason": w} for p, n, w in ind],
                  "top_counterparties": cp.head(20).to_dict("records"), "analyst": analyst()}
        st.download_button("Export report (JSON)", json.dumps(report, default=str, indent=1), f"eth_{address}.json",
                           "application/json", icon=":material/download:")

with tabs[1]:
    c1, c2, c3 = st.columns(3)
    direction = c1.radio("Follow funds", ["out", "in"], horizontal=True, key="eth_dir",
                         format_func=lambda d: "Forward (where it went)" if d == "out" else "Backward (where it came from)")
    hops = c2.slider("Hops", 1, 3, 2, key="eth_hops")
    top_k = c3.slider("Largest counterparties per wallet", 2, 5, 3, key="eth_topk")
    if st.button("Trace", icon=":material/account_tree:", key="eth_trace_btn"):
        with st.spinner("Following the money (a few seconds per wallet)…"):
            st.session_state["eth_trace"] = (address, direction, *load_trace(address, hops, top_k, direction, labels))
        store.log(analyst(), f"ethereum trace {direction} {hops} hops", module="eth", subject=address)
        flows.record_trace(analyst(), "eth", st.session_state["eth_trace"][2], asset="USD", module="eth")
    t = st.session_state.get("eth_trace")
    if t and t[0] == address and t[1] == direction:
        graph, errors = t[2], t[3]
        st.graphviz_chart(trace_dot(graph, address, unit="USD"), width="content")
        edges = pd.DataFrame([{"from": a, "to": b, "usd": d["usdt"], "transfers": d["n"]} for a, b, d in graph["edges"]])
        st.dataframe(edges, hide_index=True)
        for e in errors:
            st.caption(f"Could not fetch {e}")
        st.caption("Yellow = exchange, bridge, mixer or large service: not traced through (use Cross-chain tracing).")
        attach_to_case([store.eid("eth", n) for n in graph["nodes"] if n != address], key="eth-trace",
                       label="Attach traced wallets")
    else:
        st.caption("Press Trace to follow the largest flows across wallets.")

with tabs[2]:
    st.dataframe(cp, hide_index=True, width="stretch", column_config={
        "sent_to_it": st.column_config.NumberColumn("Sent to it (USD)", format="%.2f"),
        "received_from_it": st.column_config.NumberColumn("Received from it (USD)", format="%.2f"),
        "volume": st.column_config.NumberColumn("Total (USD)", format="%.2f"), "labels": "Public labels"})
    pick = st.selectbox("Investigate a counterparty", [""] + list(cp["counterparty"].head(50)), key="eth_pick")
    if pick and st.button("Open this address", icon=":material/arrow_forward:", key="eth_open"):
        st.session_state["eth_addr"] = pick
        st.rerun()

with tabs[3]:
    if tx.empty:
        st.info("No stablecoin or ETH transfers found.")
    else:
        view = tx.assign(link="https://eth.blockscout.com/tx/" + tx["tx_id"])
        st.dataframe(view[["ts", "direction", "asset", "amount_native", "amount", "counterparty", "link"]], hide_index=True,
                     width="stretch", column_config={
                         "ts": st.column_config.DatetimeColumn("Time (UTC)"),
                         "amount_native": st.column_config.NumberColumn("Amount", format="%.4f"),
                         "amount": st.column_config.NumberColumn("USD", format="%.2f"),
                         "link": st.column_config.LinkColumn("Transaction", display_text=r".*/tx/(.{12}).*")})
        st.download_button("Download transfers (CSV)", tx.to_csv(index=False), f"eth_{address}_transfers.csv", "text/csv")

if account["is_contract"]:
    with tabs[4]:
        if not account["is_verified"]:
            st.warning("This contract's source code is not verified on Blockscout, so it cannot be analysed from source.")
        elif st.button("Audit deployed contract", type="primary", icon=":material/bug_report:"):
            with st.spinner("Fetching verified source and running Slither…"):
                try:
                    files, main, version, name = ethereum.contract_source(address)
                    r = contracts.scan_files(files, main, solc_version=version, address=address)
                except ethereum.EthError as e:
                    r = {"error": str(e)}
            st.session_state["eth_scan"] = (address, r)
            if not r.get("error"):
                cs, cb = contracts.risk(r["findings"])
                store.upsert_entity(analyst(), "eth", address, kind="contract", label=name, module="contract",
                                    risk_score=cs, risk_band=cb,
                                    reasons=sorted({f["check"] for f in r["findings"] if f["in_main"] and f["severity"] in ("High", "Medium")}))
            store.log(analyst(), "deployed contract scan", module="contract", subject=address,
                      detail=r.get("error") or f"sha256 {r['sha256'][:16]}, {len(r['findings'])} findings")
        sc = st.session_state.get("eth_scan")
        if sc and sc[0] == address:
            r = sc[1]
            if r.get("error"):
                st.error(r["error"])
            else:
                cs, cb = contracts.risk(r["findings"])
                band_badge(cb, cs)
                own = [f for f in r["findings"] if f["in_main"]]
                st.caption(f"{r['files']} source files · solc {r['solc']} · {len(own)} findings in the contract's own file, "
                           f"{len(r['findings']) - len(own)} in imported libraries · SHA-256 {r['sha256'][:16]}…")
                only_main = st.toggle("Only the contract's own file", value=True)
                shown = [f for f in r["findings"] if (f["in_main"] or not only_main) and f["severity"] in ("High", "Medium")]
                st.dataframe(pd.DataFrame(shown, columns=["severity", "check", "file", "lines", "description"]),
                             hide_index=True, width="stretch")
