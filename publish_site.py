"""
publish_site.py — build a static, shareable, SERIES-organised bundle of scouting reports with
FRESH video links. The "Option 3" pipeline: static hosting + a periodic refresh, no backend and
no new IT grant. It uses your SSO to mint a long (near-7-day) read SAS, bakes it into a
self-contained `site/` folder you upload to any static host (or `--deploy-repo` to GitHub Pages).

Navigation (driven by `series.json`): **Series → Report type → Reports**, e.g.
    Bangladesh Home Test Series 2026 → Opposition Bowlers to LHB → Taijul / Mehidy / Nahid.
Each series has a `target_country` that conditions the video precedence — but that is baked at
RENDER time (`build_reports.py --target-country …`), so render a series' reports with its country
first; this script only refreshes the SAS and assembles the site.

Because a user-delegation SAS can't outlive 7 days, **re-run this every few days** and re-upload.
Offline copies go stale after the SAS window; the bundled PDF is the offline fallback.

Run:
    .\\venv\\Scripts\\python.exe publish_site.py                         # build site/ from series.json
    .\\venv\\Scripts\\python.exe publish_site.py --deploy-repo https://github.com/tbcricketau/scouting-reports.git
"""
import argparse
import datetime
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, r"c:\Ludis\ludis-cricket\src")

from ludis_cricket.video import (get_fairplay_sas, get_hawkeye_sas, resolve_clip,
                                  inline_player_snippet, build_player_html)

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")
SERIES_JSON = os.path.join(HERE, "series.json")
DEFAULT_SAS_HOURS = 156          # ~6.5 days; a user-delegation SAS can't exceed 7 days
_SNIPPET_RE = re.compile(r"<!--PLAYER_SNIPPET_START-->.*?<!--PLAYER_SNIPPET_END-->", re.S)
_FILE_URL_RE = re.compile(r"file:///[^\"#]*?([A-Za-z0-9_.\-]+\.player\.html)")


# ── SAS refresh ─────────────────────────────────────────────────────────────────
def _refresh_playlists(pls, hk_sas):
    for items in pls.values():
        if not isinstance(items, list):
            continue
        for it in items:
            stem = it.get("clip_stem")
            if stem:
                fresh = resolve_clip(stem)
                if fresh:
                    it["url"] = fresh
            for a in (it.get("angles") or []):
                base = (a.get("url") or "").split("?", 1)[0]
                if base:
                    a["url"] = base + hk_sas
    return pls


# ── Report → file resolution (manifest references bowlers by id + hand) ─────────
def _sidecar_map():
    """{(bowler_id, hand_tag): report_base_name} from the rendered sidecars."""
    out = {}
    for sc in glob.glob(os.path.join(REPORTS_DIR, "*.playlists.json")):
        name = os.path.basename(sc)[: -len(".playlists.json")]
        m = re.search(r"_(all|lhb|rhb)$", name)
        if not m:
            continue
        try:
            bid = str(json.load(open(sc, encoding="utf-8")).get("meta", {}).get("bowler_id"))
        except Exception:
            continue
        out[(bid, m.group(1))] = name
    return out


def _bake_report(name, dest_dir, hk_sas):
    """Refresh a report's video (SAS) and write html + player + pdf into dest_dir.
    Returns (title, n_clips, has_pdf) or None if the source isn't there."""
    html_path = os.path.join(REPORTS_DIR, name + ".html")
    sc_path = os.path.join(REPORTS_DIR, name + ".playlists.json")
    if not (os.path.exists(html_path) and os.path.exists(sc_path)):
        return None
    d = json.load(open(sc_path, encoding="utf-8"))
    pls = _refresh_playlists(d.get("playlists", d), hk_sas)
    meta = d.get("meta", {})

    page = open(html_path, encoding="utf-8").read()
    snippet = "<!--PLAYER_SNIPPET_START-->" + inline_player_snippet(pls) + "<!--PLAYER_SNIPPET_END-->"
    page = _SNIPPET_RE.sub(lambda m: snippet, page) if _SNIPPET_RE.search(page) \
        else page.replace("</body>", snippet + "</body>")
    page = _FILE_URL_RE.sub(lambda m: m.group(1), page)      # player href → relative (same folder)
    open(os.path.join(dest_dir, name + ".html"), "w", encoding="utf-8").write(page)

    build_player_html(pls, os.path.join(dest_dir, name + ".player.html"),
                      title=meta.get("bowler") or name, subtitle="bowling scout")
    has_pdf = os.path.exists(os.path.join(REPORTS_DIR, name + ".pdf"))
    if has_pdf:
        shutil.copy(os.path.join(REPORTS_DIR, name + ".pdf"), os.path.join(dest_dir, name + ".pdf"))
    n_clips = sum(len(v) for v in pls.values() if isinstance(v, list))
    return (meta.get("bowler") or name.replace("_", " ").title(), n_clips, has_pdf)


