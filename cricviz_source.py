"""
cricviz_source.py — fill the warehouse's lag from the CricViz Data API, in the WAREHOUSE row shape.

The warehouse is loaded from the CricViz feed, but not at once: on 28-10-2026 it held nothing of
England's ODI tri-series with Sri Lanka and Pakistan (20, 22 and 25 October), and England's last
match in it was 27-09. Tom's rule that day: when the warehouse has not caught up, pull the ball data
from the CricViz Data API first and the video from the Cricket-21 portal.

    python cricviz_source.py pull --country ENG --from 2026-10-01      # cache what the warehouse lacks
    python cricviz_source.py clips                                     # link each ball to its C21 clip
    python cricviz_source.py status                                    # cached, and still a gap?

The video comes second, from the Cricket-21 portal: import the competition into the mirror
(`cricket21/bulk_import.py --comps <id> --white`, which takes over the portal's single session, so
ask Tom first), then `clips` writes each ball's clip link into the cache. Done 28-10-2026 for the
tri-series (competition 3785): 1,729 of 1,730 balls linked, the batter's hand and the dismissal agree
on all 1,730, and a sample of 40 clips all serve. audit_pack_hands resolves these clips through
`delivery_facts` here, because the mirror's player map does not hold England's players.

A pulled match is written to `data/cricviz/<cricviz id>.json` (gitignored: this repo is public, and the
feed is licensed business to business). Every loader that reads deliveries then adds that match's
balls — `data_loaders._warehouse_bowler_rows`, `batting_loaders._warehouse_batter_rows`,
`load_batter_innings`, `load_batter_catch_positions` — until the warehouse holds the match itself
(`MatchExternalIds` type 40), at which point the cached copy is ignored and the warehouse's wins. So a
pull is a stop-gap that retires itself; nothing has to be undone when the data team catches up.

**Calibrated, not assumed (28-10-2026).** England v Sri Lanka, 22, 24 and 27 September, are in both
sources. Joined ball for ball (the n-th delivery of each innings), all 1,622 agree on bowler, striker,
over and runs off the bat, and the coded fields are the warehouse's own ids:

- `batting_connection_id` IS `shot_quality_id` (1,622 of 1,622), so false-shot rates carry over.
- `ball_detail_id` IS `ball_movement_id`, except 16 ("left-arm orthodox stock"), which is 1.
- shot names, feet ids and dismissal names map one to one (`_STROKE`, `_FEET`, `_HOW_OUT`).
- the wagon pair is a different polar: CricViz measures from near the middle of the ground. Fitted:
  rotate 272 deg the other way round, shift 23 units toward the bowler, mirror a left-hander, scale
  the length by 0.54 — median 1.8 deg off the warehouse angle, 90th percentile 5.6 (397 placed balls).

**What CricViz does not carry is ball tracking**: no pitch coordinates, no speed, no movement, no
release. A pulled ball looks exactly like an untracked warehouse ball (pitch_length -20000, the stumps
pair 0 / -1), so every zone, length and speed figure is built from the tracked warehouse balls alone,
by the rules that already fence off an untracked one. The zone GROUP ids are left "None" rather than
copied from the warehouse's untracked shape, which stamps the fullest bucket (see CLAUDE.md).

Not filled from here — they query the warehouse in SQL of their own: the all-formats fallback facts and
batting role in build_opponent_about, build_shot_matrix, build_h2h, attack_cards, and matchupmodel's
profile CSVs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "cricviz")
CV_TYPE = 40                                   # ExternalIdTypes: CricViz

# id spaces of our own, so a pulled row can never collide with a warehouse id (7 and 16 digits)
MATCH_PREFIX, BALL_PREFIX, PLAYER_PREFIX = "88", "88", "77"

COUNTRY = {"ENG": 1, "AUS": 2, "SA": 3, "WI": 4, "NZ": 5, "IND": 6, "PAK": 7, "SL": 8, "ZIM": 9,
           "BAN": 10}
_CLASS_FMT = {"1": "Test", "2": "ODI", "3": "T20I"}          # CricViz class id -> our format
_MATCH_LENGTH = {"Test": "5", "ODI": "1", "T20I": "7"}       # Matches.match_length_id, 2025-26
_ML_NAME = {"Test": "5 Day", "ODI": "1 Day", "T20I": "T20"}
_SERIES = {"Test": "International Tests M", "ODI": "International ODI M",
           "T20I": "International T20 M"}

# CricViz name -> warehouse id, every one measured 1:1 on the 1,622 calibration balls
_STROKE = {"leave": "1", "shoulders arms": "1", "backward defensive": "3", "forward defensive": "4",
           "cut": "6", "drive": "7", "pull": "8", "sweep": "9", "glance": "10", "slog": "12",
           "no shot": "14", "slog-sweep": "15", "hook": "16", "scoop": "17", "upper cut": "17",
           "reverse sweep": "18", "worked": "19", "pushed": "20", "flick": "21", "steer": "22",
           "late cut": "23", "fended": "24", "dropped": "25", "switch hit": "27", "reverse scoop": "32"}
_FEET = {"1": "1", "2": "3", "3": "4", "4": "7", "5": "4", "6": "10", "7": "8", "8": "9", "9": "6"}
_HOW_OUT = (("caught", "5"), ("bowled", "4"), ("leg before", "6"), ("run out", "9"),
            ("stumped", "8"), ("hit wicket", "7"))
_BOWLER_OUT = {"4", "5", "6", "7", "8"}

# the wagon fit (module docstring)
_W_ROT, _W_SENSE, _W_DY, _W_SCALE = 272.0, -1.0, 23.0, 0.54


def _wagon(direction, magnitude, lhb):
    """CricViz (field_direction, field_magnitude) -> the warehouse's batter-relative
    (hit_to_angle, hit_to_length). A zero magnitude is no placement, as a zero length is there."""
    try:
        d, m = float(direction), float(magnitude)
    except (TypeError, ValueError):
        return "None", "None"
    if m <= 0:
        return "0", "0"
    a = math.radians(_W_SENSE * d + _W_ROT)
    px, py = m * math.sin(a), m * math.cos(a) + _W_DY
    ang = math.degrees(math.atan2(px, py))
    if lhb:
        ang = -ang
    ang = (ang + 180) % 360 - 180
    return f"{ang:.1f}", f"{min(100.0, math.hypot(px, py) * _W_SCALE):.1f}"


def _how_out(name):
    n = str(name or "").lower()
    if "caught" in n and "bowled" in n:              # caught and bowled is a catch
        return "5"
    for key, hid in _HOW_OUT:
        if key in n:
            return hid
    return "0" if not n else "None"


def _style_from_desc(desc):
    """(bowler_style_id, bowler_hand_id, bowler_pace_spin_id) from CricViz's bowling description,
    for a bowler the warehouse has never seen. A known bowler takes their warehouse coding instead:
    the warehouse codes by player, so 'Left-arm medium-fast' is 3 for one bowler while
    'Right-arm medium-fast' is 2 for another (both in the calibration set)."""
    d = str(desc or "").lower()
    hand = "2" if d.startswith("left") else "1"
    if "off-break" in d or "orthodox" in d:
        return "4", hand, "2"
    if "leg-break" in d or "unorthodox" in d or "wrist" in d:
        return "5", hand, "2"
    if "medium" in d.split("-arm ")[-1][:6]:
        return "3", hand, "1"
    return "2", hand, "1"


# ── the cache ────────────────────────────────────────────────────────────────────

def _files():
    return sorted(glob.glob(os.path.join(CACHE, "*.json")))


def enabled() -> bool:
    return os.environ.get("PLAYERPROFILE_CRICVIZ", "1") != "0" and bool(_files())


_state: dict | None = None


def _load_state(keep_held=False):
    """Read every cached match once per process, drop those the warehouse now holds, and resolve
    players, teams and bowler coding in one warehouse round trip. `keep_held` keeps them, which is
    only for checking a conversion against the warehouse's own copy (`compare`)."""
    global _state
    if _state is not None:
        return _state
    _state = {"matches": {}, "players": {}, "teams": {}, "styles": {}, "look": {}, "fielding": {}}
    if not enabled():
        return _state
    docs = {}
    for f in _files():
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        docs[str(d["match"]["match_id"])] = d
    if not docs:
        return _state

    from cricket_core.config import DATA_SCHEMA as S
    from cricket_core.warehouse import run_query, set_conn_cursor
    conn, cur = set_conn_cursor()
    try:
        ids = ",".join(docs)
        held = {str(r["cv"]) for r in run_query(
            f"SELECT value_as_int32 AS cv FROM [{S}].[MatchExternalIds] WHERE external_id_type_id = {CV_TYPE} "
            f"AND value_as_int32 IN ({ids}) AND match_id IN (SELECT DISTINCT match_id FROM [{S}].[Deliveries])",
            conn, cur)}
        live = {k: v for k, v in docs.items() if keep_held or k not in held}
        if held and not keep_held:
            print(f"  cricviz_source: {len(held)} cached match(es) now in the warehouse, using the "
                  f"warehouse's copy: {', '.join(sorted(held))}", file=sys.stderr)
        _state["matches"] = live
        if not live:
            return _state
        pids = sorted({str(b.get(k)) for d in live.values() for b in d["ball"]
                       for k in ("batting_player_id", "bowling_player_id", "nonstriker_player_id",
                                 "out_player_id") if str(b.get(k) or "0") not in ("0", "None")})
        for i in range(0, len(pids), 900):
            for r in run_query(
                    f"SELECT player_id, value_as_int32 AS cv FROM [{S}].[PlayerExternalIds] "
                    f"WHERE external_id_type_id = {CV_TYPE} AND value_as_int32 IN ({','.join(pids[i:i + 900])})",
                    conn, cur):
                _state["players"][str(r["cv"])] = str(r["player_id"])
        tids = sorted({str(b.get(k)) for d in live.values() for b in d["ball"]
                       for k in ("batting_team_id", "bowling_team_id")})
        for r in run_query(f"SELECT T.team_id, T.team_name, X.value_as_int32 AS cv FROM [{S}].[TeamExternalIds] X "
                           f"JOIN [{S}].[Teams] T ON T.team_id = X.team_id WHERE X.external_id_type_id = {CV_TYPE} "
                           f"AND X.value_as_int32 IN ({','.join(tids)}) AND T.team_name LIKE '% M'", conn, cur):
            _state["teams"][str(r["cv"])] = (str(r["team_id"]), r["team_name"])
        bowlers = sorted({_state["players"][str(b["bowling_player_id"])] for d in live.values()
                          for b in d["ball"] if str(b["bowling_player_id"]) in _state["players"]})
        if bowlers:
            rows = run_query(f"""SELECT bowler_id, bowler_style_id, bowler_hand_id, bowler_pace_spin_id, COUNT(*) n
                FROM [{S}].[Deliveries] WHERE bowler_id IN ({','.join(bowlers)})
                GROUP BY bowler_id, bowler_style_id, bowler_hand_id, bowler_pace_spin_id""", conn, cur)
            for r in sorted(rows, key=lambda r: int(r["n"])):          # the most common wins
                _state["styles"][str(r["bowler_id"])] = (r["bowler_style_id"], r["bowler_hand_id"],
                                                         r["bowler_pace_spin_id"])
        for r in run_query(f"SELECT lookup_type_id, id, description FROM [{S}].[Lookups] "
                           f"WHERE lookup_type_id IN (10, 24, 2805, 2812, 33)", conn, cur):
            _state["look"][(str(r["lookup_type_id"]), str(r["id"]))] = r["description"]
    finally:
        conn.close()
    _state["fielding"] = _fielding_names(_state["look"])
    return _state


