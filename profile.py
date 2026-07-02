"""
profile.py — shared analytics core for the bowler dashboard AND the PDF reports.

`build_profile(bowler_id, hand, ...)` loads a bowler's Test deliveries, applies
the requested filters, and returns a dict of every metric, danger zone and the
filtered delivery lists.  Both app.py (Streamlit) and build_reports.py import
this so the report is guaranteed to match the dashboard — single source of truth.

No pandas / numpy — stdlib only.  This module deliberately does not import
streamlit, so the report generator stays lightweight.
"""
import csv
import os
import re
import math
import statistics
from collections import Counter, defaultdict

from data_loaders import (
    load_bowler_deliveries, load_bowler_info,
    load_bowler_catch_positions, load_fielding_positions,
)
from ludis_cricket.charts import (
    zone_concentration, danger_length, danger_line, danger_cell,
    LENGTH_ZONES_PACE, LENGTH_ZONES_SPIN, LENGTH_ZONES_1M, LENGTH_ZONES_05M, PITCH_HW,
)
from ludis_cricket.lookups import (
    SHOT_QUALITY_MAP as _SHOT_QUALITY_MAP,
    BEATEN_QUALITIES as _BEATEN_QUALITIES,
    FALSE_SHOT_QUALITIES as _FALSE_SHOT_QUALITIES,
    HOW_OUT_MAP as _HOW_OUT_MAP,
    STROKE_FAMILY as _STROKE_FAMILY,
    BATTING_HAND_OVERRIDE as _HAND_OVERRIDE,
    CAUGHT_BEHIND_POS as _CAUGHT_BEHIND_POS,
    PACE_TYPES as _PACE_TYPES,
    SPIN_TYPES as _SPIN_TYPES,
    team_flag,
)

_SPEED_PROFILE_CSV = r"c:\Ludis\referencebuilder\data\bowler_speed_profile.csv"

_SHORT_BUCKETS = {"8-9m", "9-10m", "10-11m", "11-12m", "12-13m", "13-14m", "14m+"}

_POS_MAX = {"Openers (1-2)": 2, "Top 3": 3, "Top 4": 4}
_LATER_SPELLS = {"Spell 2", "Spell 3", "Spell 4", "Spell 5+"}

_FIELD_POS = None


def _field_positions() -> dict:
    global _FIELD_POS
    if _FIELD_POS is None:
        _FIELD_POS = load_fielding_positions()
    return _FIELD_POS


def _annotate_catches(rows: list, bowler_id: str) -> None:
    """Attach catch fielding position + behind/field/unknown group to each row.
    Idempotent — only runs once per raw list."""
    if not rows or "catch_group" in rows[0]:
        return
    catch_map = load_bowler_catch_positions(str(bowler_id))
    posmap = _field_positions()
    for r in rows:
        pid = catch_map.get(r.get("delivery_id"))
        r["catch_position_id"] = pid
        r["catch_position"] = posmap.get(pid) if pid else None
        if r.get("is_wicket") and r.get("how_out") == "Caught":
            r["catch_group"] = ("behind" if pid in _CAUGHT_BEHIND_POS else "field") if pid else "unknown"
        else:
            r["catch_group"] = None


_CAUGHT_LABEL = {"behind": "Caught behind", "field": "Caught in field", "unknown": "Caught (Pos Unkwn)"}

# Filter option labels (shared with the app so both speak the same language).
HAND_OPTIONS  = ["All", "vs LHB", "vs RHB"]
POS_OPTIONS   = ["All positions", "Openers (1-2)", "Top 3", "Top 4"]
SPELL_OPTIONS = ["All", "Opening (Spell 1)", "Later (Spell 2+)"]
LEN_OPTIONS   = ["Zones", "1m bands", "0.5m bands"]


def _safe_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _quantile(data: list, q: float):
    if not data:
        return None
    s = sorted(data)
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def fmt(v, spec=".1f", unit="", fallback="—"):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return fallback
    return f"{v:{spec}}{unit}"


_SPEED_PROFILES = None


def load_speed_profiles() -> dict:
    """Bowler speed-profile CSV, keyed by bowler_id (memoised)."""
    global _SPEED_PROFILES
    if _SPEED_PROFILES is None:
        _SPEED_PROFILES = {}
        if os.path.exists(_SPEED_PROFILE_CSV):
            with open(_SPEED_PROFILE_CSV, encoding="utf-8", newline="") as f:
                _SPEED_PROFILES = {row["bowler_id"]: row for row in csv.DictReader(f)}
    return _SPEED_PROFILES


_MOVEMENT_PROFILE_CSV = r"c:\Ludis\referencebuilder\data\bowler_movement_profile.csv"
_MOVEMENT_PROFILES = None
_REPEAT_PROFILE_CSV = r"c:\Ludis\referencebuilder\data\bowler_repeatability_profile.csv"
_REPEAT_PROFILES = None
_CREASE_PROFILE_CSV = r"c:\Ludis\referencebuilder\data\bowler_crease_profile.csv"
_CREASE_PROFILES = None


def load_movement_profiles() -> dict:
    """Bowler movement-profile CSV (swing/seam/bounce + percentiles), memoised."""
    global _MOVEMENT_PROFILES
    if _MOVEMENT_PROFILES is None:
        _MOVEMENT_PROFILES = {}
        if os.path.exists(_MOVEMENT_PROFILE_CSV):
            with open(_MOVEMENT_PROFILE_CSV, encoding="utf-8", newline="") as f:
                _MOVEMENT_PROFILES = {row["bowler_id"]: row for row in csv.DictReader(f)}
    return _MOVEMENT_PROFILES


def load_repeatability_profiles() -> dict:
    """Bowler repeatability-profile CSV (length/line spread + within-type percentile),
    memoised.  Absent CSV -> empty dict (report simply omits the peer line)."""
    global _REPEAT_PROFILES
    if _REPEAT_PROFILES is None:
        _REPEAT_PROFILES = {}
        if os.path.exists(_REPEAT_PROFILE_CSV):
            with open(_REPEAT_PROFILE_CSV, encoding="utf-8", newline="") as f:
                _REPEAT_PROFILES = {row["bowler_id"]: row for row in csv.DictReader(f)}
    return _REPEAT_PROFILES


def load_crease_profiles() -> dict:
    """Bowler crease-usage profile CSV (release width + variation + within-type
    percentile), memoised.  Absent CSV -> empty dict."""
    global _CREASE_PROFILES
    if _CREASE_PROFILES is None:
        _CREASE_PROFILES = {}
        if os.path.exists(_CREASE_PROFILE_CSV):
            with open(_CREASE_PROFILE_CSV, encoding="utf-8", newline="") as f:
                _CREASE_PROFILES = {row["bowler_id"]: row for row in csv.DictReader(f)}
    return _CREASE_PROFILES


