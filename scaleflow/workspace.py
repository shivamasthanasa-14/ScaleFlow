"""Keep public demonstration follow-ups separate for each browser session."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import streamlit as st
from .store import DEFAULT_DB

def workspace_db():
    if os.getenv('SCALEFLOW_WORKSPACE_MODE', 'session') == 'local':
        return DEFAULT_DB
    if '_scaleflow_workspace' not in st.session_state:
        st.session_state['_scaleflow_workspace'] = TemporaryDirectory(prefix='scaleflow-demo-')
    return Path(st.session_state['_scaleflow_workspace'].name) / 'followups.sqlite3'
