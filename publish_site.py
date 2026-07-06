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
import stat
import subprocess
import sys


def _rmtree(path):
    """shutil.rmtree that survives Windows read-only files (git objects are read-only)."""
    def _onexc(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    if os.path.isdir(path):
        try:
            shutil.rmtree(path, onexc=_onexc)          # Python 3.12+
        except TypeError:
            shutil.rmtree(path, onerror=lambda f, p, e: (_onexc(f, p, e)))

sys.path.insert(0, r"c:\Ludis\ludis-cricket\src")

from ludis_cricket.video import (get_fairplay_sas, get_hawkeye_sas, resolve_clip,
                                  inline_player_snippet, build_player_html)

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")
SERIES_JSON = os.path.join(HERE, "series.json")
DEFAULT_SAS_HOURS = 156          # ~6.5 days; a user-delegation SAS can't exceed 7 days
_SNIPPET_RE = re.compile(r"<!--PLAYER_SNIPPET_START-->.*?<!--PLAYER_SNIPPET_END-->", re.S)
_FILE_URL_RE = re.compile(r"file:///[^\"#]*?([A-Za-z0-9_.\-]+\.player\.html)")
_TYPE_RE = re.compile(r"(Right Fast|Left Fast|Right Medium|Left Medium|Off Spin|"
                      r"Left Orthodox|Leg Break|Left Unorthodox)")


def _natural_name(nm):
    """'Rana, Nahid' -> 'Nahid Rana'."""
    if "," in nm:
        surname, first = (x.strip() for x in nm.split(",", 1))
        return f"{first} {surname}".strip()
    return nm


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
    Returns (natural_name, bowler_type, has_pdf) or None if the source isn't there."""
    html_path = os.path.join(REPORTS_DIR, name + ".html")
    sc_path = os.path.join(REPORTS_DIR, name + ".playlists.json")
    if not (os.path.exists(html_path) and os.path.exists(sc_path)):
        return None
    d = json.load(open(sc_path, encoding="utf-8"))
    pls = _refresh_playlists(d.get("playlists", d), hk_sas)
    meta = d.get("meta", {})

    page = open(html_path, encoding="utf-8").read()
    btype = (_TYPE_RE.search(page).group(1) if _TYPE_RE.search(page) else "")
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
    return (_natural_name(meta.get("bowler") or name.replace("_", " ").title()), btype, has_pdf)


# ── Site build (Series → Group → Reports) ───────────────────────────────────────
def build(out_dir, sas_hours):
    cfg = json.load(open(SERIES_JSON, encoding="utf-8"))
    smap = _sidecar_map()
    if os.path.isdir(out_dir):
        for f in os.listdir(out_dir):
            if f != ".git":
                p = os.path.join(out_dir, f)
                _rmtree(p) if os.path.isdir(p) else os.remove(p)
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
                    title, btype, has_pdf = res
                    report_cards.append((name, title, btype, has_pdf, r.get("tier", "squad")))
                    s_total += 1
                    print(f"  [ok] {s['slug']}/{g['slug']}/{title} ({btype})")
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


# Tier → (section heading, short card chip). Order defines the reading priority on the page.
_TIER_META = [("xi", "Most likely XI", "XI"),
              ("squad", "In the squad", "Squad"),
              ("fringe", "Fringe / outside chance", "Fringe"),
              ("reference", "Reference — our bowlers", "Ref")]
_TIER_CHIP = {t: chip for t, _h, chip in _TIER_META}


def _report_li(card):
    n, t, bt, pdf, tier = card
    chip = _TIER_CHIP.get(tier, "")
    return (f'<li><div class="rinfo"><b>{html.escape(t)}</b>'
            + (f'<span class="rtype">{html.escape(bt)}</span>' if bt else "")
            + (f'<span class="tier {tier}">{chip}</span>' if chip else "") + "</div>"
            f'<a class="btn" href="{n}.html">View report</a>'
            + (f'<a class="btn ghost" href="{n}.pdf">View as PDF</a>' if pdf else "") + "</li>")


def _write_group_index(g_dir, cfg, s, g, report_cards):
    tiered = False
    if report_cards:
        by_tier = {}
        for card in report_cards:
            by_tier.setdefault(card[4], []).append(card)
        if len(by_tier) <= 1:                       # single tier (e.g. reference) → flat list
            inner = f'<ul class="reports">{chr(10).join(_report_li(c) for c in report_cards)}</ul>'
        else:                                        # opposition → XI / Squad / Fringe sections
            tiered = True
            sections = []
            for tier, heading, _chip in _TIER_META:
                cards = by_tier.get(tier)
                if not cards:
                    continue
                items = "\n".join(_report_li(c) for c in cards)
                sections.append(f'<h2 class="tierhead {tier}">{heading}'
                                f'<span>{len(cards)}</span></h2><ul class="reports">{items}</ul>')
            inner = "".join(sections)
    else:
        inner = '<p class="empty">No reports yet.</p>'
    lead = html.escape(s["name"]) + (" · sorted by how likely each bowler is to play" if tiered else "")
    body = (f'<h1>{html.escape(g["name"])}</h1>'
            f'<p class="lead">{lead}</p>{inner}'
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
 ul.reports{list-style:none;padding:0;margin:0}
 ul.reports li{padding:13px 15px;border:1px solid #e5e7eb;border-radius:10px;margin:8px 0;background:#fff;display:flex;align-items:center;gap:10px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
 ul.reports .rinfo{flex:1;min-width:0} ul.reports .rinfo b{font-size:15px;color:#1a1a2e} ul.reports .rtype{color:#6b7280;margin-left:10px;font-size:13px}
 .tier{display:inline-block;margin-left:8px;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;vertical-align:middle}
 .tier.xi{background:#dcfce7;color:#15803d} .tier.squad{background:#e0e7ff;color:#3730a3} .tier.fringe{background:#eef2f6;color:#64748b} .tier.reference{background:#fef3c7;color:#92400e}
 h2.tierhead{font-size:14px;color:#1a1a2e;margin:22px 0 8px;display:flex;align-items:center;gap:8px;padding-left:8px;border-left:3px solid #cbd5e1}
 h2.tierhead:first-of-type{margin-top:10px} h2.tierhead.xi{border-left-color:#15803d} h2.tierhead.squad{border-left-color:#3730a3} h2.tierhead.fringe{border-left-color:#94a3b8}
 h2.tierhead span{font-size:12px;font-weight:600;color:#6b7280;background:#eef1f6;border-radius:999px;padding:1px 8px}
 ul.reports a.btn{flex:0 0 auto;font-size:13px;font-weight:600;text-decoration:none;padding:7px 14px;border-radius:7px;background:#003087;color:#fff;white-space:nowrap}
 ul.reports a.btn.ghost{background:#eef1f6;color:#003087;border:1px solid #d5dced}
 @media(max-width:520px){ul.reports li{flex-wrap:wrap} ul.reports .rinfo{flex:1 0 100%;margin-bottom:6px}}
 .empty{color:#6b7280;font-style:italic} .note{color:#9ca3af;font-size:12px;margin-top:22px}
</style>
<div class="crumb">{{crumb}}</div>
{{body}}
"""


def deploy_github(out_dir, repo_url, branch="main"):
    _rmtree(os.path.join(out_dir, ".git"))

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
