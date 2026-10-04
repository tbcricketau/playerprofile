"""build_coach_site.py — the coach view: their squad, and the FULL report for each of them.

Step 1 of `coachhub/docs/REPLACEMENT_PLAN.md` §6. It builds the one thing coaches open the gated
site for — *browse the opposition's dossiers for this series* — into the packs bundle, so the same
app serves both sides of the fixture.

    .\\venv\\Scripts\\python.exe build_coach_site.py --slug south-africa-odi-away-2026

Output (inside the bundle, under `coach/`):

    coach/index.html                     the series list
    coach/<slug>/index.html              their squad: bowlers and batters, tier-grouped
    coach/<slug>/reports/<base>.html     the COACH cut of each report
    coach/<slug>/reports/<base>.player.html + .clips.json

⚠ THE COACH CUT IS A DIFFERENT RENDER, NOT A STRIPPED PAGE — and the plan said otherwise.
§5 proposed "the same page with the coach sections withheld server-side". It cannot be done that
way without regex-cutting three `<h2>` blocks that carry no id or class: `Vs Our Squad`
(report.py), `How Attacks Bowl To Them` and `Our Best Options` (batting_report.py). The coach
content is never in the player-mode bytes — both builders render the template twice, with
`vs_squad=None` / `sim_options=None` / `attacked=None` — and player mode is not even a strict
subset, because a player-mode batting report *adds back* the fingerprint cards that the lean coach
exploit cut hides (`show_fp`). So a server-side strip would be both fragile and wrong.

What replaces it: both renders already exist, and the app CHOOSES THE FILE BY ROLE. The rule stays
one place and server-side, it just selects rather than edits. Everything under `coach/` is
coach-only, which is a path prefix an app can refuse in one line — see `playerpacks/app.py`.

⚠ AND IT MUST NEVER REACH GITHUB PAGES. The `aus` bundle publishes to a PUBLIC Pages site as well
as to the app, so a coach directory sitting in it would be served to anyone with the link, with no
sign-in at all. `assemble_packs` adds `coach/` only when asked, and `publish_packs` refuses a
GitHub push of any bundle that contains it.
"""
import argparse
import html as _html
import json
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

from publish_site import (_bake_report, _sidecar_map, _fmt_key, _level_key,
                          DEFAULT_SAS_HOURS, _LEVEL_DIRS)
import site_render as SR

HERE = os.path.dirname(os.path.abspath(__file__))
SERIES_JSON = os.path.join(HERE, "series.json")
DATA = os.path.join(HERE, "data")


def _series(slug):
    cfg = json.load(open(SERIES_JSON, encoding="utf-8"))
    for s in cfg.get("series", []):
        if s.get("slug") == slug:
            return s
    raise SystemExit(f"{slug} is not in series.json — nothing to build a coach view from")


def _fmt_level(entry):
    """Format and level for a series. Carried at the series level on newer entries and on the
    GROUP on older ones (the South Africa ODI entry has it only on its bowlers group), so read
    both rather than defaulting to Test and silently baking the wrong report."""
    fmt = entry.get("format")
    level = entry.get("level")
    for g in entry.get("groups", []):
        fmt = fmt or g.get("format")
        level = level or g.get("level")
    return _fmt_key(fmt or "Test"), _level_key(level or "international")


def _tiers(entry):
    """{player id: tier} from series.json — the one thing it adds that nothing else carries. The
    group reports tier the bowlers; the entry's `tiers` map covers the whole squad, batters
    included (30-09-2026). A player in neither prints no chip rather than a guessed one."""
    out = {str(k): str(v) for k, v in (entry.get("tiers") or {}).items() if v}
    for g in entry.get("groups", []):
        for r in g.get("reports", []):
            if r.get("id") and r.get("tier"):
                out[str(r["id"])] = str(r["tier"])
    return out


def _opp_key(slug):
    try:
        from squads import opp_key
        return opp_key(slug)
    except Exception:
        return str(slug).split("-")[0]


def _about(slug):
    """(bowlers, batters) from opponent_about — the roster the packs already build from, so the
    coach view cannot name a different squad from the one the packs show."""
    p = os.path.join(DATA, f"opponent_about_{_opp_key(slug)}.json")
    if not os.path.exists(p):
        raise SystemExit(f"no opposition data: {os.path.relpath(p, HERE)} "
                         f"— run build_opponent_about.py first")
    d = json.load(open(p, encoding="utf-8"))
    return d.get("bowlers") or {}, d.get("batters") or {}


