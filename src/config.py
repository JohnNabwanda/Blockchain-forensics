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