def _fielding_names(look):
    """CricViz 'short extra cover' -> the warehouse's 'Cover: short extra' (lookup 33)."""
    out = {}
    for (t, i), desc in look.items():
        if t != "33" or ":" not in desc:
            continue
        area, q = (s.strip().lower() for s in desc.split(":", 1))
        names = [f"{q} {area}", q] + ([area] if q == "regulation" else [])
        for n in names:
            out.setdefault(n, i)
    return out


def _pid(st, cvid):
    cvid = str(cvid or "0")
    if cvid in ("0", "None", ""):
        return "None"
    return st["players"].get(cvid, PLAYER_PREFIX + cvid)


def _rows_for(match):
    """One cached match -> rows in the warehouse shape (a superset of the bowling and batting
    loaders' columns, all strings)."""
    st = _state
    meta, balls = match["match"], match["ball"]
    fmt = next((_CLASS_FMT[str(c.get("id"))] for c in (meta.get("class") or [])
                if str(c.get("id")) in _CLASS_FMT), None)
    if fmt is None:
        return fmt, []
    date = str(meta.get("start_date") or "")[:10]
    mid = MATCH_PREFIX + str(meta["match_id"])
    teams = {k: st["teams"].get(str(meta.get(f"{k}_id")), (None, meta.get(f"{k}_name")))
             for k in ("team1", "team2")}
    ta, tb = teams["team1"][1] or "", teams["team2"][1] or ""
    ta = ta if ta.endswith(" M") else f"{ta} M"
    tb = tb if tb.endswith(" M") else f"{tb} M"
    dd = f"{date[8:10]}-{date[5:7]}-{date[:4]}"
    season = str(meta.get("season") or date[:4])
    facts = {"match_id": mid, "match_date": date, "match_length_id": _MATCH_LENGTH[fmt],
             "season": season, "gender_id": "1", "match_name": f"{_ML_NAME[fmt]} {ta} v {tb} {dd}",
             "venue_country": str(meta.get("country_name") or "None"),
             "venue_city": str(meta.get("ground_city") or "None"), "competition": _SERIES[fmt]}
    look = st["look"]
    order = sorted(balls, key=lambda b: (int(b["innings_number"]), int(b["innings_ball_number"])))
    arrival: dict = {}
    out = []
    for b in order:
        inn = str(b["innings_number"])
        arr = arrival.setdefault(inn, {})
        for k in ("batting_player_id", "nonstriker_player_id"):
            arr.setdefault(str(b.get(k)), len(arr) + 1)
        striker, bowler = _pid(st, b["batting_player_id"]), _pid(st, b["bowling_player_id"])
        lhb = str(b.get("batting_hand")) == "left"
        style = st["styles"].get(bowler) or _style_from_desc(b.get("bowling_desc"))
        sty, hnd, ps = (str(x) for x in style)
        wide, nb = int(b.get("wides") or 0), int(b.get("noballs") or 0)
        how = _how_out(b.get("dismissal_name"))
        out_pid = _pid(st, b.get("out_player_id"))
        # `is_out`, not the dismissals list: that also carries 'retired not out (hurt)', which the
        # warehouse does not count (the one disagreement in the 1,622 calibration balls)
        is_out = str(b.get("is_out")) == "1"
        by_bowler = str(b.get("is_dismissal_by_bowler")) == "1" or (is_out and how in _BOWLER_OUT)
        ang, ln = _wagon(b.get("field_direction"), b.get("field_magnitude"), lhb)
        stroke_id = _STROKE.get(str(b.get("batting_shot") or "").lower(), "None")
        mv = str(b.get("ball_detail_id") or "None")
        mv = "1" if mv == "16" else mv
        feet = _FEET.get(str(b.get("batting_feet_id")), "None")
        bteam = st["teams"].get(str(b.get("batting_team_id")), ("None",))[0]
        fteam = st["teams"].get(str(b.get("bowling_team_id")), ("None",))[0]
        catch_pos = "None"
        if how == "5":
            for f in b.get("fielding") or []:
                if "catch" in str(f.get("fielding_action") or ""):
                    catch_pos = st["fielding"].get(str(f.get("fielding_position") or "").lower(), "None")
        tf = lambda v: "True" if v else "False"
        r = dict(facts)
        r.update({
            "delivery_id": BALL_PREFIX + str(b["ball_id"]), "striker_id": striker, "bowler_id": bowler,
            "video_file_name": "None", "c21_video_url": str(b.get("c21_video_url") or "None"),
            "match_innings": inn, "over": str(b["over_number"]),
            "ball_in_over": str(b["ball_number"]), "bowler_spell": str(b.get("bowling_spell") or "None"),
            "match_day": str(b.get("day_number") or "1"),
            "striker_batting_position": str(arr.get(str(b["batting_player_id"]), "None")),
            "team_batting_id": bteam, "team_bowling_id": fteam,
            "over_the_wicket": {"over": "True", "round": "False"}.get(str(b.get("bowling_from")), "None"),
            "bowler_variation": "False", "legal_ball": "0" if (wide or nb) else "1",
            "wide_runs": str(wide), "noball_runs": str(nb), "bat_score": str(b.get("runs_off_bat") or 0),
            "hit_to_x_physical": "None", "hit_to_y_physical": "None",
            "hit_to_length": ln, "hit_to_angle": ang,
            "bowler_dismissal": tf(by_bowler),
            "striker_dismissed": tf(is_out and out_pid == striker),
            "batter_dismissal": tf(is_out), "how_out_id": how,
            "batter_out_id": out_pid if is_out else "None",
            "shot_quality_id": str(b.get("batting_connection_id") or "None"),
            "stroke_id": stroke_id, "stroke": look.get(("24", stroke_id), "None"),
            "striker_movement_id": feet, "striker_movement": look.get(("2812", feet), "None"),
            "off_bat_angle": "None", "off_bat_speed": "None", "batter_missed_id": "None",
            # no tracking in the CricViz feed: the warehouse's own untracked shape
            "ball_speed": "None", "pitch_line": "0", "pitch_length": "-20000",
            "pitch_line_coded": "0", "pitch_length_coded": "-20000",
            "at_stumps_line": "0", "at_stumps_height": "-1",
            "movement_in_air": "None", "movement_off_pitch": "None",
            "movement_in_air_group_swing_id": "None", "movement_off_pitch_group_seam_id": "None",
            "ball_movement_id": mv, "ball_movement": look.get(("2812", mv), "None"),
            "release_line_unmirrored": "None", "release_height": "None", "bounce_angle_delta": "None",
            "striker_hand_id": "2" if lhb else "1", "striker_hand": look.get(("10", "2" if lhb else "1"), "None"),
            "bowler_style_id": sty, "bowler_hand_id": hnd, "bowler_pace_spin_id": ps,
            "bowler_pace_spin": look.get(("2805", ps), "None"),
            "bowler_type_simple": _type_simple(sty, hnd),
            "pitch_length_group_pace": "None", "pitch_length_group_pace_2": "None",
            "pitch_line_group_pace": "None", "pitch_length_group_spin": "None",
            "pitch_line_group_spin": "None", "pitch_length_group_pace_1_id": "None",
            "pitch_length_group_pace_2_id": "None", "pitch_line_group_pace_id": "None",
            "pitch_length_group_spin_1_id": "None", "pitch_line_group_spin_id": "None",
            "source": "cricviz", "_catch_pos": catch_pos, "_cv_match": str(meta["match_id"]),
        })
        out.append(r)
    return fmt, out