def _dir_split(rows: list, col: str, thresh: float = 0.2) -> dict | None:
    """In/out split for a signed movement column (drift_n = swing, turn_n = seam).
    Movement is stored *absolute* (physical side), so a ball moves INTO the batter
    when (mov>0 & RHB) or (mov<0 & LHB) — calibrated against the real lateral shift.
    Ignores negligible movement (|mov| < thresh degrees)."""
    inn = out = 0
    for r in rows:
        v = r.get(col)
        if v is None or abs(v) < thresh:
            continue
        is_in = (v > 0) != r["is_lhb"]
        inn += is_in
        out += not is_in
    tot = inn + out
    if not tot:
        return None
    return {"in_pct": inn / tot * 100, "out_pct": out / tot * 100, "n": tot}


def process_rows(rows: list) -> list:
    """Enrich raw string-valued rows with parsed numeric and boolean fields."""
    for r in rows:
        r["is_legal"]  = r.get("legal_ball") in ("1", "True", "true")
        r["is_wicket"] = r.get("bowler_dismissal") in ("1", "True", "true")
        r["is_lhb"]    = "left" in (r.get("striker_hand") or "").lower()
        _hov = _HAND_OVERRIDE.get(str(r.get("striker_id", "")))   # correct known warehouse hand errors
        if _hov:
            r["is_lhb"] = (_hov == "Left")
        _spd = _safe_float(r.get("ball_speed"))
        r["ball_speed_n"]   = _spd if (_spd is not None and 60.0 <= _spd <= 170.0) else None
        r["pitch_length_n"] = _safe_float(r.get("pitch_length"))
        r["pitch_line_n"]   = _safe_float(r.get("pitch_line"))
        r["bat_score_n"]    = _safe_float(r.get("bat_score")) or 0.0
        r["wide_runs_n"]    = _safe_float(r.get("wide_runs")) or 0.0
        r["noball_runs_n"]  = _safe_float(r.get("noball_runs")) or 0.0
        _sp = str(r.get("bowler_spell", "")).strip()
        r["spell_group"] = (
            "Spell 1" if _sp == "1" else
            "Spell 2" if _sp == "2" else
            "Spell 3" if _sp == "3" else
            "Spell 4" if _sp == "4" else "Spell 5+"
        )
        _inn = str(r.get("match_innings", "")).strip()
        r["innings_group"] = "1st Innings" if _inn in ("1", "2") else "2nd Innings" if _inn in ("3", "4") else None
        r["match_day_n"] = int(r["match_day"]) if str(r.get("match_day", "")).strip().isdigit() else None
        r["bat_pos_n"]   = int(r["striker_batting_position"]) if str(r.get("striker_batting_position", "")).strip().isdigit() else None
        _otw = r.get("over_the_wicket")
        r["is_round"] = (False if _otw in ("True", "1", "true") else True) if _otw in ("True", "1", "true", "False", "0", "false") else None
        r["is_variation"] = r.get("bowler_variation") in ("1", "True", "true")
        _sq = _SHOT_QUALITY_MAP.get(str(r.get("shot_quality_id", "")).strip())
        r["shot_quality"]  = _sq
        r["has_shot_q"]    = _sq is not None
        r["is_beaten"]     = _sq in _BEATEN_QUALITIES
        r["is_false_shot"] = _sq in _FALSE_SHOT_QUALITIES
        r["turn_n"]  = _safe_float(r.get("movement_off_pitch"))
        r["drift_n"] = _safe_float(r.get("movement_in_air"))
        r["release_line_n"] = _safe_float(r.get("release_line_unmirrored"))  # mm, absolute (over/round flip sign)
        _rh = _safe_float(r.get("release_height"))                            # mm above ground; clip garbage
        r["release_height_n"] = _rh if (_rh is not None and 1500 <= _rh <= 2400) else None
        r["how_out"] = _HOW_OUT_MAP.get(str(r.get("how_out_id", "")).strip()) if r.get("bowler_dismissal") in ("1", "True", "true") else None
        ln = r["pitch_line_n"]
        r["pitch_line_m"] = -ln / 1000 if ln is not None else None
        asl = _safe_float(r.get("at_stumps_line"))
        r["at_stumps_line_m"] = -asl / 1000 if asl is not None else None
        ash = _safe_float(r.get("at_stumps_height"))
        r["at_stumps_height_m"] = ash / 1000 if ash is not None else None
        mm = r["pitch_length_n"]
        r["pitch_length_m"] = mm / 1000 if mm is not None else None
        if mm is None:
            r["pitch_length_group_m"] = None
        else:
            m = mm / 1000
            if m < 0:
                r["pitch_length_group_m"] = "<0m"
            elif m >= 14:
                r["pitch_length_group_m"] = "14m+"
            else:
                b = int(m)
                r["pitch_length_group_m"] = f"{b}-{b+1}m"
        r["hit_x_n"]   = _safe_float(r.get("hit_to_x_physical"))
        r["hit_y_n"]   = _safe_float(r.get("hit_to_y_physical"))
        r["hit_len_n"] = _safe_float(r.get("hit_to_length"))
        r["hit_ang_n"] = _safe_float(r.get("hit_to_angle"))
        r["over_n"] = int(r["over"]) if str(r.get("over", "")).strip().isdigit() else None
        _stroke = r.get("stroke")
        _stroke = _stroke.strip() if isinstance(_stroke, str) and _stroke not in ("None", "") else None
        r["stroke_txt"]    = _stroke if _stroke and _stroke != "Unknown" else None
        r["has_stroke"]    = r["stroke_txt"] is not None
        r["stroke_family"] = _STROKE_FAMILY.get(_stroke) if _stroke else None
    return rows


def _len_stats(rows: list) -> dict | None:
    """Length approach for a subset: median length + full% / short% (and n).
    Clamps to plausible metres to dodge the negative-length garbage."""
    ls = [r["pitch_length_m"] for r in rows
          if r.get("is_legal") and r.get("pitch_length_m") is not None and -1.0 <= r["pitch_length_m"] <= 16.0]
    if len(ls) < 20:
        return None
    n = len(ls)
    return {
        "n": n,
        "median": statistics.median(ls),
        "full_pct": sum(1 for x in ls if x < 4.0) / n * 100,     # pitched up (yorker/full)
        "short_pct": sum(1 for x in ls if x >= 10.0) / n * 100,  # banged in (short/bouncer)
    }


