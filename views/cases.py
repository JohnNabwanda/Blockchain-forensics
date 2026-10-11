"""Case workspace shared by all modules: register, review queue, case graph, timeline and evidence pack."""
import json

import pandas as pd
import streamlit as st

from src.live import evidence, feedback, store
from views.common import BAND_COLOR, CHAIN_TAG, analyst, can, dot, need, page_header, role, short

MODULES = {"bitcoin": "Bitcoin model", "btc": "Bitcoin address", "tron": "TRON / USDT", "eth": "Ethereum",
           "contract": "Smart contract", "mobile_money": "Mobile money", "crosschain": "Cross-chain"}

page_header("Casework", "Cases", "One workspace per case: every wallet, contract and account linked to it across chains, "
            "one timeline, one graph, a review queue and an evidence pack.")

c1, c2 = st.columns(2)
status = c1.multiselect("Status", store.STATUSES, default=["Open", "Escalated"])
module = c2.selectbox("Module", ["All"] + list(MODULES), format_func=lambda m: MODULES.get(m, m))
df = store.cases(status=status or None, module=None if module == "All" else module)

if df.empty:
    st.info("No cases match. Open a case from any investigation page.")
    st.stop()

view = df.assign(module=df["module"].map(lambda m: MODULES.get(m, m)))[
    ["id", "title", "module", "risk_band", "risk_score", "status", "assignee", "updated_utc"]]
st.dataframe(view, hide_index=True, width="stretch", column_config={
    "id": st.column_config.NumberColumn("Case", format="#%d"),
    "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%.0f"),
    "updated_utc": st.column_config.DatetimeColumn("Updated (UTC)")})

ids = list(df["id"])
default = ids.index(st.session_state["case_id"]) if st.session_state.get("case_id") in ids else 0
case_id = int(st.selectbox("Open case", ids, index=default,
                           format_func=lambda i: f"#{i} · {df.set_index('id').loc[i, 'title']}"))
st.session_state["case_id"] = case_id
c, trail = store.case(case_id)
ce = store.case_entities(case_id)
st.divider()
h1, h2 = st.columns([3, 1])
h1.subheader(f"#{c['id']} · {c['title']}")
if c["risk_band"]:
    h2.badge(f"{c['risk_band']} risk", color=BAND_COLOR.get(c["risk_band"], "gray"))
st.caption(f"{MODULES.get(c['module'], c['module'])} · subject `{c['subject']}` · status **{c['status']}** · "
           f"assigned to {c['assignee']} · opened {c['created_utc']}")
pending = int((ce["status"] == "Pending").sum()) if len(ce) else 0
chains = sorted({CHAIN_TAG.get(x, x) for x in ce["chain"].dropna()}) if len(ce) else []
m = st.columns(4)
m[0].metric("Linked entities", len(ce))
m[1].metric("Leads to review", pending)
m[2].metric("Chains", len(chains), " · ".join(chains) or None, delta_color="off", delta_arrow="off")
m[3].metric("Confirmed", int((ce["status"] == "Confirmed").sum()) if len(ce) else 0)

t_sum, t_leads, t_graph, t_time, t_pack = st.tabs(["Summary", "Review queue", "Case graph", "Timeline", "Evidence pack"])

with t_sum:
    if c["summary"]:
        st.markdown(f"**Summary:** {c['summary']}")
    jump = {"tron": ("tron_addr", "views/tron.py"), "eth": ("eth_addr", "views/ethereum.py"),
            "btc": ("btc_addr", "views/btc_live.py")}
    if c["module"] in jump and st.button("Open investigation", icon=":material/arrow_forward:"):
        st.session_state[jump[c["module"]][0]] = c["subject"]
        st.switch_page(jump[c["module"]][1])
    if st.button("Trace this case across chains", icon=":material/swap_horiz:"):
        st.switch_page("views/crosschain.py")
    if need("case", "change cases"):
        with st.form("update"):
            u1, u2 = st.columns([1, 2])
            allowed = store.STATUSES if can("close") else ["Open", "Escalated"]
            options = allowed if c["status"] in allowed else [c["status"]] + allowed
            new_status = u1.selectbox("Status", options, index=options.index(c["status"]),
                                      help="Only supervisors can confirm, dismiss or close a case.")
            assignee = u1.text_input("Assigned to", c["assignee"] or "")
            note = u2.text_area("Note / justification", height=110, help="Required to confirm, dismiss or close a case")
            if st.form_submit_button("Save", type="primary"):
                try:
                    store.update_case(analyst(), case_id, status=new_status if new_status != c["status"] else None,
                                      note=note, assignee=assignee if assignee != c["assignee"] else None)
                    st.success("Saved.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    st.markdown("**Case history**")
    st.dataframe(trail, hide_index=True, width="stretch")
    with st.expander("Evidence recorded when the case was opened"):
        st.json(json.loads(c["evidence"] or "{}"), expanded=False)

with t_leads:
    if ce.empty:
        st.info("Nothing attached yet. Use **Attach** after a trace, or the cross-chain page, to add leads.")
    else:
        st.caption("Confirm or dismiss each lead with a reason. Every decision is kept with the score the lead had and "
                   "retunes the risk bands for its module (see Feedback loop).")
        st.dataframe(ce[["role", "entity_id", "kind", "label", "risk_score", "risk_band", "status", "decided_by", "note"]],
                     hide_index=True, width="stretch", column_config={
                         "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%.0f")})
        queue = ce[ce["status"] == "Pending"]
        if queue.empty:
            st.success("All leads reviewed.")
        elif need("lead", "review leads"):
            pick = st.selectbox("Lead", list(queue["entity_id"]), format_func=lambda i: (
                f"{i}  ·  {queue.set_index('entity_id').loc[i, 'risk_band'] or 'unscored'}"))
            r = queue.set_index("entity_id").loc[pick]
            if isinstance(r["reasons"], str) and r["reasons"] != "[]":
                st.caption("Indicators: " + ", ".join(json.loads(r["reasons"])))
            with st.form("lead", clear_on_submit=True):
                d = st.radio("Decision", ["Confirmed", "Dismissed"], horizontal=True)
                why = st.text_area("Justification (required)", height=80)
                if st.form_submit_button("Record decision", type="primary"):
                    try:
                        store.decide_lead(analyst(), case_id, pick, d, why)
                        changed = feedback.recalibrate(analyst(), r["module"] or "")
                        st.success(f"{pick} {d.lower()}." + (
                            f" Risk bands for {feedback.MODULES[r['module']]} retuned: High from "
                            f"{changed['current_high']:g} to {changed['high']:g}." if changed else ""))
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

