"""Live TRON / USDT wallet investigation."""
import json

import pandas as pd
import streamlit as st

from src.live import store, tron
from views.common import analyst, band_badge, compact, lead_notice, open_case_button, page_header

page_header("Investigate · TRON / USDT", "Wallet investigation", "Enter any TRON wallet to analyse its USDT activity, score risk and follow the money.",
            {"Source": "live TRON blockchain (TronGrid)", "Token": "USDT TRC-20"})


@st.cache_data(ttl=300, show_spinner=False)
def load(address, max_transfers):
    return tron.fetch_transfers(address, max_transfers=max_transfers), tron.fetch_account(address)


@st.cache_data(ttl=300, show_spinner=False)
def load_trace(address, hops, top_k, direction):
    G, errors = tron.trace(address, hops=hops, top_k=top_k, direction=direction)
    return {"nodes": dict(G.nodes(data=True)), "edges": list(G.edges(data=True))}, errors


def short(a):
    return f"{a[:6]}…{a[-4:]}"


# Trace graph colours from the dashboards' palette (accent = signal, orange = illicit flow, amber = service)
GRAPH_THEME = {
    "dark": {"fill": "#101826", "line": "#2b3a50", "ink": "#e8f1fb", "muted": "#75859d", "accent": "#38d6f0",
             "root_ink": "#060a12", "bad": "#ff8a3d", "bad_fill": "#2a1a12", "warn": "#fbbf24", "warn_fill": "#2a2410"},
    "light": {"fill": "#ffffff", "line": "#b8c6d8", "ink": "#0c1524", "muted": "#627088", "accent": "#0a86a8",
              "root_ink": "#ffffff", "bad": "#e25a1f", "bad_fill": "#fde8dc", "warn": "#d99a0b", "warn_fill": "#fdf3d6"},
}


def dot(graph, root):
    c = GRAPH_THEME.get(st.context.theme.type, GRAPH_THEME["dark"])
    lines = ['digraph G { rankdir=LR; bgcolor="transparent"; pad=0.2; nodesep=0.35; ranksep=0.9; '
             f'node [shape=box, style="rounded,filled", fontname="JetBrains Mono", fontsize=10, margin="0.18,0.08", '
             f'fillcolor="{c["fill"]}", color="{c["line"]}", fontcolor="{c["ink"]}", penwidth=1.2]; '
             f'edge [fontname="JetBrains Mono", fontsize=9, color="{c["muted"]}", fontcolor="{c["muted"]}", arrowsize=0.7];']
    for n, d in graph["nodes"].items():
        attrs = {"label": short(n)}
        if n == root:
            attrs.update(fillcolor=c["accent"], fontcolor=c["root_ink"], color=c["accent"], penwidth="2")
        elif d.get("watchlist"):
            attrs.update(fillcolor=c["bad_fill"], color=c["bad"], fontcolor=c["bad"], penwidth="1.8",
                         label=f"{short(n)}\\n⚑ {d['watchlist'][:24]}")
        elif d.get("service"):
            attrs.update(fillcolor=c["warn_fill"], color=c["warn"], label=f"{short(n)}\\nservice · not traced")
        lines.append(f'"{n}" [' + ", ".join(f'{k}="{v}"' for k, v in attrs.items()) + "];")
    for a, b, d in graph["edges"]:
        lines.append(f'"{a}" -> "{b}" [label="{compact(d["usdt"])} USDT · {d["n"]}", '
                     f'penwidth={1 + min(d["usdt"] / 50000, 3):.1f}];')
    return "\n".join(lines) + "}"


with st.form("lookup"):
    c1, c2 = st.columns([4, 1])
    address = c1.text_input("Wallet address", value=st.session_state.get("tron_addr", ""),
                            placeholder="T… (34 characters)").strip()
    depth = c2.selectbox("History", [200, 1000, 3000], index=1, format_func=lambda n: f"last {n:,} transfers")
    go = st.form_submit_button("Investigate", type="primary", icon=":material/search:")

