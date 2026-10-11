"""Blockchain forensics investigation platform.   Run:  streamlit run app.py

Modules: live TRON, Ethereum and Bitcoin investigation, cross-chain tracing, smart-contract audit
(uploaded or deployed), mobile-money attribution and the Bitcoin graph model, all writing to one
shared entity graph; case workspace with review queue, feedback loop, roles, a hash-chained audit
log and evidence packs with chain of custody.
"""
import time

import streamlit as st

from src.live import store
from views import signin
from views.common import apply_style

st.set_page_config(page_title="Blockchain Forensics Platform", page_icon=":material/policy:", layout="wide")
apply_style()


def users():
    """Analyst accounts from .streamlit/secrets.toml: [auth.users] name = "password" and
    [auth.roles] name = "viewer" | "investigator" | "supervisor" (default investigator).
    Empty means no login is required (local use, full rights)."""
    try:
        auth = st.secrets["auth"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}, {}
    accounts = dict(auth.get("users", {}))
    if "username" in auth:
        accounts[auth["username"]] = auth["password"]
    roles = {u: str(auth.get("roles", {}).get(u, "investigator")) for u in accounts}
    return accounts, roles


accounts, roles = users()
IDLE_LIMIT = 30 * 60          # seconds without any interaction before the session is closed
if accounts and st.session_state.get("user") and time.time() - st.session_state.get("seen", time.time()) > IDLE_LIMIT:
    store.log(st.session_state["user"], "session expired", detail="30 minutes inactive")
    st.session_state.clear()
    st.session_state["signin_notice"] = ["Your session expired after 30 minutes of inactivity. Sign in again."]
if accounts and not st.session_state.get("user"):
    signin.render(accounts, roles)
    st.stop()
st.session_state["seen"] = time.time()
st.session_state.setdefault("user", "analyst")
st.session_state.setdefault("role", "supervisor" if not accounts else "viewer")

with st.sidebar:
    st.markdown(f"**:material/badge: {st.session_state['user']}** · {st.session_state['role']}")
    if accounts and st.button("Sign out", icon=":material/logout:"):
        store.log(st.session_state["user"], "signed out")
        st.session_state.clear()
        st.rerun()

nav = st.navigation({
    "": [st.Page("views/overview.py", title="Overview", icon=":material/space_dashboard:", default=True)],
    "Investigate": [
        st.Page("views/tron.py", title="TRON / USDT wallets", icon=":material/account_balance_wallet:"),
        st.Page("views/ethereum.py", title="Ethereum wallets", icon=":material/token:"),
        st.Page("views/btc_live.py", title="Bitcoin addresses", icon=":material/currency_bitcoin:"),
        st.Page("views/crosschain.py", title="Cross-chain tracing", icon=":material/swap_horiz:"),
        st.Page("views/contracts.py", title="Smart-contract audit", icon=":material/data_object:"),
        st.Page("views/mobile_money.py", title="Mobile-money attribution", icon=":material/phone_android:"),
        st.Page("views/bitcoin.py", title="Bitcoin graph model", icon=":material/hub:"),
    ],
    "Casework": [
        st.Page("views/cases.py", title="Cases", icon=":material/folder_open:"),
        st.Page("views/graph.py", title="Entity graph", icon=":material/share:"),
        st.Page("views/watchlist.py", title="Watchlist", icon=":material/visibility:"),
        st.Page("views/audit.py", title="Audit and custody", icon=":material/history:"),
    ],
    "Evidence": [
        st.Page("views/feedback.py", title="Feedback loop", icon=":material/model_training:"),
        st.Page("views/research.py", title="Research results", icon=":material/science:"),
    ],
})
landing = st.session_state.pop("landing", None)
if landing:
    st.switch_page(landing)
nav.run()
