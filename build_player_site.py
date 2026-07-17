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
from cricket_core.lookups import team_flag

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

N_OPP = 3               # opposition cards per pack (kept small while iterating; raise for the full pack)
ROLE_ORDER = [("Batter", "Batters"), ("All-rounder", "All-rounders"),
              ("Bowler", "Bowlers"), ("Unknown", "Unclassified")]
ROLE_CLASS = {"Batter": "squad", "All-rounder": "xi", "Bowler": "reference", "Unknown": "fringe"}

# Player-site-only styling, layered on top of the shared shell.
EXTRA_CSS = """<style>
 .roster{list-style:none;padding:0;margin:0}
 .roster li{padding:12px 14px;border:1px solid #e5e7eb;border-radius:10px;margin:8px 0;background:#fff;
   display:flex;align-items:center;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
 .roster .rmain{color:#1a1a2e;font-weight:600;flex:1;display:flex;align-items:center;gap:12px;min-width:0}
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
 .ssum{font-size:13.5px;margin:0 0 10px;line-height:1.55}
 details.sblock2{border-top:1px solid #eef1f6;margin-top:8px}
 details.sblock2>summary{list-style:none;cursor:pointer;padding:9px 0 7px;display:flex;flex-wrap:wrap;align-items:baseline;gap:6px}
 details.sblock2>summary::-webkit-details-marker{display:none}
 details.sblock2>summary::before{content:"▸";color:#9aa4b2;font-size:12px;flex:0 0 auto}
 details.sblock2[open]>summary::before{content:"▾"}
 details.sblock2 .sh{font-size:14px;font-weight:700;color:#1a1a2e}
 details.sblock2 .sh .flag{font-size:16px;vertical-align:-1px}
 details.sblock2 .smeta{color:#6b7280;font-size:12px}
 .cwatch{color:#003087;text-decoration:none;font-size:11px;margin-left:3px;white-space:nowrap}
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
 details.bwl .rlink{font-size:11px;font-weight:700;color:#003087;text-decoration:none;background:#eef1f6;padding:3px 9px;border-radius:999px;white-space:nowrap;flex:0 0 auto}
 details.bwl .rlink:hover{background:#003087;color:#fff}
 details.bwl .bhead{font-size:12px;font-weight:700;white-space:nowrap;padding:2px 9px;border-radius:999px}
 details.bwl .bhead.hard{background:#fee2e2;color:#991b1b} details.bwl .bhead.ok{background:#dcfce7;color:#15803d} details.bwl .bhead.mid{background:#eef1f6;color:#475569}
 details.bwl>.bbody{padding:2px 12px 11px 12px;font-size:13px;line-height:1.5}
 details.bwl>.bbody p{margin:5px 0} details.bwl .k{color:#6b7280}
 ul.afacts{margin:4px 0 8px;padding-left:18px} ul.afacts li{margin:3px 0}
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


def _cells_table(cells, caption, href_for=None):
    rows = []
    for idx, c in enumerate(cells):
        watch = ""
        if c["flag"] == "more" and href_for:
            h = href_for(idx)
            if h:
                watch = f' <a class="cwatch" href="{h}" title="watch">▶</a>'
        rows.append(
            f'<tr><td>{html.escape(c["label"].capitalize())}{watch}</td>'
            f'<td class="num">{c["pct"]:.0f}%</td><td class="num">{c["ctrl_pct"]:.0f}%</td>'
            f'<td class="{_FLAG[c["flag"]][1]}">{_FLAG[c["flag"]][0]}</td></tr>')
    return (f'<table class="ct"><caption>{html.escape(caption)}</caption>'
            '<tr><th>Ball</th><th class="num">You</th><th class="num">Others</th><th></th></tr>'
            + "".join(rows) + '</table>')


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


def _attack_card_html(card, opp_label, vision=None, cell_vision=None):
    """The 'how previous attacks bowled to you' block — one collapsible series each, with the
    pace plan (left) and spin plan (right) side by side, ▶ on the cells they went at you more,
    and the dismissals. `vision` = {series_i: dismissal href}; `cell_vision` = {(i,fam,idx): href}."""
    if not card or not card.get("series"):
        return ('<div class="soon">Coming soon — will be built from the scouting report.</div>')
    vision, cell_vision = vision or {}, cell_vision or {}
    n = len(card["series"])
    lead = ("How the last attack bowled to you." if n == 1
            else f"How the last {n} attacks bowled to you.")
    parts = [f'<p class="desc" style="margin-top:8px">{lead}</p>']
    for i, s in enumerate(card["series"]):
        meta = (f'{s["tests"]} Test{"s" if s["tests"] != 1 else ""} · {_dfmt(s["d0"])} → {_dfmt(s["d1"])} · '
                f'{s["balls"]} balls · {s["runs"]} runs · '
                + (f'avg {s["avg"]}' if s.get("avg") is not None else 'not dismissed'))
        flag = (team_flag(s["opp"])[0] or "")
        flag_html = (f'<span class="flag">{flag}</span> ' if flag else "")
        summ = (f'<summary><span class="sh">{flag_html}v {html.escape(s["opp"])}</span>'
                f'<span class="smeta">{meta}</span></summary>')
        # pace column (left)
        if s.get("cells"):
            pace_col = (f'<p class="ssum">{html.escape(s["summary"])}</p>'
                        + _cells_table(s["cells"], "Their pace plan vs your teammates",
                                       lambda idx: cell_vision.get((i, "cells", idx))))
        else:
            pace_col = (f'<p class="ssum" style="color:#6b7280">Too few balls to compare a pace '
                        f'plan ({s["pace_balls"]} balls tracked).</p>')
        # spin column (right) — only where they faced enough spin
        spin_col = ""
        if s.get("spin_cells"):
            spin_col = ((f'<p class="ssum">{html.escape(s["spin_summary"])}</p>' if s.get("spin_summary") else "")
                        + _cells_table(s["spin_cells"], "Their spin plan vs your teammates",
                                       lambda idx: cell_vision.get((i, "spin_cells", idx))))
        elif s.get("spin_balls", 0) >= 40:
            spin_col = '<p class="ssum" style="color:#6b7280">Spin plan matched your teammates\'.</p>'
        body = [f'<div class="sgrid"><div>{pace_col}</div><div>{spin_col}</div></div>' if spin_col
                else pace_col]
        if s.get("dismissals"):
            body.append(_dismissals_table(s["dismissals"], vision.get(i)))
        op = " open" if i == 0 else ""
        parts.append(f'<details class="sblock2"{op}>{summ}<div class="sbody">{"".join(body)}</div></details>')
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
            bts = rec.get("bowl_types", [])
            chips = [f'<a class="pchip batting" href="{sl}-batting.html">Batting</a>']
            for bt in bts:
                lbl = "Bowling" if len(bts) == 1 else f"Bowling: {bt.capitalize()}"
                chips.append(f'<a class="pchip bowling" href="{sl}-bowling-{bt}.html">{lbl}</a>')
            items.append(
                f'<li><span class="rmain">'
                f'{_avatar(pid, "avatar", _initials(name), name=name)}'
                f'<span><b>{html.escape(name)}</b><span class="rr">{html.escape(role)}</span></span></span>'
                f'<span class="packchips">{"".join(chips)}</span></li>')
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


def _opp_roster(slug):
    """({bowler_id: (name, type)}, {batter_id: (name, hand)}) for the opposition, from the store.
    Used only as a roster + labels — no matchup numbers reach the player packs."""
    try:
        from cricket_core.config import project_path
        opp = slug.split("-")[0]
        p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{opp}.json")
        store = json.load(open(p, encoding="utf-8"))
        bowlers, batters = {}, {}
        for c in store.get("we_bat", []):
            bowlers.setdefault(c["bowler_id"], (c["bowler"], c.get("bowler_type", "")))
        for c in store.get("they_bat", []):
            batters.setdefault(c["batter_id"], (c["batter"], c.get("bat_hand", "")))
        return bowlers, batters
    except Exception:
        return {}, {}


def _scouting_urls(series_slug):
    """({bowler_id: {hand: url}}, {batter_id: url}) — the scouting reports in the assembled
    bundle. A bowler's report is HAND-SPECIFIC (how they bowl to LHB vs RHB), so it's keyed by
    the batter's hand; the batter reports are not hand-split. Only rendered reports map."""
    import glob
    bowl, bat = {}, {}
    for sc in glob.glob(os.path.join(HERE, "reports", "*.playlists.json")):
        base = os.path.basename(sc)[: -len(".playlists.json")]
        try:
            meta = json.load(open(sc, encoding="utf-8")).get("meta", {})
        except Exception:
            continue
        if "_bowling_" in base and meta.get("bowler_id"):
            hand = "lhb" if base.endswith("_lhb") else "rhb"
            grp = f"bowlers-vs-{hand}"
            # link the reduced PLAYER-MODE report (matchup verdicts stripped), not the coach cut
            variant = ".pmode.html" if os.path.exists(
                os.path.join(HERE, "reports", f"{base}.pmode.html")) else ".html"
            bowl.setdefault(str(meta["bowler_id"]), {})[hand] = \
                f"../scouting/{series_slug}/{grp}/{base}{variant}"
        elif "_batting_" in base and meta.get("batter_id"):
            bat[str(meta["batter_id"])] = f"../scouting/{series_slug}/batters/{base}.html"
    return bowl, bat