if go:
    st.session_state["tron_addr"] = address
address = st.session_state.get("tron_addr", "")
if not address:
    st.info("Enter a TRON address. The platform fetches its USDT transfers, scores risk from transparent "
            "indicators, checks counterparties against the watchlist and traces funds forward and backward.")
    st.stop()
if not tron.valid_address(address):
    st.error("That is not a valid TRON address (34 characters starting with T).")
    st.stop()

with st.spinner("Fetching transfers from the TRON blockchain…"):
    try:
        tx, account = load(address, depth)
    except tron.TronError as e:
        st.error(str(e))
        st.stop()
if go:
    store.log(analyst(), "tron lookup", module="tron", subject=address, detail=f"{len(tx)} transfers")

s = tron.summarise(address, tx)
cp = tron.counterparties(tx)
ind = tron.risk_indicators(address, s, cp, account)
score = tron.risk_score(ind)
band = tron.band(score)

h1, h2 = st.columns([3, 1])
h1.subheader(address)
with h2:
    band_badge(band, score)
if not account["exists"]:
    st.warning("This address has never been activated on the TRON blockchain.")
if tx.empty:
    st.info("No USDT transfers found for this address.")
    st.stop()

m = st.columns(6)
m[0].metric("Risk score", f"{score}/100")
m[1].metric("USDT in", compact(s["usdt_in"]), f"{s['in_count']:,} transfers", delta_color="off", delta_arrow="off",
            help=f"{s['usdt_in']:,.2f} USDT")
m[2].metric("USDT out", compact(s["usdt_out"]), f"{s['out_count']:,} transfers", delta_color="off", delta_arrow="off",
            help=f"{s['usdt_out']:,.2f} USDT")
m[3].metric("Counterparties", f"{s['senders'] + s['receivers']:,}", f"{s['senders']:,} in · {s['receivers']:,} out",
            delta_color="off", delta_arrow="off")
m[4].metric("Pass-through", f"{s['pass_through']:.0%}", help="Share of incoming USDT sent on within 24 hours")
m[5].metric("TRX", compact(account["trx_balance"]), help=f"TRX balance {account['trx_balance']:,.2f}")
coverage = f"{s['first_seen']:%d %b %Y %H:%M} → {s['last_seen']:%d %b %Y %H:%M} UTC"
created = f" · account created {account['created']:%d %b %Y}" if account.get("created") is not None else ""
st.caption(f"Analysed {s['transfers']:,} transfers, {coverage}{created}"
           + (" · history limit reached, older activity not included" if len(tx) >= depth else ""))
lead_notice()

tab_risk, tab_flow, tab_cp, tab_tx = st.tabs(["Risk indicators", "Fund flow trace", "Counterparties", "Transfers"])

with tab_risk:
    if not ind:
        st.success("No risk indicators triggered on the analysed activity.")
    for pts, name, why in sorted(ind, key=lambda x: -x[0]):
        st.markdown(f"**{name}**  ·  +{pts}" if pts else f"**{name}**  ·  context")
        st.caption(why)
    daily = tx.assign(day=tx["ts"].dt.floor("D" if s["span_days"] > 3 else "h")) \
              .pivot_table(index="day", columns="direction", values="amount", aggfunc="sum").fillna(0)
    st.markdown("**USDT volume over time**")
    st.bar_chart(daily, color=["#2e7d32", "#c0392b"] if list(daily.columns) == ["in", "out"] else None)
    c1, c2, c3 = st.columns(3)
    with c1:
        open_case_button("tron", address, f"TRON wallet {short(address)}", score, band,
                         summary="; ".join(n for _, n, _ in ind), evidence={"summary": s, "indicators": ind})
    with c2:
        with st.popover("Add to watchlist", icon=":material/visibility:"):
            label = st.text_input("Reason", key="wl_label", placeholder="e.g. victim-reported scam wallet")
            source = st.text_input("Source / reference", key="wl_src", placeholder="e.g. police report RB/123/2026")
            if st.button("Save to watchlist"):
                try:
                    store.watch(analyst(), address, label, source)
                    st.success("Added. Any wallet that dealt with it will now be flagged.")
                    st.cache_data.clear()
                except ValueError as e:
                    st.error(str(e))
    with c3:
        report = {"address": address, "risk_score": score, "risk_band": band, "summary": s,
                  "indicators": [{"points": p, "name": n, "reason": w} for p, n, w in ind],
                  "top_counterparties": cp.head(20).to_dict("records"), "analyst": analyst()}
        st.download_button("Export report (JSON)", json.dumps(report, default=str, indent=1),
                           f"tron_{address}.json", "application/json", icon=":material/download:")

