"""
build_player_site.py — build the PLAYER site: a roster of OUR squad, each name opening that player's
own pack (batting always; bowling for bowlers + all-rounders) plus their vs-opponent vision.
See INDIVIDUALIZATION_PLAN.md. Driven by squads.json + players.json (written by build_squad.py).

This is the SCAFFOLD: structure, navigation and pack shells only — the sections carry "coming soon"
placeholders until the assembly-from-scouting-report step lands.

Usage:
    .\\venv\\Scripts\\python.exe build_player_site.py                 # build player_site/
    .\\venv\\Scripts\\python.exe build_player_site.py --out player_site
"""
import argparse
import html
import json
import os
import re

from site_render import page as _page
from photos import get_photo_data_uri, get_photo_path

# "file": pages reference img/{pid}.png (copied at build, lazy-loaded — keeps the roster page
# a few tens of KB instead of megabytes of inlined base64, which lagged on phone data).
# "datauri": inline images — only for the single-file preview artifact.
IMG_MODE = "file"
_SITE_IMGS: set = set()      # pids whose photo was copied into the bundle's img/

HERE = os.path.dirname(os.path.abspath(__file__))
SQUADS = os.path.join(HERE, "squads.json")
PLAYERS = os.path.join(HERE, "players.json")
CARDS = os.path.join(HERE, "data", "attack_cards.json")


def _load_cards():
    if os.path.exists(CARDS):
        return json.load(open(CARDS, encoding="utf-8"))
    return {}

ROLE_ORDER = [("Batter", "Batters"), ("All-rounder", "All-rounders"),
              ("Bowler", "Bowlers"), ("Unknown", "Unclassified")]
ROLE_CLASS = {"Batter": "squad", "All-rounder": "xi", "Bowler": "reference", "Unknown": "fringe"}

