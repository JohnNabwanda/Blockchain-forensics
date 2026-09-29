"""Run the full proof of concept end to end.

    python run_pipeline.py                 # real Elliptic data in data/elliptic_bitcoin_dataset/
    python run_pipeline.py --synthetic     # small synthetic data, to test the code only
    python run_pipeline.py --skip-anomaly  # skip the optional Isolation Forest step
"""
import argparse
import json
import time
from datetime import datetime, timezone

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, precision_recall_curve

from src import config
from src.data import feature_sets, load_elliptic, split, summary
from src.explain import HAS_SHAP, Explainer
from src.graph_features import GRAPH_COLS, compute_graph_features
from src.models import HAS_XGB, choose_threshold, evaluate, get_models, per_step_f1, risk_band


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--skip-anomaly", action="store_true")
    args = ap.parse_args()

    out = config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    data_dir = config.ROOT / "data" / "synthetic" if args.synthetic else \
        (config.ROOT / args.data_dir if args.data_dir else config.DATA_DIR)
    if args.synthetic:
        from src.synthetic import make_synthetic
        if not (data_dir / config.FEATURES_FILE).exists():
            log("Generating synthetic Elliptic-format data (for code testing only)")
            make_synthetic(data_dir)

    # ---- 1. Data ------------------------------------------------------------
    log(f"Loading data from {data_dir}")
    nodes, edges = load_elliptic(data_dir)
    info = summary(nodes, edges)
    log(f"  {info}")

    # ---- 2. Graph features --------------------------------------------------
    log("Computing graph features with NetworkX")
    nodes = compute_graph_features(nodes, edges)
    train, val, test = split(nodes)
    log(f"  labelled rows: train {len(train)}, validation {len(val)}, test {len(test)}")
    sets = feature_sets(GRAPH_COLS)

    # ---- 3. Train every model on every feature set -------------------------
    rows, fitted = [], {}
    for set_name, cols in sets.items():
        models = get_models(train["label"].values)
        for m_name, model in models.items():
            t0 = time.time()
            model.fit(train[cols], train["label"])
            p_val = model.predict_proba(val[cols])[:, 1]
            p_test = model.predict_proba(test[cols])[:, 1]
            thr, met = choose_threshold(val["label"].values, p_val)
            v = evaluate(val["label"].values, p_val, thr)
            te = evaluate(test["label"].values, p_test, thr)
            # original v1 rule, kept for transparent reporting
            thr1, _ = choose_threshold(val["label"].values, p_val, rule="point")
            te1 = evaluate(test["label"].values, p_test, thr1)
            rows.append({"model": m_name, "feature_set": set_name, "n_features": len(cols),
                         "threshold": thr, "threshold_rule": config.THRESHOLD_RULE,
                         "precision_target_met_on_val": met,
                         **{f"val_{k}": x for k, x in v.items()},
                         **{f"test_{k}": x for k, x in te.items()},
                         "v1_threshold": thr1, "v1_test_precision": te1["precision"],
                         "v1_test_recall": te1["recall"], "v1_test_f1": te1["f1"],
                         "fit_seconds": round(time.time() - t0, 1)})
            fitted[(m_name, set_name)] = (model, p_val, p_test, thr)
            log(f"  {m_name:28s} {set_name:22s} thr={thr:.3f} test P={te['precision']:.3f} R={te['recall']:.3f} "
                f"F1={te['f1']:.3f} PR-AUC={te['pr_auc']:.3f} | v1 thr={thr1:.3f} P={te1['precision']:.3f} R={te1['recall']:.3f}")
    results = pd.DataFrame(rows)
    results.to_csv(out / "results.csv", index=False)

    # ---- 4. Pick the demo model on VALIDATION PR-AUC (never on test) --------
    best = results.sort_values("val_pr_auc", ascending=False).iloc[0]
    key = (best["model"], best["feature_set"])
    model, p_val, p_test, thr = fitted[key]
    cols = sets[best["feature_set"]]
    log(f"Selected model (by validation PR-AUC): {key[0]} on {key[1]}, threshold {thr:.3f}")

    # ---- 5. Explanations and scored test set -------------------------------
    log("Generating explanations")
    expl = Explainer(model, train[cols], cols)
    scored = test[["txId", "time_step", "label"]].copy()
    scored["score"] = p_test
    scored["band"] = [risk_band(s, thr) for s in p_test]
    scored.to_csv(out / "scored_test.csv", index=False)
    # test scores of the selected model type on each feature set (for H2 curves in the dashboard)
    by_set = test[["txId", "label"]].copy()
    for set_name in sets:
        by_set[set_name] = fitted[(key[0], set_name)][2]
    by_set.to_csv(out / "test_scores_by_set.csv", index=False)
    review = scored[scored["band"] != "Low"]
    reasons = expl.top_reasons(test.loc[review.index, cols], k=5)
    json.dump({str(t): r for t, r in zip(review["txId"], reasons)}, open(out / "explanations.json", "w"), indent=1)
    log(f"  explanations for {len(review)} High/Medium transactions (method: {expl.method})")

    # dashboard also needs unlabelled test-period transactions for the neighbourhood view
    test_ids = set(nodes.loc[nodes["time_step"].isin(config.TEST_STEPS), "txId"])
    edges[edges["src"].isin(test_ids) | edges["dst"].isin(test_ids)].to_csv(out / "edges_test.csv", index=False)
    nt = nodes[nodes["txId"].isin(test_ids)]
    nt = nt[["txId", "time_step", "label"] + GRAPH_COLS].assign(score=model.predict_proba(nt[cols])[:, 1])
    nt.to_csv(out / "nodes_test.csv", index=False)   # includes unlabelled transactions, scored

    # ---- 6. Per-time-step behaviour ----------------------------------------
    steps = pd.DataFrame(per_step_f1(test, p_test, thr))
    steps.to_csv(out / "per_step_test.csv", index=False)

    # ---- 7. Optional anomaly detection -------------------------------------
    anomaly = None
    if not args.skip_anomaly:
        log("Isolation Forest (unsupervised, optional triage signal)")
        local_cols = sets["Set1_local"]
        tr_all = nodes[nodes["time_step"].isin(config.TRAIN_STEPS)]    # incl. unlabelled, no labels used
        iso = IsolationForest(n_estimators=300, contamination="auto", random_state=config.RANDOM_STATE, n_jobs=-1)
        iso.fit(tr_all[local_cols])
        a = -iso.score_samples(test[local_cols])
        k = int(test["label"].sum())
        top = np.argsort(-a)[:k]
        anomaly = {"pr_auc": float(average_precision_score(test["label"], a)),
                   "precision_at_k": float(test["label"].values[top].mean()), "k": k,
                   "illicit_base_rate": float(test["label"].mean())}
        log(f"  PR-AUC {anomaly['pr_auc']:.3f}, precision@{k} {anomaly['precision_at_k']:.3f} "
            f"(base rate {anomaly['illicit_base_rate']:.3f})")

    # ---- 8. Save model, metadata, charts, report ---------------------------
    version = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    joblib.dump({"model": model, "features": cols}, out / "model.joblib")
    meta = {"model_version": version, "model": key[0], "feature_set": key[1], "threshold": thr,
            "watch_level": thr * config.WATCH_FRACTION, "precision_target": config.PRECISION_TARGET,
            "recall_target": config.RECALL_TARGET, "explanation_method": expl.method,
            "synthetic_data": bool(args.synthetic), "dataset": info,
            "xgboost_available": HAS_XGB, "shap_available": HAS_SHAP,
            "split": {"train": [min(config.TRAIN_STEPS), max(config.TRAIN_STEPS)],
                      "val": [min(config.VAL_STEPS), max(config.VAL_STEPS)],
                      "test": [min(config.TEST_STEPS), max(config.TEST_STEPS)]},
            "anomaly": anomaly}
    json.dump(meta, open(out / "meta.json", "w"), indent=1)
    make_charts(results, fitted, test, steps, thr, key, out)
    write_report(results, best, steps, anomaly, meta, len(review), out)
    log(f"Done. Outputs in {out}")


