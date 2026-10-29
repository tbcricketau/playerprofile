"""build_bowler_plans.py — their bowlers, for our batters: the data behind the coach view's Batting plans.

    venv/bin/python build_bowler_plans.py --slug south-africa-test-away-2026 --planner-out ~/fp_bowlers

For every bowler in the series' opponent_about, against right- and left-handers: the figures, the
how-to-play lines from their bowling report, and the field they are likely to set, by category (Tom,
04-10-2026) — pace: **New ball** when they take it 10% of the time or more, **Old ball**, **Bouncer
plan**; spin: **New batter**, **Set batter**. The fields are `field_engine.bowler_field`: the stock field
for the type, our batter's hand and the phase, adjusted to the bowler's own record, with the spare.

Writes `data/bowler_plans_<opp>.json`, which build_coach_site.py reads. With --planner-out it also
writes the field planner's second side — `fieldplanner/<planner series>/bowlers.json`, a headshot, and a
runs-off-them wheel and a shot spider per hand — to upload with `playerpacks/upload_packs.py --bundle <dir> --apply`.

Two profiles per bowler from the warehouse (one delivery query, shared): run it on the build machine.
"""
import argparse
import datetime
import io
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

NEW_BALL_MIN = 10        # % of innings they open the bowling in; Tom 04-10-2026 (Rabada 57, Paterson 23, Jansen 11)
NEW_BALL_OVERS = 30      # the bowling report's own new/old split (profile.build_profile, ball_age)
HANDS = (("RHB", "vs RHB", "right-handers"), ("LHB", "vs LHB", "left-handers"))
_GROUP = {"Right Fast": "right_pace", "Right Medium": "right_pace", "Left Fast": "left_pace",
          "Left Medium": "left_pace", "Off Spin": "off_spin", "Left Orthodox": "left_orthodox",
          "Leg Break": "leg_spin", "Left Unorthodox": "left_unorthodox"}
_TIER_ORDER = {"xi": 0, "squad": 1, "fringe": 2}


def _group(P, meta):
    g = _GROUP.get(P.get("primary_type"))
    if g:
        return g
    left = (meta.get("arm") or "") == "left"
    if meta.get("is_pace"):
        return "left_pace" if left else "right_pace"
    return "left_orthodox" if left else "off_spin"


def _fielders(field):
    """The planner's form: batter-relative angle and radius, keeper left to the diagram."""
    return [{"angle": round(float(f["angle"]), 1), "radius": round(float(f["radius"]), 3),
             "label": f["position"]} for f in field if f["position"] != "Keeper"]


def _categories(raw, group, is_lhb, new_ball):
    """[(label, field dict)] for one hand, in the order the chips show."""
    import field_engine as FE
    from cricket_core import fields
    from cricket_core.lookups import FIELD_POS, field_coords
    out = []
    if group in FE._SPIN_GROUPS:
        for label, phase in (("New batter", "attack"), ("Set batter", "defend")):
            out.append((label, FE.bowler_field(raw, group, is_lhb, phase)))
        return out
    newr = [r for r in raw if r.get("over_n") is not None and r["over_n"] <= NEW_BALL_OVERS]
    oldr = [r for r in raw if r.get("over_n") is not None and r["over_n"] > NEW_BALL_OVERS]
    if (new_ball or 0) >= NEW_BALL_MIN:
        out.append(("New ball", FE.bowler_field(newr, group, is_lhb, "attack")))
    out.append(("Old ball", FE.bowler_field(oldr, group, is_lhb, "defend")))
    short = []
    for nm in fields.SHORT_BALL:                       # a set field: no run flow behind it, no spare
        c = FIELD_POS.get(nm) or field_coords(nm)
        short.append({"position": nm, "angle": c["angle"], "radius": c["radius"], "role": c["role"]})
    out.append(("Bouncer plan", {"field": short, "spare": None, "legal": None, "adjusted": False,
                                 "notes": ["The standard bouncer field: one slip, a catcher in front of "
                                           "square, and the two leg-side riders the Laws allow."]}))
    return out