# Player-site-only styling, layered on top of the shared shell.
EXTRA_CSS = """<style>
 .roster{list-style:none;padding:0;margin:0}
 .roster li{padding:12px 14px;border:1px solid #e5e7eb;border-radius:10px;margin:8px 0;background:#fff;
   display:flex;align-items:center;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
 .roster a.rmain{color:#003087;text-decoration:none;font-weight:600;flex:1;display:flex;align-items:center;gap:12px;min-width:0}
 .roster a.rmain:hover b{text-decoration:underline}
 .avatar{width:44px;height:44px;border-radius:50%;object-fit:cover;background:#eef1f6;flex:0 0 auto;
   display:flex;align-items:center;justify-content:center;font-size:20px;color:#9aa4b2}
 .roster b{display:block;font-size:15px;color:#1a1a2e} .roster .rr{color:#6b7280;font-size:12px;font-weight:400}
 .packchips{margin-left:auto;display:flex;gap:6px;white-space:nowrap;flex:0 0 auto}
 .pchip{font-size:12px;font-weight:700;padding:7px 13px;border-radius:8px;text-decoration:none;display:inline-block}
 .pchip.batting{background:#e0e7ff;color:#3730a3} .pchip.batting:hover{background:#c7d2fe}
 .pchip.bowling{background:#fef3c7;color:#92400e} .pchip.bowling:hover{background:#fde68a}
 .rtabs{display:flex;gap:8px;margin:-4px 0 16px}
 .rtab{font-size:13px;font-weight:700;padding:6px 15px;border-radius:8px;text-decoration:none;border:1px solid #d5dced;color:#003087;background:#fff}
 .rtab.on{background:#003087;color:#fff;border-color:#003087}
 .phead{display:flex;align-items:center;gap:16px;margin:4px 0 18px}
 .phead .big{width:72px;height:72px;border-radius:50%;object-fit:cover;background:#eef1f6;flex:0 0 auto;
   display:flex;align-items:center;justify-content:center;font-size:32px;color:#9aa4b2}
 .phead h1{margin:0} .phead .role{color:#6b7280;font-size:14px;margin-top:2px}
 .pack{border:1px solid #e5e7eb;border-radius:12px;background:#fff;padding:16px 18px;margin:14px 0;
   box-shadow:0 1px 3px rgba(0,0,0,.04)}
 .pack h2{font-size:16px;color:#003087;margin:0 0 4px} .pack .desc{color:#6b7280;font-size:13px;margin:0 0 10px}
 .soon{color:#9aa4b2;font-style:italic;font-size:13px;border:1px dashed #d5dced;border-radius:8px;
   padding:14px;text-align:center;background:#fafbfc}
 .sblock{border-top:1px solid #eef1f6;padding:10px 0 4px;margin-top:8px}
 .sblock .shead{font-size:14px;font-weight:700;color:#1a1a2e}
 .sblock .smeta{color:#6b7280;font-size:12px;margin:1px 0 7px}
 .sblock .ssum{font-size:13.5px;margin:0 0 10px;line-height:1.55}
 .sgrid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,4fr);gap:14px;align-items:start}
 @media(max-width:560px){.sgrid{grid-template-columns:1fr}}
 table.ct{border-collapse:collapse;width:100%;font-size:12px}
 table.ct caption{text-align:left;font-size:11px;font-weight:700;color:#6b7280;letter-spacing:.04em;text-transform:uppercase;padding-bottom:4px}
 table.ct th{font-weight:600;color:#6b7280;text-align:left;padding:3px 8px 3px 0;border-bottom:1px solid #e5e7eb;white-space:nowrap}
 table.ct td{padding:4px 8px 4px 0;border-bottom:1px solid #f1f3f7;color:#1a1a2e;font-variant-numeric:tabular-nums}
 table.ct td.num,table.ct th.num{text-align:right}
 table.ct td.dir{font-weight:700;white-space:nowrap}
 table.ct td.dir.more{color:#991b1b} table.ct td.dir.less{color:#075985}
 table.ct td.dir.even{color:#c2c9d4;font-weight:400;font-size:11px}
 table.ct tr:last-child td{border-bottom:0}
 .vwatch{font-size:11px;font-weight:700;color:#003087;text-decoration:none;background:#eef1f6;
   border:1px solid #d5dced;border-radius:6px;padding:2px 8px;margin-left:6px;letter-spacing:0;text-transform:none}
 .vwatch.off{color:#9aa4b2;border-style:dashed;cursor:default}
 /* collapsible sections */
 details.pack{border:1px solid #e5e7eb;border-radius:12px;background:#fff;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.04);overflow:hidden}
 details.pack>summary{list-style:none;cursor:pointer;padding:14px 16px;display:flex;align-items:baseline;gap:8px}
 details.pack>summary::-webkit-details-marker{display:none}
 details.pack>summary::before{content:"▸";color:#9aa4b2;font-size:13px;transition:transform .15s;flex:0 0 auto}
 details.pack[open]>summary::before{transform:rotate(90deg)}
 details.pack>summary h2{font-size:16px;color:#003087;margin:0;display:inline}
 details.pack>summary .desc{color:#6b7280;font-size:12.5px;font-weight:400;margin:0}
 details.pack>.body{padding:0 16px 14px}
 /* per-bowler cards */
 details.bwl{border:1px solid #e5e7eb;border-radius:10px;background:#fff;margin:7px 0}
 details.bwl>summary{list-style:none;cursor:pointer;padding:9px 12px;display:flex;align-items:center;gap:10px}
 details.bwl>summary::-webkit-details-marker{display:none}
 details.bwl .bav{width:38px;height:38px;border-radius:50%;object-fit:cover;background:#eef1f6;flex:0 0 auto;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#9aa4b2}
 details.bwl .bn{flex:1;min-width:0} details.bwl .bn b{font-size:14px;color:#1a1a2e;display:block}
 details.bwl .bn .bt{color:#6b7280;font-size:12px}
 details.bwl .bhead{font-size:12px;font-weight:700;white-space:nowrap;padding:2px 9px;border-radius:999px}
 details.bwl .bhead.hard{background:#fee2e2;color:#991b1b} details.bwl .bhead.ok{background:#dcfce7;color:#15803d} details.bwl .bhead.mid{background:#eef1f6;color:#475569}
 details.bwl>.bbody{padding:2px 12px 11px 12px;font-size:13px;line-height:1.5}
 details.bwl>.bbody p{margin:5px 0} details.bwl .k{color:#6b7280}
 .cohort{color:#9aa4b2;font-size:11.5px;font-style:italic}
</style>"""


def _dfmt(iso):
    """ISO -> day-first dd-mm-yyyy."""
    try:
        y, m, d = iso.split("-")
        return f"{d}-{m}-{y}"
    except Exception:
        return iso


_FLAG = {"more": ("▲ more", "dir more"), "less": ("▼ less", "dir less"),
         "even": ("· even", "dir even"), "thin": ("few balls", "dir even")}


