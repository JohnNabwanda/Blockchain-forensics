"""Mobile-money attribution on imported records.

An investigator imports a P2P trader's mobile-money statement (obtained from the operator under
lawful access) and the platform matches each payment to the trader's USDT transfers on TRON, using
the matching engine from src/phase2/matching.py (time window, implied exchange-rate spread,
repetition across trades).

Statement CSV columns:
    ts                     payment time (local time, e.g. 2026-06-01 14:05:00)
    direction              out = trader paid the counterparty, in = trader was paid
    counterparty_account   the other party's mobile-money account or phone number
    amount_tzs             amount in shillings
    operator               optional: the counterparty's operator (M-Pesa, Airtel Money, ...)
"""
import pandas as pd

from .. import config
from ..phase2 import matching

STATEMENT_COLUMNS = ["ts", "direction", "counterparty_account", "amount_tzs", "operator"]
LOCAL_TZ = "Africa/Dar_es_Salaam"
TRADER_ACCOUNT = "__trader__"


def read_statement(f):
    s = pd.read_csv(f)
    s.columns = [c.strip().lower() for c in s.columns]
    missing = [c for c in STATEMENT_COLUMNS[:4] if c not in s.columns]
    if missing:
        raise ValueError(f"Statement is missing columns: {', '.join(missing)}. "
                         f"Expected: {', '.join(STATEMENT_COLUMNS)}")
    s["direction"] = s["direction"].str.strip().str.lower()
    if not s["direction"].isin(["in", "out"]).all():
        raise ValueError("direction must be 'in' or 'out' on every row")
    s["ts"] = pd.to_datetime(s["ts"])
    if s["ts"].dt.tz is not None:
        s["ts"] = s["ts"].dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    s["amount_tzs"] = pd.to_numeric(s["amount_tzs"])
    if "operator" not in s:
        s["operator"] = ""
    return s


def _local(ts):
    return pd.to_datetime(ts, utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)


def match(trader_wallets, transfers, statement, usd_tzs):
    """Link trader statement rows to USDT transfers.

    trader_wallets: the trader's TRON addresses; transfers: their USDT transfers (src, dst, amount, ts, tx_id);
    usd_tzs: a single rate, or a DataFrame with date and usd_tzs columns.
    Returns (links, pairs): one row per matched trade, and counterparty wallet <-> account pairs.
    """
    chain = transfers.assign(asset="USDT", ts=_local(transfers["ts"]))
    st = statement.reset_index(drop=True)
    mm = pd.DataFrame({
        "mm_id": [f"ROW{i + 2}" for i in range(len(st))],     # row number in the imported file
        "ts": st["ts"],
        "src": st["counterparty_account"].where(st["direction"] == "in", TRADER_ACCOUNT),
        "dst": st["counterparty_account"].where(st["direction"] == "out", TRADER_ACCOUNT),
        "operator": st["operator"].fillna(""), "dst_operator": st["operator"].fillna(""),
        "amount_tzs": st["amount_tzs"]})
    if isinstance(usd_tzs, pd.DataFrame):
        fx = usd_tzs
    else:
        days = pd.date_range(min(chain["ts"].min(), mm["ts"].min()).normalize(),
                             max(chain["ts"].max(), mm["ts"].max()).normalize())
        fx = pd.DataFrame({"date": days.date, "usd_tzs": float(usd_tzs)})
    directory = pd.DataFrame({"trader_id": "trader", "kind": ["wallet"] * len(trader_wallets) + ["mm_account"],
                              "identifier": list(trader_wallets) + [TRADER_ACCOUNT]})
    addrs = pd.unique(pd.concat([chain["src"], chain["dst"]]))
    clusters = pd.DataFrame({"address": addrs, "cluster": addrs})        # no clustering on live data yet
    cand = matching.candidate_links(chain, mm, fx, directory, set(trader_wallets), clusters)
    links = matching.assign_links(cand)
    pairs = matching.attribute(links) if len(links) else pd.DataFrame()
    if len(pairs):
        pairs = pairs.rename(columns={"cluster": "wallet"}).drop(columns=["wallets", "traders"])
    return links, pairs


def sample_case():
    """A labelled SAMPLE for training: one synthetic trader from the Phase 2 generator.

    Returns (trader_wallets, transfers, statement, fx) in the same shapes as real imports.
    """
    d = config.PHASE2_DATA_DIR
    directory = pd.read_csv(d / "trader_directory.csv")
    t = directory[directory["trader_id"] == "trader-00"]
    wallets = list(t.loc[t["kind"] == "wallet", "identifier"])
    accounts = set(t.loc[t["kind"] == "mm_account", "identifier"])
    chain = pd.read_csv(d / "chain_transfers.csv")
    chain = chain[(chain["asset"] == "USDT") & (chain["src"].isin(wallets) | chain["dst"].isin(wallets))]
    chain = chain.assign(ts=pd.to_datetime(chain["ts"], utc=True))[["tx_id", "ts", "src", "dst", "amount"]]
    mm = pd.read_csv(d / "mobile_money.csv")
    mm = mm[mm["src"].isin(accounts) | mm["dst"].isin(accounts)]
    out = mm["src"].isin(accounts)
    statement = pd.DataFrame({
        "ts": pd.to_datetime(mm["ts"], utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None),
        "direction": out.map({True: "out", False: "in"}),
        "counterparty_account": mm["dst"].where(out, mm["src"]),
        "amount_tzs": mm["amount_tzs"],
        "operator": mm["dst_operator"].where(out, mm["operator"])}).reset_index(drop=True)
    fx = pd.read_csv(d / "fx_rates.csv")
    return wallets, chain.reset_index(drop=True), statement, fx
