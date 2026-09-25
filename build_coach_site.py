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
    """{player id: tier} from the series groups — the one thing series.json adds that nothing else
    carries. Absent for a player with no group entry (every opposition BATTER today), and an absent
    tier prints no chip rather than a guessed one."""
    out = {}
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


def build(slug, out, sas_hours=DEFAULT_SAS_HOURS):
    entry = _series(slug)
    fmt, level = _fmt_level(entry)
    tiers = _tiers(entry)
    bowlers, batters = _about(slug)
    smap = _sidecar_map()

    try:
        from publish_site import get_hawkeye_sas
        hk_sas = get_hawkeye_sas(ttl_hours=min(sas_hours, 167))
    except Exception as e:
        print(f"  (no hawkeye SAS: {type(e).__name__}) — baking without a video refresh")
        hk_sas = ""

    root = os.path.join(out, "coach", slug)
    reports = os.path.join(root, "reports")
    os.makedirs(reports, exist_ok=True)

    sections, n_baked, missing = [], 0, []
    # Which kinds actually carry something a player is not shown. Measured per report rather than
    # asserted: an ODI/T20 BOWLING report has no coach-only section at all, so its player-mode cut
    # is byte-identical, and a page claiming the coach sees the simulated match-ups would be wrong
    # for nine of this squad's nineteen reports.
    coach_only = set()

    for kind, people, heading in (("bowling", bowlers, "Their bowlers"),
                                  ("batting", batters, "Their batters")):
        rows = {t: [] for t, _h, _c in SR.TIER_META}
        rows[""] = []
        ordered = sorted(people.items(),
                         key=lambda kv: (int(kv[1].get("order") or 99), kv[1].get("name") or ""))
        for pid, meta in ordered:
            name = meta.get("name") or pid
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
            tier = tiers.get(str(pid), "")
            sub = btype or meta.get("type") or ("Batter" if kind == "batting" else "Bowler")
            rows.setdefault(tier, []).append(SR.report_card(
                name, sub,
                f"reports/{base}.html",
                pdf_href=None,                       # PDFs are gone (Tom, 25-09) — print the page
                vision_href=(f"reports/{base}.player.html"
                             if os.path.exists(os.path.join(reports, f"{base}.player.html"))
                             else None),
                badge=SR.TIER_CHIP.get(tier), badge_class=tier or "squad",
                photo=_photo(pid, name, fmt, os.path.join(root, "img")),
                initials=_initials(name)))

        body = []
        listed = 0
        for tier, head, _chip in SR.TIER_META:
            if rows.get(tier):
                body.append(SR.group_heading(head, len(rows[tier]), tier))
                body.append('<ul class="reports">' + "".join(rows[tier]) + "</ul>")
                listed += len(rows[tier])
        if rows.get(""):
            # No tier on these — every opposition BATTER today, since series.json carries tiers
            # only on the groups it builds (bowlers). Say so rather than inventing a chip.
            body.append(SR.group_heading(heading, len(rows[""])))
            body.append('<ul class="reports">' + "".join(rows[""]) + "</ul>")
            listed += len(rows[""])
        if listed:
            sections.append(f"<h1>{_html.escape(heading)}</h1>" + "".join(body))

    if not sections:
        raise SystemExit(f"no reports resolved for {slug} at {fmt}/{level} — nothing to serve")

    title = entry.get("name") or slug
    lead = entry.get("subtitle") or ""
    extra = {"batting": "how attacks have bowled to them, and our simulated best options",
             "bowling": "how they match up against our squad"}
    adds = [extra[k] for k in ("batting", "bowling") if k in coach_only]
    note = ("The coach report for each of them"
            + (" — adding " + " and ".join(adds) + ", which a player is not shown."
               if adds else ". No section here is withheld from the players in this format."))
    body = (f'<h1>{_html.escape(title)}</h1>'
            + (f'<p class="lead">{_html.escape(lead)}</p>' if lead else "")
            + f'<p class="lead">{note}</p>'
            + _plans(slug, root)
            + "".join(sections))
    open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(
        SR.page(f"{title} — their squad", body, up=("../index.html", "Scouting")))

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


def _plans(slug, root):
    """Copy this series' plan pages in beside the squad. Returns the nav HTML, or '' if none."""
    src = os.path.join(HERE, "site", slug)
    if not os.path.isdir(src):
        return ""
    dest = os.path.join(root, "plans")
    held, items = [], []
    for f in sorted(os.listdir(src)):
        if not f.endswith(".html"):
            continue
        if any(h in f for h in _PLAN_HELD):
            held.append(f)
            continue
        if f in _PLAN_PAGES:
            label = _PLAN_LABEL[f]
        elif f.startswith(_PLAN_GLOB):
            key = f[len(_PLAN_GLOB):-len(".html")]
            label = _GROUP_LABEL.get(key, key.replace("-", " ").capitalize())
        else:
            continue
        os.makedirs(dest, exist_ok=True)
        text = open(os.path.join(src, f), encoding="utf-8").read()
        # its one link is the breadcrumb to the series index, which is now a directory up
        text = text.replace('href="index.html"', 'href="../index.html"')
        open(os.path.join(dest, f), "w", encoding="utf-8").write(text)
        items.append((label, f))
    if held:
        print(f"  held back (Test-only, awaiting a white-ball version): {', '.join(held)}")
    if not items:
        return ""
    links = "".join(f'<li><a href="plans/{f}">{_html.escape(label)}</a></li>'
                    for label, f in sorted(items))
    return ('<h1>Plans</h1><p class="lead">The meeting overview for each bowling type, and the '
            'options against them.</p><ul class="cards">' + links + "</ul>")


def _write_index(out):
    """The scouting landing page — every series with a coach view built in this bundle."""
    root = os.path.join(out, "coach")
    slugs = sorted(d for d in os.listdir(root)
                   if os.path.exists(os.path.join(root, d, "index.html")))
    cfg = {s.get("slug"): s for s in json.load(open(SERIES_JSON, encoding="utf-8")).get("series", [])}
    cards = []
    for s in slugs:
        e = cfg.get(s) or {}
        cards.append(f'<li><a href="{s}/index.html">{_html.escape(e.get("name") or s)}</a>'
                     + (f'<span>{_html.escape(e.get("subtitle") or "")}</span>' if e.get("subtitle") else "")
                     + "</li>")
    body = ('<h1>Scouting</h1><p class="lead">The opposition, series by series — their squad and '
            'the full report on each player.</p><ul class="cards">' + "".join(cards) + "</ul>")
    open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(
        SR.page("Scouting", body, up=("../players/index.html", "Player packs")))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="the squad slug, as in series.json")
    ap.add_argument("--out", default="coach_build",
                    help="build directory; assemble_packs copies its coach/ into the bundle")
    ap.add_argument("--sas-hours", type=int, default=DEFAULT_SAS_HOURS)
    a = ap.parse_args()
    out = a.out if os.path.isabs(a.out) else os.path.join(HERE, a.out)
    _n, missing = build(a.slug, out, a.sas_hours)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
