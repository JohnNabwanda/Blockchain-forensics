# AI-Powered Blockchain Forensics: Proof of Concept

Code for the two-week PoC described in the revised concept note. It tests three hypotheses on the
public Elliptic Bitcoin dataset:

- **H1, detection works.** Illicit-class precision of at least 0.90 on later time steps.
- **H2, graph information helps.** Graph features raise PR-AUC over transaction-only features.
- **H3, results are explainable.** Every flag comes with its main reasons and its payment neighbourhood.

## 1. Setup

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Get the data

Download the **Elliptic Data Set** from Kaggle (search "elliptic bitcoin dataset"; a free account is
needed). Unzip it so these three files sit here:

```
data/elliptic_bitcoin_dataset/elliptic_txs_features.csv
data/elliptic_bitcoin_dataset/elliptic_txs_classes.csv
data/elliptic_bitcoin_dataset/elliptic_txs_edgelist.csv
```

## 3. Run the pipeline

```bash
python run_pipeline.py
```

This takes roughly 5 to 20 minutes on a laptop, mostly for graph features and Random Forest.
Add `--skip-anomaly` to skip the optional Isolation Forest step.

To test the code without the real data, run `python run_pipeline.py --synthetic`. It generates
small fake data in the same format. **Synthetic results mean nothing about real Bitcoin activity.**

## 4. Build the results dashboard

```bash
python build_dashboard.py
```

This writes `outputs/dashboard.html`, a single interactive page you can open in any browser or
send to reviewers. It needs no server. It shows:

- a supported or not-supported verdict for H1, H2 and H3
- a threshold slider that updates precision, recall, cases for review and false flags live,
  with the score distribution of illicit and licit transactions
- precision-recall curves for the three feature sets (H2)
- a comparison of all models, switchable between PR-AUC, F1, precision and recall, with a full table
- F1 per test time step, with illicit counts underneath
- the top 40 flagged cases, each with its reasons and payment-neighbourhood graph

Hover over any chart for exact values.

## 5. Open the analyst app

```bash
streamlit run app.py
```

It has three tabs:

- **Case review:** a queue of flagged transactions. Each case shows the risk score, the reasons,
  and the neighbourhood graph, plus Confirm / Dismiss / Escalate buttons with a required justification.
- **Model results:** the report and charts.
- **Decision log:** every analyst decision, with the model version and threshold. It can be
  downloaded as a CSV.

## What the pipeline does

| Step | Detail | Concept note |
|---|---|---|
| Split | Train on time steps 1 to 29, choose the threshold on 30 to 34, test on 35 to 49. Labelled rows only. | Section 9 |
| Feature sets | Set 1: 93 local features. Set 2: plus 72 Elliptic neighbour aggregates. Set 3: plus 8 NetworkX features (degree, PageRank, 2-hop size, cluster size, clustering). | Section 10.2 |
| Models | Logistic Regression (baseline), Random Forest, XGBoost, all with class weighting. | Section 10.3 |
| Threshold | The lowest threshold that reaches precision 0.90 on validation (i.e. the highest recall at that precision), then fixed before testing. | Section 11.1 |
| Risk bands | High = at or above the threshold. Medium = at least half the threshold. Low = the rest. | Section 11.2 |
| Model choice | The demo model is the model and feature-set pair with the best **validation** PR-AUC. Test data is never used to choose. | |
| Explanations | SHAP for tree models; exact coefficient × value for Logistic Regression. | Section 10.4 |
| Anomaly | Isolation Forest trained without labels on training-period transactions. Optional. | Section 10.3 |

The time step is deliberately not used as a feature. With a time-based split, every test value
lies outside the training range, so it cannot help.

## Outputs (in `outputs/`)

| File | Contents |
|---|---|
| `report.md` | Verdict on each hypothesis, false-positive figures, table of all models |
| `results.csv` | Every model × feature set, validation and test metrics |
| `pr_curves.png` | Precision-recall curves for the three feature sets (H2) |
| `model_comparison.png` | Test PR-AUC for all models and feature sets |
| `per_step_test.png` | Performance per test time step |
| `scored_test.csv` | Score and risk band for every labelled test transaction |
| `explanations.json` | Top reasons for each High and Medium transaction |
| `model.joblib`, `meta.json` | Saved model, threshold and run settings |
| `decisions.csv` | Analyst decisions, created by the dashboard |

## What to expect on the real data

Published work on Elliptic reports illicit-class F1 of about 0.8 for Random Forest with all
features, so H1 is realistic. Expect a sharp drop after about time step 43, when a large dark
market closed and illicit behaviour changed. That drop is a real finding about model decay and
belongs in the report. Do not tune it away.

## Settings

All tunable values (split, precision target, band levels) are in `src/config.py`.

## H1 follow-up: recalibrating the threshold from analyst feedback

The pre-registered H1 result (fixed threshold) stays **not supported**. This separate, post-hoc
experiment tests the remedy the report proposes. Its settings (5-step feedback window, High and
Medium cases reviewed, same 0.90 conservative rule) were fixed in `src/config.py` before it ran.

