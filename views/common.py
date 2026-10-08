"""Helpers shared by the platform pages: look and feel, headers, badges, case buttons."""
import html

import streamlit as st

from src.live import store

BAND_COLOR = {"High": "red", "Medium": "orange", "Low": "green"}

# Same tokens as the Phase 1-3 dashboards (src/dashboard_template.html)
TOKENS = {
    "dark": "--bg:#060a12;--glow-a:rgba(34,211,238,.20);--glow-b:rgba(255,138,61,.12);--lattice:rgba(148,197,255,.07);"
            "--surface:rgba(16,24,38,.58);--surface-2:rgba(255,255,255,.045);--edge:rgba(255,255,255,.10);"
            "--sheen:rgba(255,255,255,.07);--ink:#e8f1fb;--ink-2:#a9b8cc;--ink-3:#75859d;--line:rgba(160,190,230,.14);"
            "--accent:#38d6f0;--accent-soft:rgba(56,214,240,.13);--accent-glow:rgba(56,214,240,.45);"
            "--shadow:0 12px 40px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.07);",
    "light": "--bg:#e8eef6;--glow-a:rgba(14,165,233,.20);--glow-b:rgba(249,115,22,.10);--lattice:rgba(30,60,110,.08);"
             "--surface:rgba(255,255,255,.58);--surface-2:rgba(255,255,255,.55);--edge:rgba(255,255,255,.75);"
             "--sheen:rgba(255,255,255,.55);--ink:#0c1524;--ink-2:#3e4c62;--ink-3:#627088;--line:rgba(20,40,80,.12);"
             "--accent:#0a86a8;--accent-soft:rgba(10,134,168,.12);--accent-glow:rgba(10,134,168,.30);"
             "--shadow:0 12px 32px rgba(20,40,80,.12),inset 0 1px 0 rgba(255,255,255,.85);",
}

CSS = """
<style>
:root{%(tokens)s
  --display:"Chakra Petch","Segoe UI",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
/* backdrop: two soft light sources and a dot lattice standing in for the transaction graph */
[data-testid="stApp"]{background:var(--bg)}
[data-testid="stApp"]::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(60vmax 45vmax at 12%% -8%%,var(--glow-a),transparent 60%%),
             radial-gradient(50vmax 40vmax at 100%% 105%%,var(--glow-b),transparent 60%%),
             radial-gradient(var(--lattice) 1px,transparent 1.4px) 0 0/26px 26px;
  animation:drift 28s ease-in-out infinite alternate}
@keyframes drift{to{background-position:6%% 4%%,94%% 96%%,13px 13px}}
@media (prefers-reduced-motion:reduce){[data-testid="stApp"]::before{animation:none}}
[data-testid="stHeader"]{background:transparent}
[data-testid="stMain"],[data-testid="stSidebar"]{position:relative;z-index:1}
[data-testid="stSidebar"]{background:color-mix(in srgb,var(--bg) 70%%,transparent);backdrop-filter:blur(18px);
  -webkit-backdrop-filter:blur(18px);border-right:1px solid var(--line)}

/* headings */
h1,h2,h3{letter-spacing:.01em}
h2,h3{font-family:var(--display)!important;font-weight:600!important}

/* glass surfaces: bordered containers, forms, expanders, metric tiles */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]),
[data-testid="stForm"],[data-testid="stExpander"] details,[data-testid="stPopoverBody"]{
  background:var(--surface)!important;border:1px solid var(--edge)!important;border-radius:18px!important;
  box-shadow:var(--shadow);backdrop-filter:blur(20px) saturate(150%%);-webkit-backdrop-filter:blur(20px) saturate(150%%)}
[data-testid="stForm"]{padding:18px 20px}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stForm"]{background:none!important;border:0!important;box-shadow:none;padding:0;backdrop-filter:none}
[data-testid="stMetric"]{background:var(--surface);border:1px solid var(--edge);border-radius:14px;padding:12px 14px;
  box-shadow:var(--shadow);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);transition:transform .25s,border-color .25s}
[data-testid="stMetric"]:hover{transform:translateY(-2px);border-color:var(--accent-soft)}
[data-testid="stMetricLabel"] p{font-family:var(--mono);font-size:11px!important;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)}
[data-testid="stMetricValue"] *{font-size:inherit!important}
[data-testid="stMetricValue"]{font-family:var(--mono);font-weight:500;font-size:28px!important;letter-spacing:-.02em;text-shadow:0 0 24px var(--accent-soft)}
[data-testid="stDataFrame"],[data-testid="stTable"]{border-radius:12px;overflow:hidden;box-shadow:var(--shadow)}

/* tabs as the dashboards' pill switcher */
[data-testid="stTabs"] [role="tablist"]{gap:3px;padding:3px;border:1px solid var(--edge);border-radius:999px;background:var(--surface);
  width:fit-content;max-width:100%%;box-shadow:var(--shadow);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}
[data-testid="stTabs"] [role="tablist"]::before,[data-testid="stTabs"] [role="tablist"]::after,
[data-testid="stTab"]::before,[data-testid="stTab"]::after{display:none!important}
[data-testid="stTabs"] [role="tablist"]{border-bottom:1px solid var(--edge)!important}
[data-testid="stTab"]{border-radius:999px!important;padding:5px 16px!important;height:auto!important;margin:0!important;
  border:0!important;box-shadow:none;transition:background .2s,color .2s}
[data-testid="stTab"] p{font-size:13px;font-weight:500}
[data-testid="stTabs"] [role="tablist"] > :not([data-testid="stTab"]){display:none!important}
[data-testid="stTab"]:hover{background:var(--surface-2)}
[data-testid="stTab"][aria-selected="true"]{background:var(--accent-soft);color:var(--accent);
  box-shadow:inset 0 0 0 1px var(--accent-soft),0 0 16px var(--accent-soft)!important}
[data-testid="stTabs"] [role="tablist"] + div,[data-testid="stTabs"] > div > div:has(> [role="tablist"]){border:0!important}

/* buttons glow on hover, like the dashboards' controls */
.stButton button,.stDownloadButton button,.stFormSubmitButton button,[data-testid="stPopover"] button{transition:box-shadow .2s,border-color .2s}
.stButton button:hover,.stDownloadButton button:hover,.stFormSubmitButton button:hover,[data-testid="stPopover"] button:hover{
  box-shadow:0 0 16px var(--accent-soft);border-color:var(--accent)}

/* page header (same markup as the dashboards) */
.ph{display:grid;gap:10px;margin:0 0 6px}
.ph .eyebrow{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);font-size:11px;font-weight:500;
  letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.ph .eyebrow::before{content:"";width:7px;height:7px;border-radius:50%%;background:var(--accent);
  box-shadow:0 0 0 3px var(--accent-soft),0 0 12px var(--accent-glow)}
.ph h1{font-family:var(--display);font-size:clamp(24px,3.4vw,34px);font-weight:600;line-height:1.15;margin:0;padding:0;
  background:linear-gradient(100deg,var(--ink) 40%%,var(--accent));-webkit-background-clip:text;background-clip:text;color:transparent}
.ph .sub{color:var(--ink-2);max-width:80ch;margin:0;font-size:14px}
.ph .runline{display:flex;flex-wrap:wrap;gap:8px;color:var(--ink-3);font-size:12px}
.ph .runline span{border:1px solid var(--line);background:var(--surface-2);border-radius:999px;padding:3px 11px;backdrop-filter:blur(8px)}
.ph .runline b{color:var(--ink);font-weight:500;font-family:var(--mono);font-size:11.5px}
.eyebrow-sm{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
</style>
"""