def _cells_table(cells):
    rows = "".join(
        f'<tr><td>{html.escape(c["label"].capitalize())}</td>'
        f'<td class="num">{c["pct"]:.0f}%</td><td class="num">{c["ctrl_pct"]:.0f}%</td>'
        f'<td class="{_FLAG[c["flag"]][1]}">{_FLAG[c["flag"]][0]}</td></tr>'
        for c in cells)
    return ('<table class="ct"><caption>Their pace plan vs your teammates</caption>'
            '<tr><th>Ball</th><th class="num">You</th><th class="num">Others</th><th></th></tr>'
            + rows + '</table>')


def _dismissals_table(dismissals, vision_href=None):
    rows = "".join(
        f'<tr><td>{html.escape(str(o["bowler"] or "?"))}</td>'
        f'<td>{html.escape(o["how"])}</td>'
        f'<td>{html.escape(o["length"] or "—")}, {html.escape(o["line"] or "—")}</td>'
        f'<td>{html.escape(o["stroke"] or "—")}</td></tr>'
        for o in dismissals)
    watch = (f' <a class="vwatch" href="{vision_href}">▶ Watch</a>' if vision_href else "")
    return (f'<table class="ct"><caption>Dismissals{watch}</caption>'
            '<tr><th>Bowler</th><th>How</th><th>Ball</th><th>Shot</th></tr>'
            + rows + '</table>')


def _attack_card_html(card, opp_label, vision=None):
    """The 'how previous attacks bowled to you' block for a batting pack.
    `vision` maps series index -> href of that series' dismissal playlist."""
    if not card or not card.get("series"):
        return ('<div class="soon">Coming soon — will be built from the scouting report.</div>')
    vision = vision or {}
    n = len(card["series"])
    lead = ("How the last attack bowled to you." if n == 1
            else f"How the last {n} attacks bowled to you.")
    parts = [f'<p class="desc" style="margin-top:8px">{lead}</p>']
    for i, s in enumerate(card["series"]):
        meta = (f'{s["tests"]} Test{"s" if s["tests"] != 1 else ""} · {_dfmt(s["d0"])} → {_dfmt(s["d1"])} · '
                f'{s["balls"]} balls · {s["runs"]} runs · '
                + (f'avg {s["avg"]}' if s.get("avg") is not None else 'not dismissed'))
        block = [f'<div class="sblock"><div class="shead">v {html.escape(s["opp"])}</div>'
                 f'<div class="smeta">{meta}</div>']
        if s.get("cells"):
            block.append(f'<p class="ssum">{html.escape(s["summary"])}</p>')
        else:
            block.append(f'<p class="ssum" style="color:#6b7280">Too few balls in this series to '
                         f'compare a plan ({s["pace_balls"]} pace balls tracked).</p>')
        left = _cells_table(s["cells"]) if s.get("cells") else ""
        right = _dismissals_table(s["dismissals"], vision.get(i)) if s.get("dismissals") else ""
        if left and right:
            block.append(f'<div class="sgrid"><div>{left}</div><div>{right}</div></div>')
        elif left or right:
            block.append(left or right)
        block.append("</div>")
        parts.append("".join(block))
    return "".join(parts)


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _avatar(pid, cls, initials, fmt="test", name=None):
    if pid and IMG_MODE == "file":
        if str(pid) in _SITE_IMGS:
            return f'<img class="{cls}" src="img/{pid}.png" alt="" loading="lazy">'
    elif pid:
        uri = get_photo_data_uri(pid, fmt=fmt, name=name)
        if uri:
            return f'<img class="{cls}" src="{uri}" alt="">'
    return f'<span class="{cls}">{html.escape(initials)}</span>'