def make_charts(results, fitted, test, steps, thr, key, out):
    y = test["label"].values
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    for set_name, style in [("Set1_local", ":"), ("Set2_local+agg", "--"), ("Set3_local+agg+graph", "-")]:
        _, _, p, _ = fitted[(key[0], set_name)]
        pr, rc, _ = precision_recall_curve(y, p)
        ax.plot(rc, pr, style, label=f"{set_name} (PR-AUC {average_precision_score(y, p):.3f})")
    ax.axhline(0.90, color="grey", lw=0.8)
    ax.text(0.01, 0.905, "precision target 0.90", fontsize=8, color="grey")
    ax.set(xlabel="Recall (illicit)", ylabel="Precision (illicit)", title=f"{key[0]}: effect of graph features (test)",
           xlim=(0, 1), ylim=(0, 1.02))
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout(); fig.savefig(out / "pr_curves.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(steps["time_step"], steps["f1"], "-o", ms=3, label="F1")
    ax.plot(steps["time_step"], steps["precision"], "-", lw=1, label="Precision")
    ax.plot(steps["time_step"], steps["recall"], "-", lw=1, label="Recall")
    ax.set(xlabel="Time step (test period)", ylabel="Score", ylim=(0, 1.02),
           title="Selected model over time (test period)")
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / "per_step_test.png", dpi=150); plt.close(fig)

    piv = results.pivot(index="model", columns="feature_set", values="test_pr_auc")
    fig, ax = plt.subplots(figsize=(7, 3.8))
    piv.plot.bar(ax=ax, rot=0)
    ax.set(ylabel="Test PR-AUC (illicit)", xlabel="", ylim=(0, 1), title="Models x feature sets")
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / "model_comparison.png", dpi=150); plt.close(fig)


