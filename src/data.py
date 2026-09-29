"""Load the Elliptic Bitcoin dataset and build the three feature sets.

Elliptic layout (elliptic_txs_features.csv has no header):
  column 0      : txId
  column 1      : time step (1..49)
  columns 2-94  : 93 further local features       -> with time step = 94 local features
  columns 95-166: 72 features aggregated from one-hop neighbours
Classes file: txId, class  where '1' = illicit, '2' = licit, 'unknown' = unlabelled.
"""
import pandas as pd

from . import config

N_LOCAL_EXTRA = 93   # local features after the time step
N_AGG = 72


def feature_columns():
    local = [f"local_{i}" for i in range(1, N_LOCAL_EXTRA + 1)]
    agg = [f"agg_{i}" for i in range(1, N_AGG + 1)]
    return local, agg


def load_elliptic(data_dir=config.DATA_DIR):
    """Return (nodes, edges). nodes has txId, time_step, label (1 illicit, 0 licit, -1 unknown) and features."""
    local, agg = feature_columns()
    feats = pd.read_csv(data_dir / config.FEATURES_FILE, header=None)
    if feats.shape[1] != 2 + N_LOCAL_EXTRA + N_AGG:
        raise ValueError(f"Expected 167 columns in features file, found {feats.shape[1]}")
    feats.columns = ["txId", "time_step"] + local + agg

    classes = pd.read_csv(data_dir / config.CLASSES_FILE)
    classes.columns = ["txId", "class"]
    classes["label"] = classes["class"].astype(str).map({"1": 1, "2": 0}).fillna(-1).astype(int)

    edges = pd.read_csv(data_dir / config.EDGES_FILE)
    edges.columns = ["src", "dst"]

    nodes = feats.merge(classes[["txId", "label"]], on="txId", how="left")
    nodes["label"] = nodes["label"].fillna(-1).astype(int)
    _check(nodes, edges)
    return nodes, edges


def _check(nodes, edges):
    if nodes["txId"].duplicated().any():
        raise ValueError("Duplicate txIds in features file")
    missing = nodes.drop(columns=["txId"]).isna().sum().sum()
    if missing:
        raise ValueError(f"{missing} missing feature values")
    known = set(nodes["txId"])
    bad = (~edges["src"].isin(known) | ~edges["dst"].isin(known)).sum()
    if bad:
        raise ValueError(f"{bad} edges reference unknown transactions")


def split(nodes):
    """Labelled rows only, split strictly by time step."""
    lab = nodes[nodes["label"] >= 0]
    return (lab[lab["time_step"].isin(config.TRAIN_STEPS)],
            lab[lab["time_step"].isin(config.VAL_STEPS)],
            lab[lab["time_step"].isin(config.TEST_STEPS)])


def feature_sets(graph_cols):
    """The three sets compared to test hypothesis H2 (concept note, Section 10.2)."""
    local, agg = feature_columns()
    # The time step itself is deliberately NOT used as a feature: with a time-based split,
    # every test value lies outside the training range, so it can only add noise.
    base = list(local)                    # 93 local features
    return {
        "Set1_local": base,
        "Set2_local+agg": base + agg,
        "Set3_local+agg+graph": base + agg + list(graph_cols),
    }


def summary(nodes, edges):
    counts = nodes["label"].map({1: "illicit", 0: "licit", -1: "unknown"}).value_counts()
    return {
        "transactions": len(nodes),
        "edges": len(edges),
        "time_steps": int(nodes["time_step"].nunique()),
        **{k: int(v) for k, v in counts.items()},
    }
