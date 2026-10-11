"""Sign-in screen: network artwork on the left, the form on the right (stacks on small screens)."""
import base64
import hmac
from pathlib import Path

import streamlit as st

from src.live import store
from views.common import PERMISSIONS, TOKENS

VERSION = "v1.0.0"
ART = Path(__file__).resolve().parent.parent / "assets" / "login_art.jpg"
LANDING = {"search": "Unified search", "case": "My last case", "chain": "Selected chain"}
CHAIN_PAGE = {"tron": ("tron_addr", "views/tron.py"), "eth": ("eth_addr", "views/ethereum.py"),
              "btc": ("btc_addr", "views/btc_live.py")}

CSS = """
<style>
[data-testid="stMainBlockContainer"]{padding:0!important;max-width:100%%!important}
[data-testid="stApp"]::before{display:none}
:root{%(tokens)s}
[data-testid="stApp"]{background:var(--bg)!important;color:var(--ink)}
[data-testid="stApp"] [data-testid="stAlert"] p{color:var(--ink)}
.lg-art{height:100vh;min-height:640px;background:url(data:image/jpeg;base64,%(art)s) center/cover no-repeat;
  box-shadow:inset -120px 0 120px -60px var(--bg)}
[data-testid="stHorizontalBlock"]:has(.lg-art){gap:0!important}
@media (max-width:900px){[data-testid="stHorizontalBlock"]:has(.lg-art) > [data-testid="stColumn"]:first-child{display:none}
  [data-testid="stHorizontalBlock"]:has(.lg-art) > [data-testid="stColumn"]:last-child{padding:0 16px}
  .lg-status{padding:28px 0 0}}
.lg-status{display:flex;justify-content:flex-end;align-items:center;gap:18px;padding:48px 44px 0;font-size:14px;color:var(--ink-3)}
.lg-status .on{display:inline-flex;align-items:center;gap:10px;color:#34d399}
.lg-status .on::before{content:"";width:10px;height:10px;border-radius:50%%;background:#34d399;box-shadow:0 0 10px #34d399}
.lg-status .sep{width:1px;height:18px;background:var(--line)}
.lg-head{margin:clamp(24px,9vh,130px) 0 26px}
.lg-head h1{font-family:var(--display);font-weight:700;font-size:clamp(28px,2.6vw,44px);line-height:1.1;margin:0;padding:0;color:var(--ink);white-space:nowrap}
.lg-head h1 span{color:var(--accent);text-shadow:0 0 28px var(--accent-glow)}
.lg-head p{margin:12px 0 0;color:var(--ink-2);font-size:17px}
[data-testid="stForm"]:has(.lg-mark){background:none!important;border:0!important;box-shadow:none!important;
  padding:0!important;backdrop-filter:none!important}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputRootElement"]{height:56px;border-radius:12px!important;
  background:var(--surface)!important;border-color:var(--edge)!important;color:var(--ink)}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputRootElement"]:focus-within{border-color:var(--accent)!important;
  box-shadow:0 0 18px var(--accent-soft)}
[data-testid="stForm"]:has(.lg-mark) input{color:var(--ink)!important;-webkit-text-fill-color:var(--ink);font-size:15px}
[data-testid="stForm"]:has(.lg-mark) input::placeholder{color:var(--ink-3);-webkit-text-fill-color:var(--ink-3)}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputIcon"]{color:var(--ink-2)!important;position:relative;z-index:1;font-size:20px}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputRootElement"] button{color:var(--ink-2)!important}
[data-testid="stForm"]:has(.lg-mark) .st-key-lg-mono input{font-family:var(--mono);font-size:13px}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stWidgetLabel"] p{color:var(--ink)}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stWidgetLabel"] p::first-line{color:inherit}
[data-testid="stButtonGroup"] button{background:var(--surface-2)!important;color:var(--ink-2)!important;border-color:var(--edge)!important}
[data-testid="stButtonGroup"] button[aria-checked="true"]{background:var(--accent-soft)!important;color:var(--accent)!important;
  border-color:var(--accent)!important}
[data-testid="stForm"]:has(.lg-mark) .stFormSubmitButton button{min-height:56px;border-radius:14px!important;border:0;
  background:linear-gradient(90deg,#22d3ee,#38e1f5);color:#04121a!important;font-size:17px;font-weight:600;
  box-shadow:0 0 28px rgba(56,214,240,.35)}
[data-testid="stForm"]:has(.lg-mark) .stFormSubmitButton button:hover{box-shadow:0 0 38px rgba(56,214,240,.55)}
[data-testid="stForm"]:has(.lg-mark) .stFormSubmitButton button p{color:#04121a!important;font-size:17px;font-weight:600}
.lg-rule{display:flex;align-items:center;gap:22px;color:var(--ink-2);font-size:14px;margin:6px 0 4px}
.lg-rule::before,.lg-rule::after{content:"";flex:1;height:1px;background:var(--line)}
.lg-foot{text-align:center;color:var(--ink-3);font-size:12px;margin:0 0 40px}
</style>
"""