def _photo(pid, name, fmt, img_dir):
    """Write the headshot beside the page and return a relative href.

    A data URI would be simpler and is what a pack card uses, but there it is one photo on one
    player's page. Here it is the whole squad on one index: inlined, the South Africa page came
    out at 3.8 MB for 19 headshots. As files they are fetched in parallel, cached per photo across
    every series that names the player, and the index is a few tens of KB."""
    try:
        from photos import get_photo_bytes, _mime
        data = get_photo_bytes(pid, fmt=fmt, name=name)
    except Exception:
        return None
    if not data:
        return None
    ext = {"image/png": ".png", "image/jpeg": ".jpg"}.get(_mime(data), ".png")
    os.makedirs(img_dir, exist_ok=True)
    open(os.path.join(img_dir, f"{pid}{ext}"), "wb").write(data)
    return f"img/{pid}{ext}"


def _initials(name):
    bits = [b for b in re.split(r"[\s.-]+", str(name or "")) if b]
    return (bits[0][:1] + bits[-1][:1]).upper() if bits else "?"


def _pick(smap, pid, kind, fmt, level):
    """The report render for one opposition player: (src_dir, base) or None.

    Prefers the combined report against all batters ('' group, 'all' hand). A Test bowling report
    is rendered per hand, so fall back to whichever hand exists rather than reporting the player
    has no report at all — the coach cut of one hand beats no dossier."""
    for hand in ("all", "lhb", "rhb"):
        hit = smap.get((str(pid), hand, kind, "", fmt, level))
        if hit:
            return hit
    return None


# ── the plan packs: one for pace, one for spin (Tom, 04-10-2026) ──────────────────────────────
# Each pack is one page with a technique switch in place of a page per bowling type: South Africa's
# record against pace is 87% right-arm, and the Pace and Right-arm pace pages gave the same plan for
# 8 of 12 batters. The sub-type stays a click away on the same page. Groups are listed only when
# their overview exists for the series. The "All pace / All spin" option went too (Tom, 04-10-2026):
# with the sub-types side by side it only repeated them, so a pack opens on its first technique.
_PACKS = {"pace": ("Pace", "pace", ["right_pace", "left_pace"]),
          "spin": ("Spin", "spin", ["off_spin", "left_orthodox", "leg_spin", "left_unorthodox"])}
_SWITCH = {"pace": ("All pace", "right- and left-arm"), "spin": ("All spin", "every type"),
           "right_pace": ("Right-arm", ""), "left_pace": ("Left-arm", ""), "off_spin": ("Off spin", ""),
           "left_orthodox": ("Left-arm orthodox", ""), "leg_spin": ("Leg spin", ""),
           "left_unorthodox": ("Left-arm wrist spin", "")}
PACK_JS = os.path.join(HERE, "coach_pack.js")


def _file_version(path):
    """A file's content hash, for the URL that loads it: a changed script gets a new URL, so no
    browser can run yesterday's copy against today's page (04-10-2026)."""
    import hashlib
    try:
        return hashlib.sha1(open(path, "rb").read()).hexdigest()[:10]
    except OSError:
        return "0"


def _fields_js_version():
    """The field planner's script, as the playerpacks app serves it (sibling clone). It must match
    `fieldplanner.script_version()` to share the browser's cached copy; a mismatch only costs a
    second download, never a stale script."""
    return _file_version(os.path.join(HERE, "..", "playerpacks", "static", "fields.js"))


