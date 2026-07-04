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
from ludis_cricket.charts import LENGTH_ZONES_PACE as _LZ_PACE, LENGTH_ZONES_SPIN as _LZ_SPIN
from ludis_cricket.video import clip_stem as _clip_stem
# Shared zone vocabulary (length bands, line regions) lives with the bowling profile.
from profile import build_line_zones as _build_line_zones, _LEN_BAND, _LINE_REGION, _zone_lbl

# Coder swing/seam group labels (2827/2828) are BATTER-RELATIVE: in = into the batter, out/away
# = away from the batter (same for pace swing/seam and spin drift/turn). Verified in the bowling work.
_SWING_DIR = {"100": "in", "400": "in", "200": "straight", "500": "straight", "300": "out", "600": "out"}
_SEAM_DIR  = {"100": "in", "400": "in", "200": "straight", "500": "straight", "300": "away", "600": "away"}
_LINE_ZONES = _build_line_zones("All")   # hand-agnostic pitching-line zones

# The six bowler groups we build focused reports for (who is bowling AT the batter).
EARLY_BALLS = 30      # "start of innings" = his first 30 balls faced; after that he's set

BOWLER_GROUPS = {
    "right_pace":      ({"Right Fast", "Right Medium"}, "right-arm pace"),
    "left_pace":       ({"Left Fast", "Left Medium"},   "left-arm pace"),
    "off_spin":        ({"Off Spin"},                   "off spin"),
    "leg_spin":        ({"Leg Break"},                  "leg spin"),
    "left_orthodox":   ({"Left Orthodox"},              "left-arm orthodox"),
    "left_unorthodox": ({"Left Unorthodox"},            "left-arm wrist spin"),
}


def _speed_band(v):
    """Pace speed bands (km/h). Spin speeds all fall in the slow bucket, so only use for pace."""
    if v is None:
        return None
    if v < 125:
        return "<125"
    if v < 133:
        return "125–133"
    if v < 140:
        return "133–140"
    return "140+"


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
    # rows arrive innings-ordered (loader ORDER BY match_date, innings, over, ball), so a
    # running count per innings gives his ball-of-innings — the start-vs-set axis.
    _faced = defaultdict(int)
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
        # movement: magnitude (deg) + batter-relative direction from the coder labels
        r["turn_n"] = _safe_float(r.get("movement_off_pitch"))   # seam (pace) / turn (spin)
        r["drift_n"] = _safe_float(r.get("movement_in_air"))     # swing (pace) / drift (spin)
        r["seam_dir"] = _SEAM_DIR.get(str(r.get("movement_off_pitch_group_seam_id", "")).strip())
        r["swing_dir"] = _SWING_DIR.get(str(r.get("movement_in_air_group_swing_id", "")).strip())
        _otw = r.get("over_the_wicket")
        r["is_round"] = (False if _otw in ("True", "1", "true") else True) if _otw in ("True", "1", "true", "False", "0", "false") else None
        r["speed_band"] = _speed_band(r["ball_speed_n"])
        # length band & pitching-line region (pace vs spin zones as appropriate)
        L, X = r["pitch_length_m"], r["pitch_line_m"]
        zlen = _LZ_PACE if r["vs_pace"] else _LZ_SPIN
        r["length_band"] = _LEN_BAND.get(_zone_lbl(L, zlen) or "") if L is not None else None
        r["line_region"] = _LINE_REGION.get(_zone_lbl(X, _LINE_ZONES) or "") if X is not None else None
        # ball of innings (1-based) — legal balls he has faced in this innings so far
        _ik = (r.get("match_id"), r.get("match_innings"))
        r["ball_of_innings"] = _faced[_ik] + 1
        if r["is_legal"]:
            _faced[_ik] += 1
        r["is_early"] = r["ball_of_innings"] <= EARLY_BALLS
        # video clip stem (resolved lazily when a playlist is built)
        r["clip_stem"] = _clip_stem(r.get("season"), r.get("gender_id"),
                                    r.get("match_length_id"), r.get("match_id"),
                                    r.get("video_file_name"))
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


