"""Live Ethereum wallet and contract investigation from the public Blockscout API (no key needed).

Fetches a wallet's stablecoin (USDT, USDC) and ETH transfers, together with the public labels
Blockscout attaches to addresses (exchange names, mixers, addresses frozen by the stablecoin
issuer), and the verified source code of deployed contracts for the Slither audit.
"""
import time
from functools import lru_cache

import pandas as pd
import requests

from . import feedback, flows

API = "https://eth.blockscout.com/api/v2"
STABLECOINS = {"0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
               "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC"}
NULL = "0x" + "0" * 40              # mint/burn address: carries every tag, never a real counterparty
MIXER_WORDS = ("tornado", "mixer", "railgun", "sinbad", "blender")
BRIDGE_WORDS = ("bridge", "wormhole", "stargate", "multichain", "hop protocol", "across", "synapse", "celer", "portal")
EXCHANGE_WORDS = ("binance", "coinbase", "kraken", "okx", "bybit", "huobi", "htx", "kucoin", "gate.io", "bitfinex",
                  "crypto.com", "exchange", "hot wallet", "deposit")


class EthError(RuntimeError):
    pass


def valid_address(addr):
    a = (addr or "").strip()
    return len(a) == 42 and a.lower().startswith("0x") and all(c in "0123456789abcdefABCDEF" for c in a[2:])


def _get(path, params=None):
    for attempt in range(3):
        try:
            r = requests.get(f"{API}{path}", params=params, timeout=30)
        except requests.RequestException as e:
            if attempt == 2:
                raise EthError(f"Blockscout unreachable: {e}") from e
            time.sleep(1.5)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise EthError(f"Blockscout error {r.status_code}")
        return r.json()
    raise EthError("Blockscout is busy; try again in a minute")


def _labels(a):
    """Public labels for an address object from Blockscout."""
    if not a:
        return []
    names = [a.get("name")] + [t.get("name") for t in ((a.get("metadata") or {}).get("tags") or [])] \
        + [t.get("label") for t in (a.get("public_tags") or [])]
    return [n for n in names if n]


def classify(labels, is_scam=False):
    text = " ".join(labels).lower()
    return {"mixer": any(w in text for w in MIXER_WORDS), "bridge": any(w in text for w in BRIDGE_WORDS),
            "exchange": any(w in text for w in EXCHANGE_WORDS),
            "blocked": "blocked" in text or "frozen" in text, "sanctioned": "ofac" in text or "sanction" in text,
            "scam": bool(is_scam) or "phish" in text or "scam" in text}


def fetch_account(address):
    d = _get(f"/addresses/{address}")
    if d is None:
        return {"exists": False, "is_contract": False, "is_verified": False, "labels": [], "flags": classify([]),
                "eth_balance": 0.0, "name": None, "eth_usd": None, "created": None}
    labels = _labels(d)
    return {"exists": True, "is_contract": bool(d.get("is_contract")), "is_verified": bool(d.get("is_verified")),
            "name": d.get("name"), "labels": labels, "flags": classify(labels, d.get("is_scam")),
            "eth_balance": int(d.get("coin_balance") or 0) / 1e18,
            "eth_usd": float(d["exchange_rate"]) if d.get("exchange_rate") else None, "created": None}


@lru_cache(maxsize=1)
def _eth_usd_cached(hour):
    d = _get("/stats") or {}
    return float(d.get("coin_price") or 0) or None


