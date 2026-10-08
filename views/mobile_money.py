"""Mobile-money attribution: match a P2P trader's mobile-money statement to their USDT transfers."""
import pandas as pd
import streamlit as st

from src.live import mobile_money as mm
from src.live import store, tron
from views.common import analyst, lead_notice, open_case_button, page_header

page_header("Investigate · Mobile money", "Mobile-money attribution",
            "Links crypto cash-outs to mobile-money accounts. Import a P2P trader's statement obtained from the "
            "operator under lawful process; the platform fetches the trader's USDT transfers live and matches each "
            "payment by timing and exchange-rate spread.",
            {"Operators": "M-Pesa · Airtel Money · Tigo Pesa · HaloPesa", "On-chain": "live TRON / USDT"})

with st.expander("Statement format", icon=":material/description:"):
    st.markdown("CSV with one row per payment:\n\n"
                "| column | meaning |\n|---|---|\n"
                "| `ts` | payment time, local time (e.g. `2026-06-01 14:05:00`) |\n"
                "| `direction` | `out` = trader paid the counterparty, `in` = trader was paid |\n"
                "| `counterparty_account` | the other party's account or phone number |\n"
                "| `amount_tzs` | amount in shillings |\n"
                "| `operator` | optional: M-Pesa, Airtel Money, Tigo Pesa, HaloPesa … |")
    template = pd.DataFrame([{"ts": "2026-06-01 14:05:00", "direction": "out", "counterparty_account": "255700000000",
                              "amount_tzs": 265000, "operator": "M-Pesa"}])
    st.download_button("Download template", template.to_csv(index=False), "statement_template.csv", "text/csv")

src = st.radio("Data", ["Import a case", "Training sample"], horizontal=True,
               help="The training sample is generated data for learning the workflow, not a real case.")

if src == "Import a case":
    c1, c2 = st.columns([3, 1])
    wallets_txt = c1.text_input("Trader's TRON wallet(s)", placeholder="T…, T… (comma-separated)")
    rate = c2.number_input("USD/TZS rate", min_value=1.0, value=2700.0, step=10.0)
    up = st.file_uploader("Trader's mobile-money statement (CSV)", type=["csv"])
    if not st.button("Match", type="primary", icon=":material/link:", disabled=not (wallets_txt and up)):
        st.stop()
    wallets = [w.strip() for w in wallets_txt.split(",") if w.strip()]
    bad = [w for w in wallets if not tron.valid_address(w)]
    if bad:
        st.error(f"Not valid TRON addresses: {', '.join(bad)}")
        st.stop()
    try:
        statement = mm.read_statement(up)
    except Exception as e:
        st.error(f"Could not read the statement: {e}")
        st.stop()
    with st.spinner("Fetching the trader's USDT transfers…"):
        try:
            transfers = pd.concat([tron.fetch_transfers(w, max_transfers=3000, since=statement["ts"].min() - pd.Timedelta(days=1))
                                   for w in wallets]).drop_duplicates("tx_id")
        except tron.TronError as e:
            st.error(str(e))
            st.stop()
    fx = rate
    store.log(analyst(), "mobile-money match", module="mobile_money", subject=",".join(wallets),
              detail=f"{len(statement)} statement rows, {len(transfers)} transfers")
else:
    st.info("Training sample: generated data for one P2P trader. It shows how the matching works; it is not a real case.",
            icon=":material/school:")
    wallets, transfers, statement, fx = mm.sample_case()

if transfers.empty:
    st.warning("No USDT transfers found for these wallets in the statement period.")
    st.stop()
with st.spinner("Matching payments to transfers…"):
    links, pairs = mm.match(wallets, transfers, statement, fx)

m = st.columns(4)
m[0].metric("Statement rows", f"{len(statement):,}")
m[1].metric("USDT transfers", f"{len(transfers):,}")
m[2].metric("Matched trades", f"{len(links):,}")
m[3].metric("Wallet ↔ account pairs", len(pairs))
lead_notice()

if pairs.empty:
    st.warning("No payment matched a transfer within the time window and plausible exchange-rate spread.")
    st.stop()

st.subheader("Attributed pairs")
levels = st.multiselect("Confidence", ["High", "Medium", "Low"], default=["High", "Medium"])
pairs = pairs[pairs["confidence"].isin(levels or ["High", "Medium", "Low"])].reset_index(drop=True)
if pairs.empty:
    st.info("No pairs at this confidence level.")
    st.stop()
st.caption("High = repeated co-occurrence and strong evidence. Each pair is a lead for a lawful records request "
           "to the operator, not proof of ownership.")
st.dataframe(pairs, hide_index=True, width="stretch", column_config={
    "usdt": st.column_config.NumberColumn("USDT", format="%.2f"),
    "tzs": st.column_config.NumberColumn("TZS", format="%d"),
    "evidence": st.column_config.ProgressColumn("Evidence", min_value=0, max_value=float(max(pairs["evidence"].max(), 1)))})

pick = st.selectbox("Pair", [f"{r.wallet}  ↔  {r.mm_account}  ({r.confidence}, {r.trades} trades)" for r in pairs.itertuples()])
p = pairs.iloc[[f"{r.wallet}  ↔  {r.mm_account}  ({r.confidence}, {r.trades} trades)" for r in pairs.itertuples()].index(pick)]
st.markdown("**Matched trades for this pair**")
sel = links[(links["wallet"] == p["wallet"]) & (links["mm_account"] == p["mm_account"])]
st.dataframe(sel[["chain_ts", "side", "usdt", "mm_ts", "tzs", "lag_min", "implied_fee", "link_score", "chain_tx", "mm_tx"]],
             hide_index=True, width="stretch")
c1, c2, c3 = st.columns(3)
with c1:
    open_case_button("mobile_money", f"{p['wallet']}|{p['mm_account']}", f"Attribution {p['wallet'][:8]}… ↔ {p['mm_account']}",
                     None, p["confidence"], summary=f"{p['trades']} matched trades, {p['usdt']:,.0f} USDT",
                     evidence={"pair": p.to_dict(), "trades": sel.to_dict("records")})
with c2:
    if st.button("Investigate wallet", icon=":material/arrow_forward:") and src == "Import a case":
        st.session_state["tron_addr"] = p["wallet"]
        st.switch_page("views/tron.py")
with c3:
    st.download_button("Export all links (CSV)", links.to_csv(index=False), "attribution_links.csv", "text/csv")
