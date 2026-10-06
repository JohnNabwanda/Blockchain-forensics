"""Score Slither's findings against the SmartBugs labels.

The mapping from Slither detectors to SmartBugs categories was fixed before the scan ran.
Categories with no matching detector are reported as gaps, not hidden.
"""
from .. import config

# SmartBugs category -> Slither detectors that look for it
DETECTORS = {
    "reentrancy": ["reentrancy-eth", "reentrancy-no-eth", "reentrancy-balance", "reentrancy-benign",
                   "reentrancy-events", "reentrancy-unlimited-gas"],
    "access_control": ["arbitrary-send-eth", "arbitrary-send-erc20", "suicidal", "unprotected-upgrade",
                       "tx-origin", "controlled-delegatecall", "controlled-array-length",
                       "uninitialized-storage", "protected-vars"],
    "arithmetic": [],            # Slither has no integer overflow detector
    "bad_randomness": ["weak-prng"],
    "denial_of_service": ["calls-loop", "msg-value-loop", "delegatecall-loop", "costly-loop",
                          "incorrect-equality"],
    "front_running": [],         # transaction-ordering issues need dynamic analysis
    "time_manipulation": ["timestamp"],
    "unchecked_low_level_calls": ["unchecked-lowlevel", "unchecked-send", "unchecked-transfer", "unused-return"],
    "short_addresses": [],       # an off-chain input-encoding issue, not visible in contract code
    "other": ["uninitialized-storage", "uninitialized-state"],
}
CATEGORY_LABELS = {
    "reentrancy": "Reentrancy", "access_control": "Access control", "arithmetic": "Arithmetic overflow",
    "bad_randomness": "Bad randomness", "denial_of_service": "Denial of service",
    "front_running": "Front running", "time_manipulation": "Time manipulation",
    "unchecked_low_level_calls": "Unchecked low-level calls", "short_addresses": "Short addresses",
    "other": "Other",
}


def categories_of(check):
    return [cat for cat, checks in DETECTORS.items() if check in checks]


def near(a, b, tol=config.PHASE3_LINE_TOLERANCE):
    return any(abs(x - y) <= tol for x in a for y in b)


def evaluate(contracts):
    """Mark each label detected or not, and each finding matched or not. Returns metrics."""
    for c in contracts:
        for f in c["findings"]:
            f["categories"] = categories_of(f["check"])
            f["matched"] = False
        for lab in c["labels"]:
            same = [f for f in c["findings"] if lab["category"] in f["categories"]]
            hits = [f for f in same if near(f["lines"], lab["lines"])]
            lab["line_hit"], lab["contract_hit"] = bool(hits), bool(same)
            lab["hit_checks"] = sorted({f["check"] for f in hits})
            for f in hits:
                f["matched"] = True

    ok = [c for c in contracts if not c["error"]]
    per_cat = []
    for cat, checks in DETECTORS.items():
        labs = [lab for c in ok for lab in c["labels"] if lab["category"] == cat]
        found = [f for c in ok for f in c["findings"] if cat in f["categories"]]
        per_cat.append({
            "category": cat, "label": CATEGORY_LABELS[cat], "has_detector": bool(checks),
            "labelled": len(labs),
            "line_hits": sum(lab["line_hit"] for lab in labs),
            "contract_hits": sum(lab["contract_hit"] for lab in labs),
            "findings": len(found),
            "findings_on_label": sum(f["matched"] for f in found),
        })
    labs = [lab for c in ok for lab in c["labels"]]
    covered = [lab for lab in labs if DETECTORS[lab["category"]]]
    mapped = [f for c in ok for f in c["findings"] if f["categories"]]
    return {
        "contracts": len(contracts), "analysed": len(ok), "failed": len(contracts) - len(ok),
        "labels": len(labs), "line_hits": sum(lab["line_hit"] for lab in labs),
        "contract_hits": sum(lab["contract_hit"] for lab in labs),
        "labels_with_detector": len(covered), "covered_line_hits": sum(lab["line_hit"] for lab in covered),
        "findings_total": sum(len(c["findings"]) for c in ok),
        "findings_mapped": len(mapped), "findings_mapped_on_label": sum(f["matched"] for f in mapped),
        "findings_high": sum(f["impact"] == "High" for c in ok for f in c["findings"]),
        "line_tolerance": config.PHASE3_LINE_TOLERANCE,
        "per_category": per_cat,
    }
