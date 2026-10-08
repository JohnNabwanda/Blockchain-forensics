"""Case register shared by all modules."""
import json

import streamlit as st

from src.live import store
from views.common import BAND_COLOR, analyst, page_header

MODULES = {"bitcoin": "Bitcoin", "tron": "TRON / USDT", "contract": "Smart contract", "mobile_money": "Mobile money"}

page_header("Casework", "Cases", "Every lead opened from any module, with status, assignee and full history.")

c1, c2 = st.columns(2)
status = c1.multiselect("Status", store.STATUSES, default=["Open", "Escalated"])
module = c2.selectbox("Module", ["All"] + list(MODULES), format_func=lambda m: MODULES.get(m, m))
df = store.cases(status=status or None, module=None if module == "All" else module)

if df.empty:
    st.info("No cases match. Open a case from any investigation page.")
    st.stop()

view = df.assign(module=df["module"].map(MODULES))[["id", "title", "module", "risk_band", "risk_score", "status",
                                                     "assignee", "updated_utc"]]
st.dataframe(view, hide_index=True, width="stretch", column_config={
    "id": st.column_config.NumberColumn("Case", format="#%d"),
    "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%.0f"),
    "updated_utc": st.column_config.DatetimeColumn("Updated (UTC)")})

case_id = st.selectbox("Open case", df["id"], format_func=lambda i: f"#{i} · {df.set_index('id').loc[i, 'title']}")
c, trail = store.case(case_id)
st.divider()
h1, h2 = st.columns([3, 1])
h1.subheader(f"#{c['id']} · {c['title']}")
if c["risk_band"]:
    h2.badge(f"{c['risk_band']} risk", color=BAND_COLOR.get(c["risk_band"], "gray"))
st.caption(f"{MODULES.get(c['module'], c['module'])} · subject `{c['subject']}` · status **{c['status']}** · "
           f"assigned to {c['assignee']} · opened {c['created_utc']}")
if c["summary"]:
    st.markdown(f"**Summary:** {c['summary']}")
if c["module"] == "tron" and st.button("Open wallet investigation", icon=":material/arrow_forward:"):
    st.session_state["tron_addr"] = c["subject"]
    st.switch_page("views/tron.py")

with st.form("update"):
    u1, u2 = st.columns([1, 2])
    new_status = u1.selectbox("Status", store.STATUSES, index=store.STATUSES.index(c["status"]))
    assignee = u1.text_input("Assigned to", c["assignee"] or "")
    note = u2.text_area("Note / justification", height=110,
                        help="Required to confirm, dismiss or close a case")
    if st.form_submit_button("Save", type="primary"):
        try:
            store.update_case(analyst(), int(case_id), status=new_status if new_status != c["status"] else None,
                              note=note, assignee=assignee if assignee != c["assignee"] else None)
            st.success("Saved.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

st.markdown("**Case history**")
st.dataframe(trail, hide_index=True, width="stretch")
with st.expander("Evidence"):
    st.json(json.loads(c["evidence"] or "{}"), expanded=False)
st.download_button("Export case (JSON)",
                   json.dumps({"case": c.to_dict(), "history": trail.to_dict("records")}, default=str, indent=1),
                   f"case_{case_id}.json", "application/json", icon=":material/download:")