def _bdry_pct(rows: list):
    """Boundary runs as a share of runs scored (4s+6s ÷ runs)."""
    runs = sum(r["runs"] for r in rows)
    bdry = sum(r["runs"] for r in rows if r["runs"] in (4.0, 6.0))
    return bdry / runs * 100 if runs else None


# Display order for the categorical dimensions.
_ORDER = {
    "seam_dir":   ["in", "straight", "away"],
    "swing_dir":  ["in", "straight", "out"],
    "speed_band": ["<125", "125–133", "133–140", "140+"],
    "length_band": ["Full", "Good length", "Back of a length", "Short"],
    "line_region": ["wide outside off", "outside off", "in the channel", "on the stumps", "down the leg side"],
}


def dimension_split(rows: list, key: str, min_balls: int = 40) -> list:
    """Split faced deliveries by a categorical row key -> per-bucket batting stats. Ordered by
    the natural zone order where we have one, else by vulnerability (false-shot % desc). Buckets
    thinner than `min_balls` are dropped so a handful of balls can't define a weakness."""
    groups = defaultdict(list)
    for r in rows:
        v = r.get(key)
        if v is None:
            continue
        groups[v].append(r)
    out = []
    for v, sub in groups.items():
        s = _split_stats(sub)
        if s["balls"] < min_balls:
            continue
        s["bucket"] = v
        s["bdry_pct"] = _bdry_pct(sub)
        s["rows"] = sub                      # kept for playlists / drill-down (dropped before JSON)
        out.append(s)
    order = _ORDER.get(key)
    if order:
        out.sort(key=lambda d: order.index(d["bucket"]) if d["bucket"] in order else 99)
    else:
        out.sort(key=lambda d: -(d["false_pct"] or 0))
    return out


def grid_danger(rows: list, min_balls: int = 25) -> dict | None:
    """The (length band × line region) cell where the batter is most vulnerable — highest
    dismissals per 100 balls among cells with >= min_balls. Returns the cell's stats or None."""
    cells = defaultdict(list)
    for r in rows:
        lb, lr = r.get("length_band"), r.get("line_region")
        if lb and lr:
            cells[(lb, lr)].append(r)
    best = None
    for (lb, lr), sub in cells.items():
        s = _split_stats(sub)
        if s["balls"] < min_balls or not s["outs"]:
            continue
        s["length_band"], s["line_region"] = lb, lr
        if best is None or (s["dismissal_per100"] or 0) > (best["dismissal_per100"] or 0):
            best = s
    return best