def write_report(results, best, steps, anomaly, meta, n_review, out):
    r = results
    same = r[r["model"] == best["model"]].set_index("feature_set")
    s1 = same.loc["Set1_local", "test_pr_auc"]
    s2 = same.loc["Set2_local+agg", "test_pr_auc"]
    s3 = same.loc["Set3_local+agg+graph", "test_pr_auc"]
    h1 = best["test_precision"] >= config.PRECISION_TARGET
    h2 = max(s2, s3) > s1
    lines = []
    if meta["synthetic_data"]:
        lines += ["> **SYNTHETIC DATA. These numbers only show the code works. They say nothing about real Bitcoin activity.**", ""]
    lines += [
        "# Proof of Concept Results", "",
        f"Model version `{meta['model_version']}`. Dataset: {meta['dataset']}.", "",
        f"Split by time step: train {meta['split']['train']}, validation {meta['split']['val']}, test {meta['split']['test']}.", "",
        "## Hypotheses", "",
        f"**H1, detection works:** {'SUPPORTED' if h1 else 'NOT SUPPORTED'}. Selected model {best['model']} on "
        f"{best['feature_set']} reached test precision {best['test_precision']:.3f} (target {config.PRECISION_TARGET}) "
        f"and recall {best['test_recall']:.3f} (target {config.RECALL_TARGET}) at threshold {best['threshold']:.3f} "
        f"chosen on validation data.", "",
        f"**H2, graph information helps:** {'SUPPORTED' if h2 else 'NOT SUPPORTED'}. Test PR-AUC for {best['model']}: "
        f"local only {s1:.3f}; plus Elliptic neighbour aggregates {s2:.3f}; plus NetworkX graph features {s3:.3f}.", "",
        f"**H3, results are explainable:** explanations produced for {n_review} High/Medium transactions using "
        f"method: {meta['explanation_method']}. Judge clarity in the dashboard demo.", "",
        "## False-positive control (test period)", "",
        f"- Flagged: {int(best['test_flagged'])}; correct: {int(best['test_tp'])}; false flags: {int(best['test_fp'])} "
        f"({best['test_false_flags_per_1000']} per 1,000 flags)",
        f"- Illicit missed: {int(best['test_fn'])}",
        f"- Precision target met on validation: {bool(best['precision_target_met_on_val'])}",
        f"- Threshold rule: {best['threshold_rule']} (threshold {best['threshold']:.3f}). "
        f"Original point-estimate rule (v1): threshold {best['v1_threshold']:.3f}, test precision "
        f"{best['v1_test_precision']:.3f}, recall {best['v1_test_recall']:.3f}.", "",
        "## All models (test period, illicit class)", "",
        "| Model | Feature set | Precision | Recall | F1 | PR-AUC |", "|---|---|---|---|---|---|",
    ]
    for _, x in r.sort_values(["model", "feature_set"]).iterrows():
        lines.append(f"| {x['model']} | {x['feature_set']} | {x['test_precision']:.3f} | {x['test_recall']:.3f} | "
                     f"{x['test_f1']:.3f} | {x['test_pr_auc']:.3f} |")
    worst = steps.loc[steps["f1"].idxmin()]
    lines += ["", "## Stability over time", "",
              f"Lowest per-step F1 was {worst['f1']:.3f} at time step {int(worst['time_step'])}. "
              "On the real Elliptic data, performance is known to drop after about time step 43, when a major dark "
              "market closed and illicit behaviour changed. See per_step_test.png.", ""]
    if anomaly:
        lines += ["## Anomaly detection (optional)", "",
                  f"Isolation Forest PR-AUC {anomaly['pr_auc']:.3f}; precision in the top {anomaly['k']} most unusual "
                  f"transactions {anomaly['precision_at_k']:.3f} vs base rate {anomaly['illicit_base_rate']:.3f}.", ""]
    if not meta["xgboost_available"] or not meta["shap_available"]:
        lines += ["## Environment warning", "",
                  "XGBoost and/or SHAP were not installed, so fallbacks were used. Install requirements.txt and "
                  "re-run before reporting results.", ""]
    (out / "report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