def _our_hands(slug):
    """{our_batter_id: 'lhb'/'rhb'} from the matchup store's we_bat rows."""
    try:
        from cricket_core.config import project_path
        opp = slug.split("-")[0]
        p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{opp}.json")
        store = json.load(open(p, encoding="utf-8"))
        out = {}
        for c in store.get("we_bat", []):
            h = str(c.get("bat_hand", "")).strip().upper()
            out[c["batter_id"]] = "lhb" if (h.startswith("L") or "LEFT" in h) else "rhb"
        return out
    except Exception:
        return {}


def _opp_card(bid, name, sub, facts, vision_href, h2h_row, h2h_verb, opp_vision=None, report_url=None):
    """A per-opponent card in a PLAYER report: the distilled 'what they're about' facts (type-scoped
    by the caller), a link to the reduced PLAYER-MODE report on this opponent, video of their stock
    ball + wicket balls, and neutral footage against them. NO good/poor matchup verdict."""
    opp_vision = opp_vision or {}
    rl = (f'<a class="rlink" href="{report_url}" onclick="event.stopPropagation()" '
          f'title="full report on {html.escape(name)}">report &rarr;</a>') if report_url else ""
    av = _avatar(bid, "bav", _initials(name), name=name)
    summ = (f'<summary>{av}<span class="bn"><b>{html.escape(name)}</b>'
            f'<span class="bt">{html.escape(sub or "")}</span></span>{rl}</summary>')
    lines = []
    if facts:
        lines.append('<ul class="afacts">' + "".join(f'<li>{html.escape(f)}</li>' for f in facts) + '</ul>')
    else:
        lines.append('<p class="cohort">Not enough data on this opponent yet.</p>')
    watch = []
    if opp_vision.get((bid, "stock")):
        watch.append(f'<a class="vwatch" href="{opp_vision[(bid, "stock")]}">&#9654; Stock ball</a>')
    if opp_vision.get((bid, "wicket")):
        watch.append(f'<a class="vwatch" href="{opp_vision[(bid, "wicket")]}">&#9654; Wicket balls</a>')
    if watch:
        lines.append('<p>' + " ".join(watch) + '</p>')
    if h2h_row:                                        # footage only — no runs/wickets (that reads
        fl = h2h_row.get("format_label", "Test")       # as a matchup verdict). Label the format so
        note = "" if fl == "Test" else f' <span class="cohort">({fl}, not Test)</span>'  # non-Test is clear
        met = f'{h2h_row["balls"]} balls of you {h2h_verb} them.{note}'
        if vision_href:
            met += f' <a class="vwatch" href="{vision_href}">&#9654; Watch</a>'
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
            if not r.get("clips"):
                continue
            them = r[them_key]
            key = f"{prefix}_{them}"                 # hbat_/hbowl_ so both directions coexist
            items = [playlist_item(d["delivery_id"], d["clip_stem"],
                                   caption=f'{d["date"][8:10]}-{d["date"][5:7]}-{d["date"][:4]} · '
                                           + (f'OUT {d["wicket"]}' if d["wicket"] else f'{d["runs"]} run{"s" if d["runs"] != 1 else ""}'))
                     for d in r["deliveries"] if d["clip_stem"]]
            if items:
                playlists[key] = items
                titles[key] = (f'{label} {name_of.get(them, them)} · {r["balls"]} balls '
                               f'({r.get("format_label", "Test")})')
    add(h2h.get("our_batting", []), "striker_id", "bowler_id", "hbat", "You v")
    add(h2h.get("our_bowling", []), "bowler_id", "striker_id", "hbowl", "You to")
    return playlists, titles


