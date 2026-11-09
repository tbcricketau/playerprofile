from cricket_core.config import DATA_SCHEMA  # re-export — single source of truth


def _type_overrides() -> dict:
    import json as _json
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data",
                      "bowler_type_overrides.json")
    try:
        return _json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


_OVERRIDES = _type_overrides()

# {bowler_id: why} — bowlers who switch arms, so one style+hand code can't describe them.
# The warehouse stamps every delivery with the player's registered style and hand, so Tharindu
# Rathnayake's left-arm orthodox balls come through as right-arm off spin. They stay in the macro
# pace/spin groups (the ball is still spin) and drop out of the exact-type reels and profiles,
# which is where showing the wrong bowler actually misleads.
AMBIDEXTROUS_BOWLERS = _OVERRIDES.get("ambidextrous") or {}

# {bowler_id: {"why", "leg": [ids], "off": [ids]}} — spinners who bowl both off spin and leg spin
# with one arm (Saim Ayub, Tom 09-11-2026). Each ball is typed by its coded variation
# (Deliveries.ball_movement_id, lookup 2812): a leg id reads as leg spin, an off id as off spin, and
# any other ball of theirs goes the arm-switchers' way, out of the exact types and into the macro
# spin group. Their registered style is not used, because it is what the feed changed.
PER_BALL_TYPE_BOWLERS = {k: v for k, v in (_OVERRIDES.get("per_ball") or {}).items() if not k.startswith("_")}

# Player photos come from photos/ (filled by fetch_photos.py off cricket.com.au's static
# host, mapped via photos/ca_ids.csv). The old SharePoint/Graph backend was retired
# 2026-07-15 — no photo config needed any more; see photos.py.