def build_line_zones(hand: str = "All") -> list:
    """Stump-based line zones (each off-side band ≈ one stump width): 4th / 5th /
    6th / wide-of-6th stump.  Coordinate boundaries in metres from middle stump.

    The DB line is *batter-relative* (off side is the same sign for LHB and RHB —
    verified against caught-behind edges), so the SAME zones apply to both hands:
    off side is negative, leg side positive.  No LHB mirroring.
    """
    s = 0.1143  # ≈ half the wicket width — one "stump" out from middle
    return [
        (-PITCH_HW, -4 * s,   "Wide of 6th"),
        (-4 * s,    -3 * s,   "6th stump"),
        (-3 * s,    -2 * s,   "5th stump"),
        (-2 * s,    -s,       "4th stump"),
        (-s,         s,       "Stumps"),
        ( s,      PITCH_HW,   "Down leg"),
    ]


def _mean(vals):
    return statistics.mean(vals) if vals else None


def _hit_side(r) -> str | None:
    """Where a scoring shot went: 'off' / 'leg' / 'straight' (down-ground V).
    hit_to_angle is absolute (0 = straight, sign like hit_x: +ve = a RHB's off),
    so the off side is (angle>0) XOR left-hander.  Falls back to hit_x when the
    angle is missing.  'straight' = the down-the-ground V only (|angle| ≤ 22.5°);
    balls behind square keep their off/leg side."""
    ha = r.get("hit_ang_n")
    if ha is not None:
        if abs(ha) <= 22.5:
            return "straight"
        return "off" if ((ha > 0) != r["is_lhb"]) else "leg"
    hx = r.get("hit_x_n")
    if hx is not None:
        return "off" if ((hx > 0) != r["is_lhb"]) else "leg"
    return None


def _scoring_profile(rows: list) -> dict | None:
    """Runs breakdown for a set of legal deliveries — how the batter scores off this
    bowler: put away (boundaries) vs milked (1s/2s), off/leg/straight direction, and
    a shot-type family table (tracked subset only).  Returns None on thin data."""
    legal = [r for r in rows if r.get("is_legal")]
    n_legal = len(legal)
    runs_total = sum((r.get("bat_score_n") or 0.0) for r in legal)
    if n_legal < 50 or runs_total <= 0:
        return None

    scoring = [r for r in legal if (r.get("bat_score_n") or 0.0) > 0]
    bdry = [r for r in scoring if r["bat_score_n"] in (4.0, 6.0)]
    bdry_runs = sum(r["bat_score_n"] for r in bdry)
    n_bdry = len(bdry)

    # Direction of runs (off / leg / straight) + boundary counts by direction
    dir_runs = {"off": 0.0, "leg": 0.0, "straight": 0.0}
    dir_bdry = {"off": 0, "leg": 0, "straight": 0}
    dir_known = 0.0
    for r in scoring:
        side = _hit_side(r)
        if side is None:
            continue
        dir_runs[side] += r["bat_score_n"]
        dir_known += r["bat_score_n"]
        if r["bat_score_n"] in (4.0, 6.0):
            dir_bdry[side] += 1
    dir_pct = ({k: v / dir_known * 100 for k, v in dir_runs.items()} if dir_known else None)

    # Shot-type families (tracked subset)
    fam = defaultdict(lambda: {"balls": 0, "runs": 0.0, "bdry": 0})
    for r in scoring:
        f = r.get("stroke_family")
        if not f:
            continue
        fam[f]["balls"] += 1
        fam[f]["runs"] += r["bat_score_n"]
        if r["bat_score_n"] in (4.0, 6.0):
            fam[f]["bdry"] += 1
    fam_runs_tot = sum(v["runs"] for v in fam.values()) or 1.0
    families = sorted(
        ({"name": k, "balls": v["balls"], "runs": v["runs"], "bdry": v["bdry"],
          "rpb": v["runs"] / v["balls"], "runs_pct": v["runs"] / fam_runs_tot * 100}
         for k, v in fam.items() if v["balls"] >= 5),
        key=lambda d: -d["runs"],
    )
    n_stroke = sum(1 for r in scoring if r.get("has_stroke"))

    return {
        "n_legal": n_legal,
        "runs_total": runs_total,
        "n_scoring": len(scoring),
        "n_bdry": n_bdry,
        "bdry_runs": bdry_runs,
        "bdry_pct": bdry_runs / runs_total * 100,          # % of runs in boundaries (put away)
        "milked_pct": (runs_total - bdry_runs) / runs_total * 100,  # % in 1s/2s (milked)
        "balls_per_bdry": (n_legal / n_bdry) if n_bdry else None,
        "dir_pct": dir_pct,                                 # {off, leg, straight} % of runs
        "dir_bdry": dir_bdry,                               # boundary counts by direction
        "dir_n": dir_known,
        "families": families,
        "stroke_cov": n_stroke / len(scoring) * 100 if scoring else 0.0,
        "n_stroke": n_stroke,
    }


def _mode_stats(rows: list, line_zones: list) -> dict | None:
    """Line / length / threat summary for one delivery mode (over or round)."""
    n = len(rows)
    if n == 0:
        return None
    runs = sum((r.get("bat_score_n") or 0.0) + (r.get("wide_runs_n") or 0.0)
               + (r.get("noball_runs_n") or 0.0) for r in rows)
    wkts = sum(1 for r in rows if r.get("is_wicket"))
    lines = [r["pitch_line_m"] for r in rows if r.get("pitch_line_m") is not None]
    med_line = statistics.median(lines) if lines else None
    zc = Counter()
    for r in rows:
        x = r.get("pitch_line_m")
        if x is None:
            continue
        z = next((lbl for a, b, lbl in line_zones if a <= x < b), None)
        if z:
            zc[z] += 1
    modal_zone = zc.most_common(1)[0][0] if zc else None
    ls = _len_stats(rows)
    bat_runs = sum((r.get("bat_score_n") or 0.0) for r in rows)
    bdry_runs = sum(r["bat_score_n"] for r in rows if (r.get("bat_score_n") or 0.0) in (4.0, 6.0))
    return {
        "balls": n, "runs": runs, "wkts": wkts,
        "econ": runs / (n / 6) if n else None,
        "sr": n / wkts if wkts else None,
        "med_line": med_line, "modal_zone": modal_zone,
        "med_len": ls["median"] if ls else None,
        "short_pct": ls["short_pct"] if ls else None,
        "bdry_pct": bdry_runs / bat_runs * 100 if bat_runs else None,
    }


