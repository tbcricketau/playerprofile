"""
c21_source.py — read deliveries from the Cricket-21 local mirror in the WAREHOUSE row shape.

The warehouse holds no Indian domestic cricket at all — no Ranji, no Duleep, no Vijay Hazare — so
India A's measurable record there is 25 A-team first-class matches at 38.5% ball-tracking, and eight
of the players we scout have effectively nothing. Cricket-21 has that cricket, tracked at 98-99%
with video on every ball (`cricket21/docs/INDIA_DOMESTIC.md`).

This module is the third **source**, alongside format and level:

    format  the shape of the game        Test / ODI / T20I
    level   the standard of the game     international / a-team
    source  where the ball record is     warehouse / c21 / both

They are orthogonal. A four-day Australia A pack wants Test format, a-team level, and — for an India
A opponent — both sources, because the two are the same cricket recorded by different vendors.

## Why the coordinates can be trusted

`cricket21/docs/VERIFICATION.md` measured C21's raw line axis against the warehouse at r = -0.14:
the two systems mirror left-handers differently, which is the classic way to publish a plan that is
correct for one hand and backwards for the other. `cricket21/calibrate.py` fits the transform
**per hand** (RHB slope -7.54, LHB +8.51 — opposite signs, which IS the mirroring) and reaches
|r| ~ 0.92 for both.

Checked independently on 2026-09-07, warehouse A-team first-class vs the imported Indian domestic:

    RHB  median  warehouse 344   C21 337      LHB  median  warehouse 172   C21 188
         p90               648       662           p90               625       605

Same convention, same distribution, two unrelated sources. Line and length are safe to pool.

## What C21 does NOT carry

`ball_speed` is present on ~78% of the international-standard fixtures and **0.2% of Ranji**, so a
pace card built off Indian domestic cricket has lengths and lines but no speed. Seam/swing movement,
bowler spell and the batter-missed flag are absent entirely and come back None — the consumers all
treat those as optional. Nothing here invents a value it does not have.

## The sentinel, again

An untracked C21 ball has LengthY at or near 0, which the calibration maps to a CLUSTER around its
per-hand intercept: about **-1810 mm for a right-hander, -2195 for a left-hander** (measured
2026-09-07: RHB -1810.2 / -1798.0 / -1785.9, LHB -2195.4 / -2182.9 / -2145.5 — a spread, not one
magic number, so an equality test would miss most of it). It is **14.9% of right-hand and 15.4% of
left-hand deliveries** in the mirror.

Same trap as the warehouse's -20000, different number and no single value to match on.
`is_tracked_length` excludes the lot because it falls outside (-1000, 16000) — which is why every
consumer must use the RANGE, never `is not None` and never an equality check. Nor trust
`c21_adv_length`, which stamps those balls "Full toss" exactly as the warehouse stamps them 10999.
"""
import json
import os
import sqlite3

from cricket_core.config import project_path

HERE = os.path.dirname(os.path.abspath(__file__))
MIRROR = os.path.join(str(project_path("cricket21")), "data", "cricket21_mirror.sqlite")
PLAYER_MAP = os.path.join(HERE, "data", "c21_player_map.json")

# Competitions this module will serve. Deliberately a list, not "everything in the mirror": the
# mirror also holds Bangladesh and South African domestic cricket pulled for other series, and a
# player's record must not silently acquire it.
INDIA_DOMESTIC = ("Ranji", "Duleep", "Hazare", "Irani", "India A")

# C21 bowler_type -> the project's bowler_type_simple vocabulary (cricket_core PACE_TYPES/SPIN_TYPES)
_BOWLER_TYPE = {
    "RAF": "Right Fast", "RAFM": "Right Fast",
    "RAM": "Right Medium", "RAMF": "Right Medium",
    "LAF": "Left Fast", "LAFM": "Left Fast",
    "LAM": "Left Medium", "LAMF": "Left Medium",
    "RAO": "Off Spin", "RALB": "Leg Break",
    "SLAO": "Left Orthodox", "LAC": "Left Unorthodox", "SLAW": "Left Unorthodox",
}
# (bowler_style_id, bowler_hand_id) so the batting side's derived CASE agrees with ours
_STYLE_HAND = {
    "Right Fast": ("1", "1"), "Left Fast": ("1", "2"),
    "Right Medium": ("3", "1"), "Left Medium": ("3", "2"),
    "Off Spin": ("4", "1"), "Left Orthodox": ("4", "2"),
    "Leg Break": ("5", "1"), "Left Unorthodox": ("5", "2"),
}
# C21 how_out -> warehouse how_out_id (lookup 2806)
_HOW_OUT = {"Bowled": "4", "Caught": "5", "LBW": "6", "HitWicket": "7", "Hit Wicket": "7",
            "Stump": "8", "Stumped": "8", "RunOut": "9", "Run Out": "9"}
