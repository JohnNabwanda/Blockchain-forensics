"""Feedback loop: how analyst decisions retune the risk bands of every module."""
import json

import pandas as pd
import streamlit as st

from src import config
from src.dashboard_data import load_decisions
from src.live import feedback, store
from views.common import analyst, need, page_header

page_header("Evidence · Feedback loop", "Feedback loop",
            "Every lead an analyst confirms or dismisses is stored with the score it had. After each decision the High "
            "band is re-chosen so that, on reviewed leads, at least "
            f"{feedback.PRECISION_TARGET:.0%} of High leads were confirmed. This is the H1 follow-up running continuously.",
            {"Target": f"{feedback.PRECISION_TARGET:.0%} confirmed", "Minimum": f"{feedback.MIN_DECISIONS} decisions",
             "Rule": "lowest score meeting the target"})

rows = []
for m, name in feedback.MODULES.items():
    cur = feedback.current(m)
    d = store.decisions(m)
    p = feedback.propose(m)
    rows.append({"module": name, "high_from": cur["high"], "medium_from": cur["medium"], "decisions": len(d),
                 "confirmed": int((d["status"] == "Confirmed").sum()),
                 "precision_now": feedback.precision_at(d, cur["high"])[0] if len(d) else None,
                 "status": "calibrated from decisions" if store.thresholds(m) else
                           f"defaults (needs {max(feedback.MIN_DECISIONS - len(d), 0)} more decisions)" if not p else "defaults"})
st.subheader("Risk bands now")
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
    "high_from": st.column_config.NumberColumn("High from", format="%.0f"),
    "medium_from": st.column_config.NumberColumn("Medium from", format="%.1f"),
    "precision_now": st.column_config.ProgressColumn("Confirmed share of High leads", min_value=0, max_value=1, format="percent")})

st.subheader("Decisions behind them")
d = store.decisions()
if d.empty:
    st.info("No lead decisions yet. Review leads in a case's **Review queue**; each decision appears here.")
else:
    d = d.assign(module=d["mod"].map(lambda m: feedback.MODULES.get(m, m)))
    st.scatter_chart(d, x="score_at_review", y="module", color="status", height=240)
    st.dataframe(d[["decided_utc", "module", "entity_id", "score_at_review", "status", "decided_by", "note", "case_id"]]
                 .sort_values("decided_utc", ascending=False), hide_index=True, width="stretch")

st.subheader("Threshold history")
h = store.threshold_history()
if h.empty:
    st.caption("No recalibration yet: every module is on its default bands (High 50, Medium 20).")
else:
    st.dataframe(h.assign(module=h["module"].map(lambda m: feedback.MODULES.get(m, m)))
                 [["updated_utc", "module", "high", "medium", "precision", "decisions", "reason", "updated_by"]],
                 hide_index=True, width="stretch")
if need("recalibrate", "reset thresholds"):
    with st.popover("Reset a module to default bands", icon=":material/restart_alt:"):
        m = st.selectbox("Module", list(feedback.MODULES), format_func=feedback.MODULES.get)
        why = st.text_input("Reason")
        if st.button("Reset", disabled=not why.strip()):
            store.set_thresholds(analyst(), m, feedback.DEFAULT["high"], feedback.DEFAULT["medium"], None, 0,
                                 f"reset to defaults: {why.strip()}")
            st.rerun()

st.divider()
st.subheader("Bitcoin graph model")
meta_f = config.OUTPUT_DIR / "meta.json"
if meta_f.exists():
    meta = json.load(open(meta_f))
    bt = feedback.bitcoin_threshold(load_decisions(), meta["threshold"])
    c = st.columns(3)
    c[0].metric("Model threshold", f"{meta['threshold']:.3f}")
    c[1].metric("Recalibrated", f"{bt['threshold']:.3f}", "changed" if bt["changed"] else "unchanged",
                delta_color="off", delta_arrow="off")
    c[2].metric("Reviewed alerts", bt["decisions"])
    st.caption(f"{bt['reason']}. The Bitcoin page applies the recalibrated threshold to its alert bands. "
               "Offline study of the same loop (H1 follow-up): precision 0.516 → 0.798 with recalibration, 0.899 with retraining.")
else:
    st.caption("Bitcoin model not trained on this server.")
