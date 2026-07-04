"""video_viewer.py — watch the clips behind a bowler report.

Loads a `<report>.playlists.json` sidecar (written alongside each PDF at render time) and
plays the clips per insight (stock ball / wickets / new-ball out-swingers) with captions.
Run:  .\\venv\\Scripts\\streamlit run video_viewer.py --server.port 8061

The heavy lifting (clip resolution, the viewer widget) lives in the shared package
`ludis_cricket.video`, so the same viewer works in any Ludis app.
"""
import glob
import json
import os

import streamlit as st

from ludis_cricket.theme import apply_theme
from ludis_cricket.video import playlist_widget

st.set_page_config(page_title="Bowler video", layout="wide")
apply_theme()

st.title("🎬 Bowler report — video")

REPORTS = os.path.join(os.path.dirname(__file__), "reports")
sidecars = sorted(glob.glob(os.path.join(REPORTS, "*.playlists.json")))

if not sidecars:
    st.info("No playlist sidecars found in `reports/`. Generate a report first "
            "(`build_reports.py`) — each PDF writes a `<name>.playlists.json` beside it.")
    st.stop()


def _label(path):
    return os.path.basename(path).replace(".playlists.json", "")


choice = st.sidebar.selectbox("Report", sidecars, format_func=_label)
with open(choice, encoding="utf-8") as f:
    data = json.load(f)

meta = data.get("meta", {})
st.subheader(meta.get("bowler") or _label(choice))
counts = meta.get("counts", {})
if counts:
    st.caption(" · ".join(f"{k}: {v.get('shown')} of {v.get('in_group')}" for k, v in counts.items())
               + "  — 'in_group' = deliveries matching the insight; clips exist for recent matches only.")

playlist_widget(data.get("playlists", {}), key_prefix="viewer")
