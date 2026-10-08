"""Research results: the evaluation dashboards behind each module's methods."""
import streamlit as st

from src import config
from views.common import page_header

page_header("Evidence", "Research results", "How well each method works, measured on labelled benchmark data before it was put into the platform.")

PAGES = [("Phase 1 · Bitcoin detection", config.DASHBOARD_FILES["phase1"], "python run_pipeline.py && python build_dashboard.py"),
         ("Phase 2 · Cash-out tracing", config.DASHBOARD_FILES["phase2"], "python run_phase2.py --stress && python build_phase2_dashboard.py"),
         ("Phase 3 · Smart contracts", config.DASHBOARD_FILES["phase3"], "python run_phase3.py && python build_phase3_dashboard.py")]
# the platform navigation replaces each dashboard's own phase switcher
HIDE_SWITCHER = "<style>.switcher{display:none!important}</style>"


@st.cache_data
def page_html(path, mtime):
    return path.read_text() + HIDE_SWITCHER


for tab, (title, path, build) in zip(st.tabs([t for t, _, _ in PAGES]), PAGES):
    with tab:
        if not path.exists():
            st.info(f"Not built on this server yet. Run `{build}`.")
            continue
        st.iframe(page_html(path, path.stat().st_mtime))
