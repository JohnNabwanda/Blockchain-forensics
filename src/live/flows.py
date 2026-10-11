"""Chain-independent flow analysis shared by the TRON, Ethereum and Bitcoin modules.

Every module turns a wallet's history into the same table, one row per transfer:
    tx_id, ts (UTC), src, dst, amount (in `unit`), direction (in/out), counterparty
and gets the same behaviour summary, transparent risk indicators and fund-flow trace.
"""
import networkx as nx
import pandas as pd

from . import store

COLUMNS = ["tx_id", "ts", "src", "dst", "amount"]
SERVICE_COUNTERPARTIES = 150      # wallets with this many counterparties are treated as services


def with_direction(df, address):
    df = df.copy()
    if not df.empty:
        df["direction"] = (df["dst"] == address).map({True: "in", False: "out"})
        df["counterparty"] = df["src"].where(df["direction"] == "in", df["dst"])
    else:
        df["direction"] = pd.Series(dtype=str)
        df["counterparty"] = pd.Series(dtype=str)
    return df


def summarise(address, tx):
    """Behaviour of one wallet over the fetched transfers."""
    if tx.empty:
        return {"transfers": 0}
    i, o = tx[tx["direction"] == "in"], tx[tx["direction"] == "out"]
    span_days = max((tx["ts"].max() - tx["ts"].min()).total_seconds() / 86400, 1 / 24)
    return {"transfers": len(tx), "in_count": len(i), "out_count": len(o),
            "usdt_in": i["amount"].sum(), "usdt_out": o["amount"].sum(),
            "senders": i["src"].nunique(), "receivers": o["dst"].nunique(),
            "first_seen": tx["ts"].min(), "last_seen": tx["ts"].max(), "span_days": span_days,
            "per_day": len(tx) / span_days,
            "round_share": (tx["amount"] % 100 == 0).mean(),
            "pass_through": pass_through(tx)}


def pass_through(tx, hours=24):
    """Share of incoming value that leaves again within `hours` (money moving straight through)."""
    i = tx[tx["direction"] == "in"].sort_values("ts")
    o = tx[tx["direction"] == "out"].sort_values("ts")
    if i.empty or o.empty or i["amount"].sum() == 0:
        return 0.0
    m = pd.merge_asof(o[["ts", "amount"]], i[["ts"]].assign(t_in=i["ts"]), on="ts", direction="backward")
    fast = m[(m["ts"] - m["t_in"]).dt.total_seconds() <= hours * 3600]["amount"].sum()
    return float(min(fast / i["amount"].sum(), 1.0))


def counterparties(tx):
    if tx.empty:
        return pd.DataFrame(columns=["counterparty", "sent_to_it", "received_from_it", "transfers", "first", "last",
                                     "volume", "watchlist"])
    g = tx.groupby("counterparty")
    cp = pd.DataFrame({
        "sent_to_it": tx[tx["direction"] == "out"].groupby("counterparty")["amount"].sum(),
        "received_from_it": tx[tx["direction"] == "in"].groupby("counterparty")["amount"].sum(),
        "transfers": g.size(), "first": g["ts"].min(), "last": g["ts"].max()}).fillna(0)
    cp["volume"] = cp["sent_to_it"] + cp["received_from_it"]
    wl = store.watchlist_map()
    cp["watchlist"] = cp.index.map(lambda a: wl.get(store.norm_address(a), ""))
    return cp.sort_values("volume", ascending=False).rename_axis("counterparty").reset_index()


def risk_indicators(address, s, cp, account=None, unit="USDT", round_unit=100):
    """Transparent indicators, each with points and a plain-language reason. Score is capped at 100."""
    out = []
    wl = store.watchlist_map()
    if store.norm_address(address) in wl:
        out.append((60, "Watchlisted", f"This wallet is on the watchlist: {wl[store.norm_address(address)]}"))
    hits = cp[cp["watchlist"] != ""]
    if len(hits):
        vol = hits["volume"].sum()
        out.append((40, "Direct exposure to watchlisted wallets",
                    f"{len(hits)} counterparties on the watchlist, {vol:,.0f} {unit} exchanged with them"))
    if s.get("transfers", 0) == 0:
        return out
    if s["senders"] + s["receivers"] >= SERVICE_COUNTERPARTIES and s["per_day"] >= 200:
        out.append((0, "Likely exchange or large service",
                    f"{s['senders'] + s['receivers']} counterparties at {s['per_day']:,.0f} transfers a day; "
                    "funds through it belong to many unrelated users, so it is not traced further"))
    if s["pass_through"] >= 0.8 and s["usdt_in"] >= 1000:
        out.append((20, "Rapid pass-through",
                    f"{s['pass_through']:.0%} of incoming {unit} left again within 24 hours (layering pattern)"))
    if s["senders"] >= 20 and s["receivers"] <= 3 and s["out_count"] > 0:
        out.append((15, "Fan-in / collection wallet",
                    f"Receives from {s['senders']} wallets but sends to only {s['receivers']}"))
    if s["receivers"] >= 20 and s["senders"] <= 3 and s["in_count"] > 0:
        out.append((15, "Fan-out / distribution wallet",
                    f"Receives from {s['senders']} wallets but pays out to {s['receivers']}"))
    if s["senders"] >= 15 and s["receivers"] >= 15 and s["per_day"] >= 5:
        out.append((10, "Possible P2P trader or service",
                    f"Many counterparties both ways ({s['senders']} in, {s['receivers']} out), "
                    f"{s['per_day']:.1f} transfers a day; trace stops here unless confirmed"))
    if round_unit and s["round_share"] >= 0.6 and s["transfers"] >= 10:
        out.append((5, "Mostly round amounts", f"{s['round_share']:.0%} of transfers are multiples of {round_unit} {unit}"))
    if account and account.get("created") is not None and s["usdt_in"] >= 10000:
        age = (pd.Timestamp.now(tz="UTC") - account["created"]).days
        if age <= 30:
            out.append((10, "New wallet, large volume", f"Created {age} days ago, already received {s['usdt_in']:,.0f} {unit}"))
    return out


