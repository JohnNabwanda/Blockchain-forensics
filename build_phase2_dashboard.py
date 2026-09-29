"""Build the Phase 2 dashboard (cash-out tracing on synthetic TRON/USDT and mobile-money data).

    python build_phase2_dashboard.py     # writes outputs/phase2/dashboard_phase2.html

Run it after run_phase2.py --stress. It reuses the visual style of the Phase 1 dashboard.
"""
import json
import re

import numpy as np
import pandas as pd

from src import config
from src.phase2.wallets import load_world

TEMPLATE = config.ROOT / "src" / "phase2_template.html"
STYLE_FROM = config.ROOT / "src" / "dashboard_template.html"
N_SCATTER = 1500


def main():
    out = config.PHASE2_OUTPUT_DIR
    chain, _, fx, _, reported = load_world()
    links = pd.read_csv(out / "links.csv", parse_dates=["chain_ts", "mm_ts"])
    pairs = pd.read_csv(out / "attribution.csv")
    leads = pd.read_csv(out / "cash_out_leads.csv")
    clusters = pd.read_csv(out / "clusters.csv")
    taint = pd.read_csv(out / "taint.csv").set_index("address")["hop"]
    metrics = json.load(open(out / "metrics.json"))
    stress = pd.read_csv(out / "stress_test.csv") if (out / "stress_test.csv").exists() else None

    # evaluation only: is the lead's account owned by the wallet owner? (synthetic truth)
    tw = pd.read_csv(config.PHASE2_DATA_DIR / "truth_wallets.csv")
    ta = pd.read_csv(config.PHASE2_DATA_DIR / "truth_accounts.csv")
    ent_w, ent_a = dict(zip(tw["address"], tw["entity"])), dict(zip(ta["account"], ta["entity"]))

    usdt = chain[chain["asset"] == "USDT"]
    reported_set = set(reported["wallet"])
    L = []
    for ld in leads.itertuples():
        wallets = clusters.loc[clusters["cluster"] == ld.cluster, "address"].tolist()
        lk = links[(links["cluster"] == ld.cluster) & (links["mm_account"] == ld.mm_account)].sort_values("chain_ts")
        inflow = usdt[usdt["dst"].isin(wallets) & usdt["src"].isin(reported_set)] \
            .groupby(["src", "dst"])["amount"].agg(["sum", "size"]).reset_index()
        internal = usdt[usdt["src"].isin(wallets) & usdt["dst"].isin(wallets)] \
            .groupby(["src", "dst"])["amount"].sum().reset_index()
        sold = lk.groupby(["wallet", "trader"]).agg(usdt=("usdt", "sum"), n=("usdt", "size")).reset_index()
        paid = lk.groupby("trader").agg(tzs=("tzs", "sum"), usdt=("usdt", "sum"), n=("tzs", "size")).reset_index()
        L.append({
            "cluster": ld.cluster, "account": ld.mm_account, "operator": ld.operator, "confidence": ld.confidence,
            "trades": int(ld.trades), "evidence": float(ld.evidence), "usdt": round(float(ld.usdt), 2),
            "tzs": int(ld.tzs), "traders": int(ld.traders), "hops": int(ld.hops_from_report),
            "first": str(ld.first)[:16], "last": str(ld.last)[:16],
            "wallets": [{"id": w, "hop": int(taint.get(w, -1)), "evidence": clusters.loc[clusters["address"] == w, "evidence"].fillna("").iloc[0]}
                        for w in wallets],
            "flow": {"in": [[r.src, r.dst, round(r.sum, 2), int(r.size)] for r in inflow.itertuples()],
                     "internal": [[r.src, r.dst, round(r.amount, 2)] for r in internal.itertuples()],
                     "sold": [[r.wallet, r.trader, round(r.usdt, 2), int(r.n)] for r in sold.itertuples()],
                     "paid": [[r.trader, int(r.tzs), round(r.usdt, 2), int(r.n)] for r in paid.itertuples()]},
            "links": [[str(r.chain_ts)[:16], r.wallet, r.trader, round(r.usdt, 2), str(r.mm_ts)[:16], int(r.tzs),
                       r.lag_min, round(100 * r.implied_fee, 2), r.link_score, r.usd_tzs] for r in lk.itertuples()],
            "truth_same_owner": ent_w.get(wallets[0]) == ent_a.get(ld.mm_account),
        })

    rng = np.random.default_rng(0)
    sample = links.iloc[rng.choice(len(links), min(N_SCATTER, len(links)), replace=False)]
    data = {
        "meta": {"reported": len(reported), "transfers": int(len(chain)), "days": int(chain["ts"].dt.normalize().nunique()),
                 "sell_window": config.MATCH_SELL_WINDOW_MIN, "buy_window": config.MATCH_BUY_WINDOW_MIN,
                 "fee_range": [100 * x for x in config.MATCH_FEE_RANGE], "hops": config.TAINT_MAX_HOPS,
                 "high": [config.PAIR_HIGH_MIN_TRADES, config.PAIR_HIGH_MIN_EVIDENCE],
                 "medium": [config.PAIR_MEDIUM_MIN_TRADES, config.PAIR_MEDIUM_MIN_EVIDENCE],
                 "fx_min": float(fx["usd_tzs"].min()), "fx_max": float(fx["usd_tzs"].max()),
                 "pairs": len(pairs), "links": len(links)},
        "metrics": metrics,
        "leads": L,
        "scatter": [[s, round(l, 1), round(100 * f, 2)] for s, l, f in zip(sample["side"], sample["lag_min"], sample["implied_fee"])],
        "stress": stress.to_dict("records") if stress is not None else [],
    }
    style = re.search(r"<link rel=\"stylesheet\".*?</style>", STYLE_FROM.read_text(), re.S).group(0)
    html = TEMPLATE.read_text().replace("<!--__STYLE__-->", style) \
        .replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":"), default=str))
    (out / "dashboard_phase2.html").write_text(html)
    print(f"Dashboard written to {out / 'dashboard_phase2.html'} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
