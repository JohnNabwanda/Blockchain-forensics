"""Bitcoin transaction risk: the trained graph model on the Elliptic Bitcoin transaction graph."""
import streamlit as st

from src import config
from src.dashboard_data import load_decisions, load_outputs, plot_neighbourhood, reasons_table, record_decision, review_queue
from src.live import store
from views.common import analyst, band_badge, lead_notice, open_case_button, page_header


if not (config.OUTPUT_DIR / "meta.json").exists():
    st.error("The Bitcoin model has not been trained on this server yet. Run `python run_pipeline.py`.")
    st.stop()


@st.cache_resource
def data():
    return load_outputs()


meta, scored, expl, nodes, G = data()
if meta["synthetic_data"]:
    st.warning("The model on this server was trained on generated data, not the Elliptic dataset.")
page_header("Investigate · Bitcoin", "Transaction risk alerts",
            "A graph machine-learning model scores Bitcoin transactions, explains each alert and shows its flow of funds.",
            {"Model": meta["model"], "Version": meta["model_version"], "Threshold": f"{meta['threshold']:.3f}",
             "Scored": f"{len(scored):,} transactions"})
lead_notice()

tab_review, tab_results, tab_log = st.tabs(["Case review", "Model performance", "Analyst decisions"])

with tab_review:
    c1, c2 = st.columns([1, 2.2])
    with c1:
        search = st.text_input("Search transaction ID", placeholder="e.g. 232438397")
        if search.strip():
            hit = scored[scored["txId"].astype(str) == search.strip()]
            if hit.empty:
                st.warning("Not in the scored evaluation period.")
                st.stop()
            tx_id = hit.iloc[0]["txId"]
        else:
            bands = st.multiselect("Risk bands", ["High", "Medium"], default=["High"])
            steps = sorted(scored["time_step"].unique())
            step = st.selectbox("Time step", ["All"] + [int(s) for s in steps])
            q = review_queue(scored, bands=bands or ["High"], step=None if step == "All" else step)
            st.metric("Alerts in queue", len(q), help="Unreviewed first, highest score first")
            if q.empty:
                st.write("No alerts match these filters.")
                st.stop()
            labels = {f"{r.txId}  ·  {r.score:.2f}  ·  {r.band}{'  ✓' if r.reviewed else ''}": r.txId
                      for r in q.itertuples()}
            tx_id = labels[st.selectbox("Alert", list(labels))]
        row = scored[scored["txId"] == tx_id].iloc[0]

    with c2:
        h1, h2 = st.columns([3, 1])
        h1.subheader(f"Transaction {tx_id}")
        with h2:
            band_badge(row["band"])
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Risk score", f"{row['score']:.3f}")
        m2.metric("Band", row["band"])
        m3.metric("Time step", int(row["time_step"]))
        m4.metric("Elliptic label", {1: "Illicit", 0: "Licit"}.get(int(row["label"]), "Unknown"))

        st.markdown("**Why was this flagged?**")
        rt = reasons_table(expl, tx_id)
        if rt.empty:
            st.write("No positive contributing features recorded.")
        else:
            st.bar_chart(rt.set_index("description")["contribution"], horizontal=True)
            st.dataframe(rt.rename(columns={"description": "Reason", "feature": "Feature", "value": "Value",
                                            "contribution": "Push towards illicit"}), hide_index=True)

        st.markdown("**Flow of funds**")
        hops = st.radio("Neighbourhood depth", [1, 2], horizontal=True)
        st.pyplot(plot_neighbourhood(G, tx_id, nodes, hops=hops))
        open_case_button("bitcoin", str(tx_id), f"Bitcoin transaction {tx_id}", float(row["score"]) * 100, row["band"],
                         summary="; ".join(rt["description"].head(3)) if not rt.empty else "",
                         evidence={"score": float(row["score"]), "time_step": int(row["time_step"])})

    st.divider()
    st.subheader("Analyst decision")
    with st.form("decision", clear_on_submit=True):
        decision = st.radio("Decision", ["Confirm", "Dismiss", "Escalate"], horizontal=True)
        why = st.text_area("Justification (required)", height=100)
        if st.form_submit_button("Record decision", type="primary"):
            try:
                record_decision(tx_id, decision, why, analyst(), row, meta)
                store.log(analyst(), f"bitcoin decision: {decision}", module="bitcoin", subject=str(tx_id), detail=why)
                st.success(f"{decision} recorded for {tx_id}. Dismissed alerts feed threshold recalibration.")
            except ValueError as e:
                st.error(str(e))

with tab_results:
    st.markdown((config.OUTPUT_DIR / "report.md").read_text())
    for img, cap in [("pr_curves.png", "Precision-recall with and without graph features"),
                     ("model_comparison.png", "All models and feature sets"),
                     ("per_step_test.png", "Performance across evaluation time steps")]:
        p = config.OUTPUT_DIR / img
        if p.exists():
            st.image(str(p), caption=cap)

with tab_log:
    log = load_decisions()
    st.write(f"{len(log)} decisions recorded.")
    if not log.empty:
        st.dataframe(log.sort_values("timestamp_utc", ascending=False), hide_index=True)
        st.download_button("Download decisions (CSV)", log.to_csv(index=False), "decisions.csv", "text/csv")
