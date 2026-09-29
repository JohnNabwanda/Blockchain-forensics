"""Address-level analysis for account-based chains (TRON): services, P2P traders and wallet clusters.

Bitcoin (Phase 1) links transactions; TRON moves value between persistent accounts, so the graph
here is address-to-address and wallets can be clustered (concept note, Section 7). No ground truth
is read in this module.
"""
import numpy as np
import pandas as pd

from .. import config


def load_world(data_dir=config.PHASE2_DATA_DIR):
    chain = pd.read_csv(data_dir / "chain_transfers.csv", parse_dates=["ts"])
    mm = pd.read_csv(data_dir / "mobile_money.csv", parse_dates=["ts"])
    for df in (chain, mm):      # work in plain East Africa Time; mixing tz-aware and numpy times shifts them
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Africa/Dar_es_Salaam").dt.tz_localize(None)
    fx = pd.read_csv(data_dir / "fx_rates.csv")
    directory = pd.read_csv(data_dir / "trader_directory.csv")
    reported = pd.read_csv(data_dir / "reported_wallets.csv")
    return chain, mm, fx, directory, reported


def detect_services(chain):
    """Exchange deposit addresses and hot wallets.

    A deposit address forwards (almost) everything it receives to a single destination within a few
    hours. A destination fed by many deposit addresses is an exchange hot wallet.
    """
    u = chain[chain["asset"] == "USDT"]
    out = u.groupby("src").agg(n_dst=("dst", "nunique"), dst=("dst", "first"), out_sum=("amount", "sum"))
    inn = u.groupby("dst")["amount"].sum().rename("in_sum")
    c = out[out["n_dst"] == 1].join(inn, how="inner")
    c = c[(c["out_sum"] / c["in_sum"]).between(config.DEPOSIT_MIN_FORWARD_SHARE, 1.001)]
    # every outgoing sweep must follow an incoming payment within the time limit
    rcv = u[u["dst"].isin(c.index)][["dst", "ts"]].rename(columns={"dst": "addr", "ts": "t_in"}).sort_values("t_in")
    snd = u[u["src"].isin(c.index)][["src", "ts"]].rename(columns={"src": "addr", "ts": "t_out"}).sort_values("t_out")
    m = pd.merge_asof(snd, rcv, left_on="t_out", right_on="t_in", by="addr", direction="backward")
    lag_h = (m["t_out"] - m["t_in"]).dt.total_seconds() / 3600
    ok = lag_h.le(config.DEPOSIT_MAX_SWEEP_HOURS).groupby(m["addr"]).all()
    c = c[c.index.isin(ok[ok].index)]
    fed = c.groupby("dst").size()
    hot = set(fed[fed >= config.HOT_WALLET_MIN_DEPOSITS].index)
    deposits = set(c[c["dst"].isin(hot)].index)
    return hot, deposits


def wallet_features(chain, hot, deposits):
    """One row per address with the behaviour that separates P2P traders from everyone else."""
    u = chain[chain["asset"] == "USDT"]
    n_days = max(1, (u["ts"].max().normalize() - u["ts"].min().normalize()).days + 1)
    both = pd.concat([u[["src", "ts", "amount"]].rename(columns={"src": "address"}),
                      u[["dst", "ts", "amount"]].rename(columns={"dst": "address"})])
    f = pd.DataFrame({
        "senders": u.groupby("dst")["src"].nunique(),
        "receivers": u.groupby("src")["dst"].nunique(),
        "n_in": u.groupby("dst").size(),
        "n_out": u.groupby("src").size(),
        "usdt_in": u.groupby("dst")["amount"].sum(),
        "usdt_out": u.groupby("src")["amount"].sum(),
    }).fillna(0)
    f["active_share"] = both.groupby("address")["ts"].apply(lambda s: s.dt.normalize().nunique()) / n_days
    f["round_share"] = both.assign(r=(both["amount"] % 10 == 0)).groupby("address")["r"].mean()
    f["balance"] = np.minimum(f["senders"], f["receivers"]) / np.maximum(f[["senders", "receivers"]].max(axis=1), 1)
    f["service"] = np.where(f.index.isin(hot), "exchange_hot_wallet", np.where(f.index.isin(deposits), "exchange_deposit", ""))
    ranks = f[["senders", "receivers", "balance", "active_share"]].rank(pct=True)
    f["trader_score"] = ranks.mean(axis=1).round(4)
    f["p2p_trader"] = ((f["senders"] >= config.TRADER_MIN_COUNTERPARTIES) &
                       (f["receivers"] >= config.TRADER_MIN_COUNTERPARTIES) &
                       (f["balance"] >= config.TRADER_MIN_BALANCE) &
                       (f["active_share"] >= config.TRADER_MIN_ACTIVE_SHARE) & (f["service"] == ""))
    return f.rename_axis("address")


class _UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def cluster_wallets(chain, hot, deposits, traders):
    """Group addresses that are probably controlled by the same person or organisation.

    H1 deposit-address reuse: an exchange gives each customer one deposit address, so addresses that
       pay into the same deposit address belong to the same customer.
    H2 activation funding: a new TRON account must first receive TRX; if an ordinary wallet (not an
       exchange or trader) paid for that, the two are probably the same owner.
    Returns address -> cluster id, and which heuristic linked each address.
    """
    uf, how = _UnionFind(), {}
    services = hot | deposits
    usdt = chain[chain["asset"] == "USDT"]
    to_dep = usdt[usdt["dst"].isin(deposits) & ~usdt["src"].isin(services)]
    for _, g in to_dep.groupby("dst"):
        s = g["src"].unique()
        for a in s[1:]:
            uf.union(s[0], a)
        if len(s) > 1:
            for a in s:
                how.setdefault(a, set()).add("deposit reuse")
    trx = chain[chain["asset"] == "TRX"].sort_values("ts").drop_duplicates("dst")
    first_in = chain.sort_values("ts").drop_duplicates("dst").set_index("dst")["asset"]
    trx = trx[(first_in.reindex(trx["dst"]).values == "TRX") &
              ~trx["src"].isin(services | traders) & ~trx["dst"].isin(services)]
    for s, d in trx[["src", "dst"]].itertuples(index=False):
        uf.union(s, d)
        how.setdefault(s, set()).add("activation")
        how.setdefault(d, set()).add("activation")
    addrs = pd.unique(pd.concat([chain["src"], chain["dst"]]))
    root = {a: uf.find(a) for a in addrs}
    ids = {r: f"C{i:05d}" for i, r in enumerate(sorted(set(root.values())))}
    out = pd.DataFrame({"address": addrs, "cluster": [ids[root[a]] for a in addrs],
                        "evidence": [", ".join(sorted(how.get(a, []))) for a in addrs]})
    out["cluster_size"] = out.groupby("cluster")["address"].transform("size")
    return out


def trace_taint(chain, reported, stop, hops=config.TAINT_MAX_HOPS):
    """Follow USDT forward from victim-reported wallets, stopping at exchanges and P2P traders.

    Stopping at services matters: an exchange or trader handles money for thousands of innocent
    people, so taint must not spread through them.
    """
    u = chain[chain["asset"] == "USDT"]
    hop = {w: 0 for w in reported}
    frontier = set(reported)
    for h in range(1, hops + 1):
        nxt = set(u.loc[u["src"].isin(frontier), "dst"]) - set(stop) - set(hop)
        hop.update({w: h for w in nxt})
        frontier = nxt
    return pd.Series(hop, name="hop").rename_axis("address")