def _build_vision(dest_dir, page_slug, name, card, extra=None, opp_clips=None):
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
    # per-cell "where they went at you more" example playlists (pace + spin)
    cell_vision = {}
    for i, s in enumerate(card.get("series", []) if card else []):
        for fam, key_fam in (("cells", "p"), ("spin_cells", "s")):
            for idx, c in enumerate(s.get(fam, []) or []):
                if c.get("flag") != "more" or not c.get("examples"):
                    continue
                items = [playlist_item(e["delivery_id"], e["clip_stem"],
                                       caption=f'{c["label"]} — {s["opp"]}')
                         for e in c["examples"] if e.get("clip_stem")]
                if not items:
                    continue
                resolved, avail, _tot = resolve_playlist(items)
                if avail:
                    key = f"c{i}{key_fam}{idx}"
                    playlists[key] = resolved
                    titles[key] = f'{c["label"].capitalize()} — v {s["opp"]}'
                    cell_vision[(i, fam, idx)] = f"{page_slug}-vision.html#{key}"
    h2h_map = {}                                     # full key (hbat_/hbowl_) -> href
    for key, items in (extra[0] if extra else {}).items():
        resolved, avail, _tot = resolve_playlist(items)
        if avail:
            playlists[key] = resolved
            titles[key] = extra[1][key]
            href = f"{page_slug}-vision.html#{key}"
            h2h_links.append((href, extra[1][key]))
            h2h_map[key] = href
    # each opposition bowler's own stock ball + wicket balls (their deliveries, not the h2h)
    opp_vision = {}
    for bid, clips in (opp_clips or {}).items():
        for kind, kk, tit in (("stock", "stock", "Stock ball"), ("wicket", "wkt", "Wicket balls")):
            stems = clips.get(kind) or []
            items = [playlist_item(e["delivery_id"], e["clip_stem"], caption=tit)
                     for e in stems if e.get("clip_stem")]
            if not items:
                continue
            resolved, avail, _tot = resolve_playlist(items)
            if avail:
                key = f"{kk}_{bid}"
                playlists[key] = resolved
                titles[key] = tit
                opp_vision[(bid, kind)] = f"{page_slug}-vision.html#{key}"
    if playlists:
        build_player_html(playlists, os.path.join(dest_dir, f"{page_slug}-vision.html"),
                          title=f"{name} — vision", subtitle="dismissals + head-to-head",
                          titles=titles)
    return hrefs, h2h_links, h2h_map, cell_vision, opp_vision


