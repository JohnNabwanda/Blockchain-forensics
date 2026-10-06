"""Central settings for the PoC. Change values here, not inside the pipeline code."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "elliptic_bitcoin_dataset"   # where the Kaggle files go
OUTPUT_DIR = ROOT / "outputs"

# Elliptic file names (as distributed on Kaggle)
FEATURES_FILE = "elliptic_txs_features.csv"
CLASSES_FILE = "elliptic_txs_classes.csv"
EDGES_FILE = "elliptic_txs_edgelist.csv"

# Time-based split (concept note, Section 9). Time steps are 1..49.
TRAIN_STEPS = range(1, 30)    # 1-29  : fit models
VAL_STEPS = range(30, 35)     # 30-34 : choose the operating threshold
TEST_STEPS = range(35, 50)    # 35-49 : final, untouched evaluation

# False-positive control (concept note, Section 11)
PRECISION_TARGET = 0.90       # operating threshold must reach this on validation
# "conservative" (v2): 95% lower confidence bound of validation precision must reach the target.
# "point" (v1, original): observed validation precision must reach the target. Both are reported.
THRESHOLD_RULE = "conservative"
RECALL_TARGET = 0.65          # reported against, not optimised for
WATCH_FRACTION = 0.5          # medium band starts at WATCH_FRACTION * threshold

RANDOM_STATE = 42

# ---- H1 follow-up: recalibration from analyst feedback (post-hoc experiment) -------------
# The pre-registered H1 result above stays as reported. These settings were fixed on 2026-10-06
# BEFORE any recalibration result was computed, and every variant run is reported.
RECAL_WINDOW_STEPS = 5        # feedback from the last 5 time steps sets the next threshold
RECAL_REVIEWED_BANDS = ("High", "Medium")   # analysts see labels only for cases they reviewed
RECAL_OUTPUT_DIR = OUTPUT_DIR / "h1_recalibration"

# ---- Phase 2: TRON/USDT wallets and off-chain (mobile-money) attribution -------------------
# Synthetic data only (concept note, Section 12). No real mobile-money records are used.
PHASE2_DATA_DIR = ROOT / "data" / "phase2_synthetic"
PHASE2_OUTPUT_DIR = OUTPUT_DIR / "phase2"

# deposit-address detection: forwards (almost) everything it receives to one destination, quickly
DEPOSIT_MAX_SWEEP_HOURS = 6
DEPOSIT_MIN_FORWARD_SHARE = 0.95
HOT_WALLET_MIN_DEPOSITS = 10          # a destination fed by this many deposit addresses is an exchange

# P2P-trader detection: many distinct counterparties in both directions, active most days
TRADER_MIN_COUNTERPARTIES = 25        # distinct senders AND distinct receivers
TRADER_MIN_BALANCE = 0.25             # min(in, out) / max(in, out) of distinct counterparties
TRADER_MIN_ACTIVE_SHARE = 0.4         # share of days in the period with any activity

# off-chain matching (Section 12.3)
MATCH_SELL_WINDOW_MIN = (-5, 45)      # user sells USDT: trader pays mobile money after receiving
MATCH_BUY_WINDOW_MIN = (-60, 5)       # user buys USDT: user pays mobile money first
MATCH_FEE_RANGE = (-0.005, 0.05)      # implied trader spread accepted after FX conversion
MATCH_FEE_TYPICAL, MATCH_FEE_SD = 0.015, 0.012
MATCH_TIME_SCALE_MIN = 15             # time score halves roughly every 10 minutes
MATCH_MIN_LINK_SCORE = 0.25
# confidence of a wallet-cluster <-> mobile-money account link. Evidence = sum of link scores, so
# repeated co-occurrence adds up (Section 12.3); one strong coincidence cannot reach High.
PAIR_HIGH_MIN_TRADES, PAIR_HIGH_MIN_EVIDENCE = 3, 2.0
PAIR_MEDIUM_MIN_TRADES, PAIR_MEDIUM_MIN_EVIDENCE = 2, 1.0

TAINT_MAX_HOPS = 2                    # follow funds this far from victim-reported wallets

# ---- Phase 3: Track B smart-contract analysis (static analysis with Slither) -----------------
# Benchmark: SmartBugs curated (143 contracts with line-level vulnerability annotations), cloned to
# PHASE3_BENCHMARK_DIR. Run with the separate environment in .venv-phase3 (see README).
PHASE3_BENCHMARK_DIR = ROOT / "data" / "phase3" / "smartbugs-curated"
PHASE3_OUTPUT_DIR = OUTPUT_DIR / "phase3"
PHASE3_TIMEOUT_S = 180                # per contract
PHASE3_LINE_TOLERANCE = 2             # a finding counts as on a labelled line if within this many lines

# Phase switcher on both dashboards: online links (published pages) and offline file paths
DASHBOARD_WEB_URLS = {"phase1": "https://claude.ai/artifact/9JnreBniRRcCVZsRhfoJYt",
                      "phase2": "https://claude.ai/artifact/UqYWyPD4tY3qrD6BYa73rp",
                      "phase3": "https://claude.ai/artifact/RpAd2NeX37CqSKtqyeMpCq"}
DASHBOARD_FILES = {"phase1": OUTPUT_DIR / "dashboard.html",
                   "phase2": PHASE2_OUTPUT_DIR / "dashboard_phase2.html",
                   "phase3": OUTPUT_DIR / "phase3" / "dashboard_phase3.html"}


def switcher_links(page):
    """Links for the phase switcher on `page`, with offline paths relative to that page's file."""
    import os
    here = DASHBOARD_FILES[page].parent
    return {"current": page, "web": DASHBOARD_WEB_URLS,
            "local": {k: os.path.relpath(p, here).replace(os.sep, "/") for k, p in DASHBOARD_FILES.items()}}
