"""build_shot_types.py — the sweeps an opposition batter plays against spin, the ramps against pace,
and their false shots against slower balls, for each bowling type our squad bowls (Tom, 10-11-2026).

    venv/bin/python build_shot_types.py --slug england-odi-home-2026
    venv/bin/python build_shot_types.py --slug england-odi-home-2026 --only 2070076

For each batter and type: how often they play each shot (a share of their legal balls against the
type) with the runs and dismissals from it; against spin, the direction and distance of every
scoring sweep, for the Sweeps wagon wheel; against pace, their false-shot rate against coded slower
balls; and a reel of each shot, the newest 20 clips that play. build_hub_packs.py draws the figures,
the wheel and the buttons, and build_player_site.py puts the reels in the Pages packs' clip files,
which the hub's packs play from.

A sidecar of its own, not a field in pack_extras or the about file, so adding these rewrites nothing
already there (playerprofile/CLAUDE.md § Adding a reel must not touch a coach's notes or fields).

Shot codes (lookup 24), grouped as Tom set on 10-11-2026. Against spin: Sweep = sweep (9) + paddle
(26), Reverse sweep (18), Slog sweep (15). Against pace: Ramp = ramp (17) + paddle (26), Reverse ramp
= reverse ramp (32, coded only in the newest matches) + reverse sweep (18, how older matches code a
reverse ramp). Switch hits are left out. A slower ball is a coded variation (lookup 2812): slower
ball, off cutter, leg cutter, back of the hand or knuckle ball, the set odi_profile reads, without its
speed backfill, which needs the bowler's own stock pace.

A reel takes the exact type first and the wider pace or spin set when the exact type has none, as
the scoring and dismissal reels do, and says which (`scope`), so the pack can star it. Reads the
warehouse and probes clips: run it on the build machine.
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

SPIN_KINDS = (("sweep", ("9", "26")), ("reverse", ("18",)), ("slog", ("15",)))
PACE_KINDS = (("ramp", ("17", "26")), ("reverse_ramp", ("32", "18")))
LABEL = {"sweep": "Sweep", "reverse": "Reverse sweep", "slog": "Slog sweep",
         "ramp": "Ramp", "reverse_ramp": "Reverse ramp"}
SLOWER = {"5", "8", "9", "24", "25"}
REEL_CAP = 20
_SPIN = {"off_spin", "leg_spin", "left_orthodox", "left_unorthodox"}


def _out(r):
    return bool(r.get("is_out") or r.get("is_wicket") or str(r.get("striker_dismissed")) in ("1", "True", "true"))


def _dmy(d):
    d = str(d or "")
    return f"{d[8:10]}-{d[5:7]}-{d[:4]}" if len(d) >= 10 else ""


def _refs(rows, kind):
    """Clip references for these deliveries, newest first, each captioned with the shot, the runs
    and the date. Probed afterwards: a named clip is not footage (build_opponent_about._plays)."""
    import c21_source
    from cricket_core.video import clip_stem
    out = []
    for r in sorted(rows, key=lambda r: str(r.get("match_date") or ""), reverse=True):
        ref = c21_source.clip_ref(r, clip_stem(r.get("season"), r.get("gender_id"), r.get("match_length_id"),
                                               r.get("match_id"), r.get("video_file_name")))
        if not ref:
            continue
        runs = int(r.get("bat_score_n") or 0)
        what = "out" if _out(r) else f"{runs} run{'s' if runs != 1 else ''}"
        out.append({"delivery_id": r.get("delivery_id"), **ref,
                    "caption": f"{LABEL[kind]} · {what} · {_dmy(r.get('match_date'))}"})
    return out


def group_entry(bid, raw, g, fmt, level, source, macro_rows):
    """The figures, wheel lines, slower-ball rate and reels for one batter against one type."""
    import build_opponent_about as BOA
    from batter_profile import build_batter_profile
    P = build_batter_profile(bid, raw=raw, group=g, fmt=fmt, level=level, source=source)
    rows = [r for r in (P.get("raw") or []) if r.get("is_legal")]
    spin = g in _SPIN
    kinds = SPIN_KINDS if spin else PACE_KINDS
    x = {"balls": len(rows), "kinds": {}, "lines": [], "slow": None, "reels": {}}
    if not rows:
        return x
    for kind, codes in kinds:
        hit = [r for r in rows if str(r.get("stroke_id")) in codes]
        x["kinds"][kind] = {"n": len(hit), "runs": sum(int(r.get("bat_score_n") or 0) for r in hit),
                            "outs": sum(1 for r in hit if _out(r))}
        if spin:
            for r in hit:
                runs, ln, ang = int(r.get("bat_score_n") or 0), r.get("hit_len_n"), r.get("hit_ang_n")
                # a zero length is no placement recorded (CLAUDE.md, shot direction), not a straight hit
                if runs and ln and ang is not None:
                    x["lines"].append([kind, ang, ln, runs, str(r.get("match_date") or "")[:10]])
        # the reel: this exact type first, by the bowler's coded style and arm (the hand audit reads
        # the style code, so a ball typed by its variation alone is left out), then the wider set
        reel = BOA._playable_first(_refs([r for r in hit if BOA._style_ok(r, g)], kind), REEL_CAP)
        scope = g
        if not reel:
            fam = "spin" if spin else "pace"
            wide = [r for r in macro_rows(fam) if str(r.get("stroke_id")) in codes and BOA._style_ok(r, fam)]
            reel, scope = BOA._playable_first(_refs(wide, kind), REEL_CAP), fam
        if reel:
            x["reels"][kind] = {"scope": scope, "clips": reel}
    if not spin:
        # as build_pack_extras' short ball: the false-shot test over every ball with a shot quality,
        # the count over the legal balls
        sq = [r for r in (P.get("raw") or []) if r.get("has_shot_q") and str(r.get("ball_movement_id")) in SLOWER]
        n = sum(1 for r in rows if str(r.get("ball_movement_id")) in SLOWER)
        if sq and n:
            x["slow"] = {"balls": n, "false_pct": 100 * sum(1 for r in sq if r.get("is_false_shot")) / len(sq)}
    return x


def batter_entry(bid, meta, groups, fmt, level, before, source):
    from batter_profile import build_batter_profile, process_batting_rows
    from batting_loaders import load_batter_deliveries
    from build_pack_extras import _cut
    raw = _cut(process_batting_rows(load_batter_deliveries(bid, fmt=fmt, level=level, source=source)), before)
    wide = {}

    def macro_rows(fam):
        if fam not in wide:
            P = build_batter_profile(bid, raw=raw, group=fam, fmt=fmt, level=level, source=source)
            wide[fam] = [r for r in (P.get("raw") or []) if r.get("is_legal")]
        return wide[fam]

    return {"name": meta.get("name") or bid,
            "groups": {g: group_entry(bid, raw, g, fmt, level, source, macro_rows) for g in groups}}


def build(slug, only=None, before=None):
    import build_opponent_about as BOA
    from build_coach_site import _series, _fmt_level, _opp_key, _about
    from build_pack_extras import _our_groups
    entry = _series(slug)
    fmt, level = _fmt_level(entry)
    fmt = {"test": "Test", "odi": "ODI", "t20i": "T20I", "t20": "T20"}.get(str(fmt).lower(), fmt)
    opp = _opp_key(slug)
    _bowlers, batters = _about(slug)
    groups = [g for g in _our_groups(slug) if g in _SPIN or g.endswith("_pace")]
    path = os.path.join(DATA, f"shot_types_{opp}.json")
    prev = json.load(open(path, encoding="utf-8")) if (only and os.path.exists(path)) else None
    if before is None:
        # the same cut as the pack's other numbers, so the two never disagree
        px = os.path.join(DATA, f"pack_extras_{opp}.json")
        before = (json.load(open(px, encoding="utf-8")).get("before") if os.path.exists(px) else None)
    out = prev or {"slug": slug, "opp": opp, "format": fmt, "level": level, "batters": {}}
    out.update({"built": datetime.date.today().isoformat(), "before": before, "groups": groups})
    print(f"{slug}: {len(batters)} batters, our types {', '.join(groups)}"
          + (f", record before {before}" if before else ""), flush=True)
    BOA._require_fairplay()          # a reel probed with no credential would come out empty
    failed = []
    for bid, meta in batters.items():
        if only and bid not in only:
            continue
        source = "both" if any(str(v).startswith("C21:") for k, v in meta.items()
                               if k.startswith("clip_scope_")) else "warehouse"
        t0 = time.time()
        try:
            e = batter_entry(bid, meta, groups, fmt, level, before, source)
            out["batters"][bid] = e
            summ = " · ".join(f"{g} " + "/".join(str(k["n"]) for k in ge["kinds"].values())
                              for g, ge in e["groups"].items() if ge["balls"])
            print(f"  {meta.get('name', bid):22} {time.time() - t0:5.0f}s  {summ}", flush=True)
        except Exception as ex:
            failed.append(bid)
            print(f"  ! {meta.get('name', bid)}: {type(ex).__name__}: {str(ex)[:120]}", flush=True)
    if failed and (only or len(failed) >= 3):
        raise SystemExit(f"ABORTING: {len(failed)} batter(s) failed ({', '.join(failed)}) — "
                         f"{os.path.relpath(path, HERE)} left as it was")
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
    print(f"wrote {os.path.relpath(path, HERE)}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--only", nargs="*", help="rebuild these batter ids into the existing file")
    ap.add_argument("--before", help="ISO date: drop every match on or after it (default: pack_extras' cut)")
    a = ap.parse_args(argv)
    build(a.slug, only=set(a.only) if a.only else None, before=a.before)


if __name__ == "__main__":
    main()
