from cricket_core.config import DATA_SCHEMA  # re-export — single source of truth


def _ambidextrous_bowlers() -> dict:
    """{bowler_id: why} — bowlers who switch arms, so one style+hand code can't describe them.

    The warehouse stamps every delivery with the player's registered style and hand, so Tharindu
    Rathnayake's left-arm orthodox balls come through as right-arm off spin. They stay in the macro
    pace/spin groups (the ball is still spin) and drop out of the exact-type reels and profiles,
    which is where showing the wrong bowler actually misleads."""
    import json as _json
    import os as _os
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data",
                      "bowler_type_overrides.json")
    try:
        return _json.load(open(p, encoding="utf-8")).get("ambidextrous") or {}
    except Exception:
        return {}


AMBIDEXTROUS_BOWLERS = _ambidextrous_bowlers()

# Player photos come from photos/ (filled by fetch_photos.py off cricket.com.au's static
# host, mapped via photos/ca_ids.csv). The old SharePoint/Graph backend was retired
# 2026-07-15 — no photo config needed any more; see photos.py.
