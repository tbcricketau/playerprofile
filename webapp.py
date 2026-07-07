"""
webapp.py — a small Flask web app that serves the bowler scouting reports with
**mint-on-demand video**, so clips keep working for months instead of the 72-hour baked-SAS
limit of a standalone HTML file.

Why this exists: our video access is SSO/RBAC (user-delegation SAS), which Azure caps at
7 days — a SAS baked into a shared file can't last 6 months. Instead the player asks this app
for a fresh URL each time a clip opens (`/clip?stem=…`), and the app mints a short-lived SAS on
the spot. As long as the app is running and can authenticate, video works indefinitely.

Run locally (works now, on your own SSO):
    .\venv\Scripts\python.exe webapp.py            # http://127.0.0.1:8062
Deploy later (public + shareable, 6-month video): host on Azure App Service with a **managed
identity** granted Storage Blob Data Reader on the fairplay/hawkeye accounts — then `_credential`
below swaps from your device-code login to the managed identity and nothing else changes.
(That RBAC grant is the one IT dependency — the same kind as the Virtualeye request.)
"""
import glob
import json
import os
import sys
import urllib.parse

sys.path.insert(0, r"c:\Ludis\ludis-cricket\src")

from flask import Flask, abort, redirect, request, send_from_directory, Response

from ludis_cricket.video import resolve_clip, build_player_html
from ludis_cricket.video import get_fairplay_sas, get_hawkeye_sas

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
app = Flask(__name__)


# ── Mint-on-demand clip URL ───────────────────────────────────────────────────────
@app.route("/clip")
def clip():
    """Given a clip STEM (extension-less blob URL, no SAS), mint a fresh SAS + resolve the
    extension and 302-redirect the <video> to the playable URL. Called by the player each time a
    clip opens, so the SAS is always current (cached ~6 h, re-minted on expiry)."""
    stem = request.args.get("stem")
    if not stem:
        abort(400, "missing stem")
    try:
        url = resolve_clip(stem)      # mints SAS via the shared credential + HEAD-probes the ext
    except Exception as e:
        abort(502, f"mint failed: {type(e).__name__}")
    if not url:
        abort(404, "clip not in storage")
    return redirect(url, code=302)


@app.route("/hawkeye")
def hawkeye():
    """Mint a fresh SAS for a Hawkeye angle blob (full blob URL, no SAS in `blob`)."""
    blob = request.args.get("blob")
    if not blob:
        abort(400, "missing blob")
    try:
        sas = get_hawkeye_sas()
    except Exception as e:
        abort(502, f"mint failed: {type(e).__name__}")
    return redirect(blob + sas, code=302)


# ── Report index + serving ────────────────────────────────────────────────────────
_FMT_LABEL = {"test": "Test", "odi": "ODI", "t20": "T20", "batting": "Batting"}


def _reports():
    """Discover rendered reports (recursively, so the odi/ & t20/ packs are found) by their playlist
    sidecars → [{name (relpath, no ext), title, fmt, has_pdf/html, n_clips}]."""
    out = []
    for sidecar in sorted(glob.glob(os.path.join(REPORTS_DIR, "**", "*.playlists.json"), recursive=True)):
        name = os.path.relpath(sidecar, REPORTS_DIR)[: -len(".playlists.json")].replace(os.sep, "/")
        try:
            d = json.load(open(sidecar, encoding="utf-8"))
        except Exception:
            continue
        pls = d.get("playlists", d)
        n = sum(len(v) for v in pls.values() if isinstance(v, list))
        meta = d.get("meta", {})
        sub = name.split("/")[0] if "/" in name else ("batting" if "_batting_" in name else "test")
        out.append({"name": name, "title": meta.get("bowler") or name.split("/")[-1].replace("_", " ").title(),
                    "fmt": _FMT_LABEL.get(sub, sub.title()),
                    "has_pdf": os.path.exists(os.path.join(REPORTS_DIR, name + ".pdf")),
                    "has_html": os.path.exists(os.path.join(REPORTS_DIR, name + ".html")),
                    "n_clips": n})
    return out


def _webapp_playlists(name):
    """Load a report's playlists and rewrite every clip URL to route through /clip (and Hawkeye
    angles through /hawkeye), so the served player mints SAS on demand instead of using the baked
    72-hour URLs. Returns (playlists_dict, meta)."""
    sidecar = os.path.join(REPORTS_DIR, name + ".playlists.json")
    if not os.path.exists(sidecar):
        abort(404)
    d = json.load(open(sidecar, encoding="utf-8"))
    pls = d.get("playlists", d)
    for items in pls.values():
        if not isinstance(items, list):
            continue
        for it in items:
            stem = it.get("clip_stem")
            if stem:
                it["url"] = "/clip?stem=" + urllib.parse.quote(stem, safe="")
            for a in (it.get("angles") or []):
                u = a.get("url") or ""
                base = u.split("?", 1)[0]
                if base:
                    a["url"] = "/hawkeye?blob=" + urllib.parse.quote(base, safe="")
    return pls, d.get("meta", {})


