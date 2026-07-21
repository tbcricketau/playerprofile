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


from cricket_core.video import (get_fairplay_sas, get_hawkeye_sas, resolve_clip,
                                  inline_player_snippet, build_player_html)

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(HERE, "reports")
SERIES_JSON = os.path.join(HERE, "series.json")
DEFAULT_SAS_HOURS = 156          # ~6.5 days; a user-delegation SAS can't exceed 7 days
_SNIPPET_RE = re.compile(r"<!--PLAYER_SNIPPET_START-->.*?<!--PLAYER_SNIPPET_END-->", re.S)
_FILE_URL_RE = re.compile(r"file:///[^\"#]*?([A-Za-z0-9_.\-]+\.player\.html)")
# Card + page shell are shared with the local audit app (webapp) so the two stay identical.
from site_render import (page as _page, report_card, TIER_META as _TIER_META,
                         TIER_CHIP as _TIER_CHIP, TYPE_RE as _TYPE_RE)
from photos import get_photo_path


def _initials(name):
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else (parts[0][:2].upper() if parts else "?")


def _row_photo(pid, name, g_dir):
    """Copy the player's headshot into <group>/img/<pid>.png and return the relative href
    (or None). Keeps the index page light — no inlined base64, matching the player packs."""
    if not pid:
        return None
    p = get_photo_path(pid, fmt="test", name=name)
    if not p:
        return None
    img_dir = os.path.join(g_dir, "img")
    os.makedirs(img_dir, exist_ok=True)
    dst = os.path.join(img_dir, f"{pid}.png")
    if not os.path.exists(dst):
        shutil.copy(p, dst)
    return f"img/{pid}.png"


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
    """{(player_id, hand_tag, kind, bowl_group): report_base_name} from the rendered sidecars —
    bowling sidecars carry meta.bowler_id, batting sidecars meta.batter_id. `bowl_group` is the
    ''`_vs_<group>`'' suffix ('' for the combined report; 'pace'/'spin' for the macro batter
    reports; 'right_pace'/… for atomic ones)."""
    out = {}
    for sc in glob.glob(os.path.join(REPORTS_DIR, "*.playlists.json")):
        name = os.path.basename(sc)[: -len(".playlists.json")]
        m = re.search(r"_(all|lhb|rhb)(?:_vs_(\w+))?$", name)
        if not m:
            continue
        try:
            meta = json.load(open(sc, encoding="utf-8")).get("meta", {})
            bid = str(meta.get("bowler_id") or meta.get("batter_id"))
        except Exception:
            continue
        kind = "batting" if "_batting_" in name else "bowling"    # a player can have BOTH
        out[(bid, m.group(1), kind, m.group(2) or "")] = name
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

    # reduced PLAYER-MODE cut (Vs Our Squad stripped) — same video refresh, linked from player packs
    pm_path = os.path.join(REPORTS_DIR, name + ".pmode.html")
    if os.path.exists(pm_path):
        pm = open(pm_path, encoding="utf-8").read()
        pm = _SNIPPET_RE.sub(lambda m: snippet, pm) if _SNIPPET_RE.search(pm) \
            else pm.replace("</body>", snippet + "</body>")
        pm = _FILE_URL_RE.sub(lambda m: m.group(1), pm)
        open(os.path.join(dest_dir, name + ".pmode.html"), "w", encoding="utf-8").write(pm)

    build_player_html(pls, os.path.join(dest_dir, name + ".player.html"),
                      title=meta.get("bowler") or meta.get("batter") or name,
                      subtitle="bowling scout" if "_bowling_" in name else "batting scout")
    has_pdf = os.path.exists(os.path.join(REPORTS_DIR, name + ".pdf"))
    if has_pdf:
        shutil.copy(os.path.join(REPORTS_DIR, name + ".pdf"), os.path.join(dest_dir, name + ".pdf"))
    pid = str(meta.get("bowler_id") or meta.get("batter_id") or "")
    return (_natural_name(meta.get("bowler") or meta.get("batter") or name.replace("_", " ").title()), btype, has_pdf, pid)


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
        # series-level Match-ups matrix (render_matchups.py) — the ONE full simulated grid
        mx_src = os.path.join(REPORTS_DIR, f"matchups_{s['slug'].split('-')[0]}.html")
        has_mx = os.path.exists(mx_src)
        if has_mx:
            shutil.copy(mx_src, os.path.join(s_dir, "matchups.html"))
        group_cards, s_total = [], 0
        for g in s.get("groups", []):
            g_dir = os.path.join(s_dir, g["slug"])
            os.makedirs(g_dir, exist_ok=True)
            report_cards = []
            for r in g.get("reports", []):
                kind = g.get("kind", "bowling")
                name = smap.get((str(r["id"]), r.get("hand", "all"), kind, g.get("bowl_group", "")))
                if not name:
                    print(f"  ! {s['slug']}/{g['slug']}: report id {r['id']} ({r.get('hand')}) "
                          f"not rendered — skipped"); continue
                res = _bake_report(name, g_dir, hk_sas)
                if res:
                    title, btype, has_pdf, pid = res
                    report_cards.append((name, title, btype, has_pdf, r.get("tier", "squad"), pid))
                    s_total += 1
                    print(f"  [ok] {s['slug']}/{g['slug']}/{title} ({btype})")
            _write_group_index(g_dir, cfg, s, g, report_cards)
            group_cards.append((g["slug"], g["name"], len(report_cards)))
        # 'How bowlers have attacked our squad' — coach-side section (attack_cards + squads.json)
        has_attacks = False
        try:
            import build_player_site as bps
            if s["slug"] in json.load(open(bps.SQUADS, encoding="utf-8")):
                nap = bps.render_attack_section(os.path.join(s_dir, "attacked-our-squad"), slug=s["slug"])
                has_attacks = nap > 0
                print(f"  [ok] {s['slug']}/attacked-our-squad ({nap} players)")
        except Exception as e:
            print(f"  ! attack section {s['slug']}: {type(e).__name__}: {e}")
        _write_series_index(s_dir, cfg, s, group_cards, has_matchups=has_mx, has_attacks=has_attacks)
        series_cards.append((s["slug"], s["name"], s.get("subtitle", ""), s_total))
    _write_top_index(out_dir, cfg, series_cards)
    open(os.path.join(out_dir, ".nojekyll"), "w").close()
    print(f"\nBuilt {sum(c[3] for c in series_cards)} report(s) across "
          f"{len(series_cards)} series -> {out_dir}")


