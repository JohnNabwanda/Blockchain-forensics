"""Build a self-contained interactive HTML dashboard from the pipeline outputs.

    python build_dashboard.py            # writes outputs/dashboard.html (open it in any browser)

Run it after run_pipeline.py. The page needs no server and no internet except for web fonts.
"""
import argparse
import json

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

from src import config

TEMPLATE = config.ROOT / "src" / "dashboard_template.html"
N_CASES = 40          # flagged cases shown in the case browser
MAX_NBRS = 36         # nodes per neighbourhood drawing


def pr_points(y, p, n=160):
    prec, rec, _ = precision_recall_curve(y, p)
    idx = np.unique(np.linspace(0, len(rec) - 1, min(n, len(rec))).astype(int))
    pts = sorted({(round(float(rec[i]), 4), round(float(prec[i]), 4)) for i in idx})
    return [list(x) for x in pts]


def neighbourhood_layout(G, tx, score):
    U = G.to_undirected(as_view=True)
    nbrs = list(U.neighbors(tx))[:MAX_NBRS - 1]
    H = G.subgraph([tx] + nbrs)
    pos = nx.spring_layout(H.to_undirected(), seed=3, center=(0, 0))
    xs = np.array([v[0] for v in pos.values()]); ys = np.array([v[1] for v in pos.values()])
    span = max(np.ptp(xs), np.ptp(ys), 1e-9)
    norm = {n: [round(float((pos[n][0] - xs.mean()) / span), 3), round(float((pos[n][1] - ys.mean()) / span), 3)]
            for n in H}
    return {"nodes": [{"id": str(n), "x": norm[n][0], "y": norm[n][1],
                       "s": None if np.isnan(score.get(n, np.nan)) else round(float(score[n]), 3),
                       "self": n == tx} for n in H],
            "edges": [[str(a), str(b)] for a, b in H.edges]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fragment", action="store_true", help="omit the html/head/body wrapper")
    ap.add_argument("--out", default=str(config.OUTPUT_DIR / "dashboard.html"))
    args = ap.parse_args()
    out = config.OUTPUT_DIR

    meta = json.load(open(out / "meta.json"))
    results = pd.read_csv(out / "results.csv")
    scored = pd.read_csv(out / "scored_test.csv")
    steps = pd.read_csv(out / "per_step_test.csv")
    by_set = pd.read_csv(out / "test_scores_by_set.csv")
    expl = json.load(open(out / "explanations.json"))
    nodes = pd.read_csv(out / "nodes_test.csv")
    edges = pd.read_csv(out / "edges_test.csv")

    y = by_set["label"].values
    set_names = [c for c in by_set.columns if c.startswith("Set")]
    curves = [{"name": s, "pr_auc": round(float(average_precision_score(y, by_set[s])), 4),
               "points": pr_points(y, by_set[s].values)} for s in set_names]

    G = nx.DiGraph()
    G.add_nodes_from(nodes["txId"])
    G.add_edges_from(edges[["src", "dst"]].itertuples(index=False, name=None))
    node_score = dict(zip(nodes["txId"], nodes["score"])) if "score" in nodes else dict(zip(scored["txId"], scored["score"]))

    high = scored[scored["band"] == "High"].sort_values("score", ascending=False).head(N_CASES)
    cases = []
    for r in high.itertuples():
        cases.append({"id": str(r.txId), "score": round(float(r.score), 4), "step": int(r.time_step),
                      "label": int(r.label), "reasons": expl.get(str(r.txId), []),
                      "graph": neighbourhood_layout(G, r.txId, node_score)})

    data = {
        "meta": meta,
        "results": results[["model", "feature_set", "n_features", "threshold",
                            "test_precision", "test_recall", "test_f1", "test_pr_auc", "test_roc_auc",
                            "val_pr_auc", "test_flagged", "test_fp", "test_fn"]].round(4).to_dict("records"),
        "curves": curves,
        "steps": steps.round(4).to_dict("records"),
        # compact arrays for the client-side threshold explorer
        "scores": [round(float(s), 4) for s in scored["score"]],
        "labels": [int(v) for v in scored["label"]],
        "cases": cases,
    }
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":"))) \
        .replace("/*__LINKS__*/null", json.dumps(config.switcher_links("phase1")))
    if not args.fragment:
        html = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                '</head><body>' + html + '</body></html>')
    open(args.out, "w").write(html)
    print(f"Dashboard written to {args.out} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