def _over_round(df: list, line_zones: list) -> dict | None:
    """How the bowler changes between over and round the wicket for the current hand.
    Adaptive: `show` is only true when the minority mode is a genuine tactic
    (≥15% share and ≥50 balls) — so same-handed pace (≈100% over) stays dark."""
    legal = [r for r in df if r.get("is_legal")]
    n = len(legal)
    if n < 100:
        return None
    over = [r for r in legal if r.get("is_round") is False]
    rnd  = [r for r in legal if r.get("is_round") is True]
    o_share = len(over) / n * 100
    r_share = len(rnd) / n * 100
    minority = min(len(over), len(rnd))
    show = minority >= 50 and min(o_share, r_share) >= 15.0
    os_, rs_ = _mode_stats(over, line_zones), _mode_stats(rnd, line_zones)

    def _delta(key):
        if os_ and rs_ and os_[key] is not None and rs_[key] is not None:
            return rs_[key] - os_[key]   # round minus over
        return None

    return {
        "show": show,
        "over_share": o_share, "round_share": r_share,
        "over": os_, "round": rs_,
        "line_delta": _delta("med_line"),   # <0 = round is more to the off side
        "len_delta": _delta("med_len"),     # <0 = round is fuller
    }


# ── Ball classification (Plan A) ────────────────────────────────────────────────
# Collapse the 5 length zones → 4 natural bands and the 6 stump-line zones → 5
# regions, so a (band × region) 'ball type' has low enough cardinality that the
# modal type is a genuine stock ball.
_LEN_BAND = {
    "Yorker/Full": "Full", "Full": "Full",
    "Good Length": "Good length",
    "Back of Length": "Back of a length",
    "Short": "Short",
}
_LEN_ADJ = {
    "Full": "full", "Good length": "a good length",
    "Back of a length": "back of a length", "Short": "short",
}
_LINE_REGION = {
    "Wide of 6th": "wide outside off", "6th stump": "outside off",
    "5th stump": "outside off", "4th stump": "in the channel",
    "Stumps": "on the stumps", "Down leg": "down the leg side",
}
_STUMP_HALF = 0.1143   # half the wicket width (m)
_BAIL_H = 0.71         # top of the stumps (m)


def _zone_lbl(x: float, zones: list):
    return next((lbl for a, b, lbl in zones if a <= x < b), None)


def _at_stumps_desc(asl_list: list, ash_list: list) -> dict | None:
    """Where a group of balls ends up at the stump face (batter-relative line +
    height).  Line: off = negative."""
    if not asl_list:
        return None
    masl = statistics.median(asl_list)
    if masl < -0.16:
        line = "outside off"
    elif masl < -0.03:
        line = "off stump"
    elif masl <= _STUMP_HALF:
        line = "the stumps"
    else:
        line = "leg"
    mash = statistics.median(ash_list) if ash_list else None
    if mash is None:
        height = None
    elif mash > _BAIL_H + 0.15:
        height = "over"
    elif mash >= 0.40:
        height = "top"
    else:
        height = "base"
    return {"line": line, "height": height, "masl": masl, "mash": mash}


def classify_balls(df: list, is_pace: bool, is_spin: bool) -> dict | None:
    """Bucket each delivery into a (length band × line region) 'ball type', enriched
    with where it ends up at the stumps and which way it moves off the pitch.  Returns
    a frequency-ranked list so the modal type is the genuine stock ball."""
    style_len = LENGTH_ZONES_PACE if is_pace else LENGTH_ZONES_SPIN
    line_zones = build_line_zones("All")   # zone boundaries are hand-agnostic
    legal = [r for r in df if r.get("is_legal")]
    if len(legal) < 100:
        return None

    agg: dict = {}
    for r in legal:
        L, X = r.get("pitch_length_m"), r.get("pitch_line_m")
        if L is None or X is None:
            continue
        band = _LEN_BAND.get(_zone_lbl(L, style_len) or "")
        region = _LINE_REGION.get(_zone_lbl(X, line_zones) or "")
        if not band or not region:
            continue
        a = agg.setdefault((band, region), {
            "balls": 0, "runs": 0.0, "wkts": 0, "false": 0, "shot_n": 0,
            "asl": [], "ash": [], "mv_in": 0, "mv_out": 0, "mv_n": 0,
        })
        a["balls"] += 1
        a["runs"] += ((r.get("bat_score_n") or 0.0) + (r.get("wide_runs_n") or 0.0)
                      + (r.get("noball_runs_n") or 0.0))
        if r.get("is_wicket"):
            a["wkts"] += 1
        if r.get("has_shot_q"):
            a["shot_n"] += 1
            if r.get("is_false_shot"):
                a["false"] += 1
        asl, ash = r.get("at_stumps_line_m"), r.get("at_stumps_height_m")
        if asl is not None:
            a["asl"].append(asl)
        if ash is not None:
            a["ash"].append(ash)
        mv = r.get("turn_n")   # movement_off_pitch = seam (pace) / turn (spin)
        if mv is not None and abs(mv) >= 0.3:
            is_in = (mv > 0) != r["is_lhb"]
            a["mv_in"] += is_in
            a["mv_out"] += (not is_in)
            a["mv_n"] += 1

    classified = sum(a["balls"] for a in agg.values())
    if classified < 100:
        return None

    types = []
    for (band, region), a in agg.items():
        b = a["balls"]
        types.append({
            "band": band, "region": region,
            "phrase": f"{_LEN_ADJ.get(band, band.lower())} {region}",
            "balls": b, "pct": b / classified * 100,
            "econ": a["runs"] / (b / 6) if b else None,
            "wkts": a["wkts"],
            "wkt_rate": a["wkts"] / b * 100 if b else 0.0,
            "beaten_pct": a["false"] / a["shot_n"] * 100 if a["shot_n"] >= 15 else None,
            "at_stumps": _at_stumps_desc(a["asl"], a["ash"]),
            "mv_in_pct": a["mv_in"] / a["mv_n"] * 100 if a["mv_n"] else None,
            "mv_n": a["mv_n"],
        })
    types.sort(key=lambda t: -t["balls"])
    return {"types": types, "n": classified, "stock": types[0] if types else None}


