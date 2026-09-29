"""Per-transaction explanations (concept note, Section 10.4).

Uses SHAP when installed (the intended setup). If SHAP is missing, falls back to a clearly
labelled approximation so the pipeline can still run; do not report fallback explanations
as SHAP results.
"""
import numpy as np

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False


def describe_feature(name):
    if name.startswith("local_"):
        return f"Transaction attribute #{name.split('_')[1]} (anonymised by Elliptic)"
    if name.startswith("agg_"):
        return f"Neighbour summary #{name.split('_')[1]} (aggregated over connected transactions)"
    return {
        "g_in_degree": "Number of incoming payment flows",
        "g_out_degree": "Number of outgoing payment flows",
        "g_total_degree": "Total directly connected transactions",
        "g_pagerank": "Centrality in the payment graph (1.0 = average)",
        "g_two_hop_size": "Transactions within two hops",
        "g_component_size": "Size of the connected payment cluster",
        "g_clustering": "How tightly its neighbours transact with each other",
        "g_nbr_mean_degree": "Average connectedness of its neighbours",
    }.get(name, name)


class Explainer:
    def __init__(self, model, X_train, feature_names):
        self.model = model
        self.names = list(feature_names)
        self.method = None
        est = model.steps[-1][1] if hasattr(model, "steps") else model
        if hasattr(est, "coef_"):                       # linear model: exact contributions
            self.method = "linear"
            scaler = model.steps[0][1]
            self._lin = (scaler, est.coef_[0])
        elif HAS_SHAP:
            self.method = "shap"
            self._shap = shap.TreeExplainer(est)
        else:
            self.method = "approximate (install shap for real SHAP values)"
            imp = getattr(est, "feature_importances_", None)
            if imp is None:
                from sklearn.inspection import permutation_importance
                # cheap global importance on a sample, used only by the fallback
                idx = np.random.default_rng(0).choice(len(X_train), min(2000, len(X_train)), replace=False)
                Xs = X_train.iloc[idx]
                ys = model.predict(Xs)
                imp = permutation_importance(model, Xs, ys, n_repeats=3, random_state=0).importances_mean
            self._mu = X_train.mean().values
            self._sd = X_train.std().replace(0, 1).values
            self._imp = np.clip(np.asarray(imp), 0, None)
            p = model.predict_proba(X_train)[:, 1]
            Xc = X_train.values - self._mu
            self._dir = np.sign((Xc * (p - p.mean())[:, None]).mean(0))

    def contributions(self, X):
        """Array (n_rows, n_features): positive values push towards 'illicit'."""
        if self.method == "linear":
            scaler, coef = self._lin
            return scaler.transform(X) * coef
        if self.method == "shap":
            sv = self._shap.shap_values(X)
            if isinstance(sv, list):                    # older SHAP: list per class
                sv = sv[1]
            sv = np.asarray(sv)
            if sv.ndim == 3:                            # newer SHAP: (rows, features, classes)
                sv = sv[:, :, 1]
            return sv
        z = (X.values - self._mu) / self._sd
        return z * self._imp * self._dir

    def top_reasons(self, X, k=5):
        C = self.contributions(X)
        out = []
        for r in range(len(X)):
            order = np.argsort(-C[r])[:k]
            out.append([{"feature": self.names[j], "description": describe_feature(self.names[j]),
                         "value": float(X.iloc[r, j]), "contribution": float(C[r, j])}
                        for j in order if C[r, j] > 0])
        return out
