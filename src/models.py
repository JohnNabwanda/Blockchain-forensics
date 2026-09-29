"""Models, operating-threshold selection and evaluation metrics."""
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import config

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:          # the PoC should use XGBoost; the fallback exists only so the code runs anywhere
    HAS_XGB = False


def get_models(y_train):
    pos = max(int(y_train.sum()), 1)
    neg = int(len(y_train) - pos)
    models = {
        "LogisticRegression": make_pipeline(
            StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=3000, random_state=config.RANDOM_STATE)),
        "RandomForest": RandomForestClassifier(
            n_estimators=300, class_weight="balanced_subsample", n_jobs=-1,
            random_state=config.RANDOM_STATE),
    }
    if HAS_XGB:
        models["XGBoost"] = XGBClassifier(
            n_estimators=400, max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=neg / pos, eval_metric="aucpr", n_jobs=-1, random_state=config.RANDOM_STATE)
    else:
        models["GradBoost_sklearn_fallback"] = HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.05, class_weight="balanced", random_state=config.RANDOM_STATE)
    return models


def wilson_lower(p, n, z=1.645):
    """One-sided 95% lower confidence bound for a proportion p observed on n trials."""
    n = np.maximum(n, 1)
    centre = p + z * z / (2 * n)
    margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def choose_threshold(y_val, p_val, target=config.PRECISION_TARGET, rule=None):
    """Lowest threshold (i.e. highest recall) whose validation precision reaches the target.

    rule "point"       : observed validation precision >= target (original rule, v1).
    rule "conservative": 95% Wilson lower bound of validation precision >= target (v2).
                         Protects against a small validation window giving a lucky estimate.
    If no threshold reaches the target, fall back to the F1-maximising threshold and say so.
    """
    rule = rule or config.THRESHOLD_RULE
    prec, rec, thr = precision_recall_curve(y_val, p_val)
    prec, rec = prec[:-1], rec[:-1]            # align with thr
    if rule == "conservative":
        tp = rec * int(np.sum(y_val))
        flagged = np.where(prec > 0, tp / np.maximum(prec, 1e-12), 0)
        crit = wilson_lower(prec, flagged)
    else:
        crit = prec
    ok = np.where(crit >= target)[0]
    if len(ok):
        i = ok[np.argmax(rec[ok])]
        return float(thr[i]), True
    if rule == "conservative":
        # target not provable: take the threshold with the highest confident precision (stay cautious)
        return float(thr[np.argmax(crit)]), False
    f1 = 2 * prec * rec / np.clip(prec + rec, 1e-12, None)
    return float(thr[np.argmax(f1)]), False


def evaluate(y, p, thr):
    pred = (p >= thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    flagged = tp + fp
    return {
        "precision": precision_score(y, pred, zero_division=0),
        "recall": recall_score(y, pred, zero_division=0),
        "f1": f1_score(y, pred, zero_division=0),
        "pr_auc": average_precision_score(y, p),
        "roc_auc": roc_auc_score(y, p),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "flagged": flagged,
        "false_flags_per_1000": round(1000 * fp / flagged, 1) if flagged else 0.0,
    }


def per_step_f1(df, p, thr):
    pred = (p >= thr).astype(int)
    out = []
    for step, idx in df.groupby("time_step").indices.items():
        y = df["label"].values[idx]
        out.append({"time_step": int(step), "illicit": int(y.sum()),
                    "f1": f1_score(y, pred[idx], zero_division=0),
                    "precision": precision_score(y, pred[idx], zero_division=0),
                    "recall": recall_score(y, pred[idx], zero_division=0)})
    return out


def risk_band(score, thr, watch_fraction=config.WATCH_FRACTION):
    if score >= thr:
        return "High"
    if score >= thr * watch_fraction:
        return "Medium"
    return "Low"
