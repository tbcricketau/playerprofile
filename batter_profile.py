"""
batter_profile.py — batting scouting analytics core (Test / red-ball).

`build_batter_profile(batter_id)` loads a batter's deliveries + per-innings totals
and returns a dict of every metric: the headline (runs / avg / SR), the novel
share-of-runs metric (% of team & match runs), how they score (shot groups, areas),
how they get out, and how they fare against each bowler type + where the weaknesses are.

No pandas / numpy — stdlib only.  Reuses the shared cricket vocab from ludis_cricket.
"""
import math
import statistics
from collections import Counter, defaultdict

from batting_loaders import (
    load_batter_deliveries, load_batter_innings, load_batter_info,
)
from ludis_cricket.lookups import (
    SHOT_QUALITY_MAP as _SHOT_QUALITY_MAP,
    BEATEN_QUALITIES as _BEATEN_QUALITIES,
    FALSE_SHOT_QUALITIES as _FALSE_SHOT_QUALITIES,
    HOW_OUT_MAP as _HOW_OUT_MAP,
    STROKE_FAMILY as _STROKE_FAMILY,
    BATTING_HAND_OVERRIDE as _HAND_OVERRIDE,
    PACE_TYPES as _PACE_TYPES,
    SPIN_TYPES as _SPIN_TYPES,
    team_flag,
)


def _safe_float(v):
    try:
        f = float(v)
        return f if f == f else None   # drop NaN
    except (TypeError, ValueError):
        return None