_BOWLER_OUT = {"4", "5", "6", "7", "8"}          # run-out is not the bowler's
# C21 shot_connection -> warehouse shot_quality_id (lookup 2811). Only the ones that carry meaning
# for the false-shot definition are mapped; the rest stay None rather than guess an id.
_SHOT_Q = {"Good contact": "1", "Outside edge": "3", "Inside edge": "4",
           "Hit pad": "6", "Bottom edge": "10", "Top edge": "14", "Shoulder of bat": "17"}

# C21 stroke -> the warehouse stroke NAME, which cricket_core.STROKE_FAMILY then groups.
#
# The two vocabularies barely overlap: of 32 C21 stroke names only five ("Worked", "Flick",
# "Steer", "Slog", "Glance") are warehouse spellings. Passed through raw, every other C21 ball
# produced stroke_family=None, so a batter with 500 C21 balls and 60 warehouse ones would have had
# their "go-to shot" — a headline card fact — derived from the 60, silently. C21 is also FINER than
# the warehouse (Cover/Off/On/Straight/Square Drive all collapse to "Drive"), so this loses detail
# by design rather than inventing a category the warehouse does not have.
_STROKE = {
    "Cover Drive": "Drive", "Off Drive": "Drive", "On drive": "Drive",
    "Straight Drive": "Drive", "Square drive": "Drive", "Inside out": "Drive",
    "Square Cut": "Cut or dab", "Late Cut": "Late cut",
    "Upper Cut": "Cut or dab", "UpperCut": "Cut or dab",
    "Pull shot": "Pull", "Hook Shot": "Hook",
    "Sweep Shot": "Sweep", "Slog Sweep": "Slog sweep", "Reverse Sweep": "Reverse sweep",
    "Paddle Sweep": "Paddle", "Paddle Scoop": "Ramp", "Reverse Paddle Scoop": "Ramp",
    "Switch": "Switch hit",
    "Push": "Pushed", "Leg Glance": "Glance", "PickUp": "Flick",
    "Frontfoot defensive": "Forward defence", "Backfoot defensive": "Backward defence",
    "Defense": "Forward defence", "Intentional Padding": "Padded",
    # already warehouse spellings, listed so the map is the whole vocabulary in one place
    "Worked": "Worked", "Flick": "Flick", "Steer": "Steer", "Slog": "Slog", "Glance": "Glance",
}


def _s(v):
    """Warehouse rows arrive as strings, including the literal 'None'. Match that exactly, or the
    consumers' `not in (None, 'None', ...)` guards behave differently for C21 rows."""
    return "None" if v is None else str(v)


def available() -> bool:
    return os.path.exists(MIRROR)


def _connect():
    if not available():
        raise FileNotFoundError(
            f"no Cricket-21 mirror at {MIRROR} — run cricket21/bulk_import.py (or the India pull "
            f"in cricket21/docs/INDIA_DOMESTIC.md) before asking for source='c21'")
    return sqlite3.connect(f"file:{MIRROR}?mode=ro", uri=True)


def player_map() -> dict:
    """{warehouse_player_id: {"c21_ids": [...], "name": str}} — built by build_c21_player_map.py.

    C21 ids are its own namespace, so nothing joins without this. It is a FILE, not a name match at
    query time, because a name match that silently misses returns zero rows and reads as "this
    player has no data" — which is exactly how Saransh Jain was reported as having none when he has
    2,535 first-class deliveries."""
    if not os.path.exists(PLAYER_MAP):
        return {}
    with open(PLAYER_MAP, encoding="utf-8") as fh:
        return json.load(fh)


_FMT_MATCH = {                       # our format -> C21 mirror `format` values
    "Test": ("First Class",),
    "ODI": ("List A", "ODI", "One Day"),
    "T20I": ("T20", "T20I"),
    "T20": ("T20", "T20I"),
}