@app.route("/")
def index():
    groups = {}
    for r in _reports():
        groups.setdefault(r["fmt"], []).append(r)

    def _li(r):
        return (f'<li><a href="/r/{r["name"]}">{r["title"]}</a> '
                f'<span class="n">{r["n_clips"]} clips</span> '
                f'<a class="pdf" href="/player/{r["name"]}">▶ clips</a> '
                + (f'<a class="pdf" href="/pdf/{r["name"]}">PDF</a>' if r["has_pdf"] else "") + "</li>")
    blocks = []
    for fmt in ["Test", "ODI", "T20", "Batting"] + [g for g in sorted(groups) if g not in ("Test", "ODI", "T20", "Batting")]:
        if fmt not in groups:
            continue
        rows = "".join(_li(r) for r in groups[fmt])
        blocks.append(f'<h2>{fmt} <span class="c">{len(groups[fmt])}</span></h2><ul>{rows}</ul>')
    return Response(_INDEX_HTML.replace("{{rows}}", "".join(blocks) or "<p>No reports yet.</p>"),
                    mimetype="text/html")


@app.route("/r/<path:name>")
def report(name):
    """Serve the interactive report with video routed through the mint endpoints (durable video).
    Rebuilds the inline player from the sidecar so links keep the same ▶ behaviour."""
    html_path = os.path.join(REPORTS_DIR, name + ".html")
    if not os.path.exists(html_path):
        abort(404)
    html = open(html_path, encoding="utf-8").read()
    pls, _ = _webapp_playlists(name)
    # Rebuild the in-page player with mint-endpoint URLs and swap it into the report HTML.
    from ludis_cricket.video import inline_player_snippet
    snippet = inline_player_snippet(pls)
    # remove any previously-baked inline snippet, then inject the fresh one before </body>
    import re
    html = re.sub(r"<!--PLAYER_SNIPPET_START-->.*?<!--PLAYER_SNIPPET_END-->", "", html, flags=re.S)
    html = html.replace("</body>", snippet + "</body>")
    return Response(html, mimetype="text/html")


@app.route("/pdf/<path:name>")
def pdf(name):
    if not os.path.exists(os.path.join(REPORTS_DIR, name + ".pdf")):
        abort(404)
    return send_from_directory(REPORTS_DIR, name + ".pdf")


@app.route("/player/<path:name>")
def player(name):
    """Standalone player page (all playlists) with mint-on-demand video — for quick clip review."""
    pls, meta = _webapp_playlists(name)
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    build_player_html(pls, tmp, title=meta.get("bowler") or name, subtitle="video review")
    html = open(tmp, encoding="utf-8").read()
    os.unlink(tmp)
    return Response(html, mimetype="text/html")


_INDEX_HTML = """<!doctype html><meta charset=utf8>
<title>Bowler Scouting Reports</title>
<style>
 body{font:15px/1.5 Inter,-apple-system,Segoe UI,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#1a1a2e}
 h1{color:#003087;margin-bottom:4px} h2{color:#003087;font-size:14px;margin:22px 0 6px;border-bottom:2px solid #003087;padding-bottom:3px}
 ul{list-style:none;padding:0} li{padding:10px 12px;border:1px solid #e5e7eb;border-radius:8px;margin:6px 0;display:flex;align-items:center;gap:10px}
 a{color:#003087;text-decoration:none;font-weight:600} a:hover{text-decoration:underline}
 .n{color:#6b7280;font-size:12px;margin-left:auto} .pdf{font-size:12px;background:#eef1f6;padding:3px 8px;border-radius:5px}
 .c{color:#6b7280;font-weight:400;font-size:12px} .note{color:#6b7280;font-size:12px;margin-top:20px}
</style>
<h1>Bowler Scouting Reports</h1>
{{rows}}
<p class="note">Video is minted on demand, so clips keep working. Open a report and click ▶ to watch.</p>
"""


if __name__ == "__main__":
    print(f"Serving reports from {REPORTS_DIR}")
    print("Open http://127.0.0.1:8062")
    app.run(host="127.0.0.1", port=8062, debug=False)