with tab_flow:
    c1, c2, c3 = st.columns(3)
    direction = c1.radio("Follow funds", ["out", "in"], horizontal=True,
                         format_func=lambda d: "Forward (where it went)" if d == "out" else "Backward (where it came from)")
    hops = c2.slider("Hops", 1, 3, 2)
    top_k = c3.slider("Largest counterparties per wallet", 2, 6, 3)
    if st.button("Trace", icon=":material/account_tree:"):
        with st.spinner("Following the money across wallets…"):
            st.session_state["trace"] = (address, direction, *load_trace(address, hops, top_k, direction))
        store.log(analyst(), f"tron trace {direction} {hops} hops", module="tron", subject=address)
    t = st.session_state.get("trace")
    if t and t[0] == address and t[1] == direction:
        graph, errors = t[2], t[3]
        st.graphviz_chart(dot(graph, address), width="content")
        flagged = [n for n, d in graph["nodes"].items() if d.get("watchlist")]
        if flagged:
            st.error(f"{len(flagged)} watchlisted wallet(s) within {hops} hops: " + ", ".join(flagged))
        edges = pd.DataFrame([{"from": a, "to": b, "usdt": d["usdt"], "transfers": d["n"]} for a, b, d in graph["edges"]])
        st.dataframe(edges, hide_index=True, column_config={"usdt": st.column_config.NumberColumn("USDT", format="%.2f")})
        for e in errors:
            st.caption(f"Could not fetch {e}")
        st.caption("Yellow = likely exchange or service (many unrelated users); not traced through.")
    else:
        st.caption("Press Trace to follow the largest flows across wallets (live, a few seconds per hop).")

with tab_cp:
    st.dataframe(cp, hide_index=True, width="stretch", column_config={
        "sent_to_it": st.column_config.NumberColumn("Sent to it (USDT)", format="%.2f"),
        "received_from_it": st.column_config.NumberColumn("Received from it (USDT)", format="%.2f"),
        "volume": st.column_config.NumberColumn("Total (USDT)", format="%.2f"),
        "watchlist": "Watchlist"})
    pick = st.selectbox("Investigate a counterparty", [""] + list(cp["counterparty"].head(50)))
    if pick and st.button("Open this wallet", icon=":material/arrow_forward:"):
        st.session_state["tron_addr"] = pick
        st.rerun()

with tab_tx:
    view = tx.assign(link="https://tronscan.org/#/transaction/" + tx["tx_id"])
    st.dataframe(view[["ts", "direction", "counterparty", "amount", "link"]], hide_index=True, width="stretch",
                 column_config={"ts": st.column_config.DatetimeColumn("Time (UTC)"),
                                "amount": st.column_config.NumberColumn("USDT", format="%.2f"),
                                "link": st.column_config.LinkColumn("Transaction", display_text=r".*/transaction/(.{12}).*",
                                                                    help="Opens on Tronscan")})
    st.download_button("Download transfers (CSV)", tx.to_csv(index=False), f"tron_{address}_transfers.csv", "text/csv")
