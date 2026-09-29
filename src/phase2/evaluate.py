"""Score Phase 2 outputs against the synthetic ground truth. The only module that reads truth_*.csv."""
import pandas as pd


def _pr(pred, true):
    pred, true = set(pred), set(true)
    tp = len(pred & true)
    return {"predicted": len(pred), "actual": len(true), "correct": tp,
            "precision": round(tp / len(pred), 3) if pred else None,
            "recall": round(tp / len(true), 3) if true else None}


def _pairs(n):
    return n * (n - 1) // 2


def evaluate(data_dir, hot, deposits, feats, clusters, links, pairs, leads, directory):
    tw = pd.read_csv(data_dir / "truth_wallets.csv")
    ta = pd.read_csv(data_dir / "truth_accounts.csv")
    tt = pd.read_csv(data_dir / "truth_trades.csv").fillna({"mm_tx": ""})
    ent_w, ent_a = dict(zip(tw["address"], tw["entity"])), dict(zip(ta["account"], ta["entity"]))
    role = dict(zip(tw["address"], tw["role"]))
    m = {}
    m["hot_wallets"] = _pr(hot, tw.loc[tw["role"] == "hot_wallet", "address"])
    m["deposit_addresses"] = _pr(deposits, tw.loc[tw["role"] == "deposit", "address"])
    m["p2p_traders"] = _pr(feats.index[feats["p2p_trader"]], tw.loc[tw["role"] == "trader", "address"])

    # clustering: pairwise precision and recall over wallets people control directly
    c = clusters[clusters["address"].map(role).isin(["user", "trader", "mule", "scam_collection"])].copy()
    c["entity"] = c["address"].map(ent_w)
    same_both = c.groupby(["cluster", "entity"]).size().map(_pairs).sum()
    pred_pairs = c.groupby("cluster").size().map(_pairs).sum()
    true_pairs = c.groupby("entity").size().map(_pairs).sum()
    multi = c.groupby("entity").size()
    m["clustering"] = {"wallets": len(c), "owners_with_several_wallets": int((multi > 1).sum()),
                       "pair_precision": round(same_both / pred_pairs, 3) if pred_pairs else None,
                       "pair_recall": round(same_both / true_pairs, 3) if true_pairs else None}

    # links: only trades of traders the system detected can be linked
    detected_traders = set(directory.loc[directory["identifier"].isin(feats.index[feats["p2p_trader"]]), "trader_id"])
    elig = tt[tt["trader"].isin(detected_traders) & (tt["mm_tx"] != "")]
    m["links"] = _pr(zip(links["chain_tx"], links["mm_tx"]), zip(elig["chain_tx"], elig["mm_tx"]))
    m["links"]["eligible_note"] = "trades of detected traders that were settled by mobile money"

    # pairs: correct when the wallet cluster and the mobile-money account have the same owner
    pairs = pairs.assign(correct=[ent_w.get(w.split(";")[0]) == ent_a.get(a)
                                  for w, a in zip(pairs["wallets"], pairs["mm_account"])])
    attributable = elig.groupby("counterparty").size()
    attributable = set(attributable[attributable >= 2].index)
    by_band = {}
    for band in ["High", "Medium", "Low"]:
        b = pairs[pairs["confidence"] == band]
        by_band[band] = {"pairs": len(b), "correct": int(b["correct"].sum()),
                         "precision": round(b["correct"].mean(), 3) if len(b) else None}
    found = lambda bands: {ent_a.get(a) for a, ok, cf in zip(pairs["mm_account"], pairs["correct"], pairs["confidence"])
                           if ok and cf in bands}
    m["attribution"] = {"by_confidence": by_band, "attributable_owners": len(attributable),
                        "recall_high": round(len(found({"High"}) & attributable) / max(len(attributable), 1), 3),
                        "recall_high_medium": round(len(found({"High", "Medium"}) & attributable) / max(len(attributable), 1), 3)}

    # cash-out leads: did we reach the mules' mobile-money accounts, and only those?
    mule_accounts = set(ta.loc[ta["entity"].str.startswith("mule"), "account"])
    cashed = {a for a in mule_accounts if ent_a[a] in set(elig["counterparty"])}
    strong = leads[leads["confidence"].isin(["High", "Medium"])]
    m["leads"] = {"mule_accounts_cashing_out": len(cashed),
                  "found_high_medium": len(set(strong["mm_account"]) & cashed),
                  "recall": round(len(set(strong["mm_account"]) & cashed) / max(len(cashed), 1), 3),
                  "leads_high_medium": int(len(strong)),
                  "wrong_leads_high_medium": int((~strong["mm_account"].isin(mule_accounts)).sum()),
                  "leads_all": int(len(leads))}
    return m, pairs
