"""Investigator dashboard for the PoC.   Run:  streamlit run app.py"""
import pandas as pd
import streamlit as st

from src import config
from src.dashboard_data import (load_decisions, load_outputs, plot_neighbourhood, reasons_table,
                                record_decision, review_queue)

st.set_page_config(page_title="Blockchain Forensics PoC", layout="wide")

if not (config.OUTPUT_DIR / "meta.json").exists():
    st.error("No results yet. Run `python run_pipeline.py` first.")
    st.stop()


@st.cache_resource
def data():
    return load_outputs()


meta, scored, expl, nodes, G = data()

st.title("Blockchain Forensics: Proof of Concept")
if meta["synthetic_data"]:
    st.warning("Running on SYNTHETIC data. Results only demonstrate the software, not real detection performance.")
st.caption(f"Model {meta['model']} on {meta['feature_set']} · version {meta['model_version']} · "
           f"threshold {meta['threshold']:.3f} (precision target {meta['precision_target']:.2f}) · "
           f"explanations: {meta['explanation_method']}")
st.info("Risk scores are leads for human review, not findings. No automatic action is taken against any "
        "transaction, person or account, and nothing leaves this tool without analyst sign-off.")

tab_review, tab_results, tab_log = st.tabs(["Case review", "Model results", "Decision log"])

# ---------------------------------------------------------------- case review
with tab_review:
    c1, c2 = st.columns([1, 2])
    with c1:
        bands = st.multiselect("Risk bands", ["High", "Medium"], default=["High"])
        steps = sorted(scored["time_step"].unique())
        step = st.selectbox("Time step", ["All"] + [int(s) for s in steps])
        q = review_queue(scored, bands=bands or ["High"], step=None if step == "All" else step)
        st.metric("Cases in queue", len(q), help="Unreviewed cases are listed first, highest score first")
        if q.empty:
            st.write("No cases match these filters.")
            st.stop()
        labels = {f"{r.txId}  ·  score {r.score:.2f}  ·  {r.band}{'  ✓' if r.reviewed else ''}": r.txId
                  for r in q.itertuples()}
        tx_id = labels[st.selectbox("Select case", list(labels))]
        row = scored[scored["txId"] == tx_id].iloc[0]

    with c2:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Risk score", f"{row['score']:.3f}")
        m2.metric("Band", row["band"])
        m3.metric("Time step", int(row["time_step"]))
        m4.metric("Elliptic label*", {1: "illicit", 0: "licit"}.get(int(row["label"]), "unknown"))
        st.caption("*Ground-truth label, shown only because this is an evaluation on labelled data.")

        st.subheader("Why was this flagged?")
        rt = reasons_table(expl, tx_id)
        if rt.empty:
            st.write("No positive contributing features recorded.")
        else:
            st.bar_chart(rt.set_index("description")["contribution"], horizontal=True)
            st.dataframe(rt.rename(columns={"description": "Reason", "feature": "Feature", "value": "Value",
                                            "contribution": "Push towards illicit"}),
                         hide_index=True)

        st.subheader("Where does it sit in the flow of funds?")
        st.caption("Colour = model risk score of each neighbouring transaction, including unlabelled ones.")
        hops = st.radio("Neighbourhood depth", [1, 2], horizontal=True)
        st.pyplot(plot_neighbourhood(G, tx_id, nodes, hops=hops))

    st.divider()
    st.subheader("Analyst decision")
    with st.form("decision", clear_on_submit=True):
        d1, d2 = st.columns([1, 3])
        analyst = d1.text_input("Analyst")
        decision = d1.radio("Decision", ["Confirm", "Dismiss", "Escalate"])
        why = d2.text_area("Justification (required)", height=120)
        if st.form_submit_button("Record decision"):
            try:
                record_decision(tx_id, decision, why, analyst, row, meta)
                st.success(f"{decision} recorded for {tx_id}.")
            except ValueError as e:
                st.error(str(e))

# ---------------------------------------------------------------- results
with tab_results:
    report = (config.OUTPUT_DIR / "report.md").read_text()
    st.markdown(report)
    for img, cap in [("pr_curves.png", "Precision-recall with and without graph features"),
                     ("model_comparison.png", "All models and feature sets"),
                     ("per_step_test.png", "Performance across test time steps")]:
        p = config.OUTPUT_DIR / img
        if p.exists():
            st.image(str(p), caption=cap)

# ---------------------------------------------------------------- log
with tab_log:
    log = load_decisions()
    st.write(f"{len(log)} decisions recorded. Dismissed flags feed threshold recalibration and retraining.")
    if not log.empty:
        st.dataframe(log.sort_values("timestamp_utc", ascending=False), hide_index=True)
        counts = log["decision"].value_counts()
        st.bar_chart(counts)
        st.download_button("Download log (CSV)", log.to_csv(index=False), "decisions.csv", "text/csv")