def _rows(pid, role, fmt):
    """Raw mirror rows for one player in one format. `role` is 'bowler' or 'striker'."""
    pm = player_map().get(str(pid))
    if not pm or not pm.get("c21_ids"):
        return []
    ids = ",".join(str(int(i)) for i in pm["c21_ids"])
    comps = " OR ".join(f"m.competition_name LIKE '%{k}%'" for k in INDIA_DOMESTIC)
    fmts = _FMT_MATCH.get(fmt, ("First Class",))
    fl = " OR ".join(f"m.format = '{f}'" for f in fmts)
    col = "bowler_id" if role == "bowler" else "striker_id"
    q = f"""
    SELECT d.*, m.match_date, m.competition_name, m.format AS m_format,
           m.team_a, m.team_b, m.venue AS m_venue
    FROM deliveries d JOIN matches m ON m.match_id = d.match_id
    WHERE d.{col} IN ({ids}) AND ({comps}) AND ({fl})
    ORDER BY m.match_date, d.match_innings, d.over, d.ball_in_over
    """
    con = _connect()
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(q)]
    finally:
        con.close()


def _to_warehouse(r):
    """One mirror row -> the warehouse row shape the loaders return (all values strings).

    Only fields C21 actually holds are populated. Everything else is 'None' — the same literal the
    warehouse driver produces — so a consumer cannot tell a missing C21 field from a missing
    warehouse one, and no downstream guard needs to know where the row came from."""
    bt = _BOWLER_TYPE.get(str(r.get("bowler_type") or "").strip())
    style, hand = _STYLE_HAND.get(bt, (None, None))
    wide = r.get("wide_runs") or 0
    nb = r.get("noball_runs") or 0
    how = _HOW_OUT.get(str(r.get("how_out") or "").strip())
    dismissed = str(r.get("dismissal") or "") == "1"
    lhb = str(r.get("striker_hand") or "").strip().upper().startswith("L")
    otw = str(r.get("over_or_round") or "")
    return {
        "match_id": _s(r.get("match_id")), "delivery_id": _s(r.get("delivery_id")),
        "striker_id": _s(r.get("striker_id")), "bowler_id": _s(r.get("bowler_id")),
        "match_date": _s(r.get("match_date"))[:10],
        "season": _s(r.get("match_date"))[:4], "gender_id": "1",
        "match_length_id": "None", "match_name": _s(r.get("competition_name")),
        "match_innings": _s(r.get("match_innings")),
        "over": _s(r.get("over")), "ball_in_over": _s(r.get("ball_in_over")),
        "bowler_spell": "None", "match_day": _s(r.get("match_day")),
        "striker_batting_position": "None",
        "over_the_wicket": ("True" if otw.startswith("Over") else
                            ("False" if otw.startswith("Round") else "None")),
        "bowler_variation": "None",
        "legal_ball": "0" if (wide or nb) else "1",
        "wide_runs": _s(wide), "noball_runs": _s(nb), "bat_score": _s(r.get("bat_score") or 0),
        "hit_to_x_physical": _s(r.get("hit_to_x")), "hit_to_y_physical": _s(r.get("hit_to_y")),
        "hit_to_length": "None", "hit_to_angle": "None",
        "bowler_dismissal": "1" if (dismissed and how in _BOWLER_OUT) else "0",
        "striker_dismissed": "1" if dismissed else "0",
        "how_out_id": _s(how),
        "shot_quality_id": _s(_SHOT_Q.get(str(r.get("shot_connection") or "").strip())),
        "stroke_id": "None", "stroke": _s(_STROKE.get(str(r.get("stroke") or "").strip())),
        "batter_missed_id": "None",
        "ball_speed": _s(r.get("ball_speed")),
        "pitch_line": _s(r.get("pitch_line")), "pitch_length": _s(r.get("pitch_length")),
        "pitch_line_coded": "None", "pitch_length_coded": "None",
        "at_stumps_line": _s(r.get("at_stumps_line")),
        "at_stumps_height": _s(r.get("at_stumps_height")),
        "movement_in_air": "None", "movement_off_pitch": "None",
        "movement_in_air_group_swing_id": "None", "movement_off_pitch_group_seam_id": "None",
        "ball_movement_id": "None", "ball_movement": "None",
        "release_line_unmirrored": "None", "release_height": "None", "bounce_angle_delta": "None",
        "striker_hand_id": "2" if lhb else "1",
        "striker_hand": "Left hand" if lhb else "Right hand",
        "bowler_style_id": _s(style), "bowler_hand_id": _s(hand),
        "bowler_type_simple": _s(bt),
        "bowler_pace_spin": "Spin" if str(r.get("pace_spin")) == "2" else "Pace",
        "bowler_pace_spin_id": _s(r.get("pace_spin")),
        # The warehouse's pre-bucketed zone groups are deliberately NOT synthesised. They are a
        # lookup id space we do not own, and an untracked ball is assigned the fullest bucket in
        # them — the defect documented in CLAUDE.md. Consumers that bin by coordinate work as-is;
        # anything reading a group column gets None and falls through its own gate.
        "pitch_length_group_pace": "None", "pitch_length_group_pace_2": "None",
        "pitch_line_group_pace": "None", "pitch_length_group_spin": "None",
        "pitch_line_group_spin": "None", "pitch_length_group_pace_1_id": "None",
        "pitch_length_group_pace_2_id": "None", "pitch_line_group_pace_id": "None",
        "pitch_length_group_spin_1_id": "None", "pitch_line_group_spin_id": "None",
        "venue_country": "India", "venue_city": _s(r.get("m_venue")),
        "competition": _s(r.get("competition_name")),
        # C21 serves its own clips directly; there is no Fairplay blob for this cricket, so the
        # clip_stem path must not be given something that looks resolvable.
        "video_file_name": "None", "c21_video_url": _s(r.get("video_url")),
        "source": "c21",
    }


