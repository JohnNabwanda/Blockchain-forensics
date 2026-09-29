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

## Scope reminders

- The model classifies **transactions**, not wallets. Wallet clustering comes in Phase 2 (TRON).
- Elliptic is anonymised Bitcoin data and says nothing about Tanzania.
- Scores are leads for human review, never conclusions about any person.
