"""Helpers shared by the platform pages."""
import streamlit as st

from src.live import store

BAND_COLOR = {"High": "red", "Medium": "orange", "Low": "green"}


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
