"""Am I cooked? Streamlit entrypoint."""
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")
import streamlit as st
from database_loader import load_database
from theme import apply_theme

st.set_page_config(page_title="Am I cooked?", layout="wide", initial_sidebar_state="collapsed")
apply_theme()
load_database().init_db()
st.navigation([
    st.Page("overview.py", title="Overview", default=True),
    st.Page("settings.py", title="Settings"),
], position="top").run()