def _report_top(pid, name, role, sname, pages=None, current=None):
    """Shared header: avatar, name, role, and a tab per report page (Batting, Bowling: Pace, …).
    `pages` = [(label, href), …]; `current` = the active href."""
    tabs = ""
    if pages and len(pages) > 1:
        parts = [(f'<span class="rtab on">{html.escape(lbl)}</span>' if href == current
                  else f'<a class="rtab" href="{href}">{html.escape(lbl)}</a>')
                 for lbl, href in pages]
        tabs = f'<div class="rtabs">{"".join(parts)}</div>'
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
                  opp_bowlers=None, about=None, report_urls=None, h2h_map=None, h2h_rows=None,
                  pages=None, current=None, hand="rhb", cell_vision=None, opp_vision=None):
    """Batting pack: (1) how previous attacks bowled to you, (2) the opposition attack — one card
    per bowler with the distilled facts + a link to the hand-correct report + your footage."""
    name, role = rec.get("name", pid), rec.get("role", "")
    opp = _short_opp(meta)
    about = about or {}
    report_urls = report_urls or {}
    h2h_map = h2h_map or {}
    h2h_rows = h2h_rows or {}
    handword = "left-handers" if hand == "lhb" else "right-handers"
    body = [EXTRA_CSS, _report_top(pid, name, role, meta.get("name", ""), pages, current)]

    body.append(_pack_section("How previous attacks have bowled to you",
                              "The opposition's trends to you over your last few series.",
                              inner=_attack_card_html(card, opp, vision, cell_vision)))
    if opp_bowlers:
        ordered = sorted(opp_bowlers.items(),
                         key=lambda kv: -(about.get(kv[0], {}).get("order", 0)))[:N_OPP]
        blocks = [_opp_card(bid, nm, ty, (about.get(bid) or {}).get("facts"),
                            h2h_map.get(f"hbat_{bid}"), h2h_rows.get((pid, bid)), "facing",
                            opp_vision=opp_vision, report_url=report_urls.get(bid))
                  for bid, (nm, ty) in ordered]
        body.append(_pack_section(f"The {opp} attack",
                                  "Tap a bowler for what they're about, the fuller report, and any "
                                  "footage of you facing them.", inner="".join(blocks)))
    body.append(_pack_section(f"Your vision vs {opp}",
                              "Your most recent balls facing each of their bowlers — Test where you've "
                              "met, otherwise your ODI / T20 footage (the format is labelled).",
                              inner=_vision_list(h2h_links, "hbat", had_meetings, "facing"),
                              open=False))
    return "".join(body)