def _they(lines):
    return [str(x) for x in (lines or [])][:3]


def _webp(png_bytes, width):
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=85)
    return buf.getvalue()


WHEEL_PX = 560          # the batters' side export's wheel size (presentationbuilder export_field_planner MAX_PX)


def _zones_png(rows, is_lhb):
    """Runs by fielding area as the hub packs and web reports draw it (build_hub_packs._zones_svg,
    the green zones wheel; Tom 29-10-2026, in place of the old purple plotly one): runs, share and
    area name per sector, shaded by runs. Rasterised by cricviz.to_png's headless browser, so no
    kaleido. The sectors are charts.wagon_sector's, the same as every other runs-by-area count."""
    import tempfile
    from build_hub_packs import _zones_svg
    from cricket_core import charts, cricviz
    zones = {}
    for r in rows:
        runs = r.get("bat_score_n") or 0
        if runs and r.get("is_legal", True):
            k = charts.wagon_sector(r, is_lhb)
            if k:
                zones[k] = zones.get(k, 0) + runs
    px = 560
    inner = _zones_svg(zones, is_lhb).replace("<svg ", f'<svg width="{px}" height="{px}" ', 1)
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {px} {px}' width='{px}' height='{px}'>"
           f"{inner}</svg>")
    fd, path = tempfile.mkstemp(suffix=".png", prefix="zones_")      # %TEMP%, never the repo
    os.close(fd)
    try:
        cricviz.to_png(svg, path, scale=1)
        return open(path, "rb").read()
    finally:
        os.remove(path)                                                # our own file, made above