def _overview(slug, group):
    p = os.path.join(DATA, f"overview_{group}_{_opp_key(slug)}.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def _nav(slug, have, planner):
    """The two rows of tabs (Tom, 04-10-2026): [(side, label, [(key, label, href)])] — Batting plans
    (their bowlers, for our batters) and Bowling plans (their batters, for our bowlers), each with
    only the pages this build produced. The planner's own page reads the same rows from nav.json."""
    base = f"/coach/{slug}"
    bat = [("bowlers", "Their bowlers", f"{base}/batting/index.html")]
    if planner and have.get("bowler_plans"):
        bat.append(("bfields", "Set Field Plans", f"/fields/{planner}/?pack=vs_rhb"))
    if "matchups.html" in have:
        bat.append(("matchups", "Match-ups", f"{base}/plans/matchups.html"))
    bowl = [(key, label, f"{base}/plans/{key}.html") for key, label in (("pace", "Pace"), ("spin", "Spin")) if key in have]
    if planner:
        bowl.append(("fields", "Set Field Plans", f"/fields/{planner}/"))
    if "shot-matrix.html" in have:
        bowl.append(("shots", "Unorthodox shots", f"{base}/plans/shot-matrix.html"))
    return [("bat", "Batting plans", bat), ("bowl", "Bowling plans", bowl)]


# ── Batting plans: their bowlers, a card each, switched by our batter's hand ──────────────────────
BOWLERS_JS = os.path.join(HERE, "coach_bowlers.js")
_REELS = (("stock", "Stock ball"), ("wicket", "Wicket balls"), ("new_ball", "New ball"))


def _bowler_plans(slug):
    p = os.path.join(DATA, f"bowler_plans_{_opp_key(slug)}.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def _bowler_vision(root, bid, name, about):
    """One vision page per bowler with their reels to each hand — stock ball, wicket balls, new
    ball — keyed stockR, wktL and so on for the card's buttons. Returns {hand: {kind: n clips}}."""
    from cricket_core.video import build_player_html, playlist_item, resolve_playlist
    keys = {"stock": "stock", "wicket": "wkt", "new_ball": "nb"}
    playlists, titles, counts = {}, {}, {"RHB": {}, "LHB": {}}
    for h, word in (("RHB", "right-handers"), ("LHB", "left-handers")):
        for kind, title in _REELS:
            clips = [e for e in (about.get(f"{kind}_clips_{h.lower()}") or []) if e.get("clip_stem") or e.get("url")]
            if not clips:
                continue
            items = []
            for i, e in enumerate(clips):
                it = playlist_item(e.get("delivery_id"), e.get("clip_stem"), caption=f"{title} to {word} · {i + 1} of {len(clips)}")
                if not e.get("clip_stem") and e.get("url"):
                    it["url"] = e["url"]
                items.append(it)
            resolved, avail, _n = resolve_playlist(items)
            if avail:
                key = keys[kind] + h[0]
                playlists[key] = resolved
                titles[key] = f"{title} to {word}"
                counts[h][kind] = avail
    if playlists:
        os.makedirs(os.path.join(root, "vision"), exist_ok=True)
        build_player_html(playlists, os.path.join(root, "vision", f"{bid}.html"), title=name,
                          subtitle="Their deliveries to each hand", titles=titles)
    return counts if playlists else {}


def _bowlers_page(slug, root, entry, plans, about, tiers, heads, reports, planner):
    """batting/index.html: a card per bowler for the chosen hand — how to play them, the coaches'
    notes, the figures, their reels and report, and the field they are likely to set by category.
    The cards are drawn by coach_bowlers.js from window.BK; the planner's notes and saved fields
    arrive when the page opens, as on the Pace and Spin packs."""
    out, n_vis = [], 0
    order = sorted(plans["bowlers"].items(),
                   key=lambda kv: (-int(kv[1].get("order") or 0), kv[1].get("name") or ""))
    for bid, b in order:
        if b.get("error"):
            continue
        tier = tiers.get(bid, b.get("tier") or "")
        reels = _bowler_vision(root, bid, b["name"], about.get(bid) or {})
        n_vis += bool(reels)
        out.append({"id": bid, "name": b["name"], "type": b.get("type") or "", "pace": bool(b.get("pace")),
                    "tier": tier, "chip": SR.TIER_CHIP.get(tier, ""), "initials": _initials(b["name"]),
                    "head": ("../" + heads[bid]) if heads.get(bid) else "",
                    "report": f"../reports/{reports[bid]}.html" if reports.get(bid) else "",
                    "vision": f"../vision/{bid}.html" if reels else "", "reels": reels,
                    "hands": b["hands"]})
    tot = {h: sum((b["hands"].get(h) or {}).get("n_balls") or 0 for b in out) for h in ("RHB", "LHB")}
    data = {"series": entry.get("name") or slug, "planner": planner, "minBalls": 120,
            "hands": [{"key": "RHB", "label": "vs right-handers", "page": "vs_rhb", "balls": tot["RHB"]},
                      {"key": "LHB", "label": "vs left-handers", "page": "vs_lhb", "balls": tot["LHB"]}],
            "bowlers": out}
    seg = "".join(f'<button type="button" data-h="{h["key"]}"{" class=\"on\"" if k == 0 else ""}>{h["label"]}'
                  f'<small>{h["balls"]:,} balls from their {len(out)} bowlers</small></button>'
                  for k, h in enumerate(data["hands"]))
    who = entry.get("target_country") or "the opposition"
    lead = (f"How {_html.escape(who)}'s bowlers go at each hand, how to play them, and the field they are "
            "likely to set. Same numbers as each bowler's own report.")
    body = (f"<h1>Their bowlers</h1><p class=\"lead\">{lead}</p>"
            f'<div class="seg" role="tablist" aria-label="Batter\'s hand">{seg}</div><div id="bk-cards"></div>'
            f"<script>window.BK={json.dumps(data, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')};</script>"
            f'<script src="/static/fields.js?v={_fields_js_version()}"></script>'
            f'<script src="/coach/bowlers.js?v={_file_version(BOWLERS_JS)}"></script>')
    print(f"  their bowlers: {len(out)} cards, vision for {n_vis}")
    return body


def _overview_page(title, lead, sides, n_bowlers, n_batters):
    """index.html: the series on one screen — the two sides as large links (Tom, 04-10-2026)."""
    def card(side, kind, head, desc):
        items = next((i for k, _l, i in sides if k == side), [])
        if not items:
            return ""
        pages = " · ".join(_html.escape(lab) for _k, lab, _h in items)
        return (f'<a href="{_html.escape(items[0][2])}"><span class="k">{kind}</span><b>{head}</b>'
                f'<span class="d">{desc}</span><span class="pg">{pages}</span></a>')
    bowl_desc = (f"The plan for each of their {n_batters} batters against pace and spin, the figures behind "
                 "it, and our fields — auto-generated, or set by the coaches.")
    bat_desc = (f"How each of their {n_bowlers} bowlers goes at right- and left-handers, how to play them, "
                "and the field they are likely to set — new ball, old ball, bouncer plan.")
    return (f"<h1>{_html.escape(title)}</h1>" + (f'<p class="lead">{_html.escape(lead)}</p>' if lead else "")
            + '<div class="sides">' + card("bat", "Batting plans", "Their bowlers", bat_desc)
            + card("bowl", "Bowling plans", "Their batters", bowl_desc) + "</div>")


def _pack_page(slug, root, pack, entry, batters, tiers, smap, fmt, level, planner, heads):
    """Write plans/<pack>.html from the group overviews. Returns False when the series has no
    overview for the pack's macro group (a white-ball squad with no spin plan, say)."""
    title, macro, sub_keys = _PACKS[pack]
    groups = [(g, d) for g, d in ((g, _overview(slug, g)) for g in sub_keys) if d]
    if not groups:
        return False
    min_balls = groups[0][1].get("min_balls", 150)
    rows = {g: {r["bid"]: r for r in d["rows"]} for g, d in groups}
    whole = _overview(slug, macro)            # only for each technique's share of the balls
    whole_rows = {r["bid"]: r for r in whole["rows"]} if whole else {}
    long_label = {g: d.get("label") or g for g, d in groups}
    # the overview's own order: `order` is the career record, largest first
    order = sorted(batters.items(), key=lambda kv: (-int(kv[1].get("order") or 0), kv[1].get("name") or ""))
    out = []
    for pid, meta in order:
        pid = str(pid)
        name = meta.get("name") or pid
        base = whole_rows.get(pid) or next((rows[g][pid] for g, _d in groups if pid in rows[g]), {})
        sub = (base.get("sub") or meta.get("hand") or "").split(" · ")
        hand, role = sub[0], (sub[1] if len(sub) > 1 else (meta.get("role") or ""))
        hit = _pick(smap, pid, "batting", fmt, level)
        report = vision = ""
        if hit:
            b = hit[1]
            if os.path.exists(os.path.join(root, "reports", f"{b}.html")):
                report = f"../reports/{b}.html"
            if os.path.exists(os.path.join(root, "reports", f"{b}.player.html")):
                vision = f"../reports/{b}.player.html"
        per = {}
        for g, _d in groups:
            r = rows[g].get(pid)
            if not r:
                continue
            plan = re.sub(r"^Plan for [^:]+: ", "", r.get("plan") or "")
            per[g] = {"balls": r.get("balls") or 0, "plan": (plan[:1].upper() + plan[1:]) if plan else "",
                      "field": r.get("field"), "threat": r.get("threat"), "error": bool(r.get("error")),
                      "fields": [{"label": f["label"].replace(" — ", " · "), "fielders": f.get("fielders") or [],
                                  "spare": f.get("spare"), "spare_name": f.get("spare_name") or ""}
                                 for f in (r.get("fields") or [])]}
        tier = tiers.get(pid, "")
        out.append({"id": pid, "name": name, "hand": hand, "role": role, "tier": tier,
                    "chip": SR.TIER_CHIP.get(tier, ""), "initials": _initials(name),
                    "head": ("../" + heads[pid]) if heads.get(pid) else "", "report": report, "vision": vision,
                    "groups": per})
    data = {"pack": pack, "label": title, "series": entry.get("name") or slug, "planner": planner,
            "minBalls": min_balls,
            "groups": [{"key": g, "label": _SWITCH.get(g, (g, ""))[0], "long": long_label[g],
                        "balls": sum((rows[g].get(b["id"]) or {}).get("balls") or 0 for b in out)}
                       for g, _d in groups],
            "batters": out}
    all_balls = (sum((whole_rows.get(b["id"]) or {}).get("balls") or 0 for b in out)
                 or sum(g["balls"] for g in data["groups"]) or 1)

    def seg_button(k, g):
        small = f"{g['balls']:,} balls · {round(g['balls'] / all_balls * 100)}% of their {pack}"
        on = ' class="on"' if k == 0 else ""
        return (f'<button type="button" data-g="{_html.escape(g["key"])}"{on}>{_html.escape(g["label"])}'
                f'<small>{_html.escape(small)}</small></button>')
    seg = "".join(seg_button(k, g) for k, g in enumerate(data["groups"]))
    lead = (f"The plan against {pack} for every {_html.escape(entry.get('target_country') or 'opposition')} batter, "
            "the field it implies, and the coaches' field where one is set. Same numbers as each batter's own report.")
    body = (f"<h1>{_html.escape(title)}</h1><p class=\"lead\">{lead}</p>"
            f'<div class="seg" role="tablist" aria-label="Bowling technique">{seg}</div><div id="pk-cards"></div>'
            f"<script>window.PK={json.dumps(data, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')};</script>"
            f'<script src="/static/fields.js?v={_fields_js_version()}"></script>'
            f'<script src="/coach/pack.js?v={_file_version(PACK_JS)}"></script>')
    return body


def build(slug, out, sas_hours=DEFAULT_SAS_HOURS):
    entry = _series(slug)
    fmt, level = _fmt_level(entry)
    tiers = _tiers(entry)
    bowlers, batters = _about(slug)
    smap = _sidecar_map()
    planner = entry.get("planner_series") or ""        # the field planner's key for this series

    try:
        from publish_site import get_hawkeye_sas
        hk_sas = get_hawkeye_sas(ttl_hours=min(sas_hours, 167))
    except Exception as e:
        print(f"  (no hawkeye SAS: {type(e).__name__}) — baking without a video refresh")
        hk_sas = ""

    root = os.path.join(out, "coach", slug)
    reports = os.path.join(root, "reports")
    os.makedirs(reports, exist_ok=True)

    n_baked, missing = 0, []
    # Which kinds actually carry something a player is not shown. Measured per report rather than
    # asserted: an ODI/T20 BOWLING report has no coach-only section at all, so its player-mode cut
    # is byte-identical, and a page claiming the coach sees the simulated match-ups would be wrong
    # for nine of this squad's nineteen reports.
    coach_only = set()
    heads = {}                    # player id -> headshot href, shared by the grid and the packs
    report_of = {}                # bowler id -> report base, for the Their bowlers cards
    tiles = {t: [] for t, _h, _c in SR.TIER_META}
    tiles[""] = []

    # Both kinds are baked: the bowlers for the grid on this page, the batters for the cards in
    # the Pace and Spin packs, which carry each batter's report link (Tom, 04-10-2026 — the
    # batters' own list came off this page, since the packs show every one of them).
    for kind, people in (("bowling", bowlers), ("batting", batters)):
        ordered = sorted(people.items(),
                         key=lambda kv: (int(kv[1].get("order") or 99), kv[1].get("name") or ""))
        for pid, meta in ordered:
            name = meta.get("name") or pid
            heads.setdefault(str(pid), _photo(pid, name, fmt, os.path.join(root, "img")))
            hit = _pick(smap, pid, kind, fmt, level)
            if not hit:
                missing.append(f"{name} ({kind})")
                continue
            src_dir, base = hit
            baked = _bake_report(base, reports, hk_sas, src_dir=src_dir)
            if not baked:
                missing.append(f"{name} ({kind}, no render in {os.path.relpath(src_dir, HERE)})")
                continue
            n_baked += 1
            _nat, btype, has_pdf, _pid = baked
            pm = os.path.join(reports, f"{base}.pmode.html")
            if os.path.exists(pm) and (open(pm, "rb").read()
                                       != open(os.path.join(reports, f"{base}.html"), "rb").read()):
                coach_only.add(kind)
            if kind == "bowling":
                report_of[str(pid)] = base
                tier = tiers.get(str(pid), "")
                tiles.setdefault(tier, []).append(SR.bowler_tile(
                    name, btype or meta.get("type") or "Bowler", f"../reports/{base}.html",
                    badge=SR.TIER_CHIP.get(tier), badge_class=tier or "squad",
                    photo=("../" + heads[str(pid)]) if heads.get(str(pid)) else None, initials=_initials(name)))

    if not any(tiles.values()):
        raise SystemExit(f"no reports resolved for {slug} at {fmt}/{level} — nothing to serve")

    # the plan pages, and the two rows of tabs every page of the series carries
    title = entry.get("name") or slug
    have = _plans(slug, root, entry, batters, tiers, smap, fmt, level, planner, heads)
    plans = _bowler_plans(slug)
    have["bowler_plans"] = bool(plans)
    sides = _nav(slug, have, planner)
    nav_for = lambda side, key: SR.series_nav(sides, side, key)        # noqa: E731
    crumb = [("/coach/index.html", "Scouting"), (f"/coach/{slug}/index.html", title)]
    if any(k in have for k in ("pace", "spin")):
        shutil_copy(PACK_JS, os.path.join(out, "coach", "pack.js"))
    for f, side, key in (("matchups.html", "bat", "matchups"), ("shot-matrix.html", "bowl", "shots")):
        if f in have:
            _insert_tabs(os.path.join(root, "plans", f), nav_for(side, key))
    for key in ("pace", "spin"):
        if key in have:
            open(os.path.join(root, "plans", f"{key}.html"), "w", encoding="utf-8").write(
                SR.page(f"{_PACKS[key][0]} — {title}", have[key], up=crumb, tabs=nav_for("bowl", key), wide=True))

    # Batting plans → Their bowlers: the cards where the bowler plans are built, else the grid
    os.makedirs(os.path.join(root, "batting"), exist_ok=True)
    if plans:
        shutil_copy(BOWLERS_JS, os.path.join(out, "coach", "bowlers.js"))
        body = _bowlers_page(slug, root, entry, plans, bowlers, tiers, heads, report_of, planner)
    else:
        print(f"  no bowler plans (data/bowler_plans_{_opp_key(slug)}.json) — Their bowlers is the report grid")
        note = ("The coach report on each of them"
                + (", with how they match up against our squad, which a player is not shown."
                   if "bowling" in coach_only else "."))
        grid = []
        for tier, head, _chip in SR.TIER_META:
            if tiles.get(tier):
                grid.append(SR.group_heading(head, len(tiles[tier]), tier))
                grid.append('<ul class="bgrid">' + "".join(tiles[tier]) + "</ul>")
        if tiles.get(""):
            grid.append(SR.group_heading("Their bowlers", len(tiles[""])))
            grid.append('<ul class="bgrid">' + "".join(tiles[""]) + "</ul>")
        body = f'<h1>Their bowlers</h1><p class="lead">{note}</p>' + "".join(grid)
    open(os.path.join(root, "batting", "index.html"), "w", encoding="utf-8").write(
        SR.page(f"Their bowlers — {title}", body, up=crumb, tabs=nav_for("bat", "bowlers"), wide=True))

    # the series' own page: an overview with the two sides as large links (Tom, 04-10-2026)
    body = _overview_page(title, entry.get("subtitle") or "", sides, len(bowlers), len(batters))
    open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(
        SR.page(title, body, up=("/coach/index.html", "Scouting"), tabs=nav_for(None, None)))
    # the same rows for the field planner's page, which the app renders itself
    json.dump({"series": title, "index": f"/coach/{slug}/index.html",
               "sides": [{"key": s, "label": lab, "pages": [{"key": k, "label": l, "href": h} for k, l, h in items]}
                         for s, lab, items in sides]},
              open(os.path.join(root, "nav.json"), "w", encoding="utf-8"), indent=1)

    # PDFs are retired (Tom, 25-09) and nothing here links one, but `_bake_report` copies a
    # `<name>.pdf` whenever it finds one beside the render — 11 MB of the South Africa build, all
    # of it unreachable. Dropped here rather than in `_bake_report`, which the live coach site
    # still calls and which is not this step's to change.
    n_pdf = 0
    for f in os.listdir(reports):
        if f.endswith(".pdf"):
            os.remove(os.path.join(reports, f))
            n_pdf += 1

    _write_index(out)
    if n_pdf:
        print(f"  dropped {n_pdf} unreferenced PDF(s) — retired 25-09")
    for m in missing:
        print(f"  ! no report for {m}")
    print(f"coach view: {n_baked} report(s) baked -> {os.path.relpath(root, HERE)}"
          + (f" · {len(missing)} player(s) without one" if missing else ""))
    return n_baked, missing


# ── the plans tab (step 2) ─────────────────────────────────────────────────────────────────────
# Built pages, copied — not re-derived. `publish_site` already bakes the meeting overview per
# bowler type, the match-ups grid and the unorthodox-shot options into site/<slug>/, and each is a
# standalone page whose only link is the breadcrumb back to its series index. So the plans tab is a
# copy with that one href repointed, which is why this step needs no warehouse and cannot disagree
# with what the coach site shows.
#
# CONDITIONS AND ATTACKED-OUR-SQUAD ARE DELIBERATELY NOT COPIED (Tom, 25-09). Both are derived
# against a Test benchmark — conditions measures against NZ/SA/ENG, the attack cards read Test
# deliveries — and they are to get white-ball versions before they move. Named here rather than
# left to an accident of which files exist, so a Test series cannot quietly bring them across.
_PLAN_PAGES = ("matchups.html", "shot-matrix.html")
_PLAN_GLOB = "overview-"
_PLAN_HELD = ("conditions", "attack")

_GROUP_LABEL = {"pace": "Pace", "spin": "Spin", "right-pace": "Right-arm pace",
                "left-pace": "Left-arm pace", "off-spin": "Off spin", "leg-spin": "Leg spin",
                "left-orthodox": "Left-arm orthodox", "left-unorthodox": "Left-arm wrist spin"}
_PLAN_LABEL = {"matchups.html": "Match-ups grid",
               "shot-matrix.html": "Unorthodox shot options"}


def shutil_copy(src, dst):
    import shutil
    shutil.copyfile(src, dst)


def _insert_tabs(path, tabs):
    """Put the series' tab rows under the breadcrumb of a copied plan page (once)."""
    text = open(path, encoding="utf-8").read()
    if 'class="snav"' in text:
        text = re.sub(r'<div class="snav">.*?</div>', lambda _m: tabs, text, count=1, flags=re.S)
    elif 'class="stabs"' in text:
        text = re.sub(r'<nav class="stabs".*?</nav>', lambda _m: tabs, text, count=1, flags=re.S)
    else:
        text = text.replace("</div>", "</div>" + tabs, 1) if text.find('<div class="crumb">') >= 0 else tabs + text
    open(path, "w", encoding="utf-8").write(text)


def _plans(slug, root, entry, batters, tiers, smap, fmt, level, planner, heads):
    """The series' plan pages under plans/: the Pace and Spin packs written from the group
    overviews, and the match-ups grid and unorthodox-shot options copied from the coach site.
    Returns {key: body or True} for what exists. The per-type overview pages are no longer copied —
    the packs carry every type behind the switch (Tom, 04-10-2026)."""
    dest = os.path.join(root, "plans")
    os.makedirs(dest, exist_ok=True)
    have = {}
    for key in ("pace", "spin"):
        body = _pack_page(slug, root, key, entry, batters, tiers, smap, fmt, level, planner, heads)
        if body:
            have[key] = body
        else:
            print(f"  no {key} pack: no overview_{_PACKS[key][1]}_{_opp_key(slug)}.json")
    src = os.path.join(HERE, "site", slug)
    held = []
    if os.path.isdir(src):
        for f in sorted(os.listdir(src)):
            if not f.endswith(".html"):
                continue
            if any(h in f for h in _PLAN_HELD):
                held.append(f)
                continue
            if f not in _PLAN_PAGES:
                continue
            text = open(os.path.join(src, f), encoding="utf-8").read()
            # its one link is the breadcrumb to the series index, which is now a directory up
            text = text.replace('href="index.html"', 'href="../index.html"')
            open(os.path.join(dest, f), "w", encoding="utf-8").write(text)
            have[f] = True
    if held:
        print(f"  held back (Test-only, awaiting a white-ball version): {', '.join(held)}")
    # the per-type overview copies of the earlier layout, if a previous build left them
    for f in os.listdir(dest):
        if f.startswith(_PLAN_GLOB) and f.endswith(".html"):
            os.remove(os.path.join(dest, f))
    return have


def _day_first(iso):
    return f"{iso[8:10]}-{iso[5:7]}-{iso[:4]}" if iso and len(iso) >= 10 else (iso or "")


def _series_meta(slug, cfg, frozen, sq):
    """Name, subtitle and the date the series was archived, from whichever file still carries it:
    series.json while live, the archive manifest once frozen, squads.json for the roster's date."""
    e = cfg.get(slug) or frozen.get(slug) or {}
    m = sq.get(slug) or {}
    return (e.get("name") or m.get("name") or slug, e.get("subtitle") or "",
            m.get("archived") or e.get("archived") or "")


def _write_index(out):
    """The scouting landing page: the series being played or coming up, then every old series in a
    list that opens on request (Tom, 04-10-2026). A series is archived when its squad is
    (squads.json) — the one notion of "over" the rest of the estate uses."""
    import squads
    root = os.path.join(out, "coach")
    slugs = sorted(d for d in os.listdir(root)
                   if os.path.exists(os.path.join(root, d, "index.html")))
    cfg = {s.get("slug"): s for s in json.load(open(SERIES_JSON, encoding="utf-8")).get("series", [])}
    try:
        import archive_series
        frozen = {m["slug"]: m for m in archive_series.manifests()}
    except Exception:
        frozen = {}
    sq = squads.load()

    def card(slug, name, sub, when):
        return (f'<li><a href="{slug}/index.html"><b>{_html.escape(name)}</b>'
                + (f'<span class="sub">{_html.escape(sub)}</span>' if sub else "") + "</a>"
                + (f'<span class="n">archived {_day_first(when)}</span>' if when else "") + "</li>")

    active, old = [], []
    for s in slugs:
        name, sub, when = _series_meta(s, cfg, frozen, sq)
        (old if when else active).append((when, card(s, name, sub, when)))
    old.sort(key=lambda t: t[0], reverse=True)
    body = ('<h1>Scouting</h1><p class="lead">The opposition, series by series — their squad and '
            'the full report on each player.</p>'
            '<h2 class="sect">Active</h2>'
            + ('<ul class="cards">' + "".join(c for _w, c in active) + "</ul>" if active
               else '<p class="empty">No series on at the moment.</p>')
            + (f'<details class="archive"><summary>Archive <span class="n">{len(old)} series</span></summary>'
               '<p class="sub">Finished series, as they stood at the end. The pages do not change.</p>'
               '<ul class="cards">' + "".join(c for _w, c in old) + "</ul></details>" if old else ""))
    open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(
        SR.page("Scouting", body, up=("../players/index.html", "Player packs")))
    print(f"scouting index: {len(active)} active, {len(old)} archived")


def adopt_frozen(slug, out):
    """Serve a series frozen into archive/ (archive_series.py) from the hub too: its built pages are
    copied in under coach/<slug>/, where the app dresses them and relays their vision. Nothing is
    re-derived, so they cannot disagree with the portal's copy. An existing copy is renamed aside."""
    import datetime
    import shutil
    src = os.path.join(HERE, "archive", slug)
    if not os.path.exists(os.path.join(src, "index.html")):
        raise SystemExit(f"{slug} is not frozen in archive/ — archive_series.py freeze it first")
    dst = os.path.join(out, "coach", slug)
    if os.path.isdir(dst):
        aside = f"{dst}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        os.rename(dst, aside)
        print(f"  existing coach/{slug} renamed to {os.path.basename(aside)}")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", ".archive.json"))
    _recrumb(os.path.join(dst, "index.html"))
    n = sum(len(f) for _r, _d, f in os.walk(dst))
    print(f"  frozen {slug}: {n} files -> coach/{slug}")


def _recrumb(index_path):
    """The frozen index's breadcrumb names the portal it was built for; under the hub the same
    href is the Scouting list, so it says so. Only that label changes."""
    text = open(index_path, encoding="utf-8").read()
    new = re.sub(r'(<div class="crumb"><a href="\.\./index\.html">← )[^<]*(</a>)', r"\1Scouting\2", text, count=1)
    if new != text:
        open(index_path, "w", encoding="utf-8").write(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="the squad slug, as in series.json")
    ap.add_argument("--frozen", action="append", default=[], metavar="SLUG",
                    help="copy a series frozen in archive/ in under coach/, for the Archive list")
    ap.add_argument("--index-only", action="store_true",
                    help="rewrite coach/index.html from what is already built, baking nothing")
    ap.add_argument("--out", default="coach_build",
                    help="build directory; assemble_packs copies its coach/ into the bundle")
    ap.add_argument("--sas-hours", type=int, default=DEFAULT_SAS_HOURS)
    a = ap.parse_args()
    if not (a.slug or a.frozen or a.index_only):
        ap.error("give --slug, --frozen or --index-only")
    out = a.out if os.path.isabs(a.out) else os.path.join(HERE, a.out)
    for slug in a.frozen:
        adopt_frozen(slug, out)
    missing = []
    if a.slug:
        _n, missing = build(a.slug, out, a.sas_hours)     # writes the index itself
    elif a.frozen or a.index_only:
        _write_index(out)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