# ── Navigation pages (page shell + report card come from site_render) ────────────


def _write_top_index(out_dir, cfg, series_cards):
    items = "\n".join(
        f'<li><a href="{sl}/index.html"><b>{html.escape(nm)}</b>'
        f'<span class="sub">{html.escape(sub)}</span></a>'
        f'<span class="n">{tot} report{"s" if tot != 1 else ""}</span></li>'
        for sl, nm, sub, tot in series_cards)
    body = f'<h1>{html.escape(cfg.get("title","Scouting"))}</h1><p class="lead">Select a series.</p><ul class="cards">{items}</ul>'
    open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(_page(cfg.get("title", "Scouting"), body))


def _write_series_index(s_dir, cfg, s, group_cards, has_matchups=False, has_attacks=False):
    mx = ('<li><a href="matchups.html"><b>Match-ups</b>'
          '<span class="sub">the full simulated grid — every pairing, both directions</span></a>'
          '<span class="n">matrix</span></li>' if has_matchups else "")
    at = ('<li><a href="attacked-our-squad/index.html"><b>How bowlers have attacked our squad</b>'
          '<span class="sub">our squad · how the last few attacks came at each of them (last 3 series)</span></a>'
          '<span class="n">squad</span></li>' if has_attacks else "")
    if group_cards or mx or at:
        items = mx + at + "\n".join(
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


def _report_li(card, g_dir):
    n, t, bt, pdf, tier, pid = card
    return report_card(t, bt, f"{n}.html", pdf_href=(f"{n}.pdf" if pdf else None),
                       vision_href=f"{n}.player.html", badge=_TIER_CHIP.get(tier), badge_class=tier,
                       photo=_row_photo(pid, t, g_dir), initials=_initials(t))


def _write_group_index(g_dir, cfg, s, g, report_cards):
    tiered = False
    if report_cards:
        by_tier = {}
        for card in report_cards:
            by_tier.setdefault(card[4], []).append(card)
        if len(by_tier) <= 1:                       # single tier (e.g. reference) → flat list
            inner = f'<ul class="reports">{chr(10).join(_report_li(c, g_dir) for c in report_cards)}</ul>'
        else:                                        # opposition → XI / Squad / Fringe sections
            tiered = True
            sections = []
            for tier, heading, _chip in _TIER_META:
                cards = by_tier.get(tier)
                if not cards:
                    continue
                items = "\n".join(_report_li(c, g_dir) for c in cards)
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


def deploy_github(out_dir, repo_url, branch="main"):
    _rmtree(os.path.join(out_dir, ".git"))

    def run(*a):
        subprocess.run(a, cwd=out_dir, check=True, capture_output=True, text=True)
    run("git", "init", "-q", "-b", branch)
    run("git", "add", "-A")
    run("git", "-c", "user.name=scouting-bot", "-c", "user.email=bot@local",
        "commit", "-q", "-m", f"publish {datetime.datetime.now():%Y-%m-%d %H:%M}")
    run("git", "push", "-f", repo_url, branch)
    # The force-push replaces history each deploy; GitHub Pages often does NOT rebuild off such a
    # disconnected push (it keeps serving the old commit). A follow-up empty commit is a normal
    # fast-forward that reliably triggers the Pages build. Without this, scheduled refreshes go stale.
    run("git", "-c", "user.name=scouting-bot", "-c", "user.email=bot@local",
        "commit", "-q", "--allow-empty", "-m", "trigger pages rebuild")
    run("git", "push", repo_url, branch)
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