def _spider_png(rows, is_lhb):
    """Every scoring shot off them as a line (cricket_core.cricviz, as the batters' side spider), to
    that batter hand. Their wickets are the red lines: cricviz reads `striker_dismissed`, which the
    bowler query does not carry, so the bowler's own dismissals stand in (a run-out is not theirs)."""
    import subprocess
    import tempfile
    from cricket_core import cricviz
    marked = [dict(r, striker_dismissed="1" if r.get("is_wicket") else "0") for r in rows]
    fd, path = tempfile.mkstemp(suffix=".png", prefix="bowler_spider_")     # %TEMP%, never the repo
    os.close(fd)
    try:
        for attempt in range(3):            # a headless Chrome hangs now and then; the decks retry too
            try:
                cricviz.render("wagon_wheel", marked, path, lhb=is_lhb, width=700)
                break
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise
        return open(path, "rb").read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def build(slug, planner_out=None, only=None):
    import field_engine as FE
    import profile as PR
    from build_coach_site import _series, _fmt_level, _opp_key, _about, _tiers
    from data_loaders import load_bowler_deliveries

    entry = _series(slug)
    fmt, level = _fmt_level(entry)
    # White-ball series get the cards too (Tom, 16-10-2026: Batting plans mirror Bowling plans, as
    # the Test series' do): figures, facts and reels per hand. No estimated field — bowler_field
    # reads Test stock fields and Test catch norms, as field_engine does throughout, and the white-
    # ball Bowling plans carried no suggested field either. Since 29-10-2026 (Tom) a white-ball card
    # and its planner options are the GPS-measured fields per phase (whiteball_fields.py).
    # A T20I series reads the pooled major T20 leagues ("T20"), as the packs do (Tom, 16-10-2026):
    # far more balls per player than T20Is alone, and the packs and these cards must agree
    FMT = {"test": "Test", "odi": "ODI", "t20": "T20"}.get(fmt.lower(), "Test")
    white = FMT != "Test"
    bowlers, _batters = _about(slug)
    tiers = _tiers(entry)
    out = {"slug": slug, "series": entry.get("name") or slug, "format": FMT,
           "built": datetime.date.today().isoformat(), "new_ball_min": NEW_BALL_MIN, "bowlers": {}}
    for bid, meta in bowlers.items():
        if only and bid not in only:
            continue
        t0 = time.time()
        try:
            raw = PR.process_rows(load_bowler_deliveries(bid, fmt=FMT, level=level))
        except Exception as e:                               # a pipeline failure, said so on the card
            print(f"  ! {meta.get('name')}: no deliveries ({type(e).__name__}: {str(e)[:80]})", flush=True)
            out["bowlers"][bid] = {"name": meta.get("name"), "type": meta.get("type"), "error": True}
            continue
        b = {"name": meta.get("name") or bid, "type": meta.get("type") or "", "pace": bool(meta.get("is_pace")),
             "new_ball": meta.get("new_ball"), "order": meta.get("order") or 0, "tier": tiers.get(str(bid), ""),
             "hands": {}}
        for h, hand, word in HANDS:
            P = PR.build_profile(bid, hand=hand, raw=raw, fmt=FMT, level=level)
            group = _group(P, meta)
            b["group"] = group
            htp = P.get("how_to_play") or {}
            cats = []
            for k, (label, fs) in enumerate([] if white else
                                            _categories(raw, group, h == "LHB", meta.get("new_ball"))):
                if not fs:
                    continue
                kept = [f for f in fs["field"] if f["position"] != "Keeper"]
                spare_i = next((i for i, f in enumerate(kept) if fs.get("spare") and f["position"] == fs["spare"]), None)
                cats.append({"slot": "option1" if not cats else f"c{len(cats) + 1}", "label": label,
                             "fielders": _fielders(kept), "spare": spare_i,
                             "spare_name": FE.pretty_position(fs["spare"]) if spare_i is not None else "",
                             "adjusted": fs.get("adjusted"), "balls": fs.get("legal"), "notes": fs.get("notes") or []})
            if white:                          # GPS-measured white-ball fields per phase (whiteball_fields)
                from whiteball_fields import phase_fields
                cats = phase_fields(FMT, group, h)
            b["hands"][h] = {
                "n_balls": P.get("n_balls"), "n_wkts": P.get("n_wkts"), "runs": P.get("runs"),
                "economy": P.get("economy"), "bowl_avg": P.get("bowl_avg"), "strike_rate": P.get("strike_rate"),
                "avg_spd": P.get("avg_spd") if P.get("is_pace") else None,
                "max_spd_99": P.get("max_spd_99") if P.get("is_pace") else None,
                "short_pct": P.get("short_pct") if P.get("is_pace") else None,
                "round_pct": P.get("round_pct"),
                # labelled facts (Tom, 06-10-2026: generated text states facts, the coaches instruct);
                # the grouped keys stay for anything still reading them
                "how_to_play": {"facts": list(htp.get("facts") or [])[:6],
                                **{k: _they(htp.get(k)) for k in ("respect", "attack", "watch")}},
                "fields": cats}
            if planner_out:
                b["hands"][h]["_wheel_df"] = P.get("df")       # for the planner's wheel, dropped before writing
        print(f"  {b['name']:20} {b['hands']['RHB']['n_balls'] or 0:>6} to RHB  "
              f"{b['hands']['LHB']['n_balls'] or 0:>6} to LHB  "
              + (" / ".join(c["label"] for c in b["hands"]["RHB"]["fields"]) or "no field")
              + f"  {time.time() - t0:.0f}s", flush=True)
        out["bowlers"][bid] = b

    if planner_out:
        _planner_export(slug, entry, out, planner_out)
    for b in out["bowlers"].values():
        for x in (b.get("hands") or {}).values():
            x.pop("_wheel_df", None)
    path = os.path.join(DATA, f"bowler_plans_{_opp_key(slug)}.json")
    if only and os.path.exists(path):                     # a partial run updates, never drops the rest
        prev = json.load(open(path, encoding="utf-8"))
        prev["bowlers"].update(out["bowlers"])
        prev["built"] = out["built"]
        out = prev
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
    print(f"wrote {os.path.relpath(path, HERE)} ({len(out['bowlers'])} bowlers)")
    return out


_FMT_WORDS = {"Test": "Tests", "ODI": "ODIs", "T20": "T20s"}


