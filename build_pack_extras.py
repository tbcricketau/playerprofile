"""
build_pack_extras.py — the numbers and pictures the hub's player packs show that the coach-view files
do not carry (docs/PLAYER_PACK_REDESIGN.md).

    python build_pack_extras.py --slug south-africa-test-away-2026
    python build_pack_extras.py --slug south-africa-test-away-2026 --only 2730017 3760008
    python build_pack_extras.py --slug south-africa-test-away-2026 --before 2026-10-09

For each opposition BOWLER, per batter hand: the factual lines (`profile._how_to_play` facts), the
figures to that hand (km/h with top or range, average, Bowl SR, economy, short %, wickets), how often
their balls were on course to hit the stumps against their type (`cricket_core.stumps`), and a pitch
map and beehive of their wicket balls to that hand.

For each opposition BATTER, per bowling type our squad bowls: where their record is weakest
(`batting_report.plan_facts`, the danger ball, the first-30-balls rate, how they get out), the
figures (balls, average, balls per dismissal, false-shot %, off-side share, false v the short ball),
runs by fielding zone, and a spider wagon wheel, pitch map and beehive of their dismissals.

The fields stay in `bowler_plans_<opp>.json` and `overview_<group>_<opp>.json`, which the coach view
reads too — this file only adds to them, so building it never touches the coach view. Writes
`data/pack_extras_<opp>.json` and the pictures under `reports/pics/<opp>/`.

Facts only: no line tells a player what to do (Tom, 06-10-2026). Instructions are the coaches', in
their notes.

`--before` cuts every match on or after that day, as build_overview does: during a series, pass the
first Test's date so the packs do not quietly re-point at the game just played.
"""
import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

MIN_BALLS = 60           # as build_overview: below this against a type there is no card to set
MIN_PICS = 5             # wicket / dismissal balls before a picture says anything
_MIN_SHORT_BALLS = 40    # as build_overview._short_read
_MIN_OUTS_FOR_BPD = 3    # as build_overview._threat
_SPIN = {"off_spin", "leg_spin", "left_orthodox", "left_unorthodox", "spin"}
_LABEL = {"right_pace": "right-arm pace", "left_pace": "left-arm pace", "off_spin": "off spin",
          "leg_spin": "leg spin", "left_orthodox": "left-arm orthodox", "left_unorthodox": "left-arm wrist spin",
          "pace": "pace", "spin": "spin"}


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _cut(rows, before):
    return [r for r in rows if (r.get("match_date") or "") < before] if before else rows


def _pics(kind_rows, out_dir, stem, lhb, spin, wheel_rows=None):
    """Render the pictures for one card; returns {kind: filename} for those drawn."""
    from cricket_core import cricviz
    out = {}
    os.makedirs(out_dir, exist_ok=True)
    if len(kind_rows) >= MIN_PICS:
        marked = [dict(r, striker_dismissed="1") for r in kind_rows]
        bands = {"bands": cricviz.SPIN_BANDS} if spin else {}
        for kind, opts in (("pitch", dict(metrics=False, **bands)), ("bee", {})):
            name = f"{stem}_{kind}.png"
            cricviz.render("pitch_map" if kind == "pitch" else "beehive", marked,
                           os.path.join(out_dir, name), lhb=lhb, scale=2, **opts)
            out[kind] = name
    if wheel_rows:
        name = f"{stem}_wheel.png"
        cricviz.render("wagon_wheel", wheel_rows, os.path.join(out_dir, name), lhb=lhb, scale=2)
        out["wheel"] = name
    return out


