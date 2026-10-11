"""Live Bitcoin address investigation from the public mempool.space API (no key needed).

Complements the graph model (views/bitcoin.py), which scores transactions of the Elliptic
dataset: Elliptic's features are anonymised and cannot be computed for new transactions, so live
addresses are scored with the same transparent indicators as TRON and Ethereum, plus a
CoinJoin (mixing) check.

Each transaction becomes transfer rows in the shared table format: when the address spends, one
row per output paid to another address; when it receives, the amount is split over the input
addresses by their input value. `amount` is in USD at the day's price; `amount_native` is BTC.
"""
import time
from functools import lru_cache

import pandas as pd
import requests

from . import feedback, flows

API = "https://mempool.space/api"
PAGE = 25
COINJOIN_MIN_EQUAL = 5


class BtcError(RuntimeError):
    pass


def valid_address(addr):
    a = (addr or "").strip()
    alphabet = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    if a.lower().startswith("bc1"):
        return 14 <= len(a) <= 74 and all(c in "023456789acdefghjklmnpqrstuvwxyz" for c in a.lower()[3:])
    return a[:1] in ("1", "3") and 26 <= len(a) <= 35 and set(a) <= alphabet


def _get(path):
    for attempt in range(3):
        try:
            r = requests.get(f"{API}{path}", timeout=25)
        except requests.RequestException as e:
            if attempt == 2:
                raise BtcError(f"mempool.space unreachable: {e}") from e
            time.sleep(1.5)
            continue
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 400:
            raise BtcError("mempool.space rejected the address")
        if r.status_code != 200:
            raise BtcError(f"mempool.space error {r.status_code}")
        return r.json()
    raise BtcError("mempool.space is rate-limiting; try again in a minute")


@lru_cache(maxsize=512)
def usd_on(day):
    """BTC/USD on a day (YYYY-MM-DD), from mempool.space's price history."""
    ts = int(pd.Timestamp(day, tz="UTC").timestamp()) + 43200
    d = _get(f"/v1/historical-price?currency=USD&timestamp={ts}")
    p = (d.get("prices") or [{}])[0].get("USD")
    return float(p) if p else usd_now()


@lru_cache(maxsize=4)
def _usd_now(hour):
    return float(_get("/v1/prices")["USD"])


def usd_now():
    return _usd_now(int(time.time() // 3600))


def fetch_account(address):
    d = _get(f"/address/{address}")
    c = d.get("chain_stats", {})
    return {"exists": c.get("tx_count", 0) > 0, "tx_count": c.get("tx_count", 0),
            "received_btc": c.get("funded_txo_sum", 0) / 1e8,
            "balance_btc": (c.get("funded_txo_sum", 0) - c.get("spent_txo_sum", 0)) / 1e8, "created": None}


def fetch_txs(address, max_txs=200):
    txs = [t for t in _get(f"/address/{address}/txs") if t.get("status", {}).get("confirmed")]
    while len(txs) < max_txs and txs and len(txs) % PAGE == 0:
        more = _get(f"/address/{address}/txs/chain/{txs[-1]['txid']}")
        if not more:
            break
        txs += more
    return txs[:max_txs]


def is_coinjoin(t):
    outs = pd.Series([o["value"] for o in t["vout"]])
    return len(t["vin"]) >= COINJOIN_MIN_EQUAL and outs.value_counts().max() >= COINJOIN_MIN_EQUAL


def fetch_transfers(address, max_transfers=200, price_days=40):
    """Transfers of `address` in the shared table format; df.attrs['coinjoins'] lists CoinJoin txids."""
    if not valid_address(address):
        raise BtcError("Not a valid Bitcoin address.")
    rows, coinjoins = [], []
    for t in fetch_txs(address, max_transfers):
        ts = pd.to_datetime(t["status"]["block_time"], unit="s", utc=True)
        ins = [(v["prevout"].get("scriptpubkey_address"), v["prevout"]["value"]) for v in t["vin"] if v.get("prevout")]
        outs = [(o.get("scriptpubkey_address"), o["value"]) for o in t["vout"]]
        sent = sum(v for a, v in ins if a == address)
        received = sum(v for a, v in outs if a == address)
        if is_coinjoin(t):
            coinjoins.append(t["txid"])
        if sent > 0:
            for a, v in outs:
                if a and a != address and v > 0:
                    rows.append({"tx_id": t["txid"], "ts": ts, "src": address, "dst": a, "btc": v / 1e8})
        elif received > 0:
            others = pd.DataFrame([x for x in ins if x[0]], columns=["a", "v"]).groupby("a")["v"].sum()
            for a, v in (others / max(others.sum(), 1) * received).items():
                rows.append({"tx_id": t["txid"], "ts": ts, "src": a, "dst": address, "btc": v / 1e8})
    df = pd.DataFrame(rows, columns=["tx_id", "ts", "src", "dst", "btc"])
    if not df.empty:
        days = df["ts"].dt.strftime("%Y-%m-%d")
        uniq = days.unique()
        prices = {d: usd_on(d) for d in uniq[:price_days]}
        now = usd_now()
        df["amount"] = df["btc"] * days.map(lambda d: prices.get(d, now))
    else:
        df["amount"] = pd.Series(dtype=float)
    df = df.rename(columns={"btc": "amount_native"}).assign(asset="BTC")
    df = flows.with_direction(df[flows.COLUMNS + ["asset", "amount_native"]], address)
    df.attrs["coinjoins"] = coinjoins
    return df


def risk_indicators(address, s, cp, coinjoins):
    ind = flows.risk_indicators(address, s, cp, None, unit="USD", round_unit=None)
    if coinjoins:
        ind.append((20, "CoinJoin (mixing) participation",
                    f"Took part in {len(coinjoins)} CoinJoin transaction(s): many inputs, "
                    f"at least {COINJOIN_MIN_EQUAL} equal-value outputs"))
    return ind


def band(score):
    return feedback.band("btc", score)


def trace(address, hops=2, top_k=3, per_wallet=100, direction="out"):
    return flows.trace(address, lambda w, n: fetch_transfers(w, max_transfers=n, price_days=10), BtcError,
                       hops=hops, top_k=top_k, per_wallet=per_wallet, direction=direction, min_amount=1.0)