# ── Site build (Series → Group → Reports) ───────────────────────────────────────
def build(out_dir, sas_hours):
    cfg = json.load(open(SERIES_JSON, encoding="utf-8"))
    smap = _sidecar_map()
    if os.path.isdir(out_dir):
        for f in os.listdir(out_dir):
            if f != ".git":
                p = os.path.join(out_dir, f)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    os.makedirs(out_dir, exist_ok=True)

    print(f"Priming a {sas_hours}h (~{sas_hours/24:.1f}-day) read SAS…")
    get_fairplay_sas(ttl_hours=sas_hours)
    try:
        hk_sas = get_hawkeye_sas(ttl_hours=sas_hours)
    except Exception:
        hk_sas = ""

    series_cards = []
    for s in cfg.get("series", []):
        s_dir = os.path.join(out_dir, s["slug"])
        os.makedirs(s_dir, exist_ok=True)
        group_cards, s_total = [], 0
        for g in s.get("groups", []):
            g_dir = os.path.join(s_dir, g["slug"])
            os.makedirs(g_dir, exist_ok=True)
            report_cards = []
            for r in g.get("reports", []):
                name = smap.get((str(r["id"]), r.get("hand", "all")))
                if not name:
                    print(f"  ! {s['slug']}/{g['slug']}: report id {r['id']} ({r.get('hand')}) "
                          f"not rendered — skipped"); continue
                res = _bake_report(name, g_dir, hk_sas)
                if res:
                    title, n_clips, has_pdf = res
                    report_cards.append((name, title, n_clips, has_pdf))
                    s_total += 1
                    print(f"  [ok] {s['slug']}/{g['slug']}/{title} ({n_clips} clips)")
            _write_group_index(g_dir, cfg, s, g, report_cards)
            group_cards.append((g["slug"], g["name"], len(report_cards)))
        _write_series_index(s_dir, cfg, s, group_cards)
        series_cards.append((s["slug"], s["name"], s.get("subtitle", ""), s_total))
    _write_top_index(out_dir, cfg, series_cards)
    open(os.path.join(out_dir, ".nojekyll"), "w").close()
    print(f"\nBuilt {sum(c[3] for c in series_cards)} report(s) across "
          f"{len(series_cards)} series -> {out_dir}")


# ── Navigation pages ────────────────────────────────────────────────────────────
def _page(title, body, up=None):
    crumb = f'<a href="{up[0]}">← {html.escape(up[1])}</a>' if up else ""
    return _SHELL.replace("{{title}}", html.escape(title)).replace("{{crumb}}", crumb) \
                 .replace("{{body}}", body)


def _write_top_index(out_dir, cfg, series_cards):
    items = "\n".join(
        f'<li><a href="{sl}/index.html"><b>{html.escape(nm)}</b>'
        f'<span class="sub">{html.escape(sub)}</span></a>'
        f'<span class="n">{tot} report{"s" if tot != 1 else ""}</span></li>'
        for sl, nm, sub, tot in series_cards)
    body = f'<h1>{html.escape(cfg.get("title","Scouting"))}</h1><p class="lead">Select a series.</p><ul class="cards">{items}</ul>'
    open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(_page(cfg.get("title", "Scouting"), body))