def bowler_entry(bid, meta, fmt, level, before, pic_dir, pics=True):
    import profile as PR
    from cricket_core import stumps
    from data_loaders import load_bowler_deliveries
    raw = _cut(PR.process_rows(load_bowler_deliveries(bid, fmt=fmt, level=level)), before)
    e = {"name": meta.get("name") or bid, "hands": {}}
    for h, hand in (("RHB", "vs RHB"), ("LHB", "vs LHB")):
        P = PR.build_profile(bid, hand=hand, raw=raw, fmt=fmt, level=level)
        if not P.get("n_balls"):
            continue
        spin = bool(P.get("is_spin"))
        s = stumps.bowler_vs_type(P["df"], fmt=fmt if fmt in ("Test", "ODI", "T20I") else "Test")
        wk = [r for r in P["df"] if r.get("is_legal") and r.get("is_wicket")]
        x = {"n_balls": P.get("n_balls"), "n_wkts": P.get("n_wkts"), "bowl_avg": P.get("bowl_avg"),
             "economy": P.get("economy"), "strike_rate": P.get("strike_rate"),
             "avg_spd": P.get("avg_spd"), "top_spd": P.get("max_spd_99"),
             "spd_lo": P.get("speed_p05") if spin else None, "spd_hi": P.get("speed_p95") if spin else None,
             "short_pct": P.get("short_pct") if P.get("is_pace") else None, "round_pct": P.get("round_pct"),
             "stumps": ({k: s[k] for k in ("rate", "expected", "verdict", "label", "tracked")} if s else None),
             "facts": (P.get("how_to_play") or {}).get("facts") or [], "n_wkt_balls": len(wk), "pics": {}}
        if pics:
            x["pics"] = _pics(wk, pic_dir, f"bowl_{bid}_{h.lower()}", h == "LHB", spin)
        e["hands"][h] = x
    return e


def batter_entry(bid, meta, groups, fmt, level, before, pic_dir, source="warehouse", pics=True):
    from batter_profile import build_batter_profile, process_batting_rows
    from batting_loaders import load_batter_deliveries
    from batting_report import plan_facts, early_line
    from cricket_core import charts
    raw = _cut(process_batting_rows(load_batter_deliveries(bid, fmt=fmt, level=level, source=source)), before)
    e = {"name": meta.get("name") or bid, "source": source, "groups": {}}
    baseline = None
    for g in groups:
        P = build_batter_profile(bid, raw=raw, group=g, fmt=fmt, level=level, source=source)
        balls = int(P.get("n_balls") or 0)
        e["is_lhb"] = bool(P.get("is_lhb"))
        if balls < MIN_BALLS:
            e["groups"][g] = {"balls": balls, "thin": True}
            continue
        if g in _SPIN and g != "spin" and baseline is None:
            try:
                baseline = build_batter_profile(bid, raw=raw, group="spin", fmt=fmt, level=level,
                                                source=source).get("dims") or {}
            except Exception:
                baseline = {}
        facts = plan_facts(P, baseline=baseline if g in _SPIN else None)
        gd = P.get("grid_danger")
        if gd:
            facts.append({"label": "Out most to",
                          "text": f"<b>{gd['length_band'].lower()} {gd['line_region']}</b> · "
                                  f"{gd['dismissal_per100']:.1f} per 100 balls"})
        ph = P.get("phase") or {}
        es, ss = ph.get("early"), ph.get("set")
        if (es and ss and es.get("dismissal_per100") and ss.get("dismissal_per100")
                and es["dismissal_per100"] >= 1.4 * ss["dismissal_per100"]):
            facts.append({"label": "First 30 balls", "text": early_line(es, ss)[len("First 30 balls: "):].rstrip(".")})
        dis = P.get("dismissals") or {}
        n = sum(dis.values()) if dis else 0
        if n:
            mode, c = max(dis.items(), key=lambda kv: kv[1])
            facts.append({"label": "How out", "text": f"{mode} {c / n * 100:.0f}%"})
        rows = [r for r in (P.get("raw") or []) if r.get("is_legal")]
        sq = [r for r in (P.get("raw") or []) if r.get("has_shot_q")]     # as build_overview._threat
        short = next((d for d in ((P.get("dims") or {}).get("length") or [])
                      if str(d.get("bucket", "")).lower() == "short"), None)
        n_out = int(P.get("n_out") or 0)
        zones = {}
        for r in rows:
            runs = r.get("bat_score_n") or 0
            if runs:
                k = charts.wagon_sector(r, bool(P.get("is_lhb")))
                if k:
                    zones[k] = zones.get(k, 0) + runs
        x = {"balls": balls, "average": P.get("average"), "n_out": n_out,
             "bpd": (balls / n_out) if n_out >= _MIN_OUTS_FOR_BPD else None,
             "false_pct": (100 * sum(1 for r in sq if r.get("is_false_shot")) / len(sq)) if sq else None,
             "off_pct": (P.get("dir_pct") or {}).get("off"),
             "short_false": (short["false_pct"] if short and short.get("balls", 0) >= _MIN_SHORT_BALLS
                             and short.get("false_pct") is not None else None),
             "facts": facts, "zones": zones, "n_dismissals": n, "pics": {}}
        if pics:
            outs = [r for r in rows if r.get("is_out") or r.get("is_wicket")
                    or str(r.get("striker_dismissed")) in ("1", "True", "true")]
            x["pics"] = _pics(outs, pic_dir, f"bat_{bid}_{g}", bool(P.get("is_lhb")), g in _SPIN, wheel_rows=rows)
        e["groups"][g] = x
    return e