def _bowling_body(meta, pid, rec, opp_batters=None, about=None, report_urls=None, h2h_links=None,
                  had_meetings=False, h2h_map=None, h2h_rows=None, pages=None, current=None,
                  btype="pace"):
    """Bowling pack, SCOPED to one bowling type (pace or spin): one card per opposition batter,
    showing only how they play THAT type + footage of you bowling to them."""
    name, role = rec.get("name", pid), rec.get("role", "")
    opp = _short_opp(meta)
    about = about or {}
    report_urls = report_urls or {}
    h2h_map = h2h_map or {}
    h2h_rows = h2h_rows or {}
    tw = "spin" if btype == "spin" else "pace"
    body = [EXTRA_CSS, _report_top(pid, name, role, meta.get("name", ""), pages, current)]

    if opp_batters:
        ordered = sorted(opp_batters.items(),
                         key=lambda kv: -(about.get(kv[0], {}).get("order", 0)))[:N_OPP]
        blocks = [_opp_card(bid, nm, hand, (about.get(bid) or {}).get(f"facts_{tw}"),
                            h2h_map.get(f"hbowl_{bid}"), h2h_rows.get((pid, bid)), "bowling to")
                  for bid, (nm, hand) in ordered]
        body.append(_pack_section(f"The {opp} batters — bowling {tw}",
                                  f"How each of them plays {tw}, plus any footage of you bowling to "
                                  "them. Tap a batter.", inner="".join(blocks)))
    body.append(_pack_section(f"Your vision vs {opp}",
                              "Your most recent balls bowling to each of their batters — Test where "
                              "you've met, otherwise your ODI / T20 footage (the format is labelled).",
                              inner=_vision_list(h2h_links, "hbowl", had_meetings, "bowling to"),
                              open=False))
    return "".join(body)


