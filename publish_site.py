"""
publish_site.py — build a static, shareable bundle of the reports with FRESH video links.

This is the "Option 3" pipeline: static hosting + a periodic refresh, with NO backend and NO new
IT grant. It uses your own SSO to mint a long (near-7-day) read SAS, bakes it into a
self-contained `site/` folder (reports + a player per report + PDFs + an index), which you upload
to any static host (Cloudflare Pages, GitHub Pages, Azure Static Web Apps, Netlify…).

Because a user-delegation SAS is capped at 7 days, **re-run this every few days** (before the SAS
expires) — e.g. a Windows Task Scheduler job — and re-upload `site/`. The hosted link then always
serves working video. (Offline copies go stale after the SAS window; the PDF is the offline
fallback.)

Run:
    .\\venv\\Scripts\\python.exe publish_site.py                 # all reports -> site/
    .\\venv\\Scripts\\python.exe publish_site.py --hand lhb --ids 2700039 3080087 5460155
    .\\venv\\Scripts\\python.exe publish_site.py --out site --sas-hours 156
"""
import argparse
import glob
import json
import os
import re
import shutil
import sys

sys.path.insert(0, r"c:\Ludis\ludis-cricket\src")

from ludis_cricket.video import (get_fairplay_sas, get_hawkeye_sas, resolve_clip,
                                  inline_player_snippet, build_player_html)

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
# A user-delegation SAS can't outlive 7 days; stay just under and refresh more often than this.
DEFAULT_SAS_HOURS = 156          # ~6.5 days
_SNIPPET_RE = re.compile(r"<!--PLAYER_SNIPPET_START-->.*?<!--PLAYER_SNIPPET_END-->", re.S)
_FILE_URL_RE = re.compile(r"file:///[^\"#]*?([A-Za-z0-9_.\-]+\.player\.html)")


def _refresh_hawkeye_url(url: str, hk_sas: str) -> str:
    """Swap the SAS on a Hawkeye angle URL for a fresh one."""
    base = (url or "").split("?", 1)[0]
    return (base + hk_sas) if base else url


def _refresh_playlists(pls: dict, hk_sas: str) -> dict:
    """Re-mint every clip URL (fairplay main + hawkeye angles) with the freshly-primed SAS."""
    for items in pls.values():
        if not isinstance(items, list):
            continue
        for it in items:
            stem = it.get("clip_stem")
            if stem:
                fresh = resolve_clip(stem)          # uses the long SAS primed in main()
                if fresh:
                    it["url"] = fresh
            for a in (it.get("angles") or []):
                a["url"] = _refresh_hawkeye_url(a.get("url"), hk_sas)
    return pls


def _reports(ids, hand):
    """Select report base-names from the sidecars, optionally filtered by id / hand-tag."""
    hand_tag = {"all": "all", "lhb": "lhb", "rhb": "rhb"}.get((hand or "").lower())
    names = []
    for sc in sorted(glob.glob(os.path.join(REPORTS_DIR, "*.playlists.json"))):
        name = os.path.basename(sc)[: -len(".playlists.json")]
        if hand_tag and not name.endswith("_" + hand_tag):
            continue
        names.append(name)
    if ids:
        keep = set(str(i) for i in ids)
        names = [n for n in names
                 if str(json.load(open(os.path.join(REPORTS_DIR, n + ".playlists.json"),
                                     encoding="utf-8")).get("meta", {}).get("bowler_id")) in keep]
    return names