def _our_groups(slug):
    """The bowling types our squad bowls — the groups a bowling pack is about."""
    import build_player_site as BPS
    from squads import roster
    by_bowler = BPS._our_bowl_groups(slug)
    players = json.load(open(os.path.join(HERE, "players.json"), encoding="utf-8"))
    out = set()
    for pid in roster(slug):
        rec = players.get(str(pid), {})
        for bt in rec.get("bowl_types") or []:
            g = (by_bowler.get(str(pid)) or {}).get(bt)
            out.add(g or bt)
    return sorted(out)


def build(slug, only=None, before=None, pics=True):
    from build_coach_site import _series, _fmt_level, _opp_key, _about
    entry = _series(slug)
    fmt, level = _fmt_level(entry)
    fmt = {"test": "Test", "odi": "ODI", "t20i": "T20I", "t20": "T20"}.get(str(fmt).lower(), fmt)
    opp = _opp_key(slug)
    bowlers, batters = _about(slug)
    groups = _our_groups(slug)
    pic_dir = os.path.join(HERE, "reports", "pics", opp)
    path = os.path.join(DATA, f"pack_extras_{opp}.json")
    prev = json.load(open(path, encoding="utf-8")) if (only and os.path.exists(path)) else None
    out = prev or {"slug": slug, "opp": opp, "format": fmt, "level": level, "bowlers": {}, "batters": {}}
    out.update({"built": datetime.date.today().isoformat(), "before": before, "groups": groups})
    print(f"{slug}: {len(bowlers)} bowlers, {len(batters)} batters, our types {', '.join(groups)}"
          + (f", record before {before}" if before else ""), flush=True)
    failed = []
    for bid, meta in bowlers.items():
        if only and bid not in only:
            continue
        t0 = time.time()
        try:
            out["bowlers"][bid] = bowler_entry(bid, meta, fmt, level, before, pic_dir, pics)
            print(f"  bowler {meta.get('name', bid):22} {time.time() - t0:5.0f}s", flush=True)
        except Exception as e:
            failed.append(bid)
            print(f"  ! bowler {meta.get('name', bid)}: {type(e).__name__}: {str(e)[:120]}", flush=True)
    for bid, meta in batters.items():
        if only and bid not in only:
            continue
        # a player with no record at this level is profiled from Cricket-21 as well, as the card is
        # (build_opponent_about marks the clips C21:<group>)
        source = "both" if any(str(v).startswith("C21:") for k, v in meta.items()
                               if k.startswith("clip_scope_")) else "warehouse"
        t0 = time.time()
        try:
            out["batters"][bid] = batter_entry(bid, meta, groups, fmt, level, before, pic_dir, source, pics)
            print(f"  batter {meta.get('name', bid):22} {time.time() - t0:5.0f}s  {source}", flush=True)
        except Exception as e:
            failed.append(bid)
            print(f"  ! batter {meta.get('name', bid)}: {type(e).__name__}: {str(e)[:120]}", flush=True)
    if failed and (only or len(failed) >= 3):
        # a warehouse drop fails everyone after it; never write that over a good file
        raise SystemExit(f"ABORTING: {len(failed)} player(s) failed ({', '.join(failed)}) — "
                         f"{os.path.relpath(path, HERE)} left as it was")
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
    print(f"wrote {os.path.relpath(path, HERE)} and pictures under {os.path.relpath(pic_dir, HERE)}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--only", nargs="*", help="rebuild these opposition ids into the existing file")
    ap.add_argument("--before", help="ISO date: drop every match on or after it")
    ap.add_argument("--no-pics", action="store_true", help="numbers only, no pictures")
    a = ap.parse_args(argv)
    build(a.slug, only=set(a.only) if a.only else None, before=a.before, pics=not a.no_pics)


if __name__ == "__main__":
    main()
