"""Append-only, hash-chained audit trail; chain-of-custody register; evidence-pack verification."""
import streamlit as st

from src.live import evidence, store
from views.common import analyst, need, page_header

page_header("Casework · Audit", "Audit log", "Every sign-in, lookup, scan, case change and decision, with who did it and when "
            "(UTC). Each entry carries the SHA-256 of the one before it, so editing or deleting any entry is detectable.")

t_log, t_cust, t_verify = st.tabs(["Audit log", "Chain of custody", "Verify evidence pack"])

with t_log:
    if need("verify", "verify the audit chain"):
        if st.button("Verify audit chain", icon=":material/verified:"):
            ok, n, bad, head = store.verify_audit()
            store.log(analyst(), "audit chain verified" if ok else "audit chain BROKEN", detail=f"{n} entries, head {head[:16]}")
            if ok:
                st.success(f"Intact: all {n} entries chain correctly. Head hash `{head}`")
            else:
                st.error(f"Broken at entry #{bad}: that entry or one before it was altered or removed.")
    log = store.audit(limit=2000)
    c1, c2 = st.columns(2)
    who = c1.multiselect("Analyst", sorted(log["analyst"].unique()))
    what = c2.text_input("Filter action or subject")
    if who:
        log = log[log["analyst"].isin(who)]
    if what:
        m = log["action"].str.contains(what, case=False, na=False) | log["subject"].fillna("").str.contains(what, case=False)
        log = log[m]
    st.dataframe(log, hide_index=True, width="stretch", column_config={
        "hash": st.column_config.TextColumn("Entry hash", width="small"),
        "prev_hash": st.column_config.TextColumn("Previous hash", width="small")})
    st.download_button("Download (CSV)", log.to_csv(index=False), "audit_log.csv", "text/csv", icon=":material/download:")

with t_cust:
    st.caption("Every evidence pack exported or checked, with the SHA-256 of the pack file.")
    cust = store.custody_log()
    if cust.empty:
        st.info("No evidence packs exported yet. Build one from a case's **Evidence pack** tab.")
    else:
        st.dataframe(cust, hide_index=True, width="stretch")

with t_verify:
    st.caption("Upload an evidence pack received from this platform to check that no file was changed and that the "
               "pack is the one recorded at export.")
    if need("verify", "verify evidence packs"):
        up = st.file_uploader("Evidence pack (.zip)", type=["zip"])
        if up and st.button("Verify pack", type="primary"):
            r = evidence.verify(analyst(), up.getvalue(), up.name)
            if r["ok"] and r["registered"]:
                st.success(f"Intact and registered: every file matches the manifest, and this exact pack was exported "
                           f"on {r['manifest']['exported_utc']} by {r['manifest']['exported_by']}.")
            elif r["ok"]:
                st.warning("Files match the manifest, but this pack's hash is not in the custody register "
                           "(it was re-zipped or exported elsewhere).")
            else:
                st.error("Tampered or incomplete: " + "; ".join(r["problems"]))
            st.caption(f"Pack SHA-256 `{r['sha256']}`")
