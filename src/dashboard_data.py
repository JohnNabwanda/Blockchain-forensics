"""Data access and plotting for the dashboard, kept separate from the Streamlit UI so it can be tested."""
import csv
import json
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

from . import config
from .graph_features import neighbourhood

DECISIONS_FILE = config.OUTPUT_DIR / "decisions.csv"
DECISION_FIELDS = ["timestamp_utc", "txId", "decision", "justification", "analyst",
                   "score", "band", "threshold", "model_version"]


def load_outputs(out=config.OUTPUT_DIR):
    meta = json.load(open(out / "meta.json"))
    scored = pd.read_csv(out / "scored_test.csv")
    expl = json.load(open(out / "explanations.json"))
    nodes = pd.read_csv(out / "nodes_test.csv")
    edges = pd.read_csv(out / "edges_test.csv")
    G = nx.DiGraph()
    G.add_nodes_from(nodes["txId"])
    G.add_edges_from(edges[["src", "dst"]].itertuples(index=False, name=None))
    return meta, scored, expl, nodes, G


def review_queue(scored, bands=("High",), step=None):
    q = scored[scored["band"].isin(bands)]
    if step is not None:
        q = q[q["time_step"] == step]
    decided = set(load_decisions()["txId"].astype(str)) if DECISIONS_FILE.exists() else set()
    q = q.assign(reviewed=q["txId"].astype(str).isin(decided))
    return q.sort_values(["reviewed", "score"], ascending=[True, False])


def reasons_table(expl, tx_id):
    rows = expl.get(str(tx_id), [])
    return pd.DataFrame(rows, columns=["description", "feature", "value", "contribution"])


def plot_neighbourhood(G, tx_id, nodes, hops=1):
    """nodes: all test-period transactions (labelled and unlabelled) with a 'score' column."""
    H = neighbourhood(G, tx_id, hops=hops)
    score = dict(zip(nodes["txId"], nodes["score"]))
    pos = nx.spring_layout(H, seed=1, k=0.9 / max(len(H), 1) ** 0.5)
    fig, ax = plt.subplots(figsize=(6, 4.5))
    others = [n for n in H if n != tx_id]
    colors = [score.get(n, float("nan")) for n in others]
    nx.draw_networkx_edges(H, pos, ax=ax, alpha=0.4, arrows=True, arrowsize=8, edge_color="#777777")
    known = [n for n, c in zip(others, colors) if c == c]
    unknown = [n for n, c in zip(others, colors) if c != c]
    if unknown:
        nx.draw_networkx_nodes(H, pos, nodelist=unknown, node_size=60, node_color="#d9d9d9",
                               edgecolors="#888888", ax=ax, label="Outside test period")
    if known:
        sc = nx.draw_networkx_nodes(H, pos, nodelist=known, node_size=90, ax=ax, cmap="Reds", vmin=0, vmax=1,
                                    node_color=[score[n] for n in known], edgecolors="#555555", label="Other transactions")
        fig.colorbar(sc, ax=ax, label="Risk score", shrink=0.8)
    nx.draw_networkx_nodes(H, pos, nodelist=[tx_id], node_size=260, node_color="#2E5597",
                           node_shape="*", ax=ax, label="Selected transaction")
    ax.legend(fontsize=7, loc="lower left")
    ax.set_title(f"Payment neighbourhood of {tx_id} ({len(H)} transactions)", fontsize=9)
    ax.axis("off")
    fig.tight_layout()
    return fig


def record_decision(tx_id, decision, justification, analyst, row, meta):
    if decision not in {"Confirm", "Dismiss", "Escalate"}:
        raise ValueError("decision must be Confirm, Dismiss or Escalate")
    if not justification.strip():
        raise ValueError("a short justification is required")
    new = not DECISIONS_FILE.exists()
    DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DECISION_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "txId": tx_id, "decision": decision, "justification": justification.strip(),
                    "analyst": analyst.strip() or "unnamed", "score": round(float(row["score"]), 4),
                    "band": row["band"], "threshold": round(meta["threshold"], 4),
                    "model_version": meta["model_version"]})


def load_decisions():
    if not DECISIONS_FILE.exists():
        return pd.DataFrame(columns=DECISION_FIELDS)
    return pd.read_csv(DECISIONS_FILE)