with t_graph:
    if ce.empty:
        st.info("No entities attached to this case yet.")
    else:
        hops = st.radio("Show", [0, 1, 2], index=1, horizontal=True,
                        format_func=lambda h: {0: "Case entities only", 1: "+ direct links", 2: "+ two hops"}[h])
        ents, links = store.neighbourhood(list(ce["entity_id"]), hops=max(hops, 1) if hops else 0, max_nodes=60)
        if hops == 0:
            ents = ents[ents["id"].isin(ce["entity_id"])]
            links = links[links["src"].isin(ce["entity_id"]) & links["dst"].isin(ce["entity_id"])] if len(links) else links
        role_of = ce.set_index("entity_id")
        nodes = {}
        for e in ents.itertuples():
            r = role_of.loc[e.id] if e.id in role_of.index else None
            nodes[e.id] = {"label": f"{CHAIN_TAG.get(e.chain, e.chain)} {short(e.address)}",
                           "sub": (e.label or (f"{e.risk_band} risk" if e.risk_band else e.kind)),
                           "root": r is not None and r["role"] == "subject",
                           "status": None if r is None else r["status"],
                           "flag": e.risk_band == "High", "service": e.kind == "service"}
        style = {"same_key": ("dashed", "violet"), "cross_chain": ("bold", "accent"), "attribution": ("solid", "bad")}
        edges = []
        for l in links.itertuples() if len(links) else []:
            amt = l.amount_usd if l.amount_usd == l.amount_usd and l.amount_usd is not None else l.amount
            lab = l.kind.replace("_", " ") + (f" · {amt:,.0f}" if amt == amt and amt is not None else "")
            st_, col = style.get(l.kind, ("solid", None))
            edges.append((l.src, l.dst, {"label": lab, "style": st_, "color": col,
                                         "width": 2.2 if l.kind in style else 1.2}))
        if len(nodes) > 60:
            st.caption("Large graph: showing the first 60 entities.")
        st.graphviz_chart(dot(nodes, edges), width="content")
        st.caption("Blue = case subject · orange = confirmed or high risk · green dashed = dismissed · yellow = service · "
                   "violet dashed = same key · bold blue = cross-chain hop.")

with t_time:
    ents, links = store.neighbourhood(list(ce["entity_id"]), hops=1) if len(ce) else (pd.DataFrame(), pd.DataFrame())
    tl = evidence.timeline(case_id, links)
    if tl.empty:
        st.info("No dated events yet.")
    else:
        st.scatter_chart(tl, x="ts_utc", y="type", color="type", height=220)
        st.dataframe(tl, hide_index=True, width="stretch",
                     column_config={"ts_utc": st.column_config.DatetimeColumn("Time (UTC)", format="D MMM YYYY, HH:mm")})

with t_pack:
    st.markdown("An evidence pack bundles the case, its leads and decisions, the case graph, the timeline, the audit trail "
                "and a readable report, with a SHA-256 manifest. Its hash is entered in the custody register.")
    if need("export", "export evidence"):
        if st.button("Build evidence pack", type="primary", icon=":material/inventory_2:"):
            data, digest, name = evidence.build(analyst(), case_id)
            st.session_state["pack"] = (case_id, data, digest, name)
        p = st.session_state.get("pack")
        if p and p[0] == case_id:
            st.success(f"Pack built and registered. SHA-256 `{p[2]}`")
            st.download_button("Download evidence pack (.zip)", p[1], p[3], "application/zip", icon=":material/download:")
    st.markdown("**Custody record**")
    cust = store.custody_log(case_id)
    if cust.empty:
        st.caption("No exports yet.")
    else:
        st.dataframe(cust[["ts_utc", "analyst", "action", "item", "sha256", "detail"]], hide_index=True, width="stretch")