def eth_usd():
    return _eth_usd_cached(int(time.time() // 3600))


def fetch_transfers(address, max_transfers=500, include_eth=True):
    """Stablecoin and ETH transfers of `address`, newest first, in the shared table format.

    `amount` is in USD (stablecoins at face value; ETH at today's price, an approximation).
    Labels of every counterparty seen are returned in df.attrs['labels'].
    """
    if not valid_address(address):
        raise EthError("Not a valid Ethereum address (0x followed by 40 hex characters).")
    address = address.lower()
    rows, labels = [], {}

    def note(a):
        if a and a.get("hash"):
            h = a["hash"].lower()
            if h not in labels:
                labels[h] = _labels(a)
            return h
        return None

    params, pages = {"type": "ERC-20"}, 0
    while len(rows) < max_transfers and pages < max(2, max_transfers // 25):
        d = _get(f"/addresses/{address}/token-transfers", params)
        pages += 1
        if not d:
            break
        for t in d.get("items", []):
            tok = (t.get("token") or {}).get("address_hash", "").lower()
            if tok not in STABLECOINS:
                continue
            dec = int((t.get("total") or {}).get("decimals") or 6)
            amt = int((t.get("total") or {}).get("value") or 0) / 10 ** dec
            rows.append({"tx_id": t["transaction_hash"], "ts": pd.Timestamp(t["timestamp"]), "src": note(t["from"]),
                         "dst": note(t["to"]), "amount": amt, "asset": STABLECOINS[tok], "amount_native": amt})
        if not d.get("next_page_params"):
            break
        params = {"type": "ERC-20", **d["next_page_params"]}
    if include_eth:
        price = eth_usd() or 0
        params, pages = None, 0
        while pages < max(1, max_transfers // 100):
            d = _get(f"/addresses/{address}/transactions", params)
            pages += 1
            if not d:
                break
            for t in d.get("items", []):
                v = int(t.get("value") or 0) / 1e18
                if v <= 0 or t.get("result") != "success":
                    continue
                rows.append({"tx_id": t["hash"], "ts": pd.Timestamp(t["timestamp"]), "src": note(t.get("from")),
                             "dst": note(t.get("to")), "amount": v * price, "asset": "ETH", "amount_native": v})
            if not d.get("next_page_params"):
                break
            params = d["next_page_params"]
    df = pd.DataFrame(rows, columns=flows.COLUMNS + ["asset", "amount_native"]).dropna(subset=["src", "dst"])
    df = df.sort_values("ts", ascending=False).head(max_transfers).reset_index(drop=True)
    df = flows.with_direction(df, address)
    df.attrs["labels"] = labels
    return df


def risk_indicators(address, s, cp, account, labels):
    """Shared indicators plus Ethereum label checks (mixers, frozen addresses, scam flags)."""
    ind = flows.risk_indicators(address, s, cp, None, unit="USD")
    own = list(dict.fromkeys(account["labels"] + labels.get(address.lower(), [])))
    account["labels"] = own
    f = account["flags"] = classify(own, account["flags"]["scam"])
    if f["sanctioned"]:
        ind.append((60, "Sanctioned address", "On a sanctions list (OFAC): " + ", ".join(own[:3])))
    if f["blocked"]:
        ind.append((40, "Frozen by the stablecoin issuer", "Labelled BLOCKED: the USDT/USDC issuer froze this address"))
    if f["scam"]:
        ind.append((40, "Flagged as scam or phishing", "Public label: " + ", ".join(account["labels"][:3])))
    if f["mixer"]:
        ind.append((0, "Mixer contract", "This address is a mixing service: " + ", ".join(account["labels"][:2])))
    exposure = {"mixer": [], "sanctioned": [], "blocked": [], "scam": []}
    for a in cp["counterparty"]:
        if a == NULL:
            continue
        c = classify(labels.get(a, []))
        c["blocked"] &= not c["sanctioned"]          # counted once, as the stronger indicator
        for k in exposure:
            if c[k]:
                exposure[k].append(a)
    vol = cp.set_index("counterparty")["volume"]
    if exposure["mixer"]:
        ind.append((40, "Direct exposure to a mixer",
                    f"{len(exposure['mixer'])} mixer counterparties, {vol[exposure['mixer']].sum():,.0f} USD exchanged"))
    if exposure["sanctioned"]:
        ind.append((40, "Direct exposure to sanctioned addresses",
                    f"{len(exposure['sanctioned'])} sanctioned counterparties, "
                    f"{vol[exposure['sanctioned']].sum():,.0f} USD exchanged"))
    if exposure["blocked"]:
        ind.append((25, "Dealt with frozen addresses",
                    f"{len(exposure['blocked'])} counterparties frozen by the stablecoin issuer"))
    if exposure["scam"]:
        ind.append((25, "Dealt with flagged scam addresses", f"{len(exposure['scam'])} counterparties flagged"))
    return ind


def band(score):
    return feedback.band("eth", score)


def trace(address, hops=2, top_k=3, per_wallet=200, direction="out", labels=None):
    labels = dict(labels or {})

    def fetch(w, n):
        tx = fetch_transfers(w, max_transfers=n)
        labels.update(tx.attrs.get("labels", {}))
        return tx

    def is_service(w):
        c = classify(labels.get(w, []))
        return c["exchange"] or c["bridge"] or c["mixer"]

    G, errors = flows.trace(address.lower(), fetch, EthError, hops=hops, top_k=top_k, per_wallet=per_wallet,
                            direction=direction, min_amount=1.0, is_service=is_service)
    for n in G:
        G.nodes[n]["label"] = ", ".join(labels.get(n, [])[:2])
    return G, errors


def contract_source(address):
    """Verified source of a deployed contract: (files {path: source}, main path, compiler version, name)."""
    d = _get(f"/smart-contracts/{address}")
    if not d or not d.get("source_code"):
        raise EthError("No verified source code is published for this contract.")
    if (d.get("language") or "solidity").lower() != "solidity":
        raise EthError(f"Contract is written in {d.get('language')}; only Solidity is supported.")
    main = d.get("file_path") or f"{d.get('name') or 'Contract'}.sol"
    files = {main: d["source_code"]}
    for extra in d.get("additional_sources") or []:
        files[extra["file_path"]] = extra["source_code"]
    version = (d.get("compiler_version") or "").lstrip("v").split("+")[0]
    return files, main, version, d.get("name") or address
