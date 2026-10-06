"""H1 follow-up: does recalibrating the threshold from analyst feedback restore precision?

    python run_h1_recalibration.py

The pre-registered H1 result (fixed threshold, run_pipeline.py) stays as reported. This is a
separate, post-hoc experiment testing the fix named in the report: recalibrate from analyst
feedback. Its settings are fixed in src/config.py and every variant run is reported.

The model is the one selected on validation PR-AUC: Random Forest on feature Set 3.
Test time steps are processed in order, as they would arrive in operation:

  fixed      threshold chosen once on validation (steps 30-34), as in run_pipeline.py
  feedback   before each step, the threshold is re-chosen from cases analysts reviewed
             (High and Medium bands) in the previous RECAL_WINDOW_STEPS steps. Only the labels
             of reviewed cases are used, because those are the only ones an analyst would see.
  retrain    as feedback, and the model is also refitted before each step on every label from
             earlier steps. This assumes full labels arrive within one step: a best case.
"""
import json
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import config
from src.data import feature_sets, load_elliptic
from src.graph_features import GRAPH_COLS, compute_graph_features
from src.models import choose_threshold, evaluate, get_models

MODEL, FEATURE_SET = "RandomForest", "Set3_local+agg+graph"
DARK_MARKET_STEP = 43


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_nodes(out):
    cache = out / "nodes_with_graph.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    nodes, edges = load_elliptic()
    log("Computing graph features with NetworkX")
    nodes = compute_graph_features(nodes, edges)
    nodes.to_pickle(cache)
    return nodes


def fit(train, cols):
    model = get_models(train["label"].values)[MODEL]
    model.fit(train[cols], train["label"])
    return model


def feedback_threshold(history, steps, previous):
    """Threshold from reviewed cases in `steps`. Same rule as validation (conservative, target 0.90)."""
    h = history[history["time_step"].isin(steps) & history["reviewed"]]
    if len(h) == 0:
        return previous
    if h["label"].sum() == 0:
        # every reviewed case was licit: flag nothing that scores like those false flags
        return float(np.nextafter(h["score"].max(), 1.0))
    thr, _ = choose_threshold(h["label"].values, h["score"].values)
    return thr


def run_variant(name, lab, cols, base_model, thr0):
    """Score the test steps in time order; return per-transaction rows with the threshold used."""
    val = lab[lab["time_step"].isin(config.VAL_STEPS)]
    p_val = base_model.predict_proba(val[cols])[:, 1]
    history = pd.DataFrame({"time_step": val["time_step"].values, "label": val["label"].values,
                            "score": p_val, "reviewed": p_val >= thr0 * config.WATCH_FRACTION})
    thr, rows = thr0, []
    for t in config.TEST_STEPS:
        step = lab[lab["time_step"] == t]
        model = base_model
        if name == "retrain":
            model = fit(lab[lab["time_step"] < t], cols)
        if name in ("feedback", "retrain"):
            thr = feedback_threshold(history, range(t - config.RECAL_WINDOW_STEPS, t), thr)
        p = model.predict_proba(step[cols])[:, 1]
        rows.append(pd.DataFrame({"txId": step["txId"].values, "time_step": t, "label": step["label"].values,
                                  "score": p, "threshold": thr}))
        history = pd.concat([history, pd.DataFrame({
            "time_step": t, "label": step["label"].values, "score": p,
            "reviewed": p >= thr * config.WATCH_FRACTION})], ignore_index=True)
        log(f"  {name:9s} step {t}: threshold {thr:.3f}, flagged {int((p >= thr).sum())}")
    return pd.concat(rows, ignore_index=True)


def summarise(df):
    """Metrics for all test steps, before the dark-market closure and after it."""
    out = {}
    for part, mask in [("all", df["time_step"] > 0),
                       (f"35-{DARK_MARKET_STEP - 1}", df["time_step"] < DARK_MARKET_STEP),
                       (f"{DARK_MARKET_STEP}-49", df["time_step"] >= DARK_MARKET_STEP)]:
        d = df[mask]
        # evaluate() takes one threshold; per-step thresholds are applied by passing the margin
        m = evaluate(d["label"].values, d["score"].values - d["threshold"].values, 0.0)
        m.pop("roc_auc"), m.pop("pr_auc")
        out[part] = m
    return out


