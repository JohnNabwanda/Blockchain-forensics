"""Live TRON / USDT wallet investigation from the public TronGrid API.

Fetches a wallet's real USDT (TRC-20) transfers, summarises its behaviour, follows funds a few hops
forward and backward, and scores risk from transparent indicators. Every indicator is a lead for an
analyst, never proof of wrongdoing.
"""
import time

import networkx as nx
import pandas as pd
import requests

from .. import config
from . import store

API = "https://api.trongrid.io"
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
PAGE = 200


class TronError(RuntimeError):
    pass


def _headers():
    key = config.secret("tron", "api_key")
    return {"TRON-PRO-API-KEY": key} if key else {}


def valid_address(addr):
    return isinstance(addr, str) and len(addr) == 34 and addr.startswith("T") and addr.isalnum()


def fetch_transfers(address, max_transfers=1000, since=None):
    """Real USDT transfers in and out of `address`, newest first, as a DataFrame."""
    if not valid_address(address):
        raise TronError("Not a valid TRON address (34 characters starting with T).")
    url = f"{API}/v1/accounts/{address}/transactions/trc20"
    params = {"limit": PAGE, "contract_address": USDT_CONTRACT, "only_confirmed": "true"}
    if since is not None:
        params["min_timestamp"] = int(pd.Timestamp(since).timestamp() * 1000)
    rows = []
    while url and len(rows) < max_transfers:
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, headers=_headers(), timeout=20)
            except requests.RequestException as e:
                if attempt == 2:
                    raise TronError(f"TronGrid unreachable: {e}") from e
                time.sleep(1.5)
                continue
            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        d = r.json()
        if not d.get("success", False):
            raise TronError(d.get("error") or f"TronGrid error {r.status_code}")
        for t in d.get("data", []):
            dec = int(t["token_info"].get("decimals", 6))
            rows.append({"tx_id": t["transaction_id"], "ts": pd.to_datetime(t["block_timestamp"], unit="ms", utc=True),
                         "src": t["from"], "dst": t["to"], "amount": int(t["value"]) / 10 ** dec})
        url = d.get("meta", {}).get("links", {}).get("next")
        params = None                                    # the next link already carries them
    df = pd.DataFrame(rows[:max_transfers], columns=["tx_id", "ts", "src", "dst", "amount"])
    if not df.empty:
        df["direction"] = (df["dst"] == address).map({True: "in", False: "out"})
        df["counterparty"] = df["src"].where(df["direction"] == "in", df["dst"])
    return df


def fetch_account(address):
    """Basic account facts: creation time and TRX balance."""
    r = requests.get(f"{API}/v1/accounts/{address}", headers=_headers(), timeout=20).json()
    data = (r.get("data") or [{}])[0]
    created = data.get("create_time")
    return {"exists": bool(r.get("data")),
            "created": pd.to_datetime(created, unit="ms", utc=True) if created else None,
            "trx_balance": data.get("balance", 0) / 1e6}


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
            "pass_through": _pass_through(tx)}


def _pass_through(tx, hours=24):
    """Share of incoming USDT that leaves again within `hours` (money moving straight through)."""
    i = tx[tx["direction"] == "in"].sort_values("ts")
    o = tx[tx["direction"] == "out"].sort_values("ts")
    if i.empty or o.empty or i["amount"].sum() == 0:
        return 0.0
    m = pd.merge_asof(o[["ts", "amount"]], i[["ts"]].assign(t_in=i["ts"]), on="ts", direction="backward")
    fast = m[(m["ts"] - m["t_in"]).dt.total_seconds() <= hours * 3600]["amount"].sum()
    return float(min(fast / i["amount"].sum(), 1.0))


