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


# Roles: viewer reads; investigator investigates, opens cases and reviews leads; supervisor also
# closes cases, removes watchlist entries, verifies evidence and resets thresholds.
PERMISSIONS = {
    "viewer": set(),
    "investigator": {"case", "lead", "watch", "export"},
    "supervisor": {"case", "lead", "watch", "export", "close", "unwatch", "verify", "recalibrate"},
}


def role():
    return st.session_state.get("role", "investigator")


def can(action):
    return action in PERMISSIONS.get(role(), set())


def need(action, what="do this"):
    """Show a notice and return False when the signed-in role may not perform `action`."""
    if can(action):
        return True
    st.caption(f":material/lock: Your role ({role()}) cannot {what}.")
    return False


def band_badge(band, score=None):
    label = f"{band} risk" + (f" · {score:.0f}/100" if score is not None and score > 1 else "")
    st.badge(label, color=BAND_COLOR.get(band, "gray"), icon=":material/flag:")


def lead_notice():
    st.caption(":material/gavel: Scores and indicators are investigative leads for analyst review, not findings. "
               "No action is taken against any person or account without analyst sign-off.")


def open_case_button(module, subject, title, score=None, band=None, summary="", evidence=None, key=None, entity_id=None):
    if not need("case", "open cases"):
        return
    if st.button("Open case", icon=":material/create_new_folder:", key=key or f"case-{module}-{subject}"):
        case_id, new = store.open_case(analyst(), module, subject, title, score, band, summary, evidence,
                                       entity_id=entity_id)
        if new:
            st.success(f"Case #{case_id} opened. Find it under **Cases**.")
        else:
            if entity_id:
                store.attach(analyst(), case_id, [entity_id], role="subject")
            st.info(f"An open case already exists for this subject: case #{case_id}.")


def attach_to_case(entity_ids, key, label="Attach to case as leads"):
    """Pick an open case and attach graph entities to it as leads for review."""
    if not entity_ids or not need("case", "attach leads to cases"):
        return
    open_cases = store.cases(status=["Open", "Escalated"])
    if open_cases.empty:
        st.caption("Open a case first to attach these as leads.")
        return
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    cid = c1.selectbox("Case", open_cases["id"], key=f"att-case-{key}",
                       format_func=lambda i: f"#{i} · {open_cases.set_index('id').loc[i, 'title']}")
    if c2.button(label, key=f"att-btn-{key}", icon=":material/attach_file:"):
        n = store.attach(analyst(), int(cid), list(entity_ids))
        st.success(f"{n} new lead(s) attached to case #{cid}." if n else "Already attached.")


# ---------------------------------------------------------------- graph drawing (Graphviz)
# Colours from the dashboards' palette (accent = signal, orange = illicit flow, amber = service)
GRAPH_THEME = {
    "dark": {"fill": "#101826", "line": "#2b3a50", "ink": "#e8f1fb", "muted": "#75859d", "accent": "#38d6f0",
             "root_ink": "#060a12", "bad": "#ff8a3d", "bad_fill": "#2a1a12", "warn": "#fbbf24", "warn_fill": "#2a2410",
             "ok": "#4ade80", "violet": "#a78bfa"},
    "light": {"fill": "#ffffff", "line": "#b8c6d8", "ink": "#0c1524", "muted": "#627088", "accent": "#0a86a8",
              "root_ink": "#ffffff", "bad": "#e25a1f", "bad_fill": "#fde8dc", "warn": "#d99a0b", "warn_fill": "#fdf3d6",
              "ok": "#16a34a", "violet": "#7c3aed"},
}
CHAIN_TAG = {"tron": "TRON", "eth": "ETH", "btc": "BTC", "btc-tx": "BTC tx", "mm": "M-money", "contract": "contract"}


def short(a):
    a = str(a)
    return a if len(a) <= 14 else f"{a[:6]}…{a[-4:]}"


def _q(x):
    return str(x).replace("\\", "\\\\").replace('"', '\\"')


def dot(nodes, edges, rankdir="LR"):
    """nodes: {id: {label, sub, root, flag, service, status}}; edges: [(a, b, {label, width, style, color})]."""
    c = GRAPH_THEME.get(st.context.theme.type, GRAPH_THEME["dark"])
    lines = [f'digraph G {{ rankdir={rankdir}; bgcolor="transparent"; pad=0.2; nodesep=0.35; ranksep=0.9; '
             f'node [shape=box, style="rounded,filled", fontname="JetBrains Mono", fontsize=10, margin="0.18,0.08", '
             f'fillcolor="{c["fill"]}", color="{c["line"]}", fontcolor="{c["ink"]}", penwidth=1.2]; '
             f'edge [fontname="JetBrains Mono", fontsize=9, color="{c["muted"]}", fontcolor="{c["muted"]}", arrowsize=0.7];']
    for n, d in nodes.items():
        label = _q(d.get("label") or short(n))
        if d.get("sub"):
            label += "\\n" + _q(d["sub"])[:40]
        attrs = {"label": label}
        if d.get("root"):
            attrs.update(fillcolor=c["accent"], fontcolor=c["root_ink"], color=c["accent"], penwidth="2")
        elif d.get("status") == "Confirmed":
            attrs.update(fillcolor=c["bad_fill"], color=c["bad"], fontcolor=c["bad"], penwidth="2.4")
        elif d.get("status") == "Dismissed":
            attrs.update(color=c["ok"], fontcolor=c["muted"], style="rounded,filled,dashed")
        elif d.get("flag"):
            attrs.update(fillcolor=c["bad_fill"], color=c["bad"], fontcolor=c["bad"], penwidth="1.8")
        elif d.get("service"):
            attrs.update(fillcolor=c["warn_fill"], color=c["warn"])
        lines.append(f'"{_q(n)}" [' + ", ".join(f'{k}="{v}"' for k, v in attrs.items()) + "];")
    for a, b, d in edges:
        color = {"accent": c["accent"], "violet": c["violet"], "bad": c["bad"]}.get(d.get("color"), c["muted"])
        lines.append(f'"{_q(a)}" -> "{_q(b)}" [label="{_q(d.get("label", ""))}", penwidth={d.get("width", 1.2):.1f}, '
                     f'color="{color}", fontcolor="{color}", style="{d.get("style", "solid")}"];')
    return "\n".join(lines) + "}"


def trace_dot(graph, root, unit="USDT"):
    """Trace graph from flows.trace() as Graphviz."""
    nodes = {}
    for n, d in graph["nodes"].items():
        sub = (f"⚑ {d['watchlist'][:24]}" if d.get("watchlist") else
               "service · not traced" if d.get("service") else d.get("label") or "")
        nodes[n] = {"root": n == root, "flag": bool(d.get("watchlist")), "service": d.get("service"), "sub": sub}
    edges = [(a, b, {"label": f"{compact(d['usdt'])} {unit} · {d['n']}", "width": 1 + min(d["usdt"] / 50000, 3)})
             for a, b, d in graph["edges"]]
    return dot(nodes, edges)
