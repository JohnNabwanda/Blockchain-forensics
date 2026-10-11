"""Build the mobile-money test statements in demo/statements/ from one wallet's real USDT transfers.

    .venv/bin/python demo/make_statements.py

The on-chain side is real: the OFAC-listed TRON wallet below and its actual USDT transfers. The
mobile-money side is made up for testing: every account is a TEST-ACC-… placeholder, never a real
number, and each payment is placed relative to a real transfer so that the matching engine has
something to find (or, on purpose, nothing). Import each file with the wallet below and rate 2700.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.live import tron                         # noqa: E402

WALLET = "TTjHn8qNVxazB3UroiekGRPuM2w2GwvNbn"
RATE = 2700.0                                     # USD/TZS entered on the page
SPREAD = 0.015                                    # a typical P2P trader margin
LOCAL = "Africa/Dar_es_Salaam"
OUT = ROOT / "demo" / "statements"


def picks(tx, counterparty, direction, n):
    t = tx[(tx["counterparty"] == counterparty) & (tx["direction"] == direction) & (tx["amount"] >= 50)]
    return t.sort_values("ts").head(n)


def rows(t, account, operator, lag_min=None, spread=SPREAD):
    """One payment per transfer. Trader sent USDT ("out"): the buyer paid shillings to the trader first.
    Trader received USDT ("in"): the trader paid the seller shillings shortly after."""
    out = []
    for r in t.itertuples():
        buyer_paid = r.direction == "out"
        lag = lag_min if lag_min is not None else (-6 if buyer_paid else 4)
        ts = (r.ts + pd.Timedelta(minutes=lag)).tz_convert(LOCAL).tz_localize(None)
        factor = 1 + spread if buyer_paid else 1 - spread
        out.append({"ts": ts.strftime("%Y-%m-%d %H:%M:%S"), "direction": "in" if buyer_paid else "out",
                    "counterparty_account": account, "amount_tzs": round(r.amount * RATE * factor, -2),
                    "operator": operator})
    return out


def save(name, data):
    df = pd.DataFrame(data).sort_values("ts")
    df.to_csv(OUT / name, index=False)
    print(f"  {name}: {len(df)} rows")


def main():
    tx = tron.fetch_transfers(WALLET, max_transfers=3000)
    high = rows(picks(tx, "TDxQY8axwyTEWXiixVzVBG6Q46zKLU9fjb", "out", 5), "TEST-ACC-0001", "M-Pesa")
    medium = rows(picks(tx, "TBfmthKfVDWbmxzaFmtp61zaTHiyNaLfLs", "in", 2), "TEST-ACC-0002", "Airtel Money")
    low = rows(picks(tx, "TRcB6eKEAnwDfsFV1n7ar9BSqm9s4YwGdz", "in", 1), "TEST-ACC-0003", "Tigo Pesa")
    late = rows(picks(tx, "TPC9By4t2rzCCMe1MnugRLtCSPbeiBe4wJ", "out", 4), "TEST-ACC-0004", "HaloPesa", lag_min=-180)
    spread = rows(picks(tx, "TGFWLzVvyDdwnrN3XKKGsqthFf61nTX155", "out", 4), "TEST-ACC-0005", "M-Pesa", spread=0.12)
    decoys = [{"ts": "2025-11-15 09:00:00", "direction": "out", "counterparty_account": "TEST-ACC-0090",
               "amount_tzs": 150000, "operator": "M-Pesa"},
              {"ts": "2025-11-20 18:30:00", "direction": "in", "counterparty_account": "TEST-ACC-0091",
               "amount_tzs": 820000, "operator": "Airtel Money"},
              {"ts": "2025-12-03 12:10:00", "direction": "out", "counterparty_account": "TEST-ACC-0092",
               "amount_tzs": 45000, "operator": "Tigo Pesa"}]
    save("mm1_high_repeated_trades.csv", high)
    save("mm2_medium_two_trades.csv", medium)
    save("mm3_low_single_trade.csv", low)
    save("mm4_no_match_timing.csv", late)
    save("mm5_no_match_spread.csv", spread)
    save("mm6_mixed_high_medium_low.csv", high + medium + low + decoys)


if __name__ == "__main__":
    main()