# ── Sequencing (Plan B, stages B1–B2) ───────────────────────────────────────────
def _sequencing(df: list) -> dict | None:
    """B1 repeatability (how tightly he lands the ball) + B2 over-shape (how length
    changes across the six balls of an over)."""
    legal = [r for r in df if r.get("is_legal")]
    if len(legal) < 200:
        return None

    lens = [r["pitch_length_m"] for r in legal
            if r.get("pitch_length_m") is not None and 0.0 <= r["pitch_length_m"] <= 15.0]
    lines = [r["pitch_line_m"] for r in legal
             if r.get("pitch_line_m") is not None and abs(r["pitch_line_m"]) <= 2.0]
    length_sd = statistics.pstdev(lens) if len(lens) > 20 else None
    line_sd = statistics.pstdev(lines) if len(lines) > 20 else None

    # B2 — aggregate by ball-in-over position (1..6)
    pos_agg: dict = defaultdict(lambda: {"balls": 0, "lens": [], "short": 0, "wkts": 0,
                                         "runs": 0.0, "crease": []})
    for r in legal:
        p = str(r.get("ball_in_over", "")).strip()
        if not p.isdigit():
            continue
        pp = int(p)
        if pp < 1 or pp > 6:
            continue
        b = pos_agg[pp]
        b["balls"] += 1
        L = r.get("pitch_length_m")
        if L is not None and 0.0 <= L <= 15.0:
            b["lens"].append(L)
            if L >= 10.0:
                b["short"] += 1
        if r.get("is_wicket"):
            b["wkts"] += 1
        b["runs"] += ((r.get("bat_score_n") or 0.0) + (r.get("wide_runs_n") or 0.0)
                      + (r.get("noball_runs_n") or 0.0))
        rl = r.get("release_line_n")
        if rl is not None and abs(rl) <= 1500:
            b["crease"].append(abs(rl) / 10.0)
    over_shape = []
    for pp in range(1, 7):
        b = pos_agg.get(pp)
        if not b or b["balls"] < 30:
            continue
        over_shape.append({
            "pos": pp, "balls": b["balls"],
            "med_len": statistics.median(b["lens"]) if b["lens"] else None,
            "short_pct": b["short"] / b["balls"] * 100,
            "econ": b["runs"] / (b["balls"] / 6),
            "wkt_rate": b["wkts"] / b["balls"] * 100,
            "crease_cm": statistics.mean(b["crease"]) if len(b["crease"]) >= 20 else None,
        })

    return {"length_sd": length_sd, "line_sd": line_sd, "n": len(legal), "over_shape": over_shape}


def _crease_usage(raw: list) -> dict | None:
    """How the bowler uses the crease at release, from release_line_unmirrored (mm,
    absolute — over/round the wicket sit on opposite sides).  Within each angle the
    magnitude = distance from the middle stump (wide vs tight) and the SD = how much
    he moves around on the crease.  Career-wide (all batters)."""
    legal = [r for r in raw if r.get("is_legal") and r.get("release_line_n") is not None
             and r.get("is_round") is not None and abs(r["release_line_n"]) <= 1500]
    if len(legal) < 80:
        return None

    def _stats(rows):
        if len(rows) < 50:
            return None
        vals = [r["release_line_n"] for r in rows]
        dist = [abs(v) / 10.0 for v in vals]   # cm from middle stump, per ball
        n = len(rows)
        return {
            "n": n,
            "width_cm": abs(statistics.mean(vals)) / 10.0,   # avg distance from middle stump
            "sd_cm": statistics.pstdev(vals) / 10.0,          # spread on the crease
            # usage mix: how often he releases tight / standard / wide
            "tight_pct": sum(1 for d in dist if d < 45) / n * 100,
            "std_pct":   sum(1 for d in dist if 45 <= d <= 75) / n * 100,
            "wide_pct":  sum(1 for d in dist if d > 75) / n * 100,
        }

    over = _stats([r for r in legal if r["is_round"] is False])
    rnd = _stats([r for r in legal if r["is_round"] is True])
    if not over and not rnd:
        return None
    n_over = over["n"] if over else 0
    n_rnd = rnd["n"] if rnd else 0
    dominant = "over" if n_over >= n_rnd else "round"
    heights = [r["release_height_n"] for r in legal if r.get("release_height_n") is not None]

    # outcomes by crease band — how he goes when tight / standard / wide
    def _band(d):
        return "tight" if d < 45 else "standard" if d <= 75 else "wide"
    agg = {b: {"balls": 0, "runs": 0.0, "wkts": 0} for b in ("tight", "standard", "wide")}
    for r in legal:
        a = agg[_band(abs(r["release_line_n"]) / 10.0)]
        a["balls"] += 1
        a["runs"] += ((r.get("bat_score_n") or 0.0) + (r.get("wide_runs_n") or 0.0)
                      + (r.get("noball_runs_n") or 0.0))
        if r.get("is_wicket"):
            a["wkts"] += 1
    bands = {}
    for b, a in agg.items():
        if a["balls"] < 30:
            continue
        bands[b] = {
            "balls": a["balls"], "share": a["balls"] / len(legal) * 100,
            "econ": a["runs"] / (a["balls"] / 6),
            "wkts": a["wkts"],
            "avg": a["runs"] / a["wkts"] if a["wkts"] else None,
            "sr": a["balls"] / a["wkts"] if a["wkts"] else None,
        }

    return {"over": over, "round": rnd, "dominant": dominant, "n": len(legal),
            "over_share": n_over / len(legal) * 100, "round_share": n_rnd / len(legal) * 100,
            "height_cm": statistics.mean(heights) / 10.0 if heights else None,
            "n_height": len(heights), "bands": bands}


_FP_PEER = {"Right pace": "right-arm pace", "Left pace": "left-arm pace",
            "Right spin": "right-arm spin", "Left spin": "left-arm spin"}


def _pctl_of(value, pop) -> float | None:
    pop = [p for p in pop if p is not None]
    if not pop or value is None:
        return None
    return sum(1 for p in pop if p <= value) / len(pop) * 100