def load_bowler_deliveries(bowler_id, fmt="Test"):
    """C21 deliveries bowled by this player, in the warehouse row shape."""
    return [_to_warehouse(r) for r in _rows(bowler_id, "bowler", fmt)]


def load_batter_deliveries(batter_id, fmt="Test"):
    """C21 deliveries faced by this player, in the warehouse row shape."""
    return [_to_warehouse(r) for r in _rows(batter_id, "striker", fmt)]


def clip_ref(row, stem=None):
    """What a playlist item should carry for this delivery: {"clip_stem": …} or {"url": …} or {}.

    Fairplay clips are stored extension-less and resolved with a fresh read SAS at bake time, so
    they travel as a STEM. C21 serves its own clips from hdvod.cricket-21.com at a complete,
    unauthenticated URL — there is nothing to resolve and no SAS to mint — so they travel as a
    finished `url`. `publish_site._refresh_playlists` only touches items that have a `clip_stem`,
    so a direct url passes through every refresh untouched, which is what we want: re-stamping it
    would corrupt it.

    Pass the already-computed Fairplay `stem` if you have one; this only reaches for C21 when there
    is no Fairplay clip, so a warehouse delivery is never displaced by a mirror one."""
    if stem:
        return {"clip_stem": stem}
    u = row.get("c21_video_url")
    if u and u not in (None, "None", "none", ""):
        return {"url": u}
    return {}


def delivery_facts(delivery_ids):
    """{delivery_id: (hand, format)} for C21 deliveries — what audit_pack_hands needs to check a
    reel it cannot look up in the warehouse.

    Without this the hand audit sees a C21 clip, fails to resolve it, and either drops the reel
    (making an unscoped reel look clean) or refuses the publish. A gate that cannot see half the
    footage is the "gate that only checks what it was built to check" failure again."""
    ids = [str(i) for i in delivery_ids if str(i).strip()]
    if not ids or not available():
        return {}
    out = {}
    con = _connect()
    try:
        for i in range(0, len(ids), 800):
            chunk = ids[i:i + 800]
            marks = ",".join("?" * len(chunk))
            q = (f"SELECT d.delivery_id, d.striker_hand, m.format, m.competition_name "
                 f"FROM deliveries d JOIN matches m ON m.match_id = d.match_id "
                 f"WHERE d.delivery_id IN ({marks})")
            for did, hand, fmt, comp in con.execute(q, chunk):
                lhb = str(hand or "").strip().upper().startswith("L")
                f = str(fmt or "")
                # Same red/white vocabulary audit_pack_hands._series_fmt speaks.
                coarse = ("Test" if "class" in f.lower() or "Test" in f
                          else "ODI" if ("list a" in f.lower() or "ODI" in f or "One Day" in f)
                          else "T20" if "T20" in f else "")
                out[str(did)] = ("lhb" if lhb else "rhb", coarse)
    finally:
        con.close()
    return out


def coverage(pid, fmt="Test"):
    """(bowling balls, batting balls) available for a player — for a gate to decide whether to
    reach for C21 at all, without loading the rows."""
    return len(_rows(pid, "bowler", fmt)), len(_rows(pid, "striker", fmt))
