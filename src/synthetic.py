"""Generate a small synthetic dataset in the exact Elliptic file format.

FOR TESTING THE PIPELINE ONLY. Results on this data mean nothing about real Bitcoin
activity. Run the real pipeline on the Kaggle Elliptic files.
"""
import numpy as np
import pandas as pd

from . import config
from .data import N_AGG, N_LOCAL_EXTRA


def make_synthetic(out_dir, n_per_step=400, n_steps=49, illicit_rate=0.10, labelled_rate=0.25, seed=0):
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, classes, edges = [], [], []
    tx = 1_000_000
    signal_dims = rng.choice(N_LOCAL_EXTRA, 12, replace=False)
    for step in range(1, n_steps + 1):
        ids = np.arange(tx, tx + n_per_step)
        tx += n_per_step
        illicit = rng.random(n_per_step) < illicit_rate
        # behaviour drifts slowly over time so the time split matters
        drift = 0.4 * np.sin(step / 8)
        X = rng.normal(0, 1, (n_per_step, N_LOCAL_EXTRA))
        X[np.ix_(illicit, signal_dims)] += 0.9 + drift
        # payment flows only within a time step (as in Elliptic); illicit nodes cluster together
        nbr = {i: [] for i in range(n_per_step)}
        for i in range(n_per_step):
            k = rng.poisson(3 if illicit[i] else 1) + 1
            same = np.where(illicit == illicit[i])[0]
            pool = same if rng.random() < 0.7 else np.arange(n_per_step)
            for j in rng.choice(pool, size=min(k, len(pool)), replace=False):
                if j != i:
                    edges.append((ids[i], ids[j]))
                    nbr[i].append(j)
                    nbr[j].append(i)
        # aggregated features: mean of neighbours' first 72 local features
        A = np.array([X[nbr[i], :N_AGG].mean(0) if nbr[i] else np.zeros(N_AGG) for i in range(n_per_step)])
        for i in range(n_per_step):
            rows.append([ids[i], step, *X[i], *A[i]])
            if rng.random() < labelled_rate:
                classes.append((ids[i], "1" if illicit[i] else "2"))
            else:
                classes.append((ids[i], "unknown"))
    pd.DataFrame(rows).to_csv(out_dir / config.FEATURES_FILE, header=False, index=False, float_format="%.5f")
    pd.DataFrame(classes, columns=["txId", "class"]).to_csv(out_dir / config.CLASSES_FILE, index=False)
    pd.DataFrame(sorted(set(edges)), columns=["txId1", "txId2"]).to_csv(out_dir / config.EDGES_FILE, index=False)
    return out_dir