def build_batter_profile(batter_id: str, raw: list | None = None, group: str | None = None) -> dict:
    if raw is None:
        raw = process_batting_rows(load_batter_deliveries(batter_id))
    # correct known warehouse hand errors for the profiled batter (all his deliveries)
    _hov = _HAND_OVERRIDE.get(str(batter_id))
    if _hov:
        for r in raw:
            r["is_lhb"] = (_hov == "Left")
    innings = load_batter_innings(batter_id)
    info = load_batter_info(batter_id)

    # Optional bowler-group filter (focused report). Headline + dimensions then reflect only
    # deliveries from that group; hand + share-of-runs stay on the full career.
    raw_all = raw
    group_label = None
    is_spin_group = group in ("off_spin", "leg_spin", "left_orthodox", "left_unorthodox")
    if group and group in BOWLER_GROUPS:
        types, group_label = BOWLER_GROUPS[group]
        raw = [r for r in raw_all if r.get("bowler_type_simple") in types]

    name = (info.get("player_name") or f"Batter {batter_id}").strip()
    team = (info.get("team_name") or "").strip()
    flag = team_flag(team)

    legal = [r for r in raw if r["is_legal"]]
    n_balls = len(legal)
    runs = sum(r["runs"] for r in raw)
    n_out = sum(1 for r in raw if r["is_out"])
    is_lhb = sum(1 for r in raw_all if r["is_lhb"]) > len(raw_all) / 2 if raw_all else False

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

    # start of innings vs set (his first EARLY_BALLS balls of each innings vs the rest)
    phase = None
    early_rows = [r for r in raw if r["is_early"]]
    set_rows = [r for r in raw if not r["is_early"]]
    if (sum(1 for r in early_rows if r["is_legal"]) >= 150
            and sum(1 for r in set_rows if r["is_legal"]) >= 150):
        phase = {}
        for key, sub in (("early", early_rows), ("set", set_rows)):
            s = _split_stats(sub)
            s["bdry_pct"] = _bdry_pct(sub)
            # what he scores off in this phase (top stroke families by runs)
            fr = defaultdict(float)
            for r in sub:
                if r.get("stroke_family") and r["runs"] > 0:
                    fr[r["stroke_family"]] += r["runs"]
            ftot = sum(fr.values())
            s["top_shots"] = [(k, v / ftot * 100) for k, v in
                              sorted(fr.items(), key=lambda kv: -kv[1])[:2]] if ftot else []
            # where the runs go in this phase (for field placement by phase)
            dr = {"off": 0.0, "leg": 0.0, "straight": 0.0}
            dk = 0.0
            for r in sub:
                if r["runs"] > 0:
                    side = _hit_side(r)
                    if side:
                        dr[side] += r["runs"]
                        dk += r["runs"]
            s["dir_pct"] = {k: v / dk * 100 for k, v in dr.items()} if dk else None
            phase[key] = s

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

    # ── Vulnerability dimensions ─────────────────────────────────────────────────
    # Focused report: on the group. Combined report: the movement/speed detail is pace-centric
    # (seam/swing live on pace), so run it on the pace subset; spin gets a length/line block.
    if group:
        arows, is_pace_dims = raw, not is_spin_group
    else:
        arows, is_pace_dims = [r for r in raw if r["vs_pace"]], True
    dims = {
        "seam":  dimension_split(arows, "seam_dir"),
        "swing": dimension_split(arows, "swing_dir"),
        "speed": dimension_split(arows, "speed_band") if is_pace_dims else [],
        "length": dimension_split(arows, "length_band"),
        "line":  dimension_split(arows, "line_region"),
        "over_round": dimension_split(arows, "is_round", min_balls=60),
        "stroke": dimension_split(arows, "stroke_family", min_balls=25),
    }
    grid = grid_danger(arows)
    dims_spin = None
    if group is None:
        srows = [r for r in raw if r["vs_spin"]]
        if sum(1 for r in srows if r["is_legal"]) >= 150:
            dims_spin = {"length": dimension_split(srows, "length_band"),
                         "line": dimension_split(srows, "line_region"),
                         "turn": dimension_split(srows, "seam_dir")}

    return {
        "batter_id": str(batter_id), "name": name, "team": team, "flag": flag, "is_lhb": is_lhb,
        "raw": raw, "raw_all": raw_all, "n_balls": n_balls, "runs": runs, "n_out": n_out,
        "group": group, "group_label": group_label, "is_spin_group": is_spin_group,
        "average": runs / n_out if n_out else None,
        "strike_rate": runs / n_balls * 100 if n_balls else None,
        "share": _bat_share(innings),
        "vs": vs, "vs_detail": detail, "weakness": weakness, "phase": phase,
        "shot_groups": shot_groups, "dir_pct": dir_pct,
        "dismissals": dis, "n_dismissals": sum(dis.values()),
        "dismissal_bowler_type": dismissal_bowler_type,
        "dims": dims, "dims_spin": dims_spin, "grid_danger": grid, "n_faced_dims": len(arows),
    }
