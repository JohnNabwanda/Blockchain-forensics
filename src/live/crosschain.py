"""Cross-chain tracing between TRON, Ethereum and Bitcoin.

Two methods:

1. Same key (deterministic). A TRON address is base58check(0x41 + the same 20-byte key hash an
   Ethereum address uses). Every TRON address therefore has exactly one Ethereum twin; if both
   show activity, one private key controls both, so the same person or service holds them.

2. Hop matching (heuristic). Funds that leave a case wallet on one chain, typically into a bridge
   or an exchange, and reappear in a case wallet on another chain shortly after, for about the same
   USD value less fees. Each candidate pair is scored on time gap and amount difference and paired
   one-to-one. These are leads that need confirming with the bridge's or exchange's records.
"""
import hashlib

import pandas as pd

from . import bitcoin_live, ethereum, store, tron

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MAX_HOURS = 48           # an exchange withdrawal can take a day or two
TOLERANCE = 0.03         # bridge / exchange fee and slippage
FIXED_FEE_USD = 5.0
MIN_USD = 50.0


def _b58decode(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def _b58encode(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def tron_to_eth(address):
    raw = _b58decode(address)
    body, check = raw[:-4], raw[-4:]
    if len(body) != 21 or body[0] != 0x41 or hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] != check:
        raise ValueError("not a valid TRON address (checksum failed)")
    return "0x" + body[1:].hex()


def eth_to_tron(address):
    body = b"\x41" + bytes.fromhex(address.lower().removeprefix("0x"))
    return _b58encode(body + hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4])


def same_key(address):
    """For a TRON or Ethereum address: its twin on the other chain and whether the twin is active."""
    chain = store.chain_of(address)
    if chain == "tron":
        twin = tron_to_eth(address)
        c = ethereum._get(f"/addresses/{twin}/counters") or {}
        n = int(c.get("transactions_count") or 0) + int(c.get("token_transfers_count") or 0)
        return {"chain": "tron", "address": address, "twin_chain": "eth", "twin": twin, "active": n > 0,
                "activity": f"{n:,} Ethereum transactions and token transfers"}
    if chain == "eth":
        twin = eth_to_tron(address)
        acc = tron.fetch_account(twin)
        return {"chain": "eth", "address": address.lower(), "twin_chain": "tron", "twin": twin, "active": acc["exists"],
                "activity": (f"activated on TRON, {acc['trx_balance']:,.2f} TRX" if acc["exists"] else "never activated on TRON")}
    return None


def flows_of(chain, address, max_transfers=300):
    """Transfers of one wallet with USD values and counterparty labels, in a common shape."""
    if chain == "tron":
        tx = tron.fetch_transfers(address, max_transfers=max_transfers).assign(asset="USDT")
        labels = {}
    elif chain == "eth":
        tx = ethereum.fetch_transfers(address, max_transfers=max_transfers)
        labels = tx.attrs.get("labels", {})
    elif chain == "btc":
        tx = bitcoin_live.fetch_transfers(address, max_transfers=max_transfers)
        labels = {}
    else:
        raise ValueError(f"unsupported chain {chain}")
    tx = tx.assign(chain=chain, wallet=store.norm_address(address), amount_usd=tx["amount"])
    tx["via"] = tx["counterparty"].map(lambda a: ", ".join(labels.get(a, [])[:2]))
    return tx