def _fingerprint(bowler_id: str, is_pace: bool, is_spin: bool) -> list:
    """Percentile 'fingerprint' — release/crease + movement + speed metrics, each with the
    peer distribution (its correctly-scoped group) and where this bowler sits.  Returns a
    list of card dicts: label, value (for the strip), values (peer distribution), pctl,
    invert (True -> lower value plots to the right), disp (formatted), peer (human label)."""
    bid = str(bowler_id)
    cards = []

    def _num(r, k):
        try:
            return float(r.get(k))
        except (TypeError, ValueError):
            return None

    # ── speed (pace only) — no precomputed pctl, so rank mean_kph among pace bowlers ──
    if is_pace:
        sp = load_speed_profiles(); srow = sp.get(bid)
        if srow:
            v = _num(srow, "mean_kph")
            peers = [_num(r, "mean_kph") for r in sp.values()
                     if (r.get("bowler_type_simple") in _PACE_TYPES)]
            peers = [x for x in peers if x]
            if v is not None and len(peers) >= 8:
                cards.append({"label": "Pace", "value": v, "values": peers,
                              "pctl": _pctl_of(v, peers), "invert": False,
                              "disp": f"{v:.0f} kph", "peer": "pace bowlers"})

    # ── crease / release (hand × pace/spin peer group) ──
    cr = load_crease_profiles(); crow = cr.get(bid)
    if crow:
        pg = crow.get("peer_group")
        peers_rows = [r for r in cr.values() if r.get("peer_group") == pg]
        plabel = _FP_PEER.get(pg, pg or "")
        for col, pcol, label, invert, disp in [
            ("release_height_cm", "height_pctl", "Release height", False, lambda v: f"{v / 100:.2f} m"),
            ("width_cm", "width_pctl", "Crease width", False, lambda v: f"{v:.0f} cm"),
            ("var_cm", "var_pctl", "Crease variation", False, lambda v: f"±{v:.0f} cm"),
        ]:
            v = _num(crow, col)
            vals = [_num(r, col) for r in peers_rows]
            vals = [x for x in vals if x is not None]
            pc = _num(crow, pcol)
            if v is not None and len(vals) >= 8:
                cards.append({"label": label, "value": v, "values": vals, "pctl": pc,
                              "invert": invert, "disp": disp(v), "peer": plabel})

    # ── movement (pace/spin peer group) ──
    mv = load_movement_profiles(); mrow = mv.get(bid)
    if mrow:
        ps = mrow.get("pace_spin")
        peers_rows = [r for r in mv.values() if r.get("pace_spin") == ps]
        for col, pcol, ncol, pace_lbl, spin_lbl in [
            ("avg_seam", "seam_pctl", "n_seam", "Seam", "Turn"),
            ("avg_swing", "swing_pctl", "n_swing", "Swing", "Drift"),
            ("avg_bounce", "bounce_pctl", "n_bounce", "Bounce", "Bounce"),
        ]:
            v = _num(mrow, col)
            if v is None or (_num(mrow, ncol) or 0) < 40:
                continue
            vals = [_num(r, col) for r in peers_rows]
            vals = [x for x in vals if x is not None]
            if len(vals) >= 8:
                cards.append({"label": spin_lbl if is_spin else pace_lbl, "value": v, "values": vals,
                              "pctl": _num(mrow, pcol), "invert": False,
                              "disp": f"{v:.1f}°", "peer": f"{ps} bowlers"})

    # ── length repeatability (pace/spin) — lower SD = tighter, so invert ──
    rp = load_repeatability_profiles(); rrow = rp.get(bid)
    if rrow:
        ps = rrow.get("pace_spin")
        v = _num(rrow, "length_sd")
        vals = [_num(r, "length_sd") for r in rp.values() if r.get("pace_spin") == ps]
        vals = [x for x in vals if x is not None]
        pc = _num(rrow, "length_sd_pctl")
        if v is not None and len(vals) >= 8:
            cards.append({"label": "Repeatability", "value": v, "values": vals,
                          "pctl": (100 - pc) if pc is not None else None, "invert": True,
                          "disp": f"±{v:.1f} m", "peer": f"{ps} bowlers"})
    return cards


def _build_overs(rows: list) -> list:
    """Group legal deliveries into overs (match × innings × over), each sorted by
    ball-in-over, so consecutive balls in a sequence are genuinely consecutive."""
    overs: dict = defaultdict(list)
    for r in rows:
        if not r.get("is_legal"):
            continue
        bio = str(r.get("ball_in_over", "")).strip()
        if not bio.isdigit():
            continue
        overs[(r.get("match_id"), r.get("match_innings"), r.get("over"))].append((int(bio), r))
    seqs = []
    for balls in overs.values():
        balls.sort(key=lambda x: x[0])
        seqs.append([r for _, r in balls])
    return seqs


def _sequencing_patterns(raw: list, is_pace: bool, is_spin: bool) -> dict | None:
    """B3 ball-to-ball setups + B4 wicket set-ups, over consecutive deliveries within
    an over (career-wide, all batters — an over is bowled to whoever is on strike)."""
    overs = _build_overs(raw)
    if not overs:
        return None
    SHORT, FULL = 10.0, 7.0   # metres: banged in vs pitched up
    DL = 1.0                  # length delta (m) to count 'fuller'/'shorter'
    DX = 0.10                 # line delta (m) to count 'straighter'/'wider'

    n_pairs = after_short_n = after_short_fuller = 0
    after_bdry_n = after_bdry_shorter = after_bdry_straighter = 0
    wk_total = wk_with_prev = wk_fuller = wk_shorter = wk_straighter = wk_wider = wk_first = 0

    for seq in overs:
        for i, cur in enumerate(seq):
            prev = seq[i - 1] if i > 0 else None
            pL = prev.get("pitch_length_m") if prev else None
            pX = prev.get("pitch_line_m") if prev else None
            cL = cur.get("pitch_length_m")
            cX = cur.get("pitch_line_m")

            if prev is not None and pL is not None and cL is not None:
                n_pairs += 1
                if pL >= SHORT:
                    after_short_n += 1
                    if cL < FULL:
                        after_short_fuller += 1
                if (prev.get("bat_score_n") or 0.0) in (4.0, 6.0):
                    after_bdry_n += 1
                    if cL - pL >= DL:
                        after_bdry_shorter += 1
                    if pX is not None and cX is not None and abs(cX) <= abs(pX) - DX:
                        after_bdry_straighter += 1

            if cur.get("is_wicket"):
                wk_total += 1
                if prev is None:
                    wk_first += 1
                elif pL is not None and cL is not None:
                    wk_with_prev += 1
                    if cL - pL <= -DL:
                        wk_fuller += 1
                    elif cL - pL >= DL:
                        wk_shorter += 1
                    if pX is not None and cX is not None:
                        if abs(cX) <= abs(pX) - DX:
                            wk_straighter += 1
                        elif abs(cX) >= abs(pX) + DX:
                            wk_wider += 1

    def _pct(a, b):
        return a / b * 100 if b else None

    return {
        "n_pairs": n_pairs,
        "after_short_n": after_short_n,
        "after_short_fuller_pct": _pct(after_short_fuller, after_short_n),
        "after_bdry_n": after_bdry_n,
        "after_bdry_shorter_pct": _pct(after_bdry_shorter, after_bdry_n),
        "after_bdry_straighter_pct": _pct(after_bdry_straighter, after_bdry_n),
        "wk_total": wk_total, "wk_with_prev": wk_with_prev, "wk_first": wk_first,
        "wk_fuller_pct": _pct(wk_fuller, wk_with_prev),
        "wk_shorter_pct": _pct(wk_shorter, wk_with_prev),
        "wk_straighter_pct": _pct(wk_straighter, wk_with_prev),
        "wk_wider_pct": _pct(wk_wider, wk_with_prev),
    }


