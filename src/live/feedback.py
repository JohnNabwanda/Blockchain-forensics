"""Continuous feedback loop: analyst decisions retune the risk bands (the H1 follow-up, running live).

Indicator modules (TRON, Ethereum, live Bitcoin addresses, contracts) score 0-100. Every lead an
analyst confirms or dismisses is stored with the score it had. After each decision the High
threshold is re-chosen as the lowest score whose confirmed share among decided leads at or above it
reaches PRECISION_TARGET, with at least MIN_DECISIONS decisions; Medium stays at the same fraction
of High. Below MIN_DECISIONS the defaults stand.

The Bitcoin graph model (0-1 scores) is recalibrated the same way from its own decision log with
the threshold rule used on validation (src/models.choose_threshold).
"""
from .. import config
from ..models import choose_threshold
from . import store

DEFAULT = {"high": 50.0, "medium": 20.0}
MEDIUM_FRACTION = DEFAULT["medium"] / DEFAULT["high"]
PRECISION_TARGET = 0.80
MIN_DECISIONS = 5
MODULES = {"tron": "TRON / USDT", "eth": "Ethereum", "btc": "Bitcoin addresses (live)", "contract": "Smart contracts"}


def current(module):
    r = store.thresholds(module)
    return {"high": r[0], "medium": r[1]} if r else dict(DEFAULT)


def band(module, score):
    t = current(module)
    return "High" if score >= t["high"] else "Medium" if score >= t["medium"] else "Low"


def precision_at(d, thr):
    hit = d[d["score_at_review"] >= thr]
    return (float((hit["status"] == "Confirmed").mean()) if len(hit) else None), len(hit)


def propose(module):
    """The threshold the decisions support, with before/after precision. None if too few decisions."""
    d = store.decisions(module)
    if len(d) < MIN_DECISIONS:
        return None
    cur = current(module)
    before, n_before = precision_at(d, cur["high"])
    ok = []
    for t in sorted(d["score_at_review"].unique()):
        p, n = precision_at(d, t)
        if p is not None and p >= PRECISION_TARGET:
            ok.append(t)
    if ok:
        high = float(min(ok))
        reason = f"lowest score where >= {PRECISION_TARGET:.0%} of decided leads were confirmed"
    else:
        # no level is precise enough: only scores above every dismissed lead stay High
        high = float(min(100.0, d.loc[d["status"] == "Dismissed", "score_at_review"].max() + 1))
        reason = f"no score level reached {PRECISION_TARGET:.0%} confirmed; raised above every dismissed lead"
    after, n_after = precision_at(d, high)
    return {"module": module, "decisions": len(d), "confirmed": int((d["status"] == "Confirmed").sum()),
            "current_high": cur["high"], "high": high, "medium": round(high * MEDIUM_FRACTION, 1),
            "precision_before": before, "flagged_before": n_before, "precision_after": after,
            "flagged_after": n_after, "reason": reason}


def recalibrate(analyst, module):
    """Apply the proposal if it changes the threshold. Called after every lead decision."""
    if module not in MODULES:
        return None
    p = propose(module)
    if p and abs(p["high"] - p["current_high"]) > 1e-9:
        store.set_thresholds(analyst, module, p["high"], p["medium"], p["precision_after"], p["decisions"],
                             f"{p['decisions']} decisions; {p['reason']}")
        return p
    return None


# ---------------------------------------------------------------- Bitcoin graph model
def bitcoin_threshold(decisions, model_threshold):
    """Recalibrated alert threshold from the Bitcoin decision log (Confirm = illicit, Dismiss = licit)."""
    d = decisions[decisions["decision"].isin(["Confirm", "Dismiss"])]
    if len(d) < MIN_DECISIONS or d["decision"].nunique() < 2:
        return {"threshold": model_threshold, "decisions": len(d), "changed": False,
                "reason": f"needs at least {MIN_DECISIONS} decisions with both outcomes"}
    y = (d["decision"] == "Confirm").astype(int).values
    s = d["score"].astype(float).values
    thr, met = choose_threshold(y, s, target=config.PRECISION_TARGET, rule="point")
    thr = float(thr)
    return {"threshold": thr, "decisions": len(d), "changed": abs(thr - model_threshold) > 1e-9,
            "reason": "precision target met on reviewed alerts" if met else "target not reached; most precise level used"}
