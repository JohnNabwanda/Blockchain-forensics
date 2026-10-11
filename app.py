"""Blockchain forensics investigation platform.   Run:  streamlit run app.py

Modules: live TRON, Ethereum and Bitcoin investigation, cross-chain tracing, smart-contract audit
(uploaded or deployed), mobile-money attribution and the Bitcoin graph model, all writing to one
shared entity graph; case workspace with review queue, feedback loop, roles, a hash-chained audit
log and evidence packs with chain of custody.
"""
import hmac

import streamlit as st

from src.live import store
from views.common import PERMISSIONS, apply_style, page_header

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


def login(accounts):
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.space("large")
        page_header("Investigation platform", "Sign in", "Authorised investigators only. All activity is recorded in the audit log.")
        with st.form("login"):
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                if user in accounts and hmac.compare_digest(pw, str(accounts[user])):
                    st.session_state["user"] = user
                    st.session_state["role"] = roles[user] if roles[user] in PERMISSIONS else "viewer"
                    store.log(user, "signed in", detail=f"role {st.session_state['role']}")
                    st.rerun()
                store.log(user or "(blank)", "failed sign-in")
                st.error("Wrong username or password.")


accounts, roles = users()
if accounts and not st.session_state.get("user"):
    login(accounts)
    st.stop()
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
nav.run()