def _write_series_index(s_dir, cfg, s, group_cards):
    if group_cards:
        items = "\n".join(
            f'<li><a href="{gl}/index.html"><b>{html.escape(gn)}</b></a>'
            f'<span class="n">{c} report{"s" if c != 1 else ""}</span></li>'
            for gl, gn, c in group_cards)
        inner = f'<ul class="cards">{items}</ul>'
    else:
        inner = '<p class="empty">Reports for this series are coming soon.</p>'
    body = (f'<h1>{html.escape(s["name"])}</h1>'
            f'<p class="lead">{html.escape(s.get("subtitle",""))}</p>{inner}')
    open(os.path.join(s_dir, "index.html"), "w", encoding="utf-8").write(
        _page(s["name"], body, up=("../index.html", cfg.get("title", "Series"))))


def _write_group_index(g_dir, cfg, s, g, report_cards):
    if report_cards:
        items = "\n".join(
            f'<li><a href="{n}.html"><b>{html.escape(t)}</b></a>'
            f'<span class="n">{c} clips</span>'
            + (f'<a class="pdf" href="{n}.pdf">PDF</a>' if pdf else "") + "</li>"
            for n, t, c, pdf in report_cards)
        inner = f'<ul class="cards">{items}</ul>'
    else:
        inner = '<p class="empty">No reports yet.</p>'
    body = (f'<h1>{html.escape(g["name"])}</h1>'
            f'<p class="lead">{html.escape(s["name"])}</p>{inner}'
            '<p class="note">Open a report and tap ▶ to watch clips. If a clip doesn\'t load the '
            'link may be due a refresh — the PDF always works offline.</p>')
    open(os.path.join(g_dir, "index.html"), "w", encoding="utf-8").write(
        _page(g["name"], body, up=("../index.html", s["name"])))


_SHELL = """<!doctype html><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{{title}}</title>
<style>
 :root{color-scheme:light}
 body{font:15px/1.5 Inter,-apple-system,Segoe UI,sans-serif;max-width:760px;margin:0 auto;padding:24px 16px 48px;color:#1a1a2e;background:#F5F7FA}
 .crumb{font-size:13px;margin-bottom:14px} .crumb a{color:#6b7280;text-decoration:none} .crumb a:hover{color:#003087}
 h1{color:#003087;font-size:22px;margin:2px 0 2px} .lead{color:#6b7280;margin:0 0 16px}
 ul.cards{list-style:none;padding:0;margin:0}
 ul.cards li{padding:13px 15px;border:1px solid #e5e7eb;border-radius:10px;margin:8px 0;background:#fff;display:flex;align-items:center;gap:10px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
 ul.cards a{color:#003087;text-decoration:none;font-weight:600;flex:1} ul.cards a:hover b{text-decoration:underline}
 ul.cards b{display:block} .sub{display:block;color:#6b7280;font-size:12px;font-weight:400;margin-top:2px}
 .n{color:#6b7280;font-size:12px;white-space:nowrap} .pdf{flex:0 0 auto;font-size:12px;background:#eef1f6;padding:3px 9px;border-radius:6px;font-weight:600}
 .empty{color:#6b7280;font-style:italic} .note{color:#9ca3af;font-size:12px;margin-top:22px}
</style>
<div class="crumb">{{crumb}}</div>
{{body}}
"""


def deploy_github(out_dir, repo_url, branch="main"):
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
          f"If Pages isn't on: repo Settings > Pages > Deploy from branch > {branch} / root.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="site")
    ap.add_argument("--sas-hours", type=int, default=DEFAULT_SAS_HOURS)
    ap.add_argument("--deploy-repo", help="GitHub repo URL to publish site/ to")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()
    out = os.path.join(HERE, args.out)
    build(out, min(args.sas_hours, 167))
    if args.deploy_repo:
        deploy_github(out, args.deploy_repo, args.branch)
    else:
        print("Upload that folder to your static host, or pass --deploy-repo to push to GitHub Pages.")


if __name__ == "__main__":
    main()
