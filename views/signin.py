"""Sign-in screen: network artwork on the left, the form on the right (stacks on small screens)."""
import base64
import hmac
from pathlib import Path

import streamlit as st

from src.live import store
from views.common import PERMISSIONS, TOKENS

VERSION = "v1.0.0"
ART = Path(__file__).resolve().parent.parent / "assets" / "login_art.jpg"
LANDING = {"search": "Unified search", "case": "My last case"}

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
.lg-status{display:flex;justify-content:flex-end;align-items:center;gap:18px;padding:30px 44px 0;font-size:14px;color:var(--ink-3)}
.lg-status .on{display:inline-flex;align-items:center;gap:10px;color:#34d399}
.lg-status .on::before{content:"";width:10px;height:10px;border-radius:50%%;background:#34d399;box-shadow:0 0 10px #34d399}
.lg-status .sep{width:1px;height:18px;background:var(--line)}
.lg-head{margin:clamp(12px,5vh,90px) 0 18px}
.lg-head h1{font-family:var(--display);font-weight:700;font-size:clamp(28px,2.6vw,44px);line-height:1.1;margin:0;padding:0;color:var(--ink);white-space:nowrap}
.lg-head h1 span{color:var(--accent);text-shadow:0 0 28px var(--accent-glow)}
.lg-head p{margin:12px 0 0;color:var(--ink-2);font-size:17px}
[data-testid="stForm"]:has(.lg-mark){background:#0b1220!important;border:1px solid #1e2a3c!important;border-radius:18px!important;
  padding:26px 30px 18px!important;box-shadow:0 24px 60px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.05)!important;
  backdrop-filter:none!important}
.lg-card h2{font-family:var(--display);font-size:28px;font-weight:600;margin:0;padding:0;color:var(--ink)}
.lg-card p{margin:6px 0 4px;color:var(--ink-3);font-size:13px}
.lg-div{height:1px;background:#1e2a3c;margin:4px 0}
.lg-note{text-align:center;color:var(--ink-3);font-size:12px;margin:2px 0 0}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputRootElement"]{height:48px;border-radius:10px!important;
  background:#0f1828!important;border-color:#1e2a3c!important;color:var(--ink)}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputRootElement"]:focus-within{border-color:var(--accent)!important;
  box-shadow:0 0 18px var(--accent-soft)}
[data-testid="stForm"]:has(.lg-mark) input{color:var(--ink)!important;-webkit-text-fill-color:var(--ink);font-size:15px}
[data-testid="stForm"]:has(.lg-mark) input::placeholder{color:var(--ink-3);-webkit-text-fill-color:var(--ink-3)}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputIcon"]{color:var(--ink-2)!important;position:relative;z-index:1;font-size:20px}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stTextInputRootElement"] button{color:var(--ink-2)!important}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stWidgetLabel"] p{color:var(--ink)}
[data-testid="stForm"]:has(.lg-mark) [data-testid="stWidgetLabel"] p::first-line{color:inherit}
[data-testid="stButtonGroup"] button{background:var(--surface-2)!important;color:var(--ink-2)!important;border-color:var(--edge)!important}
[data-testid="stButtonGroup"] button[aria-checked="true"]{background:var(--accent-soft)!important;color:var(--accent)!important;
  border-color:var(--accent)!important}
[data-testid="stForm"]:has(.lg-mark) .stFormSubmitButton button{min-height:50px;border-radius:999px!important;border:0;
  background:linear-gradient(90deg,#22d3ee,#38e1f5);color:#04121a!important;font-size:17px;font-weight:600;
  box-shadow:0 0 28px rgba(56,214,240,.35)}
[data-testid="stForm"]:has(.lg-mark) .stFormSubmitButton button:hover{box-shadow:0 0 38px rgba(56,214,240,.55)}
[data-testid="stForm"]:has(.lg-mark) .stFormSubmitButton button p{color:#04121a!important;font-size:17px;font-weight:600}
.lg-rule{display:flex;align-items:center;gap:22px;color:var(--ink-3);font-size:13px;margin:14px 0 40px}
.lg-rule::before,.lg-rule::after{content:"";flex:1;height:1px;background:var(--line)}
</style>
"""


@st.cache_data(show_spinner=False)
def _art():
    return base64.b64encode(ART.read_bytes()).decode() if ART.exists() else ""


def _land(user, choice):
    """Where to go once signed in: stored in the session and acted on after the navigation exists."""
    if choice == "case":
        cid = store.last_case(user)
        if cid:
            st.session_state["case_id"] = int(cid)
        return "views/cases.py"
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
                st.html('<div class="lg-card lg-mark"><h2>Sign in</h2>'
                        '<p>Authorised investigators only. All activity is audited.</p></div>')
                user = st.text_input("Username", autocomplete="username").strip()
                pw = st.text_input("Password", type="password", autocomplete="current-password")
                st.html('<div class="lg-div"></div>')
                choice = st.pills("After sign-in, open", list(LANDING), default="search", required=True,
                                  format_func=LANDING.get)
                ok = st.form_submit_button("Sign in", type="primary", width="stretch")
                st.html('<p class="lg-note">Failed attempts are logged. Sessions expire after 30 minutes of inactivity.</p>')
            if ok:
                if user in accounts and hmac.compare_digest(pw, str(accounts[user])):
                    st.session_state["user"] = user
                    st.session_state["role"] = roles[user] if roles[user] in PERMISSIONS else "viewer"
                    st.session_state["landing"] = _land(user, choice)
                    store.log(user, "signed in", detail=f"role {st.session_state['role']}, open {LANDING[choice].lower()}")
                    st.rerun()
                store.log(user or "(blank)", "failed sign-in")
                st.error("Wrong username or password.")
            st.html('<div class="lg-rule">Authorized access only</div>')