def _initials(name):
    parts = [p for p in name.split() if p]
    return (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else (parts[0][:2].upper() if parts else "??")


def _roster_body(meta, roster):
    """roster: list of (pid, rec). Grouped by role."""
    by_role = {}
    for pid, rec in roster:
        by_role.setdefault(rec.get("role", "Unknown"), []).append((pid, rec))
    sections = []
    for role, heading in ROLE_ORDER:
        group = by_role.get(role)
        if not group:
            continue
        items = []
        for pid, rec in group:
            name = rec.get("name", pid)
            sl = _slug(name)
            chips = "".join(
                f'<a class="pchip {p}" href="{sl}-{p}.html">{p.capitalize()}</a>'
                for p in rec.get("packs", []))
            items.append(
                f'<li><a class="rmain" href="{sl}-batting.html">'
                f'{_avatar(pid, "avatar", _initials(name), name=name)}'
                f'<span><b>{html.escape(name)}</b><span class="rr">{html.escape(role)}</span></span></a>'
                f'<span class="packchips">{chips}</span></li>')
        sections.append(f'<h2 class="tierhead {ROLE_CLASS.get(role,"squad")}">{heading}'
                        f'<span>{len(group)}</span></h2><ul class="roster">{"".join(items)}</ul>')
    lead = html.escape(meta.get("opposition") or meta.get("name", ""))
    return (EXTRA_CSS + f'<h1>Player packs</h1><p class="lead">{lead} · tap <b>Batting</b> or '
            '<b>Bowling</b></p>'
            + "".join(sections)
            + '<p class="note">Batting: how their attack will come at you. Bowling: how to bowl to '
              'each of their batters. Both carry footage of the real meetings — video links refresh '
              'periodically.</p>')


def _pack_section(title, desc, inner=None, open=True):
    """A collapsible pack section (details/summary)."""
    body = inner or '<div class="soon">Coming soon — will be built from the scouting report.</div>'
    return (f'<details class="pack"{" open" if open else ""}>'
            f'<summary><h2>{html.escape(title)}</h2>'
            f'<span class="desc">{html.escape(desc)}</span></summary>'
            f'<div class="body">{body}</div></details>')


# ── Per-opposition-bowler matchup (SCOUTING_REBUILD.md we_bat direction) ──────────
def _matchups(slug):
    """{our_batter_id: [we_bat cells]} sorted most-dangerous first, from the matchup store."""
    try:
        from cricket_core.config import project_path
        opp = slug.split("-")[0]
        p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{opp}.json")
        store = json.load(open(p, encoding="utf-8"))
        by_bat = {}
        for c in store.get("we_bat", []):
            if c.get("sim_avg") is not None:
                by_bat.setdefault(c["batter_id"], []).append(c)
        for cells in by_bat.values():
            cells.sort(key=lambda c: c["sim_avg"])         # lowest exp avg = most dangerous
        return by_bat
    except Exception:
        return {}


def _matchups_they_bat(slug):
    """{our_bowler_id: [they_bat cells]} sorted most-exploitable first (lowest their sim avg)."""
    try:
        from cricket_core.config import project_path
        opp = slug.split("-")[0]
        p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{opp}.json")
        store = json.load(open(p, encoding="utf-8"))
        by_bowl = {}
        for c in store.get("they_bat", []):
            if c.get("sim_avg") is not None:
                by_bowl.setdefault(c["bowler_id"], []).append(c)
        for cells in by_bowl.values():
            cells.sort(key=lambda c: -c["sim_avg"])    # highest = their danger men, plan first
        return by_bowl
    except Exception:
        return {}


def _batter_block(cell, vision_href=None, h2h_row=None):
    """One collapsible per-opposition-BATTER card in OUR bowler's bowling report.
    cell is a they_bat matchup: sim_avg is the opposition batter's expected average vs this bowler
    (low = the bowler is on top)."""
    bid, name = cell["batter_id"], cell["batter"]
    avg = cell["sim_avg"]
    if avg <= 25:
        band, cls = "you're on top", "ok"
    elif avg >= 45:
        band, cls = "tough to shift", "hard"
    else:
        band, cls = "even", "mid"
    av = _avatar(bid, "bav", _initials(name), name=name)
    summ = (f'<summary>{av}<span class="bn"><b>{html.escape(name)}</b>'
            f'<span class="bt">{html.escape(cell.get("bat_hand",""))}</span></span>'
            f'<span class="bhead {cls}">{band}</span></summary>')
    lines = []
    cohort = cell.get("confidence") == "None"
    lines.append(f'<p><span class="k">Projected matchup:</span> they average about '
                 f'<b>{avg:.0f}</b> against you in the simulation (strike rate ~{cell["sim_sr"]:.0f})'
                 + ('. <span class="cohort">Based on how batters like them fare — too few personal '
                    'balls for an individual read.</span>' if cohort else '.') + '</p>')
    if cell.get("top_dismissal"):
        lines.append(f'<p><span class="k">How you\'re most likely to get them:</span> '
                     f'{html.escape(cell["top_dismissal"])}'
                     + (f', at {html.escape(cell["danger"])}' if cell.get("danger") else '') + '.</p>')
    fts = cell.get("fail_to_set_pct")
    if fts not in (None, "", "None"):
        try:
            if float(fts) >= 35:
                lines.append(f'<p><span class="k">Get them early:</span> in the sim they fall inside '
                             f'the first 30 balls about {float(fts):.0f}% of the time against you.</p>')
        except (TypeError, ValueError):
            pass
    if cell.get("structural_threat"):
        lines.append('<p><span class="k">Structural:</span> you take the ball away from them — a '
                     'genuine edge; keep the angle when they stay on strike.</p>')
    if h2h_row:
        met = (f'You have bowled to them <b>{h2h_row["balls"]}</b> balls in Tests '
               f'({h2h_row["runs"]} conceded, {h2h_row["wickets"]} wkt).')
        if vision_href:
            met += f' <a class="vwatch" href="{vision_href}">▶ Watch</a>'
        lines.append(f'<p>{met}</p>')
    return f'<details class="bwl">{summ}<div class="bbody">{"".join(lines)}</div></details>'


def _bowler_block(cell, vision_href=None, h2h_row=None):
    """One collapsible per-opposition-bowler card in a batter's pack."""
    bid, name = cell["bowler_id"], cell["bowler"]
    avg = cell["sim_avg"]
    # headline band by expected average (hedged — this is a projection, not a record)
    if avg <= 25:
        band, cls = "tough matchup", "hard"
    elif avg >= 45:
        band, cls = "you project on top", "ok"
    else:
        band, cls = "even", "mid"
    av = _avatar(bid, "bav", _initials(name), name=name)
    summ = (f'<summary>{av}<span class="bn"><b>{html.escape(name)}</b>'
            f'<span class="bt">{html.escape(cell.get("bowler_type",""))}</span></span>'
            f'<span class="bhead {cls}">{band}</span></summary>')
    lines = []
    cohort = cell.get("confidence") == "None"
    lines.append(f'<p><span class="k">Projected matchup:</span> you average about '
                 f'<b>{avg:.0f}</b> against them in the simulation (strike rate ~{cell["sim_sr"]:.0f})'
                 + ('. <span class="cohort">Based on how batters like you fare — too few personal '
                    'balls for an individual read.</span>' if cohort else '.') + '</p>')
    if cell.get("top_dismissal"):
        lines.append(f'<p><span class="k">Most likely to get you:</span> '
                     f'{html.escape(cell["top_dismissal"])}'
                     + (f', targeting {html.escape(cell["danger"])}' if cell.get("danger") else '') + '.</p>')
    fts = cell.get("fail_to_set_pct")
    if fts not in (None, "", "None"):
        try:
            if float(fts) >= 35:
                lines.append(f'<p><span class="k">Watch early:</span> in the sim you fall inside the '
                             f'first 30 balls about {float(fts):.0f}% of the time against them.</p>')
        except (TypeError, ValueError):
            pass
    if cell.get("structural_threat"):
        lines.append('<p><span class="k">Structural:</span> they take the ball away from your bat — '
                     'a genuine matchup, not just form. Rotating strike to keep the angle changing helps.</p>')
    if h2h_row:
        met = (f'You have faced them <b>{h2h_row["balls"]}</b> balls in Tests '
               f'({h2h_row["runs"]} runs, {h2h_row["wickets"]} wkt).')
        if vision_href:
            met += f' <a class="vwatch" href="{vision_href}">▶ Watch</a>'
        lines.append(f'<p>{met}</p>')
    return f'<details class="bwl">{summ}<div class="bbody">{"".join(lines)}</div></details>'


def _short_opp(meta):
    """'Australia v Bangladesh · 2 Tests · in Australia' -> 'Bangladesh'."""
    if meta.get("opponent"):
        return meta["opponent"]
    sub = meta.get("opposition") or meta.get("name", "the opposition")
    if " v " in sub:
        return sub.split(" v ", 1)[1].split("·", 1)[0].strip()
    return sub


def _load_h2h(slug):
    """h2h_{opp}.json for this series, indexed both ways, or None."""
    opp = slug.split("-")[0]
    p = os.path.join(HERE, "data", f"h2h_{opp}.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    return d


def _opp_names(slug):
    """id -> display name for the opposition, from the matchup store (matchupmodel)."""
    try:
        from cricket_core.config import project_path
        opp = slug.split("-")[0]
        p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{opp}.json")
        store = json.load(open(p, encoding="utf-8"))
        names = {}
        for blk in ("we_bat", "they_bat"):
            for c in store.get(blk, []):
                names[c["batter_id"]] = c["batter"]
                names[c["bowler_id"]] = c["bowler"]
        return names
    except Exception:
        return {}


def _h2h_playlists(h2h, pid, players, opp_names=None):
    """This player's real meetings, one playlist per opponent: batting rows where they struck,
    bowling rows where they bowled. Returns (playlists, titles) with unresolved stems."""
    from cricket_core.video import playlist_item
    playlists, titles = {}, {}
    name_of = {p: r.get("name", p) for p, r in players.items()}
    name_of.update(opp_names or {})

    def add(rows, me_key, them_key, prefix, label):
        mine = [r for r in rows if r[me_key] == pid]
        mine.sort(key=lambda r: -r["balls"])
        for r in mine:
            if not r["clips"]:
                continue
            them = r[them_key]
            key = f"{prefix}_{them}"                 # hbat_/hbowl_ so both directions coexist
            items = [playlist_item(d["delivery_id"], d["clip_stem"],
                                   caption=f'{d["date"][8:10]}-{d["date"][5:7]}-{d["date"][:4]} · '
                                           + (f'OUT {d["wicket"]}' if d["wicket"] else f'{d["runs"]} run{"s" if d["runs"] != 1 else ""}'))
                     for d in r["deliveries"] if d["clip_stem"]]
            if items:
                playlists[key] = items
                titles[key] = f'{label} {name_of.get(them, them)} · {r["balls"]} balls, {r["runs"]} runs, {r["wickets"]} wkt'
    add(h2h.get("our_batting", []), "striker_id", "bowler_id", "hbat", "You v")
    add(h2h.get("our_bowling", []), "bowler_id", "striker_id", "hbowl", "You to")
    return playlists, titles


def _build_vision(dest_dir, page_slug, name, card, extra=None):
    """One modal-player page per player: a 'Dismissals — v X' playlist per attack-card series,
    plus any `extra` (playlists, titles) — the real head-to-head meetings. Fresh SAS minted at
    build time, like publish_site. Returns (dismissal_hrefs, h2h_links): {series_index: href#key}
    and [(href, title)] for the h2h playlists whose clips resolved."""
    from cricket_core.video import playlist_item, resolve_playlist, build_player_html
    playlists, titles, hrefs, h2h_links = {}, {}, {}, []
    for i, s in enumerate(card.get("series", []) if card else []):
        items = [playlist_item(o["delivery_id"], o["clip_stem"],
                               caption=f'{o["how"]} — {o["bowler"] or "?"} · '
                                       f'{o["length"] or "?"}, {o["line"] or "?"} · {_dfmt(o["date"])}')
                 for o in s.get("dismissals", []) if o.get("clip_stem")]
        if not items:
            continue
        resolved, avail, _tot = resolve_playlist(items)
        if avail:
            key = f"s{i}"
            playlists[key] = resolved
            titles[key] = f'Dismissals — v {s["opp"]}'
            hrefs[i] = f"{page_slug}-vision.html#{key}"
    h2h_map = {}                                     # full key (hbat_/hbowl_) -> href
    for key, items in (extra[0] if extra else {}).items():
        resolved, avail, _tot = resolve_playlist(items)
        if avail:
            playlists[key] = resolved
            titles[key] = extra[1][key]
            href = f"{page_slug}-vision.html#{key}"
            h2h_links.append((href, extra[1][key]))
            h2h_map[key] = href
    if playlists:
        build_player_html(playlists, os.path.join(dest_dir, f"{page_slug}-vision.html"),
                          title=f"{name} — vision", subtitle="dismissals + head-to-head",
                          titles=titles)
    return hrefs, h2h_links, h2h_map


def _report_top(pid, name, role, sname, kind, other_href=None):
    """Shared header: avatar, name, role, and a Batting|Bowling toggle when both exist."""
    tabs = ""
    if other_href:
        other = "Bowling" if kind == "batting" else "Batting"
        tabs = (f'<div class="rtabs"><span class="rtab on">{kind.capitalize()}</span>'
                f'<a class="rtab" href="{other_href}">{other} &rarr;</a></div>')
    return (f'<div class="phead">{_avatar(pid, "big", _initials(name), name=name)}'
            f'<div><h1>{html.escape(name)}</h1><div class="role">{html.escape(role)} · '
            f'{html.escape(sname)}</div></div></div>{tabs}')


def _vision_list(h2h_links, prefix, had_meetings, verb):
    """The 'all footage' section body, filtered to one direction (#hbat_ / #hbowl_)."""
    links = [(h, t) for h, t in (h2h_links or []) if f"#{prefix}_" in h]
    if links:
        items = "".join(f'<li style="margin:6px 0"><a class="vwatch" href="{href}">▶ Watch</a> '
                        f'<span style="font-size:13px">{html.escape(title)}</span></li>'
                        for href, title in links)
        return '<ul style="list-style:none;padding:0;margin:0">' + items + '</ul>'
    if had_meetings:
        return (f'<p class="ssum" style="color:#6b7280">You have {verb} them in Tests, but that '
                'footage is not in the clip library (older matches are not clipped).</p>')
    return ('<p class="ssum" style="color:#6b7280">No Test meetings with this opposition yet — '
            'nothing to show.</p>')


def _batting_body(meta, pid, rec, card=None, vision=None, h2h_links=None, had_meetings=False,
                  mcells=None, h2h_map=None, h2h_rows=None, other_href=None):
    name, role = rec.get("name", pid), rec.get("role", "")
    opp = _short_opp(meta)
    h2h_map = h2h_map or {}
    h2h_rows = h2h_rows or {}
    body = [EXTRA_CSS, _report_top(pid, name, role, meta.get("name", ""), "batting", other_href)]

    body.append(_pack_section("How previous attacks have bowled to you",
                              "Their plans against you over your last few series — not a forecast, "
                              "what actually happened.", inner=_attack_card_html(card, opp, vision)))
    if mcells:
        blocks = [_bowler_block(c, h2h_map.get(f'hbat_{c["bowler_id"]}'),
                                h2h_rows.get((pid, c["bowler_id"]))) for c in mcells]
        body.append(_pack_section(f"Vs each {opp} bowler",
                                  "Tap a bowler for the matchup and any footage of you against them. "
                                  "Ordered by how tough they project.", inner="".join(blocks)))
    body.append(_pack_section(f"Your vision vs {opp}",
                              "Your most recent balls facing each of their bowlers (Tests only, "
                              "capped at the 20 most recent per bowler).",
                              inner=_vision_list(h2h_links, "hbat", had_meetings, "faced"),
                              open=False))
    return "".join(body)


def _bowling_body(meta, pid, rec, bcells=None, h2h_links=None, had_meetings=False,
                  h2h_map=None, h2h_rows=None, other_href=None):
    name, role = rec.get("name", pid), rec.get("role", "")
    opp = _short_opp(meta)
    h2h_map = h2h_map or {}
    h2h_rows = h2h_rows or {}
    body = [EXTRA_CSS, _report_top(pid, name, role, meta.get("name", ""), "bowling", other_href)]

    if bcells:
        blocks = [_batter_block(c, h2h_map.get(f'hbowl_{c["batter_id"]}'),
                                h2h_rows.get((pid, c["batter_id"]))) for c in bcells]
        body.append(_pack_section(f"How to bowl to each {opp} batter",
                                  "Tap a batter for the matchup and any footage of you bowling to "
                                  "them. Their danger batters first.",
                                  inner="".join(blocks)))
    else:
        body.append(_pack_section(f"How to bowl to each {opp} batter",
                                  "Matchups load from the simulation once built.", inner=None))
    body.append(_pack_section(f"Your vision vs {opp}",
                              "Your most recent balls bowling to each of their batters (Tests only, "
                              "capped at the 20 most recent per batter).",
                              inner=_vision_list(h2h_links, "hbowl", had_meetings, "bowled to"),
                              open=False))
    return "".join(body)


def build(out_dir, no_video=False):
    squads = json.load(open(SQUADS, encoding="utf-8"))
    players = json.load(open(PLAYERS, encoding="utf-8"))
    cards = _load_cards()
    os.makedirs(out_dir, exist_ok=True)
    # clear (keep any .git)
    for f in os.listdir(out_dir):
        if f == ".git":
            continue
        p = os.path.join(out_dir, f)
        if os.path.isdir(p):
            import shutil
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)

    slugs = list(squads.keys())
    single = len(slugs) == 1

    for slug in slugs:
        meta = squads[slug]
        roster = [(pid, players.get(pid, {"name": pid, "role": "Unknown", "packs": ["batting"]}))
                  for pid in meta.get("players", [])]
        s_dir = out_dir if single else os.path.join(out_dir, slug)
        os.makedirs(s_dir, exist_ok=True)
        if IMG_MODE == "file":                       # copy each roster photo into the bundle once
            img_dir = os.path.join(s_dir, "img")
            os.makedirs(img_dir, exist_ok=True)
            import shutil
            for pid, rec in roster:
                p = get_photo_path(pid, fmt="test", name=rec.get("name"))
                if p:
                    shutil.copy(p, os.path.join(img_dir, f"{pid}.png"))
                    _SITE_IMGS.add(str(pid))
        up = None if single else ("../index.html", "Series")
        open(os.path.join(s_dir, "index.html"), "w", encoding="utf-8").write(
            _page(f"{meta.get('name','')} — player packs", _roster_body(meta, roster), up=up))
        h2h = _load_h2h(slug)
        opp_names = _opp_names(slug)
        matchups = _matchups(slug)                    # we_bat: our batter -> opp bowler cells
        bmatchups = _matchups_they_bat(slug)          # they_bat: our bowler -> opp batter cells
        # h2h counts kept per DIRECTION — an all-rounder can both face and bowl to the same
        # opponent, so a single (me, them) dict would collide (wrong count vs a correct video).
        bat_rows = {(r["striker_id"], r["bowler_id"]): r for r in (h2h or {}).get("our_batting", [])}
        bowl_rows = {(r["bowler_id"], r["striker_id"]): r for r in (h2h or {}).get("our_bowling", [])}
        # copy opposition photos (bowlers for batting reports, batters for bowling reports)
        if IMG_MODE == "file":
            import shutil
            pairs = ([(c["bowler_id"], c.get("bowler")) for cs in matchups.values() for c in cs]
                     + [(c["batter_id"], c.get("batter")) for cs in bmatchups.values() for c in cs])
            for oid, onm in pairs:
                if str(oid) in _SITE_IMGS:
                    continue
                p = get_photo_path(oid, fmt="test", name=onm)
                if p:
                    shutil.copy(p, os.path.join(s_dir, "img", f"{oid}.png"))
                    _SITE_IMGS.add(str(oid))
        for pid, rec in roster:
            name = rec.get("name", pid)
            pslug = _slug(name)
            has_bowling = "bowling" in rec.get("packs", [])
            vision, h2h_links, h2h_map = {}, [], {}
            extra = _h2h_playlists(h2h, pid, players, opp_names) if h2h else ({}, {})
            had_bat = bool(h2h and any(r["striker_id"] == pid for r in h2h.get("our_batting", [])))
            had_bowl = bool(h2h and any(r["bowler_id"] == pid for r in h2h.get("our_bowling", [])))
            if not no_video and (cards.get(pid) or extra[0]):
                try:
                    vision, h2h_links, h2h_map = _build_vision(s_dir, pslug, name, cards.get(pid), extra)
                except Exception as e:
                    print(f"  ! vision for {name}: {type(e).__name__}: {e}")
            bat_href, bowl_href = f"{pslug}-batting.html", f"{pslug}-bowling.html"
            open(os.path.join(s_dir, bat_href), "w", encoding="utf-8").write(
                _page(f"{name} — batting",
                      _batting_body(meta, pid, rec, cards.get(pid), vision, h2h_links, had_bat,
                                    mcells=matchups.get(pid), h2h_map=h2h_map, h2h_rows=bat_rows,
                                    other_href=bowl_href if has_bowling else None),
                      up=("index.html", "Squad")))
            if has_bowling:
                open(os.path.join(s_dir, bowl_href), "w", encoding="utf-8").write(
                    _page(f"{name} — bowling",
                          _bowling_body(meta, pid, rec, bcells=bmatchups.get(pid), h2h_links=h2h_links,
                                        had_meetings=had_bowl, h2h_map=h2h_map, h2h_rows=bowl_rows,
                                        other_href=bat_href),
                          up=("index.html", "Squad")))
        print(f"  {slug}: {len(roster)} players -> {s_dir}")

    if not single:
        items = "\n".join(
            f'<li><a href="{s}/index.html"><b>{html.escape(squads[s].get("name", s))}</b>'
            f'<span class="sub">{html.escape(squads[s].get("opposition",""))}</span></a>'
            f'<span class="n">{len(squads[s].get("players",[]))} players</span></li>' for s in slugs)
        open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(
            _page("Player packs", f'<h1>Player packs</h1><p class="lead">Select a series.</p>'
                                  f'<ul class="cards">{items}</ul>'))
    open(os.path.join(out_dir, ".nojekyll"), "w").close()
    print(f"Built player site -> {out_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="player_site")
    ap.add_argument("--no-video", action="store_true",
                    help="skip minting SAS / resolving dismissal clips (fast offline build)")
    args = ap.parse_args()
    build(os.path.join(HERE, args.out), no_video=args.no_video)


if __name__ == "__main__":
    main()
