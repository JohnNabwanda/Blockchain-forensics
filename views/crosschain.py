"""Cross-chain tracing: link a case's wallets across TRON, Ethereum and Bitcoin."""
import pandas as pd
import streamlit as st

from src.live import crosschain, store
from views.common import CHAIN_TAG, analyst, dot, lead_notice, need, page_header, short

page_header("Investigate · Cross-chain", "Cross-chain tracing",
            "Follow funds that move between TRON, Ethereum and Bitcoin. Finds addresses controlled by the same key on "
            "TRON and Ethereum, and matches money leaving one chain with money arriving on another by amount and time.",
            {"Chains": "TRON · Ethereum · Bitcoin", "Window": f"{crosschain.MAX_HOURS} h",
             "Fee tolerance": f"{crosschain.TOLERANCE:.0%} + ${crosschain.FIXED_FEE_USD:.0f}"})


@st.cache_data(ttl=600, show_spinner=False)
def run(wallets_key):
    wallets = {c: list(a) for c, a in wallets_key}
    return crosschain.run(wallets)


cases = store.cases(status=["Open", "Escalated"])
case_id = st.selectbox("Case (optional)", [None] + list(cases["id"]),
                       format_func=lambda i: "No case: enter wallets below" if i is None
                       else f"#{i} · {cases.set_index('id').loc[i, 'title']}")
pre = {"tron": [], "eth": [], "btc": []}
if case_id:
    ce = store.case_entities(int(case_id))
    for r in ce.itertuples():
        if r.chain in pre and r.kind != "service":
            pre[r.chain].append(r.address)

with st.form("wallets"):
    c1, c2, c3 = st.columns(3)
    t = c1.text_area("TRON wallets", "\n".join(pre["tron"][:8]), height=120, placeholder="T…")
    e = c2.text_area("Ethereum wallets", "\n".join(pre["eth"][:8]), height=120, placeholder="0x…")
    b = c3.text_area("Bitcoin addresses", "\n".join(pre["btc"][:8]), height=120, placeholder="bc1…")
    go = st.form_submit_button("Trace across chains", type="primary", icon=":material/swap_horiz:")

parse = lambda txt: sorted({x.strip() for x in txt.replace(",", "\n").splitlines() if x.strip()})
wallets = {"tron": parse(t), "eth": [a.lower() for a in parse(e)], "btc": parse(b)}
bad = [a for c, xs in wallets.items() for a in xs if store.chain_of(a) != c]
if go:
    if bad:
        st.error("Not valid for their chain: " + ", ".join(bad))
        st.stop()
    if sum(map(len, wallets.values())) == 0:
        st.error("Enter at least one wallet.")
        st.stop()
    st.session_state["xc"] = (tuple((c, tuple(a)) for c, a in wallets.items() if a), case_id)
    store.log(analyst(), "cross-chain trace", case_id, "crosschain",
              detail=", ".join(f"{len(a)} {c}" for c, a in wallets.items() if a))

if "xc" not in st.session_state:
    st.info("Pick a case to load its wallets, or enter wallets on any of the three chains. One wallet is enough for the "
            "same-key check; hop matching needs wallets on at least two chains.")
    st.stop()

key, run_case = st.session_state["xc"]
with st.spinner("Fetching flows on each chain and matching…"):
    twins, hops, errors = run(key)
for err in errors:
    st.caption(f":material/warning: {err}")
lead_notice()

st.subheader("Same key on TRON and Ethereum")
if twins:
    tw = pd.DataFrame(twins)
    st.dataframe(tw[["chain", "address", "twin_chain", "twin", "active", "activity"]], hide_index=True, width="stretch",
                 column_config={"active": st.column_config.CheckboxColumn("Twin active")})
    active = tw[tw["active"]]
    if len(active):
        st.success(f"{len(active)} address(es) have an active twin: the same private key controls both. Add the twin "
                   "to the case and investigate it on its chain.")
    else:
        st.caption("No twin is active: these keys have only been used on one chain.")
else:
    st.caption("Enter a TRON or Ethereum wallet to run the same-key check.")

st.subheader("Matched hops between chains")
if hops.empty:
    st.info("No outflow on one chain matched an inflow on another within the window and fee tolerance.")
else:
    levels = st.multiselect("Confidence", ["High", "Medium", "Low"], default=["High", "Medium"])
    shown = hops[hops["confidence"].isin(levels or ["High", "Medium", "Low"])]
    st.dataframe(shown[["confidence", "score", "from_chain", "from_wallet", "out_usd", "out_ts", "out_via", "to_chain",
                        "to_wallet", "in_usd", "in_ts", "in_via", "gap_h", "diff_pct", "out_tx", "in_tx"]],
                 hide_index=True, width="stretch", column_config={
                     "out_usd": st.column_config.NumberColumn("Left (USD)", format="%.2f"),
                     "in_usd": st.column_config.NumberColumn("Arrived (USD)", format="%.2f"),
                     "gap_h": st.column_config.NumberColumn("Hours later", format="%.1f"),
                     "diff_pct": st.column_config.NumberColumn("Less (%)", format="%.2f"),
                     "out_ts": st.column_config.DatetimeColumn("Left (UTC)"),
                     "in_ts": st.column_config.DatetimeColumn("Arrived (UTC)")})
    st.caption("Each hop is a lead: confirm it with the bridge's or exchange's records (deposit and withdrawal logs) "
               "under lawful request before relying on it.")

# picture of the result
nodes, edges = {}, []
for c, xs in key:
    for a in xs:
        nodes[store.eid(c, a)] = {"label": f"{CHAIN_TAG[c]} {short(a)}", "root": True}
for tw_ in twins:
    if tw_["active"]:
        a, b2 = store.eid(tw_["chain"], tw_["address"]), store.eid(tw_["twin_chain"], tw_["twin"])
        nodes.setdefault(b2, {"label": f"{CHAIN_TAG[tw_['twin_chain']]} {short(tw_['twin'])}", "sub": "same-key twin"})
        edges.append((a, b2, {"label": "same key", "style": "dashed", "color": "violet", "width": 2}))
for h in hops.itertuples() if len(hops) else []:
    edges.append((store.eid(h.from_chain, h.from_wallet), store.eid(h.to_chain, h.to_wallet),
                  {"label": f"${h.out_usd:,.0f} → ${h.in_usd:,.0f} · {h.gap_h:.1f} h · {h.confidence}",
                   "color": "accent", "width": 1.5 + 1.5 * (h.confidence == "High")}))
if edges:
    st.graphviz_chart(dot(nodes, edges), width="content")

if (twins and any(x["active"] for x in twins)) or len(hops):
    if need("case", "save links to the graph or a case"):
        label = f"Save links to the entity graph" + (f" and attach to case #{run_case}" if run_case else "")
        if st.button(label, type="primary", icon=":material/save:"):
            keep = hops[hops["confidence"].isin(["High", "Medium"])] if len(hops) else hops
            n, ids = crosschain.record(analyst(), twins, keep, int(run_case) if run_case else None)
            st.success(f"{n} new link(s) saved" + (f"; {len(ids)} wallets attached to case #{run_case} as leads." if run_case else "."))