def per_step(df):
    rows = []
    for t, d in df.groupby("time_step"):
        pred = d["score"] >= d["threshold"]
        tp = int((pred & (d["label"] == 1)).sum())
        fp = int((pred & (d["label"] == 0)).sum())
        rows.append({"time_step": t, "threshold": d["threshold"].iloc[0], "flagged": tp + fp, "tp": tp, "fp": fp,
                     "illicit": int(d["label"].sum()),
                     "precision": tp / (tp + fp) if tp + fp else np.nan,
                     "recall": tp / d["label"].sum() if d["label"].sum() else np.nan})
    return pd.DataFrame(rows)


def chart(steps, out):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name, s in steps.items():
        axes[0].plot(s["time_step"], s["precision"], "-o", ms=3, label=name)
        axes[1].plot(s["time_step"], s["threshold"], "-o", ms=3, label=name)
    axes[0].axhline(config.PRECISION_TARGET, color="grey", lw=0.8)
    axes[0].set(title="Precision per test step", xlabel="Time step", ylim=(0, 1.02))
    axes[1].set(title="Threshold used", xlabel="Time step", ylim=(0, 1.02))
    for ax in axes:
        ax.axvline(DARK_MARKET_STEP - 0.5, color="grey", ls=":", lw=0.8)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "recalibration.png", dpi=150)
    plt.close(fig)


def write_report(summary, steps, thr0, out):
    target = config.PRECISION_TARGET
    lines = ["# H1 follow-up: threshold recalibration from analyst feedback", "",
             "Post-hoc experiment. The pre-registered H1 result (fixed threshold) stays **not supported**; this tests "
             "the remedy proposed in the report. Settings were fixed in `src/config.py` before results were computed "
             f"(window {config.RECAL_WINDOW_STEPS} steps, reviewed bands {', '.join(config.RECAL_REVIEWED_BANDS)}, "
             f"precision target {target}, {config.THRESHOLD_RULE} rule). All variants run are reported.", "",
             f"Model: {MODEL} on {FEATURE_SET}, selected on validation PR-AUC. Initial threshold {thr0:.3f}.", "",
             "| Variant | Period | Flagged | False flags | Precision | Recall | F1 |", "|---|---|---|---|---|---|---|"]
    for name, parts in summary.items():
        for part, m in parts.items():
            lines.append(f"| {name} | {part} | {m['flagged']} | {m['fp']} | {m['precision']:.3f} | "
                         f"{m['recall']:.3f} | {m['f1']:.3f} |")
    lines += ["", "Variants:", "",
              "- **fixed**: threshold chosen once on validation (as in the main report).",
              "- **feedback**: threshold re-chosen before each step from High and Medium cases reviewed in the previous "
              f"{config.RECAL_WINDOW_STEPS} steps. Uses only labels an analyst would have seen.",
              "- **retrain**: as feedback, plus the model is refitted on all earlier labels before each step. Assumes "
              "labels arrive within one step, so it is a best case.", "",
              f"Time step {DARK_MARKET_STEP} is when a major dark market closed. After it, illicit behaviour changes "
              "and no variant can learn the new pattern until labels for it exist.", "",
              "See `recalibration.png` and `per_step_<variant>.csv`."]
    (out / "report.md").write_text("\n".join(lines))


def main():
    out = config.RECAL_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    nodes = load_nodes(out)
    lab = nodes[nodes["label"] >= 0]
    cols = feature_sets(GRAPH_COLS)[FEATURE_SET]

    train = lab[lab["time_step"].isin(config.TRAIN_STEPS)]
    val = lab[lab["time_step"].isin(config.VAL_STEPS)]
    log(f"Fitting {MODEL} on steps 1-29")
    base = fit(train, cols)
    thr0, _ = choose_threshold(val["label"].values, base.predict_proba(val[cols])[:, 1])
    log(f"Validation threshold {thr0:.3f}")

    summary, steps = {}, {}
    for name in ("fixed", "feedback", "retrain"):
        df = run_variant(name, lab, cols, base, thr0)
        df.to_csv(out / f"scored_{name}.csv", index=False)
        summary[name] = summarise(df)
        steps[name] = per_step(df)
        steps[name].to_csv(out / f"per_step_{name}.csv", index=False)
        a = summary[name]["all"]
        log(f"{name}: precision {a['precision']:.3f}, recall {a['recall']:.3f}, flagged {a['flagged']}")

    json.dump({"initial_threshold": thr0, "window_steps": config.RECAL_WINDOW_STEPS,
               "precision_target": config.PRECISION_TARGET, "summary": summary},
              open(out / "summary.json", "w"), indent=1)
    chart(steps, out)
    write_report(summary, steps, thr0, out)
    log(f"Done. Outputs in {out}")


if __name__ == "__main__":
    main()
