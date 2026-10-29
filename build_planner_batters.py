"""build_planner_batters.py — the field planner's batter side for a series with no decks.

The planner (playerpacks `/fields/<series>/`) starts each batter from presentationbuilder's
individual-opposition decks (`scripts/export_field_planner.py`). A white-ball series has no decks,
so the Bowling plans cards had nowhere to set a field (Tom, 29-10-2026). This writes the same
`fieldplanner/<planner series>/manifest.json` from our own data instead: a pack per bowler type the
coach view shows, a card per opposition batter (headshot, sample line, the runs-by-area wheel and the
spider), and the GPS-corrected middle-overs field for that type and the batter's hand as Option 1
(whiteball_fields.py). Coaches set the rest in the planner.

    venv/bin/python build_planner_batters.py --slug england-odi-home-2026 --out ~/fp_eng

Run it on the build machine (it reads deliveries), with `build_bowler_plans.py --planner-out` into
the same --out for the planner's bowler side, then upload <out> with playerpacks/upload_packs.py.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# the coach view's packs, in its order
GROUP_WORDS = {"right_pace": "right-arm pace", "left_pace": "left-arm pace", "off_spin": "off spin",
               "left_orthodox": "left-arm orthodox", "leg_spin": "leg spin", "left_unorthodox": "left-arm wrist spin"}
FMT_WORD = {"ODI": "ODIs", "T20": "T20s"}
MIN_WHEEL = 30          # legal balls against the type before a wheel says anything


def build(slug, out_root):
    from batter_profile import build_batter_profile, process_batting_rows
    from batting_loaders import load_batter_deliveries
    from build_bowler_plans import _webp, _zones_png, WHEEL_PX
    from build_coach_site import _PACKS, _about, _fmt_level, _overview, _series
    from photos import get_photo_bytes
    from report import _start_kaleido
    from whiteball_fields import middle_field
    from cricket_core import cricviz

    entry = _series(slug)
    series = entry.get("planner_series")
    if not series:
        raise SystemExit(f"{slug} has no planner_series in series.json")
    fmt, level = _fmt_level(entry)
    FMT = {"odi": "ODI", "t20": "T20", "t20i": "T20"}.get(fmt.lower())
    if not FMT:
        raise SystemExit(f"{slug} is {fmt}: a Test series takes its planner from the decks")
    load_fmt = "T20" if FMT == "T20" else "ODI"       # a T20I series reads the pooled leagues, as the packs do
    _start_kaleido()
    base = os.path.join(os.path.expanduser(out_root), "fieldplanner", series)
    img = os.path.join(base, "img")
    os.makedirs(img, exist_ok=True)

    _bowlers, batters = _about(slug)
    groups = [g for key in ("pace", "spin") for g in _PACKS[key][2] if _overview(slug, g)]
    order = sorted(batters.items(), key=lambda kv: (-int(kv[1].get("order") or 0), kv[1].get("name") or ""))
    hand_of = {}
    for g in groups:
        for r in _overview(slug, g)["rows"]:
            hand_of.setdefault(str(r["bid"]), (r.get("sub") or "").split(" · ")[0])
    packs = {g: [] for g in groups}
    for pid, meta in order:
        pid, name = str(pid), meta.get("name") or str(pid)
        hand = hand_of.get(pid) or meta.get("hand") or "RHB"
        lhb = hand.upper() == "LHB"
        head = ""
        try:
            data = get_photo_bytes(pid, fmt=load_fmt.lower(), name=name)
            if data:
                open(os.path.join(img, f"head_{pid}.webp"), "wb").write(_webp(data, 192))
                head = f"img/head_{pid}.webp"
        except Exception as e:
            print(f"  ! headshot {name}: {type(e).__name__}")
        raw = process_batting_rows(load_batter_deliveries(pid, fmt=load_fmt, level=level))
        seen = {}
        for g in groups:
            P = build_batter_profile(pid, raw=raw, group=g, fmt=load_fmt, level=level)
            rows = [r for r in (P.get("raw") or []) if r.get("is_legal")]
            runs = int(sum(r.get("bat_score_n") or 0 for r in rows))
            seen[g] = len(rows)
            words = f"{FMT_WORD[FMT]} v {GROUP_WORDS[g]}, career"
            wheels, note = {}, ""
            if len(rows) >= MIN_WHEEL:
                try:
                    name_a = f"{g}_{pid}_zones.webp"      # a new name for the green wheel: browsers keep images a day
                    open(os.path.join(img, name_a), "wb").write(_webp(_zones_png(rows, lhb), WHEEL_PX))
                    wheels["report"] = f"img/{name_a}"
                    tmp = os.path.join(img, f"_{g}_{pid}_spider.png")
                    cricviz.render("wagon_wheel", rows, tmp, lhb=lhb, scale=2)
                    name_s = f"{g}_{pid}_spider.webp"
                    open(os.path.join(img, name_s), "wb").write(_webp(open(tmp, "rb").read(), WHEEL_PX))
                    os.remove(tmp)                      # our own intermediate, written a line above
                    wheels["spider"] = f"img/{name_s}"
                except Exception as e:
                    print(f"  ! wheels {name} {g}: {type(e).__name__}: {str(e)[:60]}")
            else:
                note = f"{len(rows)} {FMT_WORD[FMT]} balls v {GROUP_WORDS[g]}, too few to draw"
            packs[g].append({"player_id": pid, "name": name, "hand": hand.upper(), "notes": [],
                             "sample": f"{words} · {runs:,} runs off {len(rows):,} balls" if rows else "",
                             "wheels": wheels, "wheel_note": note, "headshot": head,
                             "deck_field": {"fielders": middle_field(FMT, g, hand.upper())}})
        print(f"  {name:22} {hand:4} " + " · ".join(f"{g} {n}" for g, n in seen.items()), flush=True)
    man = {"series": series, "format": FMT, "opposition": entry.get("opposition") or entry.get("target_country") or "",
           "coach_slug": slug, "coach_series_name": entry.get("name") or slug,
           "title": entry.get("name") or slug, "venue": "",
           "exported_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "playerprofile build_planner_batters.py (no decks): Option 1 is the stock field "
                     "for the type and hand, middle overs",
           "geometry": {"note": "angle: degrees from straight, + = batter's off side, +/-180 behind the "
                                "keeper; radius: 0 at the bat, 1 at the rope in that direction. Batter-relative."},
           "packs": [{"key": g, "label": GROUP_WORDS[g][:1].upper() + GROUP_WORDS[g][1:], "bowler_type": GROUP_WORDS[g],
                      "deck": "", "stock_field": {"fielders": middle_field(FMT, g, "RHB")},
                      "batters": packs[g]} for g in groups]}
    json.dump(man, open(os.path.join(base, "manifest.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"planner batter side: {len(groups)} packs, {len(order)} batters -> {base}")
    return man


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--out", required=True, help="the folder that gets fieldplanner/<series>/ (not the repo)")
    a = ap.parse_args()
    build(a.slug, a.out)
    from report import finish_rendering           # the wheels went through kaleido: skip its exit hang
    finish_rendering(0)


if __name__ == "__main__":
    main()