def _load_about(slug):
    opp = slug.split("-")[0]
    p = os.path.join(HERE, "data", f"opponent_about_{opp}.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    return {**d.get("bowlers", {}), **d.get("batters", {})}   # keyed by opponent id


def build(out_dir, no_video=False, only=None):
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

    if not no_video:                                   # prime a long read SAS so vision links don't
        try:                                           # die after the default 6 h (was the bug)
            from cricket_core.video import get_fairplay_sas
            get_fairplay_sas(ttl_hours=156)
        except Exception as e:
            print(f"  ! SAS prime failed ({e}) — vision links may be short-lived")

    slugs = list(squads.keys())
    single = len(slugs) == 1

    for slug in slugs:
        meta = squads[slug]
        roster = [(pid, players.get(pid, {"name": pid, "role": "Unknown", "packs": ["batting"]}))
                  for pid in meta.get("players", []) if not only or pid in only]
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
        opp_bowlers, opp_batters = _opp_roster(slug)  # {id: (name, type/hand)}
        about = _load_about(slug)                      # distilled facts, keyed by opponent id
        # stock-ball + wicket-ball example clips for the bowlers shown in the batting packs (N_OPP)
        _bord = sorted((opp_bowlers or {}).items(),
                       key=lambda kv: -(about.get(kv[0], {}).get("order", 0)))[:N_OPP]
        opp_clips = {bid: {"stock": (about.get(bid) or {}).get("stock_clips") or [],
                           "wicket": (about.get(bid) or {}).get("wicket_clips") or []}
                     for bid, _ in _bord}
        bowl_urls, bat_urls = _scouting_urls(slug)     # {bowler:{hand:url}}, {batter:url}
        our_hands = _our_hands(slug)                   # our_batter_id -> lhb/rhb
        # h2h counts kept per DIRECTION — an all-rounder can both face and bowl to the same
        # opponent, so a single (me, them) dict would collide (wrong count vs a correct video).
        bat_rows = {(r["striker_id"], r["bowler_id"]): r for r in (h2h or {}).get("our_batting", [])}
        bowl_rows = {(r["bowler_id"], r["striker_id"]): r for r in (h2h or {}).get("our_bowling", [])}
        # copy opposition photos (bowlers + batters)
        if IMG_MODE == "file":
            import shutil
            for oid, (onm, _t) in list(opp_bowlers.items()) + list(opp_batters.items()):
                if str(oid) in _SITE_IMGS:
                    continue
                p = get_photo_path(oid, fmt="test", name=onm)
                if p:
                    shutil.copy(p, os.path.join(s_dir, "img", f"{oid}.png"))
                    _SITE_IMGS.add(str(oid))
        for pid, rec in roster:
            name = rec.get("name", pid)
            if only and pid not in only:               # prototype: build a chosen few
                continue
            pslug = _slug(name)
            bts = rec.get("bowl_types", [])            # [] for a batter, [pace]/[spin]/[pace,spin]
            vision, h2h_links, h2h_map, cell_vision, opp_vision = {}, [], {}, {}, {}
            extra = _h2h_playlists(h2h, pid, players, opp_names) if h2h else ({}, {})
            had_bat = bool(h2h and any(r["striker_id"] == pid for r in h2h.get("our_batting", [])))
            had_bowl = bool(h2h and any(r["bowler_id"] == pid for r in h2h.get("our_bowling", [])))
            # a batter's page shows the opposition-bowler stock/wicket clips even with no h2h footage
            is_batter = not rec.get("bowl_types")
            if not no_video and (cards.get(pid) or extra[0] or (is_batter and opp_clips)):
                try:
                    vision, h2h_links, h2h_map, cell_vision, opp_vision = _build_vision(
                        s_dir, pslug, name, cards.get(pid), extra,
                        opp_clips=opp_clips if is_batter else None)
                except Exception as e:
                    print(f"  ! vision for {name}: {type(e).__name__}: {e}")
            # tab list: Batting + one page per bowling type
            bat_href = f"{pslug}-batting.html"
            pages = [("Batting", bat_href)]
            for bt in bts:
                lbl = "Bowling" if len(bts) == 1 else f"Bowling: {bt.capitalize()}"
                pages.append((lbl, f"{pslug}-bowling-{bt}.html"))
            hand = our_hands.get(pid, "rhb")           # link the bowler report for THIS hand
            bat_report = {bid: hmap.get(hand) for bid, hmap in bowl_urls.items() if hmap.get(hand)}
            open(os.path.join(s_dir, bat_href), "w", encoding="utf-8").write(
                _page(f"{name} — batting",
                      _batting_body(meta, pid, rec, cards.get(pid), vision, h2h_links, had_bat,
                                    opp_bowlers=opp_bowlers, about=about, report_urls=bat_report,
                                    h2h_map=h2h_map, h2h_rows=bat_rows,
                                    pages=pages, current=bat_href, hand=hand, cell_vision=cell_vision,
                                    opp_vision=opp_vision),
                      up=("index.html", "Squad")))
            for bt in bts:
                bowl_href = f"{pslug}-bowling-{bt}.html"
                open(os.path.join(s_dir, bowl_href), "w", encoding="utf-8").write(
                    _page(f"{name} — bowling ({bt})",
                          _bowling_body(meta, pid, rec, opp_batters=opp_batters, about=about,
                                        report_urls=bat_urls, h2h_links=h2h_links,
                                        had_meetings=had_bowl, h2h_map=h2h_map, h2h_rows=bowl_rows,
                                        pages=pages, current=bowl_href, btype=bt),
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
    ap.add_argument("--only", nargs="*", help="build only these player ids (prototype)")
    args = ap.parse_args()
    build(os.path.join(HERE, args.out), no_video=args.no_video,
          only=set(args.only) if args.only else None)


if __name__ == "__main__":
    main()
