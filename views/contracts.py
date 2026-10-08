"""Smart-contract audit: live Slither analysis of uploaded or pasted Solidity source."""
import json

import pandas as pd
import streamlit as st

from src import config
from src.live import contracts, store
from views.common import analyst, band_badge, lead_notice, open_case_button

st.title(":material/data_object: Smart-contract audit")
st.caption("Static analysis with Slither. Upload or paste a Solidity contract, e.g. one used in a reported "
           "investment scam, to find the flaws or hidden functions that put users' funds at risk.")

if not (config.SLITHER_ENV / "bin" / "slither").exists():
    st.error("Slither is not installed on this server (see README, Phase 3 setup).")
    st.stop()

tab_up, tab_paste = st.tabs(["Upload file", "Paste source"])
with tab_up:
    up = st.file_uploader("Solidity file", type=["sol"])
with tab_paste:
    pasted = st.text_area("Solidity source", height=220, placeholder="pragma solidity ^0.8.0;\ncontract …")
    name = st.text_input("File name", "Contract.sol")

source, filename = (up.getvalue().decode("utf-8", "replace"), up.name) if up else (pasted, name)
c1, c2 = st.columns([1, 3])
show_low = c2.toggle("Include low-severity and informational findings", value=False)
if c1.button("Analyse contract", type="primary", icon=":material/bug_report:", disabled=not source.strip()):
    with st.spinner("Compiling and analysing…"):
        st.session_state["scan"] = contracts.scan_source(source, filename)
    r = st.session_state["scan"]
    store.log(analyst(), "contract scan", module="contract", subject=filename,
              detail=f"sha256 {r['sha256'][:16]}, {len(r['findings'])} findings" + (f", error: {r['error']}" if r["error"] else ""))
st.caption(f"Compilers available: {', '.join(contracts.installed_solc())}")

r = st.session_state.get("scan")
if not r:
    st.stop()
if r["error"]:
    st.error(r["error"])
    st.stop()

findings = [f for f in r["findings"] if show_low or f["severity"] in ("High", "Medium")]
score, band = contracts.risk(r["findings"])
h1, h2 = st.columns([3, 1])
h1.subheader(r["filename"])
with h2:
    band_badge(band, score)
counts = pd.Series([f["severity"] for f in r["findings"]]).value_counts()
m = st.columns(5)
m[0].metric("High", int(counts.get("High", 0)))
m[1].metric("Medium", int(counts.get("Medium", 0)))
m[2].metric("Low", int(counts.get("Low", 0)))
m[3].metric("Compiler", r["solc"])
m[4].metric("Lines", r["lines"])
st.caption(f"Contracts: {', '.join(r['contracts']) or '-'} · SHA-256 {r['sha256']}")
lead_notice()

if not findings:
    st.success("No findings at this severity level.")
for f in findings:
    icon = {"High": ":material/error:", "Medium": ":material/warning:"}.get(f["severity"], ":material/info:")
    with st.expander(f"{f['severity']} · {f['check']} · lines {', '.join(map(str, f['lines'][:6])) or '-'}", icon=icon):
        st.markdown(f"Confidence: **{f['confidence']}**")
        st.code(f["description"], language=None, wrap_lines=True)
        if source and f["lines"]:
            src_lines = source.splitlines()
            lo, hi = max(min(f["lines"]) - 2, 1), min(max(f["lines"]) + 2, len(src_lines))
            st.code("\n".join(f"{i:>4}  {src_lines[i - 1]}" for i in range(lo, hi + 1)), language="solidity")

c1, c2 = st.columns(2)
with c1:
    open_case_button("contract", r["sha256"][:16], f"Contract {r['filename']}", score, band,
                     summary=", ".join(sorted({f["check"] for f in r["findings"] if f["severity"] in ("High", "Medium")})),
                     evidence={"sha256": r["sha256"], "solc": r["solc"], "findings": r["findings"]})
with c2:
    st.download_button("Export findings (JSON)", json.dumps(r, indent=1), f"{r['filename']}.audit.json",
                       "application/json", icon=":material/download:")