def build_profile(
    bowler_id: str,
    hand: str = "All",
    position: str = "All positions",
    spell: str = "All",
    length_mode: str = "Zones",
    raw=None,
) -> dict:
    """Compute the full bowler profile for the given filters.

    Returns a dict of metrics, danger zones and the filtered delivery lists.
    `raw` may be passed pre-loaded/processed to avoid re-querying (the app does
    this so filter changes don't re-hit the DB).
    """
    if raw is None:
        raw = process_rows(load_bowler_deliveries(bowler_id))
    _annotate_catches(raw, bowler_id)

    info = load_bowler_info(str(bowler_id)) or {}
    name = (info.get("player_name") or "").strip() or f"Bowler {bowler_id}"
    team = (info.get("team_name") or "").strip()
    flag, _ = team_flag(team)

    sp = load_speed_profiles().get(str(bowler_id), {})
    speed_p95 = _safe_float(sp.get("p95_kph")) if sp else None
    speed_p05 = _safe_float(sp.get("off_pace_kph")) if sp else None

    type_counts = Counter(r["bowler_type_simple"] for r in raw if r["is_legal"])
    primary_type = type_counts.most_common(1)[0][0] if type_counts else "Unknown"
    is_pace = primary_type in _PACE_TYPES
    is_spin = primary_type in _SPIN_TYPES

    # ── Filters ────────────────────────────────────────────────────────────────
    df = list(raw)
    if hand == "vs LHB":
        df = [r for r in df if r["is_lhb"]]
    elif hand == "vs RHB":
        df = [r for r in df if not r["is_lhb"]]
    hand_df = list(df)   # hand-filtered only — basis for the length match-ups below
    if position in _POS_MAX:
        pm = _POS_MAX[position]
        df = [r for r in df if r.get("bat_pos_n") is not None and r["bat_pos_n"] <= pm]
    if spell == "Opening (Spell 1)":
        df = [r for r in df if r["spell_group"] == "Spell 1"]
    elif spell == "Later (Spell 2+)":
        df = [r for r in df if r["spell_group"] in _LATER_SPELLS]

    legal = [r for r in df if r["is_legal"]]
    n_balls = len(legal)
    n_wkts  = sum(1 for r in df if r["is_wicket"])
    runs_tot = int(sum(r["bat_score_n"] + r["wide_runs_n"] + r["noball_runs_n"] for r in legal))

    speeds = [r["ball_speed_n"] for r in legal if r["ball_speed_n"] is not None]
    avg_spd = _mean(speeds)
    max_spd_99 = _quantile(speeds, 0.99)

    def _speeds(pred):
        return [r["ball_speed_n"] for r in raw if r["is_legal"] and pred(r) and r["ball_speed_n"] is not None]

    spd_spell1  = _mean(_speeds(lambda r: r["spell_group"] == "Spell 1"))
    spd_spell2  = _mean(_speeds(lambda r: r["spell_group"] == "Spell 2"))
    spd_spell3p = _mean(_speeds(lambda r: r["spell_group"] not in ("Spell 1", "Spell 2")))
    spd_inn1    = _mean(_speeds(lambda r: r["innings_group"] == "1st Innings"))
    spd_inn2    = _mean(_speeds(lambda r: r["innings_group"] == "2nd Innings"))

    def _lengths(pred):
        return [r["pitch_length_m"] for r in raw if r["is_legal"] and pred(r) and r["pitch_length_m"] is not None]

    len_spell1  = _mean(_lengths(lambda r: r["spell_group"] == "Spell 1"))
    len_spell2  = _mean(_lengths(lambda r: r["spell_group"] == "Spell 2"))
    len_spell3p = _mean(_lengths(lambda r: r["spell_group"] not in ("Spell 1", "Spell 2")))

    lengths = [r["pitch_length_n"] for r in legal if r["pitch_length_n"] is not None]
    # Median, not mean: ~10% of deliveries carry bad/negative length values
    # (full tosses coded negative, occasional −20 m garbage) that wreck the mean.
    avg_len_m = statistics.median(lengths) / 1000 if lengths else None
    # Most common 1 m length band (their "good length" in metres)
    _len_bands = Counter(
        r["pitch_length_group_m"] for r in legal
        if r.get("pitch_length_group_m") and r["pitch_length_group_m"] != "<0m"
    )
    common_len_band = _len_bands.most_common(1)[0][0] if _len_bands else None

    short_balls = [r for r in legal if r.get("pitch_length_group_m") in _SHORT_BUCKETS]
    short_pct   = len(short_balls) / n_balls * 100 if n_balls else 0.0
    sb_wkts = sum(1 for r in short_balls if r["is_wicket"])
    sb_runs = int(sum(r["bat_score_n"] + r["wide_runs_n"] + r["noball_runs_n"] for r in short_balls))
    sb_econ = sb_runs / (len(short_balls) / 6) if short_balls else None

    known_round = [r for r in legal if r.get("is_round") is not None]
    round_pct = sum(1 for r in known_round if r["is_round"]) / len(known_round) * 100 if known_round else None
    career_round = [r for r in raw if r["is_legal"] and r.get("is_round") is not None]
    _rl = [r for r in career_round if r["is_lhb"]]
    _rr = [r for r in career_round if not r["is_lhb"]]
    round_lhb = sum(1 for r in _rl if r["is_round"]) / len(_rl) * 100 if _rl else None
    round_rhb = sum(1 for r in _rr if r["is_round"]) / len(_rr) * 100 if _rr else None

    # Slower-ball usage, defined off the bowler's own speed profile: a delivery below
    # off_pace_kph (mean − 2σ ≈ 7% below stock) is a genuine change-up. A raw low
    # percentile (p10/p20) is both too shallow and tautological, so we don't use it.
    slower_ball_pct = slower_ball_kph = None
    if is_pace and speed_p05 is not None:
        _spd = [r["ball_speed_n"] for r in legal if r["ball_speed_n"] is not None]
        _slow = [v for v in _spd if v < speed_p05]
        if _spd:
            slower_ball_pct = len(_slow) / len(_spd) * 100
            slower_ball_kph = statistics.median(_slow) if _slow else None

    tracked = [r for r in legal if r.get("has_shot_q")]
    n_tracked = len(tracked)
    beaten_pct = sum(1 for r in tracked if r["is_beaten"]) / n_tracked * 100 if n_tracked else None
    false_pct  = sum(1 for r in tracked if r["is_false_shot"]) / n_tracked * 100 if n_tracked else None

    wkts = [r for r in df if r["is_wicket"] and r.get("how_out")]

    def _dlabel(r):
        if r["how_out"] == "Caught":
            return _CAUGHT_LABEL.get(r.get("catch_group"), "Caught")
        return r["how_out"]

    dismissal_counts = Counter(_dlabel(r) for r in wkts)   # detailed (caught split by position)
    n_dismissals = sum(dismissal_counts.values())
    # Headline uses the BROAD mode (Caught/Bowled/LBW/Stumped) — avoids surfacing
    # "Caught (posn?)" when catch positions are poorly recorded (e.g. spinners).
    _broad = Counter(r["how_out"] for r in wkts)
    top_dismissal = _broad.most_common(1)[0] if _broad else None
    # Specific catching positions (edges to the cordon etc.)
    catch_pos_counts = Counter(
        r["catch_position"] for r in wkts if r["how_out"] == "Caught" and r.get("catch_position")
    )
    n_caught = sum(1 for r in wkts if r["how_out"] == "Caught")
    caught_behind = sum(1 for r in wkts if r.get("catch_group") == "behind")
    caught_field  = sum(1 for r in wkts if r.get("catch_group") == "field")

    turn_vals  = [abs(r["turn_n"])  for r in legal if r.get("turn_n")  is not None]
    drift_vals = [abs(r["drift_n"]) for r in legal if r.get("drift_n") is not None]
    avg_turn  = _mean(turn_vals)
    avg_drift = _mean(drift_vals)
    big_turn_pct = sum(1 for t in turn_vals if t >= 5.0) / len(turn_vals) * 100 if turn_vals else None

    # ── Zones & danger ───────────────────────────────────────────────────────────
    line_zones = build_line_zones(hand)
    length_zones = {
        "Zones":      LENGTH_ZONES_PACE if is_pace else LENGTH_ZONES_SPIN,
        "1m bands":   LENGTH_ZONES_1M,
        "0.5m bands": LENGTH_ZONES_05M,
    }[length_mode]

    beaten_df = [r for r in df if r.get("is_beaten")]

    # ── Length match-ups (on the hand-filtered set, all positions/overs) ─────────
    new_ball = _len_stats([r for r in hand_df if r.get("over_n") is not None and r["over_n"] < 10])
    old_ball = _len_stats([r for r in hand_df if r.get("over_n") is not None and r["over_n"] >= 40])
    pos_groups = {
        "Top 3": _len_stats([r for r in hand_df if (r.get("bat_pos_n") or 0) in (1, 2, 3)]),
        "4–7":   _len_stats([r for r in hand_df if (r.get("bat_pos_n") or 0) in (4, 5, 6, 7)]),
        "Tail":  _len_stats([r for r in hand_df if (r.get("bat_pos_n") or 0) >= 8]),
    }

    # ── Movement: percentile vs same-type bowlers + in/out direction ─────────────
    mp = load_movement_profiles().get(str(bowler_id), {})
    movement = None
    if mp:
        movement = {
            "pace_spin": mp.get("pace_spin"),
            "avg_swing": _safe_float(mp.get("avg_swing")),   "swing_pctl": _safe_float(mp.get("swing_pctl")),
            "avg_seam": _safe_float(mp.get("avg_seam")),     "seam_pctl": _safe_float(mp.get("seam_pctl")),
            "avg_bounce": _safe_float(mp.get("avg_bounce")), "bounce_pctl": _safe_float(mp.get("bounce_pctl")),
            "swing_dir": _dir_split(legal, "drift_n"),   # movement_in_air
            "seam_dir":  _dir_split(legal, "turn_n"),    # movement_off_pitch
        }

    return {
        # identity
        "bowler_id": str(bowler_id), "name": name, "team": team, "flag": flag,
        "primary_type": primary_type, "is_pace": is_pace, "is_spin": is_spin,
        # delivery lists + zones (for figures)
        "raw": raw, "df": df, "legal": legal, "beaten_df": beaten_df,
        "line_zones": line_zones, "length_zones": length_zones,
        "speed_p05": speed_p05, "speed_p95": speed_p95,
        "filters": {"hand": hand, "position": position, "spell": spell, "length_mode": length_mode},
        # headline
        "n_balls": n_balls, "n_wkts": n_wkts, "runs": runs_tot,
        "economy": runs_tot / (n_balls / 6) if n_balls else None,
        "bowl_avg": runs_tot / n_wkts if n_wkts else None,
        "strike_rate": n_balls / n_wkts if n_wkts else None,
        "avg_spd": avg_spd, "max_spd_99": max_spd_99,
        "avg_len_m": avg_len_m, "short_pct": short_pct, "common_len_band": common_len_band,
        "new_ball": new_ball, "old_ball": old_ball, "pos_groups": pos_groups,
        "movement": movement,
        "round_pct": round_pct, "round_lhb": round_lhb, "round_rhb": round_rhb,
        "slower_ball_pct": slower_ball_pct, "slower_ball_kph": slower_ball_kph,
        "scoring": _scoring_profile(df),
        "over_round": _over_round(df, line_zones),
        "ball_types": classify_balls(df, is_pace, is_spin),
        "sequencing": _sequencing(df),
        "seq_patterns": _sequencing_patterns(raw, is_pace, is_spin),
        "repeatability": load_repeatability_profiles().get(str(bowler_id)),
        "crease": _crease_usage(raw),
        "crease_ref": load_crease_profiles().get(str(bowler_id)),
        "fingerprint": _fingerprint(bowler_id, is_pace, is_spin),
        # threat
        "beaten_pct": beaten_pct, "false_pct": false_pct, "n_tracked": n_tracked,
        "dismissal_counts": dismissal_counts, "n_dismissals": n_dismissals, "top_dismissal": top_dismissal,
        "catch_pos_counts": catch_pos_counts, "n_caught": n_caught,
        "caught_behind": caught_behind, "caught_field": caught_field,
        "avg_turn": avg_turn, "avg_drift": avg_drift, "big_turn_pct": big_turn_pct,
        "stock": zone_concentration(legal, line_zones, length_zones, "count"),
        # trends
        "spd_spell1": spd_spell1, "spd_spell2": spd_spell2, "spd_spell3p": spd_spell3p,
        "spd_inn1": spd_inn1, "spd_inn2": spd_inn2,
        "len_spell1": len_spell1, "len_spell2": len_spell2, "len_spell3p": len_spell3p,
        # danger
        "wkt_zone": zone_concentration(df, line_zones, length_zones, "wickets"),
        "run_zone": zone_concentration(df, line_zones, length_zones, "runs"),
        "danger_line": danger_line(df, line_zones),
        "danger_length": danger_length(df, length_zones),
        "danger_cell": danger_cell(df, line_zones, length_zones),
        # short ball (pace)
        "sb_wkts": sb_wkts, "sb_runs": sb_runs, "sb_econ": sb_econ, "sb_n": len(short_balls),
    }
