"""Blockchain forensics investigation platform.   Run:  streamlit run app.py

Modules: Bitcoin transaction risk, live TRON/USDT wallet investigation, smart-contract audit,
mobile-money attribution, and a shared case register with an audit trail.
"""
import hmac

import streamlit as st

from src.live import store
from views.common import apply_style, page_header

st.set_page_config(page_title="Blockchain Forensics Platform", page_icon=":material/policy:", layout="wide")
apply_style()


def users():
    """Analyst accounts from .streamlit/secrets.toml: [auth.users] name = "password"
    (or the older [auth] username/password). Empty means no login is required."""
    try:
        auth = st.secrets["auth"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}
    accounts = dict(auth.get("users", {}))
    if "username" in auth:
        accounts[auth["username"]] = auth["password"]
    return accounts


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
                    store.log(user, "signed in")
                    st.rerun()
                store.log(user or "(blank)", "failed sign-in")
                st.error("Wrong username or password.")


accounts = users()
if accounts and not st.session_state.get("user"):
    login(accounts)
    st.stop()
st.session_state.setdefault("user", "analyst")

with st.sidebar:
    st.markdown(f"**:material/badge: {st.session_state['user']}**")
    if accounts and st.button("Sign out", icon=":material/logout:"):
        store.log(st.session_state["user"], "signed out")
        st.session_state.clear()
        st.rerun()

nav = st.navigation({
    "": [st.Page("views/overview.py", title="Overview", icon=":material/space_dashboard:", default=True)],
    "Investigate": [
        st.Page("views/bitcoin.py", title="Bitcoin transactions", icon=":material/currency_bitcoin:"),
        st.Page("views/tron.py", title="TRON / USDT wallets", icon=":material/account_balance_wallet:"),
        st.Page("views/contracts.py", title="Smart-contract audit", icon=":material/data_object:"),
        st.Page("views/mobile_money.py", title="Mobile-money attribution", icon=":material/phone_android:"),
    ],
    "Casework": [
        st.Page("views/cases.py", title="Cases", icon=":material/folder_open:"),
        st.Page("views/watchlist.py", title="Watchlist", icon=":material/visibility:"),
        st.Page("views/audit.py", title="Audit log", icon=":material/history:"),
    ],
    "Evidence": [st.Page("views/research.py", title="Research results", icon=":material/science:")],
})
nav.run()
