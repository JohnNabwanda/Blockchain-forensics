"""Phase 2: TRON/USDT wallet analysis and off-chain (mobile-money) attribution, on SYNTHETIC data.

    python run_phase2.py              # generate the synthetic world (first run) and analyse it
    python run_phase2.py --regenerate # rebuild the synthetic world
    python run_phase2.py --stress     # also re-run under harder assumptions (takes a few minutes)

No real mobile-money or P2P records are used (concept note, Section 12). The results show that the
logic works end to end and how it degrades; they say nothing about real-world accuracy.
"""
import argparse
import json
import shutil
import time

import pandas as pd

from src import config
from src.phase2.evaluate import evaluate
from src.phase2.matching import assign_links, attribute, candidate_links, cash_out_leads
from src.phase2.synthetic_world import make_phase2_world
from src.phase2.wallets import cluster_wallets, detect_services, load_world, trace_taint, wallet_features

STRESS = [   # name, generator settings, what it tests
    ("baseline", {}, "assumptions shared with the matcher"),
    ("3x decoy payments", {"decoy_factor": 3}, "busier trader mobile-money accounts"),
    ("10x decoy payments", {"decoy_factor": 10}, "very busy trader accounts"),
    ("slow settlement", {"timing_scale": 3}, "trader pays up to 60 min later (window is 45)"),
    ("wider spreads", {"fee_scale": 2}, "trader spread up to 6% (accepted range ends at 5%)"),
    ("all combined", {"decoy_factor": 3, "timing_scale": 2, "fee_scale": 1.5}, "several things at once"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def analyse(data_dir, verbose=True):
    say = log if verbose else (lambda *_: None)
    chain, mm, fx, directory, reported = load_world(data_dir)
    say(f"  {len(chain):,} chain transfers, {len(mm):,} mobile-money payments, {len(reported)} reported wallets")
    hot, deposits = detect_services(chain)
    feats = wallet_features(chain, hot, deposits)
    traders = set(feats.index[feats["p2p_trader"]])
    say(f"  services: {len(hot)} exchange hot wallets, {len(deposits)} deposit addresses; {len(traders)} P2P-trader wallets")
    clusters = cluster_wallets(chain, hot, deposits, traders)
    say(f"  {clusters['cluster'].nunique():,} clusters from {len(clusters):,} addresses")
    cand = candidate_links(chain, mm, fx, directory, traders, clusters)
    links = assign_links(cand)
    pairs = attribute(links)
    taint = trace_taint(chain, reported["wallet"], hot | deposits | traders)
    leads = cash_out_leads(pairs, clusters, taint)
    say(f"  {len(cand):,} candidate links -> {len(links):,} assigned -> {len(pairs):,} account pairs, {len(leads)} cash-out leads")
    metrics, pairs = evaluate(data_dir, hot, deposits, feats, clusters, links, pairs, leads, directory)
    leads = leads.merge(pairs[["cluster", "mm_account", "correct"]], on=["cluster", "mm_account"], how="left")
    return dict(chain=chain, mm=mm, feats=feats, clusters=clusters, links=links, pairs=pairs, leads=leads,
                taint=taint, reported=reported, metrics=metrics, n_cand=len(cand))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regenerate", action="store_true")
    ap.add_argument("--stress", action="store_true")
    args = ap.parse_args()
    data_dir, out = config.PHASE2_DATA_DIR, config.PHASE2_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    if args.regenerate or not (data_dir / "chain_transfers.csv").exists():
        log("Generating synthetic TRON/USDT and mobile-money world (for testing the logic only)")
        make_phase2_world(data_dir)
    log("Analysing")
    r = analyse(data_dir)

    r["feats"].sort_values("trader_score", ascending=False).to_csv(out / "wallet_features.csv")
    r["clusters"].to_csv(out / "clusters.csv", index=False)
    r["links"].to_csv(out / "links.csv", index=False)
    r["pairs"].drop(columns="correct").to_csv(out / "attribution.csv", index=False)
    r["leads"].drop(columns="correct").to_csv(out / "cash_out_leads.csv", index=False)
    r["taint"].to_csv(out / "taint.csv")

    stress = None
    if args.stress:
        rows = []
        for name, kw, why in STRESS:
            log(f"Stress test: {name}")
            d = config.ROOT / "data" / "phase2_stress" / name.replace(" ", "_")
            make_phase2_world(d, seed=1, **kw)          # a different world from the one analysed above
            m = analyse(d, verbose=False)["metrics"]
            hb = m["attribution"]["by_confidence"]["High"]
            rows.append({"scenario": name, "tests": why, "trader_recall": m["p2p_traders"]["recall"],
                         "link_precision": m["links"]["precision"], "link_recall": m["links"]["recall"],
                         "high_pairs": hb["pairs"], "high_precision": hb["precision"],
                         "owner_recall_high": m["attribution"]["recall_high"],
                         "mule_accounts_found": f"{m['leads']['found_high_medium']}/{m['leads']['mule_accounts_cashing_out']}",
                         "wrong_leads": m["leads"]["wrong_leads_high_medium"]})
        stress = pd.DataFrame(rows)
        stress.to_csv(out / "stress_test.csv", index=False)
        shutil.rmtree(config.ROOT / "data" / "phase2_stress", ignore_errors=True)

    json.dump(r["metrics"], open(out / "metrics.json", "w"), indent=1, default=str)
    write_report(r, stress, out)
    log(f"Done. Outputs in {out}")


def write_report(r, stress, out):
    m = r["metrics"]
    fmt = lambda v: "n/a" if v is None else f"{v:.3f}"
    L = ["> **SYNTHETIC DATA.** Every wallet, account and payment was generated. These results show the logic works "
         "and how it degrades; they say nothing about real P2P markets or mobile-money records.", "",
         "# Phase 2 Results: TRON/USDT wallets and off-chain attribution", "",
         f"{len(r['chain']):,} on-chain transfers and {len(r['mm']):,} mobile-money payments over "
         f"{r['chain']['ts'].dt.normalize().nunique()} days. {len(r['reported'])} wallets reported by victims.", "",
         "## 1. Services and P2P traders", "",
         "| Detected | Found | Actual | Precision | Recall |", "|---|---|---|---|---|"]
    for k, lab in [("hot_wallets", "Exchange hot wallets"), ("deposit_addresses", "Exchange deposit addresses"),
                   ("p2p_traders", "P2P-trader wallets")]:
        x = m[k]
        L.append(f"| {lab} | {x['predicted']} | {x['actual']} | {fmt(x['precision'])} | {fmt(x['recall'])} |")
    cl = m["clustering"]
    L += ["", "## 2. Wallet clustering", "",
          f"Deposit-address reuse and TRX activation funding, over {cl['wallets']:,} wallets "
          f"({cl['owners_with_several_wallets']} owners have more than one). Pairwise precision {fmt(cl['pair_precision'])}: "
          f"of address pairs put in the same cluster, this share really have one owner. Pairwise recall "
          f"{fmt(cl['pair_recall'])}: of same-owner pairs, this share were joined.", "",
          "## 3. Linking trades to mobile-money payments", "",
          f"{r['n_cand']:,} candidate links passed the time window and exchange-rate check; one-to-one assignment kept "
          f"{m['links']['predicted']:,}. Link precision {fmt(m['links']['precision'])}, recall {fmt(m['links']['recall'])} "
          f"(out of {m['links']['actual']:,} {m['links']['eligible_note']}).", "",
          "| Confidence | Wallet-cluster to account pairs | Correct | Precision |", "|---|---|---|---|"]
    for band, x in m["attribution"]["by_confidence"].items():
        L.append(f"| {band} | {x['pairs']} | {x['correct']} | {fmt(x['precision'])} |")
    L += ["", f"Of {m['attribution']['attributable_owners']} owners with at least two mobile-money-settled trades, "
          f"{m['attribution']['recall_high']:.1%} were linked to their own account at High confidence and "
          f"{m['attribution']['recall_high_medium']:.1%} at High or Medium.", "",
          "## 4. Cash-out leads from victim reports", "",
          f"Funds were traced up to {config.TAINT_MAX_HOPS} hops from the reported wallets, stopping at exchanges and "
          f"traders. {m['leads']['found_high_medium']} of {m['leads']['mule_accounts_cashing_out']} mule mobile-money "
          f"accounts that cashed out through detected traders appear as High or Medium leads; "
          f"{m['leads']['wrong_leads_high_medium']} High or Medium leads point to someone else.", ""]
    if stress is not None:
        L += ["## 5. Stress test", "",
              "The generator and the matcher share assumptions, so the baseline flatters the method. Each scenario "
              "breaks one assumption.", "",
              "| Scenario | Tests | Trader recall | Link precision | Link recall | High pairs | High precision | "
              "Owners found (High) | Mule accounts found | Wrong leads |", "|---|---|---|---|---|---|---|---|---|---|"]
        for x in stress.itertuples():
            L.append(f"| {x.scenario} | {x.tests} | {fmt(x.trader_recall)} | {fmt(x.link_precision)} | "
                     f"{fmt(x.link_recall)} | {x.high_pairs} | {fmt(x.high_precision)} | {x.owner_recall_high:.1%} | "
                     f"{x.mule_accounts_found} | {x.wrong_leads} |")
        L.append("")
    else:
        L += ["## 5. Stress test", "", "Not run this time. Run `python run_phase2.py --stress` to add it.", ""]
    L += ["## What this does not show", "",
          "- Real accuracy. Real traders, fees, delays and decoy traffic will differ from the generator. The stress "
          "test shows settlement delay and trader spread matter most: both must be calibrated on real statements.",
          "- Real coincidences. High-confidence precision is perfect here partly because generated decoy payments never "
          "repeat for the same wallet and account. Family members or regular customers paying a trader will create "
          "some false High links in real data.",
          "- Nominee accounts. Mules often cash out through a relative's or an agent's account. A correct link then "
          "points to the account holder, who may not be the wallet owner.",
          "- Identity. A link says a wallet and an account co-occur in trades; an analyst must verify it through "
          "lawful process before any action.",
          "- Access. Trader mobile-money statements (trader_directory.csv here) require lawful requests to operators.", ""]
    (out / "report.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