def risk_score(indicators):
    return min(100, sum(p for p, _, _ in indicators))


def trace(address, fetch, error=Exception, hops=2, top_k=4, per_wallet=300, direction="out", min_amount=1.0,
          is_service=None):
    """Follow the largest flows `hops` steps forward (out) or backward (in) from `address`.

    fetch(wallet, max_transfers) returns the wallet's transfers in the shared table format.
    Wallets with very many counterparties (or flagged by is_service) are treated as services
    (exchanges, traders) and not expanded: they handle money for many innocent people.
    """
    G = nx.DiGraph()
    G.add_node(address, hop=0)
    frontier = [address]
    errors = []
    for h in range(1, hops + 1):
        nxt = []
        for w in frontier:
            try:
                tx = fetch(w, per_wallet)
            except error as e:
                errors.append(f"{w}: {e}")
                continue
            if tx.empty:
                continue
            n_cp = tx["counterparty"].nunique()
            if w != address and (n_cp >= SERVICE_COUNTERPARTIES or (is_service and is_service(w))):
                G.nodes[w]["service"] = True
                continue
            side = tx[tx["direction"] == direction]
            agg = side.groupby("counterparty")["amount"].agg(["sum", "size"]).sort_values("sum", ascending=False)
            for cp_addr, r in agg.head(top_k).iterrows():
                if r["sum"] < min_amount:
                    continue
                if cp_addr not in G:
                    G.add_node(cp_addr, hop=h)
                    nxt.append(cp_addr)
                a, b = (w, cp_addr) if direction == "out" else (cp_addr, w)
                G.add_edge(a, b, usdt=float(r["sum"]), n=int(r["size"]))
        frontier = nxt
    wl = store.watchlist_map()
    for n in G:
        G.nodes[n]["watchlist"] = wl.get(store.norm_address(n), "")
    return G, errors


def record(analyst, chain, address, tx, score=None, band=None, indicators=None, module=None, top=25, asset=None,
           kind="wallet", label=None):
    """Write the wallet and its largest counterparty flows into the shared entity graph."""
    me = store.upsert_entity(analyst, chain, address, kind=kind, label=label, risk_score=score, risk_band=band,
                             reasons=None if indicators is None else [n for _, n, _ in indicators], module=module)
    if tx.empty:
        return me
    agg = tx.groupby(["src", "dst"]).agg(amount=("amount", "sum"), n=("amount", "size"), first=("ts", "min")) \
            .reset_index().sort_values("amount", ascending=False).head(top)
    rows = [{"src": store.eid(chain, r.src), "dst": store.eid(chain, r.dst), "kind": "transfer", "chain": chain,
             "asset": asset, "amount": float(r.amount), "amount_usd": float(r.amount) if asset in ("USDT", "USDC", "USD") else None,
             "tx_id": f"agg:{r.n}", "ts": r.first, "detail": f"{r.n} transfers"} for r in agg.itertuples()]
    store.ensure_entities(analyst, {x["src"] for x in rows} | {x["dst"] for x in rows}, module)
    store.add_links(analyst, rows, module)
    return me


def record_trace(analyst, chain, graph, asset=None, module=None):
    """Write a trace graph ({nodes, edges}) into the shared entity graph."""
    rows = [{"src": store.eid(chain, a), "dst": store.eid(chain, b), "kind": "trace", "chain": chain, "asset": asset,
             "amount": d["usdt"], "amount_usd": d["usdt"] if asset in ("USDT", "USDC", "USD") else None,
             "tx_id": f"trace:{d['n']}", "detail": f"{d['n']} transfers (trace)"} for a, b, d in graph["edges"]]
    for n, d in graph["nodes"].items():
        if d.get("service"):
            store.upsert_entity(analyst, chain, n, kind="service", label="likely exchange or service", module=module)
    store.ensure_entities(analyst, {x["src"] for x in rows} | {x["dst"] for x in rows}, module)
    store.add_links(analyst, rows, module)
    return [store.eid(chain, n) for n in graph["nodes"]]