def apply_style():
    mode = st.context.theme.type if st.context.theme.type in TOKENS else "dark"
    st.html(CSS % {"tokens": TOKENS[mode]})


def page_header(eyebrow, title, sub=None, chips=None):
    """Header in the dashboards' style: mono eyebrow, gradient title, subtitle and fact chips."""
    e = html.escape
    chips_html = "".join(f"<span>{e(k)} <b>{e(str(v))}</b></span>" for k, v in (chips or {}).items())
    st.html(f'<div class="ph"><div class="eyebrow">Blockchain forensics · {e(eyebrow)}</div><h1>{e(title)}</h1>'
            + (f'<p class="sub">{e(sub)}</p>' if sub else "")
            + (f'<div class="runline">{chips_html}</div>' if chips_html else "") + "</div>")


def compact(x):
    """26588.2 -> 26.6K; keeps tiles readable at any width."""
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= div:
            return f"{x / div:.1f}{unit}"
    return f"{x:,.0f}"


def analyst():
    return st.session_state.get("user", "analyst")


def band_badge(band, score=None):
    label = f"{band} risk" + (f" · {score:.0f}/100" if score is not None and score > 1 else "")
    st.badge(label, color=BAND_COLOR.get(band, "gray"), icon=":material/flag:")


def lead_notice():
    st.caption(":material/gavel: Scores and indicators are investigative leads for analyst review, not findings. "
               "No action is taken against any person or account without analyst sign-off.")


def open_case_button(module, subject, title, score=None, band=None, summary="", evidence=None, key=None):
    if st.button("Open case", icon=":material/create_new_folder:", key=key or f"case-{module}-{subject}"):
        case_id, new = store.open_case(analyst(), module, subject, title, score, band, summary, evidence)
        if new:
            st.success(f"Case #{case_id} opened. Find it under **Cases**.")
        else:
            st.info(f"An open case already exists for this subject: case #{case_id}.")
