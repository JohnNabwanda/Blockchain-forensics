"""Shared entity graph: every wallet, contract, transaction and account any module has looked at."""
import json

import pandas as pd
import streamlit as st

from src.live import store
from views.common import CHAIN_TAG, attach_to_case, compact, dot, page_header, short

page_header("Casework · Entity graph", "Entity graph",
            "One map shared by every module. Wallets on TRON, Ethereum and Bitcoin, contracts, Bitcoin model "
            "transactions and mobile-money accounts, with the flows, same-key links, cross-chain hops and attributions "
            "between them.")

n, l = store.graph_stats()
m = st.columns(6)
m[0].metric("Entities", f"{sum(n.values()):,}")
m[1].metric("TRON", f"{n.get('tron', 0):,}")
m[2].metric("Ethereum", f"{n.get('eth', 0):,}")
m[3].metric("Bitcoin", f"{n.get('btc', 0) + n.get('btc-tx', 0):,}")
m[4].metric("Mobile money", f"{n.get('mm', 0):,}")
m[5].metric("Links", f"{sum(l.values()):,}",
            " · ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(l.items())) or None, delta_color="off", delta_arrow="off")

ents = store.entities()
if ents.empty:
    st.info("The graph is empty. Investigate a wallet on any chain: it and its largest flows are added automatically.")
    st.stop()

c1, c2, c3 = st.columns([3, 1, 1])
q = c1.text_input("Find an address, transaction or label").strip().lower()
chains = c2.multiselect("Chain", sorted(ents["chain"].unique()), format_func=lambda c: CHAIN_TAG.get(c, c))
risk = c3.multiselect("Risk", ["High", "Medium", "Low"])
view = ents
if q:
    view = view[view["id"].str.lower().str.contains(q, regex=False) | view["label"].fillna("").str.lower().str.contains(q, regex=False)]
if chains:
    view = view[view["chain"].isin(chains)]
if risk:
    view = view[view["risk_band"].isin(risk)]
st.dataframe(view[["id", "kind", "label", "risk_score", "risk_band", "module", "updated_utc"]], hide_index=True,
             width="stretch", height=260, column_config={
                 "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%.0f")})
if view.empty:
    st.stop()

pick = st.selectbox("Explore around", list(view["id"].head(200)))
hops = st.radio("Distance", [1, 2], horizontal=True, format_func=lambda h: f"{h} hop" + ("s" if h > 1 else ""))
e_n, e_l = store.neighbourhood([pick], hops=hops, max_nodes=50)
nodes = {e.id: {"label": f"{CHAIN_TAG.get(e.chain, e.chain)} {short(e.address)}",
                "sub": e.label or (f"{e.risk_band} risk" if e.risk_band else e.kind), "root": e.id == pick,
                "flag": e.risk_band == "High", "service": e.kind == "service"} for e in e_n.itertuples()}
style = {"same_key": ("dashed", "violet"), "cross_chain": ("bold", "accent"), "attribution": ("solid", "bad")}
edges = []
for x in e_l.itertuples() if len(e_l) else []:
    amt = x.amount_usd if x.amount_usd == x.amount_usd and x.amount_usd is not None else x.amount
    s_, c_ = style.get(x.kind, ("solid", None))
    edges.append((x.src, x.dst, {"label": x.kind.replace("_", " ") + (f" · {compact(amt)}" if amt == amt and amt is not None else ""),
                                 "style": s_, "color": c_, "width": 2.2 if x.kind in style else 1.2}))
st.graphviz_chart(dot(nodes, edges), width="content")
e = store.entity(pick)
if e is not None and isinstance(e["reasons"], str):
    st.caption("Indicators: " + ", ".join(json.loads(e["reasons"])))
attach_to_case([pick] + [i for i in nodes if i != pick], key="graph", label="Attach these to case")
with st.expander("Links in view"):
    st.dataframe(e_l, hide_index=True, width="stretch")