```bash
python run_h1_recalibration.py       # about 2 minutes after graph features are cached
```

Test steps are scored in time order. Before each step the threshold is re-chosen from the cases
analysts reviewed in the previous five steps, using only those labels. A second variant also
refits the model on all earlier labels, which assumes labels arrive within one step (a best case).

| Variant (test steps 35-49) | Precision | Recall | False flags |
|---|---|---|---|
| Fixed threshold (main result) | 0.516 | 0.745 | 756 |
| Recalibrated from analyst feedback | 0.798 | 0.724 | 199 |
| Recalibrated and retrained (best case) | 0.899 | 0.741 | 90 |

Before step 43 the retrained variant reaches precision 0.914. From step 43, after a major dark
market closed, no variant finds the new illicit behaviour (recall 1 to 5%), but recalibration
stops the flood of false flags. Outputs are in `outputs/h1_recalibration/`.

## Phase 2: TRON/USDT wallets and mobile-money attribution (synthetic data)

Implements concept note Section 12 on a **generated** world: users, P2P traders, two exchanges
and a scam ring whose mules sell USDT to traders and receive shillings on M-Pesa, Tigo Pesa,
Airtel Money or HaloPesa. No real mobile-money or P2P records are used.

```bash
python run_phase2.py --stress        # generate the world, analyse it, stress-test (about 2 minutes)
python build_phase2_dashboard.py     # writes outputs/phase2/dashboard_phase2.html
```

The pipeline, in `src/phase2/`:

1. **Services and traders** (`wallets.py`): finds exchange deposit addresses (forward everything
   to one hot wallet within hours) and P2P-trader wallets (many distinct counterparties in both
   directions, active most days).
2. **Wallet clustering**: deposit-address reuse and TRX activation funding.
3. **Off-chain matching** (`matching.py`): each trade with a known trader is matched to a payment on
   the trader's mobile-money statement by time window and by the trader spread implied by that
   day's USD/TZS rate. Evidence adds up per wallet cluster and account; High needs repetition.
4. **Cash-out leads**: funds are traced two hops from victim-reported wallets, stopping at
   exchanges and traders, and joined to the attribution pairs.
5. **Evaluation** (`evaluate.py`) is the only code that reads the ground-truth files.

The stress test regenerates the world with more decoy payments, slower settlement and wider
spreads. Settlement delay and spread matter most, so both windows must be calibrated on real
statements before any pilot. `trader_directory.csv` stands in for trader statements, which in
reality need lawful requests to operators. Every link is a lead, never proof of identity, and a
linked account may belong to a relative or agent rather than the wallet owner.

Settings are in the Phase 2 block of `src/config.py`.

## Phase 3: smart-contract static analysis (Track B)

Track B asks a different question from Track A: is this contract code exploitable, before or at
deployment? It runs Slither on the SmartBugs curated benchmark (143 Solidity contracts, each flaw
labelled by line) and scores what static analysis catches. It needs its own environment.

```bash
python -m venv .venv-phase3
.venv-phase3/bin/pip install -r requirements-phase3.txt
git clone --depth 1 https://github.com/smartbugs/smartbugs-curated data/phase3/smartbugs-curated
.venv-phase3/bin/solc-select install 0.4.0 0.4.2 0.4.9 0.4.10 0.4.11 0.4.13 0.4.15 0.4.16 \
    0.4.18 0.4.19 0.4.21 0.4.22 0.4.23 0.4.24 0.4.25 0.5.0
.venv-phase3/bin/python run_phase3.py        # under a minute; raw Slither output is cached
python build_phase3_dashboard.py             # writes outputs/phase3/dashboard_phase3.html
```

Results (141 of 143 contracts analysed; Slither crashes on 2):

| Category | Labelled | Found on the labelled line |
|---|---|---|
| Unchecked low-level calls | 75 | 59 (79%) |
| Reentrancy | 30 | 27 (90%) |
| Access control | 21 | 5 (24%) |
| Bad randomness | 31 | 1 (3%) |
| Time manipulation | 7 | 3 (43%) |
| Arithmetic overflow, front running, short addresses | 31 | no static detector |
| **All** | **205** | **99 (48%)**; 57% where a detector exists |

A finding counts when a detector for the same category reports within 2 lines of a labelled line.
The detector-to-category mapping in `src/phase3/evaluate.py` was fixed before the scan ran.
Static analysis misses arithmetic and transaction-ordering flaws, so the full Phase 3 adds fuzzing
(Echidna or Foundry). The tracks meet at one point: addresses that interacted with a contract
found to be malicious become starting points for Track A and Phase 2 tracing.

## Scope reminders

- The Phase 1 model classifies **transactions**, not wallets. Wallet clustering is in Phase 2 (TRON).
- Elliptic is anonymised Bitcoin data and says nothing about Tanzania.
- Scores are leads for human review, never conclusions about any person.