@st.cache_data(show_spinner=False)
def _art():
    return base64.b64encode(ART.read_bytes()).decode() if ART.exists() else ""


def _land(user, choice, address):
    """Where to go once signed in: stored in the session and acted on after the navigation exists."""
    chain = store.chain_of(address) if address else None
    if choice == "case":
        cid = store.last_case(user)
        if cid:
            st.session_state["case_id"] = int(cid)
        return "views/cases.py"
    if choice == "chain" and chain:
        key, page = CHAIN_PAGE[chain]
        st.session_state[key] = address
        return page
    if address:
        st.session_state["jump_addr"] = address
    return "views/overview.py"


def render(accounts, roles):
    st.html(CSS % {"art": _art(), "tokens": TOKENS["dark"]})      # always dark: the artwork is
    art, form = st.columns([1.15, 1], gap=None)
    with art:
        st.html('<div class="lg-art" role="img" aria-label="Wallets on Bitcoin, Ethereum, TRON and USDT linked in a '
                'transaction graph"></div>')
    with form:
        st.html(f'<div class="lg-status"><span class="on">System Online</span><span class="sep"></span>'
                f'<span>{VERSION}</span></div>')
        _, mid, _ = st.columns([0.14, 0.72, 0.14])
        with mid:
            st.html('<div class="lg-head"><h1>Blockchain <span>Forensics</span></h1>'
                    '<p>Sign in to access the investigation platform</p></div>')
            for msg in st.session_state.pop("signin_notice", []):
                st.info(msg, icon=":material/schedule:")
            with st.form("login", border=False):
                st.html('<span class="lg-mark"></span>')
                user = st.text_input("Username", placeholder="Enter your username", icon=":material/person:",
                                     autocomplete="username", label_visibility="collapsed").strip()
                pw = st.text_input("Password", type="password", placeholder="Enter your password",
                                   icon=":material/lock:", autocomplete="current-password", label_visibility="collapsed")
                with st.container(key="lg-mono", border=False):
                    address = st.text_input("Jump to an address (optional)", placeholder="Paste a TRON, Ethereum or Bitcoin address",
                                            icon=":material/search:").strip()
                choice = st.pills("After sign-in, open", list(LANDING), default="search", required=True,
                                  format_func=LANDING.get)
                ok = st.form_submit_button("Sign in  →", type="primary", width="stretch")
            if ok:
                if user in accounts and hmac.compare_digest(pw, str(accounts[user])):
                    if address and not store.chain_of(address):
                        st.error("That address is not a TRON, Ethereum or Bitcoin address. Leave it empty or fix it.")
                        st.stop()
                    st.session_state["user"] = user
                    st.session_state["role"] = roles[user] if roles[user] in PERMISSIONS else "viewer"
                    st.session_state["landing"] = _land(user, choice, address)
                    store.log(user, "signed in", detail=f"role {st.session_state['role']}, open {LANDING[choice].lower()}")
                    st.rerun()
                store.log(user or "(blank)", "failed sign-in")
                st.error("Wrong username or password.")
            st.html('<div class="lg-rule">Authorized access only</div>'
                    '<p class="lg-foot">Failed attempts are logged. Sessions expire after 30 minutes of inactivity.</p>')