def counterparties(tx):
    if tx.empty:
        return pd.DataFrame(columns=["counterparty", "sent_to_it", "received_from_it", "transfers", "first", "last"])
    g = tx.groupby("counterparty")
    cp = pd.DataFrame({
        "sent_to_it": tx[tx["direction"] == "out"].groupby("counterparty")["amount"].sum(),
        "received_from_it": tx[tx["direction"] == "in"].groupby("counterparty")["amount"].sum(),
        "transfers": g.size(), "first": g["ts"].min(), "last": g["ts"].max()}).fillna(0)
    cp["volume"] = cp["sent_to_it"] + cp["received_from_it"]
    wl = store.watchlist_map()
    cp["watchlist"] = cp.index.map(lambda a: wl.get(a, ""))
    return cp.sort_values("volume", ascending=False).rename_axis("counterparty").reset_index()


def risk_indicators(address, s, cp, account=None):
    """Transparent indicators, each with points and a plain-language reason. Score is capped at 100."""
    out = []
    wl = store.watchlist_map()
    if address in wl:
        out.append((60, "Watchlisted", f"This wallet is on the watchlist: {wl[address]}"))
    hits = cp[cp["watchlist"] != ""]
    if len(hits):
        vol = hits["volume"].sum()
        out.append((40, "Direct exposure to watchlisted wallets",
                    f"{len(hits)} counterparties on the watchlist, {vol:,.0f} USDT exchanged with them"))
    if s.get("transfers", 0) == 0:
        return out
    if s["senders"] + s["receivers"] >= 150 and s["per_day"] >= 200:
        out.append((0, "Likely exchange or large service",
                    f"{s['senders'] + s['receivers']} counterparties at {s['per_day']:,.0f} transfers a day; "
                    "funds through it belong to many unrelated users, so it is not traced further"))
    if s["pass_through"] >= 0.8 and s["usdt_in"] >= 1000:
        out.append((20, "Rapid pass-through",
                    f"{s['pass_through']:.0%} of incoming USDT left again within 24 hours (layering pattern)"))
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
    if s["round_share"] >= 0.6 and s["transfers"] >= 10:
        out.append((5, "Mostly round amounts", f"{s['round_share']:.0%} of transfers are multiples of 100 USDT"))
    if account and account.get("created") is not None and s["usdt_in"] >= 10000:
        age = (pd.Timestamp.now(tz="UTC") - account["created"]).days
        if age <= 30:
            out.append((10, "New wallet, large volume", f"Created {age} days ago, already received {s['usdt_in']:,.0f} USDT"))
    return out


def risk_score(indicators):
    return min(100, sum(p for p, _, _ in indicators))


def band(score):
    return "High" if score >= 50 else "Medium" if score >= 20 else "Low"


def trace(address, hops=2, top_k=4, per_wallet=300, direction="out", min_usdt=1.0):
    """Follow the largest USDT flows `hops` steps forward (out) or backward (in) from `address`.

    Wallets with very many counterparties are treated as services (exchanges, traders) and not
    expanded: they handle money for many innocent people.
    """
    G = nx.DiGraph()
    G.add_node(address, hop=0)
    frontier = [address]
    errors = []
    for h in range(1, hops + 1):
        nxt = []
        for w in frontier:
            try:
                tx = fetch_transfers(w, max_transfers=per_wallet)
            except TronError as e:
                errors.append(f"{w}: {e}")
                continue
            if tx.empty:
                continue
            n_cp = tx["counterparty"].nunique()
            if w != address and n_cp >= 150:
                G.nodes[w]["service"] = True
                continue
            side = tx[tx["direction"] == direction]
            agg = side.groupby("counterparty")["amount"].agg(["sum", "size"]).sort_values("sum", ascending=False)
            for cp_addr, r in agg.head(top_k).iterrows():
                if r["sum"] < min_usdt:
                    continue
                if cp_addr not in G:
                    G.add_node(cp_addr, hop=h)
                    nxt.append(cp_addr)
                a, b = (w, cp_addr) if direction == "out" else (cp_addr, w)
                G.add_edge(a, b, usdt=float(r["sum"]), n=int(r["size"]))
        frontier = nxt
    wl = store.watchlist_map()
    for n in G:
        G.nodes[n]["watchlist"] = wl.get(n, "")
    return G, errors