def build(out_dir, ids, hand, sas_hours):
    os.makedirs(out_dir, exist_ok=True)
    print(f"Priming a {sas_hours}h ({sas_hours/24:.1f}-day) read SAS…")
    get_fairplay_sas(ttl_hours=sas_hours)            # primes the cached SAS used by resolve_clip
    try:
        hk_sas = get_hawkeye_sas(ttl_hours=sas_hours)
    except Exception:
        hk_sas = ""                                   # no Hawkeye coverage / access — main clips still refresh

    names = _reports(ids, hand)
    if not names:
        sys.exit("No matching reports. Render some first (build_reports.py).")
    cards = []
    for name in names:
        html_path = os.path.join(REPORTS_DIR, name + ".html")
        sc_path = os.path.join(REPORTS_DIR, name + ".playlists.json")
        if not (os.path.exists(html_path) and os.path.exists(sc_path)):
            print(f"  skip {name} (missing html/sidecar)"); continue
        d = json.load(open(sc_path, encoding="utf-8"))
        pls = _refresh_playlists(d.get("playlists", d), hk_sas)
        meta = d.get("meta", {})

        # 1) report html: swap the in-page player for a fresh-SAS one; point the ▶ fallback at the
        #    relative player file (the file:// path from render time won't exist on the host).
        html = open(html_path, encoding="utf-8").read()
        snippet = "<!--PLAYER_SNIPPET_START-->" + inline_player_snippet(pls) + "<!--PLAYER_SNIPPET_END-->"
        if _SNIPPET_RE.search(html):
            html = _SNIPPET_RE.sub(lambda m: snippet, html)
        else:
            html = html.replace("</body>", snippet + "</body>")
        html = _FILE_URL_RE.sub(lambda m: m.group(1), html)
        open(os.path.join(out_dir, name + ".html"), "w", encoding="utf-8").write(html)

        # 2) standalone player (the href fallback) + 3) the PDF
        build_player_html(pls, os.path.join(out_dir, name + ".player.html"),
                          title=meta.get("bowler") or name, subtitle="bowling scout")
        pdf_src = os.path.join(REPORTS_DIR, name + ".pdf")
        has_pdf = os.path.exists(pdf_src)
        if has_pdf:
            shutil.copy(pdf_src, os.path.join(out_dir, name + ".pdf"))

        n_clips = sum(len(v) for v in pls.values() if isinstance(v, list))
        cards.append((name, meta.get("bowler") or name.replace("_", " ").title(), n_clips, has_pdf))
        print(f"  [ok] {name}  ({n_clips} clips)")

    # index
    rows = "\n".join(
        f'<li><a href="{n}.html">{title}</a> <span class="n">{c} clips</span>'
        + (f' · <a class="pdf" href="{n}.pdf">PDF</a>' if pdf else "") + "</li>"
        for n, title, c, pdf in cards)
    open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(
        _INDEX.replace("{{rows}}", rows))
    open(os.path.join(out_dir, ".nojekyll"), "w").close()   # serve files as-is (no Jekyll)
    print(f"\nBuilt {len(cards)} report(s) -> {os.path.abspath(out_dir)}")
    return cards


def deploy_github(out_dir, repo_url, branch="main"):
    """Publish the site/ folder to a GitHub repo as a single fresh commit (force), so the Pages
    repo never accumulates history. Enable Pages once: repo Settings → Pages → Deploy from branch
    → <branch> / root. Site then serves at https://<user>.github.io/<repo>/."""
    import datetime
    import subprocess
    gitdir = os.path.join(out_dir, ".git")
    if os.path.isdir(gitdir):
        shutil.rmtree(gitdir)

    def run(*a):
        subprocess.run(a, cwd=out_dir, check=True, capture_output=True, text=True)
    run("git", "init", "-q", "-b", branch)
    run("git", "add", "-A")
    run("git", "-c", "user.name=scouting-bot", "-c", "user.email=bot@local",
        "commit", "-q", "-m", f"publish {datetime.datetime.now():%Y-%m-%d %H:%M}")
    run("git", "push", "-f", repo_url, branch)
    print(f"Deployed to {repo_url} ({branch}). "
          f"If Pages isn't on yet: repo Settings → Pages → Deploy from branch → {branch} / root.")


_INDEX = """<!doctype html><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Bowler Scouting Reports</title>
<style>
 body{font:15px/1.5 Inter,-apple-system,Segoe UI,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#1a1a2e;background:#F5F7FA}
 h1{color:#003087} ul{list-style:none;padding:0} li{padding:11px 13px;border:1px solid #e5e7eb;border-radius:8px;margin:7px 0;background:#fff;display:flex;align-items:center;gap:8px}
 a{color:#003087;text-decoration:none;font-weight:600} a:hover{text-decoration:underline}
 .n{color:#6b7280;font-size:12px;margin-left:auto} .pdf{font-size:12px}
 .note{color:#6b7280;font-size:12px;margin-top:20px}
</style>
<h1>Bowler Scouting Reports</h1>
<ul>{{rows}}</ul>
<p class="note">Open a report and tap ▶ to watch clips. Video links refresh periodically; if a clip
doesn't load, the report may be due a refresh — the PDF always works offline.</p>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="site", help="output folder (default: site)")
    ap.add_argument("--ids", nargs="+", help="only these bowler ids")
    ap.add_argument("--hand", help="only this hand tag: all | lhb | rhb")
    ap.add_argument("--sas-hours", type=int, default=DEFAULT_SAS_HOURS, help="SAS lifetime (max ~168)")
    ap.add_argument("--deploy-repo", help="GitHub repo URL to publish site/ to (e.g. "
                    "https://github.com/tbcricketau/scouting-reports.git)")
    ap.add_argument("--branch", default="main", help="branch to push (default: main)")
    args = ap.parse_args()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.out)
    build(out, args.ids, args.hand, min(args.sas_hours, 167))
    if args.deploy_repo:
        deploy_github(out, args.deploy_repo, args.branch)
    else:
        print("Upload that folder to your static host, or pass --deploy-repo to push to GitHub Pages.")


if __name__ == "__main__":
    main()
