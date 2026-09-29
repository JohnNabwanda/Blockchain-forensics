"""Off-chain attribution: link on-chain P2P trades to mobile-money payments (concept note, Section 12.3).

Inputs are a detected P2P trader's wallets, and that trader's mobile-money statement obtained
under lawful access (trader_directory.csv stands in for this). For each USDT transfer between the
trader and a counterparty wallet we look for the matching shilling payment:

    time window     a seller is paid after sending USDT; a buyer pays before receiving it
    amount          shillings / (USDT x exchange rate) must imply a plausible trader spread
    repetition      the same wallet cluster and mobile-money account co-occurring across trades

Every link is a lead for an analyst to verify, never proof of who owns a wallet.
"""
import numpy as np
import pandas as pd

from .. import config


def candidate_links(chain, mm, fx, directory, trader_wallets, clusters):
    rate = dict(zip(pd.to_datetime(fx["date"]).dt.date, fx["usd_tzs"]))
    d = directory[directory["trader_id"].isin(
        directory.loc[directory["identifier"].isin(trader_wallets), "trader_id"])]
    wallet_of = dict(d.loc[d["kind"] == "wallet", ["identifier", "trader_id"]].values)
    accounts = d[d["kind"] == "mm_account"].groupby("trader_id")["identifier"].apply(set).to_dict()
    cluster_of = dict(zip(clusters["address"], clusters["cluster"]))

    u = chain[(chain["asset"] == "USDT") & (chain["src"].isin(wallet_of) ^ chain["dst"].isin(wallet_of))].copy()
    u["side"] = np.where(u["dst"].isin(wallet_of), "sell", "buy")        # from the counterparty's view
    u["trader"] = np.where(u["side"] == "sell", u["dst"].map(wallet_of), u["src"].map(wallet_of))
    u["wallet"] = np.where(u["side"] == "sell", u["src"], u["dst"])
    u["rate"] = u["ts"].dt.date.map(rate)

    rows = []
    for trader, g in u.groupby("trader"):
        accs = accounts.get(trader, set())
        pays = mm[mm["src"].isin(accs)].sort_values("ts")      # trader pays out: counterparty sold USDT
        gets = mm[mm["dst"].isin(accs)].sort_values("ts")      # trader is paid: counterparty bought USDT
        for side, book, win, acct_col, op_col in [("sell", pays, config.MATCH_SELL_WINDOW_MIN, "dst", "dst_operator"),
                                                  ("buy", gets, config.MATCH_BUY_WINDOW_MIN, "src", "operator")]:
            t_book = book["ts"].values
            for r in g[g["side"] == side].itertuples():
                lo = np.searchsorted(t_book, np.datetime64(r.ts + pd.Timedelta(minutes=win[0])))
                hi = np.searchsorted(t_book, np.datetime64(r.ts + pd.Timedelta(minutes=win[1])), side="right")
                for m in book.iloc[lo:hi].itertuples():
                    implied = m.amount_tzs / (r.amount * r.rate)
                    fee = 1 - implied if side == "sell" else implied - 1
                    if not config.MATCH_FEE_RANGE[0] <= fee <= config.MATCH_FEE_RANGE[1]:
                        continue
                    lag = (m.ts - r.ts).total_seconds() / 60
                    s_time = np.exp(-abs(lag) / config.MATCH_TIME_SCALE_MIN)
                    s_amt = np.exp(-0.5 * ((fee - config.MATCH_FEE_TYPICAL) / config.MATCH_FEE_SD) ** 2)
                    rows.append((r.tx_id, m.mm_id, side, trader, r.wallet, cluster_of.get(r.wallet, r.wallet),
                                 getattr(m, acct_col), getattr(m, op_col), r.ts, m.ts, round(lag, 1), r.amount,
                                 m.amount_tzs, round(r.rate, 2), round(fee, 4), round(s_time * s_amt, 4)))
    return pd.DataFrame(rows, columns=["chain_tx", "mm_tx", "side", "trader", "wallet", "cluster", "mm_account",
                                       "operator", "chain_ts", "mm_ts", "lag_min", "usdt", "tzs", "usd_tzs",
                                       "implied_fee", "link_score"])


def assign_links(cand, min_score=config.MATCH_MIN_LINK_SCORE):
    """Greedy one-to-one assignment: each transfer and each payment is used at most once, best first."""
    cand = cand[cand["link_score"] >= min_score].sort_values("link_score", ascending=False)
    used_c, used_m, keep = set(), set(), []
    for i, c, m in zip(cand.index, cand["chain_tx"], cand["mm_tx"]):
        if c not in used_c and m not in used_m:
            used_c.add(c); used_m.add(m); keep.append(i)
    return cand.loc[keep].sort_values("chain_ts").reset_index(drop=True)


def attribute(links):
    """Aggregate links into wallet-cluster <-> mobile-money account pairs with a confidence level."""
    g = links.groupby(["cluster", "mm_account"])
    p = g.agg(trades=("chain_tx", "size"), evidence=("link_score", "sum"), mean_score=("link_score", "mean"),
              usdt=("usdt", "sum"),
              tzs=("tzs", "sum"), traders=("trader", "nunique"), operator=("operator", "first"),
              wallets=("wallet", lambda s: ";".join(sorted(set(s)))),
              first=("chain_ts", "min"), last=("chain_ts", "max")).reset_index()
    # a cluster that trades with several accounts spreads its evidence; favour the dominant account
    p["share_of_cluster"] = p["trades"] / p.groupby("cluster")["trades"].transform("sum")
    high = (p["trades"] >= config.PAIR_HIGH_MIN_TRADES) & (p["evidence"] >= config.PAIR_HIGH_MIN_EVIDENCE) & \
           (p["share_of_cluster"] >= 0.5)
    med = (p["trades"] >= config.PAIR_MEDIUM_MIN_TRADES) & (p["evidence"] >= config.PAIR_MEDIUM_MIN_EVIDENCE)
    p["confidence"] = np.where(high, "High", np.where(med, "Medium", "Low"))
    p[["evidence", "mean_score", "share_of_cluster"]] = p[["evidence", "mean_score", "share_of_cluster"]].round(3)
    order = {"High": 0, "Medium": 1, "Low": 2}
    return p.sort_values(["confidence", "trades"], key=lambda s: s.map(order) if s.name == "confidence" else -s) \
            .reset_index(drop=True)


def cash_out_leads(pairs, clusters, taint):
    """Attribution pairs whose wallet cluster received funds traced from victim-reported wallets."""
    tainted = clusters[clusters["address"].isin(taint.index)]
    hop = tainted.assign(hop=tainted["address"].map(taint)).groupby("cluster")["hop"].min()
    leads = pairs[pairs["cluster"].isin(hop.index)].copy()
    leads["hops_from_report"] = leads["cluster"].map(hop).astype(int)
    return leads.reset_index(drop=True)