def _pctl(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def process_batting_rows(rows: list) -> list:
    """Enrich raw string rows with parsed numeric/boolean fields."""
    for r in rows:
        r["is_legal"] = r.get("legal_ball") in ("1", "True", "true")
        r["is_out"] = r.get("striker_dismissed") in ("1", "True", "true")
        r["is_lhb"] = "left" in (r.get("striker_hand") or "").lower()
        r["runs"] = _safe_float(r.get("bat_score")) or 0.0
        # aliases so the shared bowling charts (wagon wheel etc.) work on batting rows
        r["bat_score_n"] = r["runs"]
        r["is_wicket"] = r["is_out"]
        r["wide_runs_n"] = _safe_float(r.get("wide_runs")) or 0.0
        r["noball_runs_n"] = _safe_float(r.get("noball_runs")) or 0.0
        r["hit_y_n"] = None
        r["ball_speed_n"] = (lambda v: v if (v is not None and 60 <= v <= 170) else None)(_safe_float(r.get("ball_speed")))
        r["pitch_line_m"] = (lambda v: -v / 1000 if v is not None else None)(_safe_float(r.get("pitch_line")))
        r["pitch_length_m"] = (lambda v: v / 1000 if v is not None else None)(_safe_float(r.get("pitch_length")))
        r["at_stumps_line_m"] = (lambda v: -v / 1000 if v is not None else None)(_safe_float(r.get("at_stumps_line")))
        r["at_stumps_height_m"] = (lambda v: v / 1000 if v is not None else None)(_safe_float(r.get("at_stumps_height")))
        r["off_bat_angle_n"] = _safe_float(r.get("off_bat_angle"))
        r["off_bat_speed_n"] = _safe_float(r.get("off_bat_speed"))
        # off_bat_angle is effectively empty — hit_to_angle is the real shot direction
        # (100% coverage, absolute: 0 = straight, sign = physical side, +ve = a RHB's off).
        r["hit_ang_n"] = _safe_float(r.get("hit_to_angle"))
        r["hit_x_n"] = _safe_float(r.get("hit_to_x_physical"))
        r["hit_len_n"] = _safe_float(r.get("hit_to_length"))
        _sq = _SHOT_QUALITY_MAP.get(str(r.get("shot_quality_id", "")).strip())
        r["shot_quality"] = _sq
        r["has_shot_q"] = _sq is not None
        r["is_false_shot"] = _sq in _FALSE_SHOT_QUALITIES
        r["stroke_txt"] = (lambda s: s.strip() if isinstance(s, str) and s not in ("None", "", "Unknown") else None)(r.get("stroke"))
        r["stroke_family"] = _STROKE_FAMILY.get(r.get("stroke")) if r.get("stroke") else None
        r["how_out"] = _HOW_OUT_MAP.get(str(r.get("how_out_id", "")).strip()) if r["is_out"] else None
        _t = r.get("bowler_type_simple")
        r["vs_pace"] = _t in _PACE_TYPES
        r["vs_spin"] = _t in _SPIN_TYPES
    return rows


def _hit_side(r):
    """off / leg / straight for a scoring shot (hit_to_angle is absolute: 0 = straight
    down the ground, sign = physical side, +ve = a RHB's off; flip for LHB)."""
    a = r.get("hit_ang_n")
    if a is None:
        return None
    if abs(a) <= 22.5:
        return "straight"
    return "off" if ((a > 0) != r["is_lhb"]) else "leg"


def _bat_share(innings: list) -> dict | None:
    """Novel metric — share of team & match runs.
    Volume-weighted career share (sum/sum) is the headline; median per-innings share
    is the typical contribution (mean is skewed by big scores); plus a 'carried the
    innings' rate (share >= 25%)."""
    per = []
    for r in innings:
        his = _safe_float(r.get("his_runs")) or 0.0
        team = _safe_float(r.get("team_bat")) or 0.0
        match = _safe_float(r.get("match_bat")) or 0.0
        if team <= 0:
            continue
        per.append({"his": his, "team": team, "match": match,
                    "team_share": his / team * 100,
                    "match_share": his / match * 100 if match > 0 else None})
    if len(per) < 5:
        return None
    tot_his = sum(p["his"] for p in per)
    tot_team = sum(p["team"] for p in per)
    tot_match = sum(p["match"] for p in per)
    team_shares = sorted(p["team_share"] for p in per)
    match_shares = sorted(p["match_share"] for p in per if p["match_share"] is not None)
    return {
        "innings": len(per),
        "team_share_career": tot_his / tot_team * 100 if tot_team else None,
        "team_share_median": statistics.median(team_shares),
        "match_share_career": tot_his / tot_match * 100 if tot_match else None,
        "match_share_median": statistics.median(match_shares) if match_shares else None,
        "carried_rate": sum(1 for s in team_shares if s >= 25) / len(team_shares) * 100,
        "big_rate": sum(1 for s in team_shares if s >= 40) / len(team_shares) * 100,
    }


def _split_stats(rows: list) -> dict:
    """avg / SR / false% / dismissal rate for a subset of deliveries faced."""
    legal = [r for r in rows if r["is_legal"]]
    balls = len(legal)
    runs = sum(r["runs"] for r in rows)          # runs count even off no-balls
    outs = sum(1 for r in rows if r["is_out"])
    shotq = [r for r in rows if r["has_shot_q"]]
    false = sum(1 for r in shotq if r["is_false_shot"])
    return {
        "balls": balls, "runs": runs, "outs": outs,
        "avg": runs / outs if outs else None,
        "sr": runs / balls * 100 if balls else None,
        "false_pct": false / len(shotq) * 100 if shotq else None,
        "dismissal_per100": outs / balls * 100 if balls else None,
        "n_shotq": len(shotq),
    }


def build_batter_profile(batter_id: str, raw: list | None = None) -> dict:
    if raw is None:
        raw = process_batting_rows(load_batter_deliveries(batter_id))
    # correct known warehouse hand errors for the profiled batter (all his deliveries)
    _hov = _HAND_OVERRIDE.get(str(batter_id))
    if _hov:
        for r in raw:
            r["is_lhb"] = (_hov == "Left")
    innings = load_batter_innings(batter_id)
    info = load_batter_info(batter_id)

    name = (info.get("player_name") or f"Batter {batter_id}").strip()
    team = (info.get("team_name") or "").strip()
    flag = team_flag(team)

    legal = [r for r in raw if r["is_legal"]]
    n_balls = len(legal)
    runs = sum(r["runs"] for r in raw)
    n_out = sum(1 for r in raw if r["is_out"])
    is_lhb = sum(1 for r in raw if r["is_lhb"]) > len(raw) / 2 if raw else False

    # vs bowler type
    vs = {}
    for key, sub in (("pace", [r for r in raw if r["vs_pace"]]),
                     ("spin", [r for r in raw if r["vs_spin"]])):
        s = _split_stats(sub)
        if s["balls"] >= 50:
            vs[key] = s
    detail = {}
    by_type = defaultdict(list)
    for r in raw:
        t = r.get("bowler_type_simple")
        if t and t != "Other":
            by_type[t].append(r)
    for t, sub in by_type.items():
        s = _split_stats(sub)
        if s["balls"] >= 100:
            detail[t] = s

    # shot groups (tracked strokes)
    fam = defaultdict(lambda: {"balls": 0, "runs": 0.0, "outs": 0})
    for r in raw:
        f = r.get("stroke_family")
        if not f:
            continue
        fam[f]["balls"] += 1
        fam[f]["runs"] += r["runs"]
        if r["is_out"]:
            fam[f]["outs"] += 1
    fam_tot = sum(v["balls"] for v in fam.values()) or 1
    shot_groups = sorted(
        ({"name": k, "balls": v["balls"], "runs": v["runs"], "outs": v["outs"],
          "balls_pct": v["balls"] / fam_tot * 100,
          "runs_pct": v["runs"] / max(1.0, sum(x["runs"] for x in fam.values())) * 100}
         for k, v in fam.items() if v["balls"] >= 15),
        key=lambda d: -d["runs"])

    # scoring areas (off_bat_angle)
    dir_runs = {"off": 0.0, "leg": 0.0, "straight": 0.0}
    dir_known = 0.0
    for r in raw:
        if r["runs"] <= 0:
            continue
        side = _hit_side(r)
        if side is None:
            continue
        dir_runs[side] += r["runs"]
        dir_known += r["runs"]
    dir_pct = {k: v / dir_known * 100 for k, v in dir_runs.items()} if dir_known else None

    # dismissals
    dis = Counter(r["how_out"] for r in raw if r["is_out"] and r["how_out"])
    dismissal_bowler_type = Counter(r["bowler_type_simple"] for r in raw
                                    if r["is_out"] and r.get("bowler_type_simple") not in (None, "Other"))

    # weakness read: which of pace/spin dismisses more often / concedes fewer runs
    weakness = None
    if "pace" in vs and "spin" in vs:
        p, s = vs["pace"], vs["spin"]
        if p["avg"] and s["avg"]:
            if s["avg"] < p["avg"] * 0.75:
                weakness = "spin"
            elif p["avg"] < s["avg"] * 0.75:
                weakness = "pace"

    return {
        "batter_id": str(batter_id), "name": name, "team": team, "flag": flag, "is_lhb": is_lhb,
        "raw": raw, "n_balls": n_balls, "runs": runs, "n_out": n_out,
        "average": runs / n_out if n_out else None,
        "strike_rate": runs / n_balls * 100 if n_balls else None,
        "share": _bat_share(innings),
        "vs": vs, "vs_detail": detail, "weakness": weakness,
        "shot_groups": shot_groups, "dir_pct": dir_pct,
        "dismissals": dis, "n_dismissals": sum(dis.values()),
        "dismissal_bowler_type": dismissal_bowler_type,
    }