def match(flows, max_hours=MAX_HOURS, tol=TOLERANCE, fee=FIXED_FEE_USD, min_usd=MIN_USD):
    """Pair outflows on one chain with inflows on another chain (one-to-one, best score first)."""
    if flows.empty:
        return pd.DataFrame()
    out = flows[(flows["direction"] == "out") & (flows["amount_usd"] >= min_usd)]
    inn = flows[(flows["direction"] == "in") & (flows["amount_usd"] >= min_usd * (1 - tol) - fee)]
    rows = []
    for o in out.itertuples():
        c = inn[(inn["chain"] != o.chain)]
        gap = (c["ts"] - o.ts).dt.total_seconds() / 3600
        lo = o.amount_usd * (1 - tol) - fee
        c = c[(gap >= 0) & (gap <= max_hours) & (c["amount_usd"] >= lo) & (c["amount_usd"] <= o.amount_usd * 1.002)]
        for i in c.itertuples():
            g = (i.ts - o.ts).total_seconds() / 3600
            diff = (o.amount_usd - i.amount_usd) / o.amount_usd
            score = round(1 - 0.4 * g / max_hours - 0.6 * max(diff, 0) / (tol + fee / o.amount_usd), 3)
            rows.append({"from_chain": o.chain, "from_wallet": o.wallet, "out_tx": o.tx_id, "out_ts": o.ts,
                         "out_usd": o.amount_usd, "out_to": o.counterparty, "out_via": o.via,
                         "to_chain": i.chain, "to_wallet": i.wallet, "in_tx": i.tx_id, "in_ts": i.ts,
                         "in_usd": i.amount_usd, "in_from": i.counterparty, "in_via": i.via,
                         "gap_h": round(g, 2), "diff_pct": round(100 * diff, 2), "score": score})
    if not rows:
        return pd.DataFrame()
    cand = pd.DataFrame(rows).sort_values("score", ascending=False)
    used_out, used_in, keep = set(), set(), []
    for idx, r in cand.iterrows():
        if r["out_tx"] in used_out or r["in_tx"] in used_in:
            continue
        used_out.add(r["out_tx"]); used_in.add(r["in_tx"]); keep.append(idx)
    res = cand.loc[keep].reset_index(drop=True)
    via_service = (res["out_via"].str.len() > 0) | (res["in_via"].str.len() > 0)
    res["confidence"] = ["High" if s >= 0.8 and (v or d <= 0.5) else "Medium" if s >= 0.55 else "Low"
                         for s, v, d in zip(res["score"], via_service, res["diff_pct"])]
    return res


def run(wallets, max_transfers=300):
    """wallets: {chain: [addresses]}. Returns (same-key results, matched hops, fetch errors)."""
    twins, frames, errors = [], [], []
    for chain, addrs in wallets.items():
        for a in addrs:
            if chain in ("tron", "eth"):
                try:
                    twins.append(same_key(a))
                except Exception as e:                      # one failing lookup must not stop the run
                    errors.append(f"same-key check {a}: {e}")
            try:
                frames.append(flows_of(chain, a, max_transfers))
            except Exception as e:
                errors.append(f"{chain} {a}: {e}")
    flows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return [t for t in twins if t], match(flows), errors


def record(analyst, twins, hops, case_id=None):
    """Write same-key and hop links into the shared graph and, optionally, attach them to a case."""
    rows, ids = [], set()
    for t in twins:
        if t["active"]:
            a, b = store.eid(t["chain"], t["address"]), store.eid(t["twin_chain"], t["twin"])
            rows.append({"src": a, "dst": b, "kind": "same_key", "confidence": "High", "tx_id": "",
                         "detail": f"same private key ({t['activity']})"})
            ids |= {a, b}
    for h in hops.itertuples() if len(hops) else []:
        a, b = store.eid(h.from_chain, h.from_wallet), store.eid(h.to_chain, h.to_wallet)
        via = h.out_via or h.in_via or "unlabelled intermediary"
        rows.append({"src": a, "dst": b, "kind": "cross_chain", "chain": f"{h.from_chain}->{h.to_chain}",
                     "amount_usd": float(h.out_usd), "amount": float(h.in_usd), "asset": "USD",
                     "tx_id": f"{h.out_tx}>{h.in_tx}", "ts": h.out_ts, "confidence": h.confidence,
                     "detail": f"via {via}; {h.gap_h} h later; {h.diff_pct}% less"})
        ids |= {a, b}
    store.ensure_entities(analyst, ids, "crosschain")
    n = store.add_links(analyst, rows, "crosschain")
    store.log(analyst, "cross-chain links recorded", case_id, "crosschain", detail=f"{n} new links")
    if case_id:
        store.attach(analyst, case_id, sorted(ids))
    return n, sorted(ids)