def _planner_export(slug, entry, out, root):
    """The field planner's second side: a page per batter hand, a card per bowler (headshot, sample
    line, the runs-off-them wheel and the spider, and the categories' fields as the options it starts from)."""
    from photos import get_photo_bytes
    from report import _start_kaleido
    _start_kaleido()            # one Chrome for every wheel: a browser per figure hung on the second
    series = entry.get("planner_series")
    if not series:
        raise SystemExit(f"{slug} has no planner_series in series.json — nothing to export the planner to")
    base = os.path.join(os.path.expanduser(root), "fieldplanner", series)
    img = os.path.join(base, "img")
    os.makedirs(img, exist_ok=True)
    rows = []
    ordered = sorted(out["bowlers"].items(), key=lambda kv: (_TIER_ORDER.get(kv[1].get("tier"), 3), -int(kv[1].get("order") or 0)))
    for bid, b in ordered:
        if b.get("error"):
            continue
        head = ""
        try:
            data = get_photo_bytes(bid, fmt="test", name=b["name"])
            if data:
                open(os.path.join(img, f"bowler_{bid}.webp"), "wb").write(_webp(data, 132))
                head = f"img/bowler_{bid}.webp"
        except Exception as e:
            print(f"  ! headshot {b['name']}: {type(e).__name__}")
        hands = {}
        for h, _hand, word in HANDS:
            x = b["hands"][h]
            wheel = spider = ""
            if x.get("n_balls"):
                # the batters' cards' pair, at their size (11-10-2026): runs by area, then the spider.
                # New names, not the old bowler_<id>_<hand>.webp: the app lets a browser keep an
                # image for a day, so a redrawn wheel under the old name could show the old one.
                for kind, draw in (("wheel", _zones_png), ("spider", _spider_png)):
                    name = f"bowler_{bid}_{h.lower()}_" + ("area" if kind == "wheel" else "spider") + ".webp"
                    try:
                        png = draw(x["_wheel_df"], h == "LHB")
                        open(os.path.join(img, name), "wb").write(_webp(png, WHEEL_PX))
                        if kind == "wheel":
                            wheel = f"img/{name}"
                        else:
                            spider = f"img/{name}"
                    except Exception as e:
                        print(f"  ! {kind} {b['name']} {h}: {type(e).__name__}: {str(e)[:60]}")
            n, w = x.get("n_balls") or 0, x.get("n_wkts") or 0
            fw = _FMT_WORDS.get(out.get("format") or "Test", "Tests")
            fields = [{"slot": c["slot"], "label": c["label"], "spare": c["spare"],
                       "fielders": [{"angle": f["angle"], "radius": f["radius"]} for f in c["fielders"]]}
                      for c in x["fields"] if len(c["fielders"]) == 9]
            hands[h] = {"sample": f"{fw} to {word}, career · {w:,} wickets off {n:,} balls" if n else "",
                        "wheel": wheel, "spider": spider, "wheel_note": f"No {fw[:-1]} balls to {word}",
                        "fields": fields}
        rows.append({"player_id": bid, "name": b["name"], "type": b["type"], "tier": b.get("tier", ""),
                     "headshot": head, "hands": hands})
    man = {"series": series, "opposition": entry.get("opposition") or entry.get("target_country") or "",
           "format": out.get("format") or "Test",
           "coach_slug": slug, "coach_series_name": entry.get("name") or slug, "built": out["built"],
           "pages": [{"key": "vs_rhb", "label": "vs right-handers", "hand": "RHB"},
                     {"key": "vs_lhb", "label": "vs left-handers", "hand": "LHB"}],
           "bowlers": rows}
    json.dump(man, open(os.path.join(base, "bowlers.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"planner export: {len(rows)} bowlers -> {base}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="the squad slug, as in series.json")
    ap.add_argument("--planner-out", help="also write the field planner's bowler side under this directory")
    ap.add_argument("--only", action="append", default=[], metavar="ID", help="just these bowlers (repeatable)")
    a = ap.parse_args()
    build(a.slug, a.planner_out, set(a.only) or None)
    if a.planner_out:                   # the wheels went through kaleido: leave without its exit hang
        from report import finish_rendering
        finish_rendering(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