def _type_simple(style, hand):
    """The loaders' CASE expression, so a pulled row's type reads exactly as a warehouse one."""
    if style in ("1", "2"):
        return "Right Fast" if hand == "1" else "Left Fast"
    if style == "3":
        return "Right Medium" if hand == "1" else "Left Medium"
    if style == "4":
        return "Off Spin" if hand == "1" else "Left Orthodox"
    if style == "5":
        return "Leg Break" if hand == "1" else "Left Unorthodox"
    return "Other"


_converted: dict | None = None


def _all_rows():
    global _converted
    if _converted is None:
        st = _load_state()
        _converted = {}
        for m in st["matches"].values():
            fmt, rows = _rows_for(m)
            if fmt:
                _converted.setdefault(fmt, []).extend(rows)
    return _converted


def _in_scope(fmt, level):
    """Only senior internationals are pulled. The pooled T20 scope takes the T20Is too."""
    if level != "international":
        return []
    rows = _all_rows()
    if fmt == "T20":
        return rows.get("T20I", [])
    return rows.get(fmt, [])


def _public(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def bowler_rows(bowler_id, fmt="Test", level="international"):
    if not enabled():
        return []
    return [_public(r) for r in _in_scope(fmt, level) if r["bowler_id"] == str(bowler_id)]


def batter_rows(batter_id, fmt="Test", level="international"):
    if not enabled():
        return []
    return [_public(r) for r in _in_scope(fmt, level) if r["striker_id"] == str(batter_id)]


def batter_innings(batter_id, fmt="Test", level="international"):
    """`batting_loaders.load_batter_innings` rows for the pulled matches."""
    if not enabled():
        return []
    rows = _in_scope(fmt, level)
    bid = str(batter_id)
    mine = {r["match_id"] for r in rows if r["striker_id"] == bid}
    inn: dict = {}
    for r in rows:
        if r["match_id"] not in mine:
            continue
        k = (r["match_id"], r["match_innings"])
        t = inn.setdefault(k, {"team_bat": 0, "his_runs": 0, "his_balls": 0, "his_out": 0})
        runs = int(r["bat_score"] or 0)
        t["team_bat"] += runs
        if r["striker_id"] == bid:
            t["his_runs"] += runs
            t["his_balls"] += r["legal_ball"] == "1"
            t["his_out"] = max(t["his_out"], int(r["striker_dismissed"] == "True"))
    match_bat: dict = {}
    for (m, _i), t in inn.items():
        match_bat[m] = match_bat.get(m, 0) + t["team_bat"]
    return [{"match_id": m, "match_innings": i, "team_bat": str(t["team_bat"]),
             "his_runs": str(t["his_runs"]), "his_balls": str(t["his_balls"]), "his_out": str(t["his_out"]),
             "match_bat": str(match_bat[m])}
            for (m, i), t in sorted(inn.items()) if t["his_balls"] > 0]


def batter_catch_positions(batter_id, fmt="Test", level="international"):
    if not enabled():
        return {}
    return {r["delivery_id"]: (None if r["_catch_pos"] == "None" else r["_catch_pos"])
            for r in _in_scope(fmt, level)
            if r["striker_id"] == str(batter_id) and r["striker_dismissed"] == "True" and r["how_out_id"] == "5"}


def merge(base, extra):
    """Warehouse rows plus pulled rows, in the loaders' order."""
    if not extra:
        return base
    key = lambda r: (str(r.get("match_date") or ""), int(r.get("match_innings") or 0),
                     int(r.get("over") or 0), int(r.get("ball_in_over") or 0))
    return sorted(list(base) + list(extra), key=key)


# ── the pull ─────────────────────────────────────────────────────────────────────

def _client():
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scorecarddb"))
    from scorecarddb.cricviz import CricViz              # reads its own gitignored .env
    return CricViz()


def _bbb(cv, cvid):
    balls, page = [], 1
    while page:
        d = cv._raw(f"match/{cvid}/bbb?page={page}")
        balls += d.get("ball") or []
        page = (d.get("page") or {}).get("next_page")
        time.sleep(1.0)
    return balls


def pull(country, start, end, force=False):
    """Cache every senior international the country played in the window that the warehouse does
    not hold ball by ball. Returns the ids written."""
    from cricket_core.config import DATA_SCHEMA as S
    from cricket_core.warehouse import run_query, set_conn_cursor
    cv = _client()
    ms = [m for m in cv.results(min_start_date=start, max_start_date=end, team_country_id=COUNTRY[country])
          if any(str(c.get("id")) in _CLASS_FMT for c in (m.get("class") or []))
          and str(m.get("live_status_name") or "").lower() not in ("upcoming", "scheduled")]
    if not ms:
        print("no results in the window")
        return []
    conn, cur = set_conn_cursor()
    ids = ",".join(str(m["match_id"]) for m in ms)
    held = {str(r["cv"]) for r in run_query(
        f"SELECT value_as_int32 AS cv FROM [{S}].[MatchExternalIds] WHERE external_id_type_id = {CV_TYPE} "
        f"AND value_as_int32 IN ({ids}) AND match_id IN (SELECT DISTINCT match_id FROM [{S}].[Deliveries])",
        conn, cur)}
    conn.close()
    os.makedirs(CACHE, exist_ok=True)
    wrote = []
    for m in sorted(ms, key=lambda m: m["start_date"]):
        cvid = str(m["match_id"])
        dest = os.path.join(CACHE, f"{cvid}.json")
        label = f"{cvid} {m['start_date'][:10]} {m.get('team1_name')} v {m.get('team2_name')}"
        if cvid in held:
            print(f"  in the warehouse   {label}")
            continue
        if os.path.exists(dest) and not force:
            print(f"  already cached     {label}")
            continue
        balls = _bbb(cv, cvid)
        if not balls:
            print(f"  no ball-by-ball    {label}")
            continue
        tmp = dest + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"match": m, "ball": balls, "pulled_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, fh)
        os.replace(tmp, dest)
        wrote.append(cvid)
        print(f"  pulled {len(balls):4d} balls {label}")
    return wrote


def attach_clips():
    """Write each cached ball's Cricket-21 clip link into the cache, from the Cricket-21 mirror
    (`cricket21/bulk_import.py --comps <id> --white` first). The clip goes into the cached file, not
    into a lookup at load time, so a machine with the cache and no mirror (the build box) plays it.

    A C21 match is found by date and the two team names, and its deliveries are lined up with
    CricViz's by order within each innings — C21 numbers overs from 0, so (over, ball) never
    matches directly. An innings is linked only when both hold the same number of deliveries and
    runs off the bat, wides and no-balls agree on every one; anything else is left without footage
    and said so, because a clip on the wrong ball is worse than none."""
    import sqlite3
    import c21_source
    con = sqlite3.connect(f"file:{c21_source.MIRROR}?mode=ro", uri=True)
    try:
        for f in _files():
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            m = d["match"]
            date = str(m["start_date"])[:10]
            names = {str(m.get("team1_name")), str(m.get("team2_name"))}
            hit = [r for r in con.execute("SELECT match_id, team_a, team_b FROM matches WHERE match_date = ?", (date,))
                   if {r[1], r[2]} == names]
            label = f"{m['match_id']} {date} {m.get('team1_name')} v {m.get('team2_name')}"
            if len(hit) != 1:
                print(f"  no Cricket-21 match   {label} ({len(hit)} found)")
                continue
            c21 = {}
            for inn, bat, wd, nb, did, url in con.execute(
                    "SELECT match_innings, bat_score, wide_runs, noball_runs, delivery_id, video_url "
                    "FROM deliveries WHERE match_id = ? ORDER BY match_innings, over, ball_in_over, delivery_id",
                    (hit[0][0],)):
                c21.setdefault(str(inn), []).append((int(bat or 0), int(wd or 0), int(nb or 0), did, url))
            cv = {}
            for b in sorted(d["ball"], key=lambda b: (int(b["innings_number"]), int(b["innings_ball_number"]))):
                cv.setdefault(str(b["innings_number"]), []).append(b)
            linked = 0
            for inn, balls in cv.items():
                theirs = c21.get(inn, [])
                same = len(theirs) == len(balls) and all(
                    (int(b.get("runs_off_bat") or 0), int(b.get("wides") or 0), int(b.get("noballs") or 0)) == t[:3]
                    for b, t in zip(balls, theirs))
                for b, t in zip(balls, theirs):
                    b["c21_video_url"] = t[4] if same and t[4] else None
                    b["c21_delivery_id"] = t[3] if same else None
                if same:
                    linked += sum(1 for t in theirs if t[4])
                else:
                    print(f"  innings {inn} does not line up ({len(balls)} CricViz v {len(theirs)} C21) — no clips")
            tmp = f + ".part"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            os.replace(tmp, f)
            print(f"  {linked:4d} of {len(d['ball'])} balls linked to a clip   {label}")
    finally:
        con.close()


_GROUP_OF = {"Right Fast": "right_pace", "Right Medium": "right_pace", "Left Fast": "left_pace",
             "Left Medium": "left_pace", "Off Spin": "off_spin", "Leg Break": "leg_spin",
             "Left Orthodox": "left_orthodox", "Left Unorthodox": "left_unorthodox"}
_COARSE = {"Test": "Test", "ODI": "ODI", "T20I": "T20"}


def delivery_facts(delivery_ids):
    """{delivery_id: {hand, fmt, striker, bowler, group}} for pulled balls — what
    audit_pack_hands needs to check a reel holding them, in the shape c21_source.delivery_facts
    returns. A pulled ball's clip is a Cricket-21 url, but its players are WAREHOUSE ids already,
    which the mirror's player map (Indian, Zimbabwean and South African cricket) could not give."""
    want = {str(i) for i in delivery_ids}
    out = {}
    for fmt, rows in _all_rows().items():
        for r in rows:
            if r["delivery_id"] in want:
                out[r["delivery_id"]] = {"hand": "lhb" if r["striker_hand_id"] == "2" else "rhb",
                                         "fmt": _COARSE[fmt], "striker": r["striker_id"],
                                         "bowler": r["bowler_id"], "group": _GROUP_OF.get(r["bowler_type_simple"])}
    return out


def status():
    st = _load_state()
    for f in _files():
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        m = d["match"]
        gap = str(m["match_id"]) in st["matches"]
        print(f"  {m['match_id']} {m['start_date'][:10]} {m.get('team1_name')} v {m.get('team2_name')}: "
              f"{len(d['ball'])} balls, {'filling a gap' if gap else 'now in the warehouse (ignored)'}")
    unmapped = sorted({r["striker_id"] for rows in _all_rows().values() for r in rows
                       if r["striker_id"].startswith(PLAYER_PREFIX)}
                      | {r["bowler_id"] for rows in _all_rows().values() for r in rows
                         if r["bowler_id"].startswith(PLAYER_PREFIX)})
    if unmapped:
        print(f"  {len(unmapped)} player(s) with no warehouse id (kept under {PLAYER_PREFIX}<cricviz id>)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--country", required=True, choices=sorted(COUNTRY))
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", default=dt.date.today().isoformat())
    p.add_argument("--force", action="store_true")
    sub.add_parser("status")
    sub.add_parser("clips", help="link each cached ball to its Cricket-21 clip, from the mirror")
    a = ap.parse_args()
    if a.cmd == "pull":
        pull(a.country, a.start, a.end, a.force)
    elif a.cmd == "clips":
        attach_clips()
    else:
        status()
