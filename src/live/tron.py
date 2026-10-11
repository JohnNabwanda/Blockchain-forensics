"""Live TRON / USDT wallet investigation from the public TronGrid API.

Fetches a wallet's real USDT (TRC-20) transfers, summarises its behaviour, follows funds a few hops
forward and backward, and scores risk from transparent indicators. Every indicator is a lead for an
analyst, never proof of wrongdoing.
"""
import hashlib
import time

import pandas as pd
import requests

from .. import config
from . import feedback, flows

API = "https://api.trongrid.io"
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
PAGE = 200


class TronError(RuntimeError):
    pass


def _headers():
    key = config.secret("tron", "api_key")
    return {"TRON-PRO-API-KEY": key} if key else {}


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def valid_address(addr):
    """A TRON address: base58check of 0x41 + 20 bytes, so a mistyped character fails the checksum."""
    if not (isinstance(addr, str) and len(addr) == 34 and addr.startswith("T") and all(c in B58 for c in addr)):
        return False
    n = 0
    for c in addr:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes(25, "big")
    return raw[0] == 0x41 and hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4] == raw[21:]


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
    return flows.with_direction(pd.DataFrame(rows[:max_transfers], columns=flows.COLUMNS), address)


def fetch_account(address):
    """Basic account facts: creation time and TRX balance."""
    r = requests.get(f"{API}/v1/accounts/{address}", headers=_headers(), timeout=20).json()
    data = (r.get("data") or [{}])[0]
    created = data.get("create_time")
    return {"exists": bool(r.get("data")),
            "created": pd.to_datetime(created, unit="ms", utc=True) if created else None,
            "trx_balance": data.get("balance", 0) / 1e6}


# Behaviour summary, indicators and tracing are shared with the other chains (flows.py)
summarise = flows.summarise
counterparties = flows.counterparties
risk_indicators = flows.risk_indicators
risk_score = flows.risk_score


def band(score):
    return feedback.band("tron", score)


def trace(address, hops=2, top_k=4, per_wallet=300, direction="out", min_usdt=1.0):
    """Follow the largest USDT flows `hops` steps forward (out) or backward (in) from `address`."""
    return flows.trace(address, lambda w, n: fetch_transfers(w, max_transfers=n), TronError, hops=hops, top_k=top_k,
                       per_wallet=per_wallet, direction=direction, min_amount=min_usdt)
