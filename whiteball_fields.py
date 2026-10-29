"""whiteball_fields.py — the automatically generated fields for a white-ball series (Tom, 29-10-2026).

`field_engine` is red-ball: its tactics and trigger norms are Test, and it knows nothing of fielding
restrictions, so white-ball cards had no field at all. What does exist for white-ball is measured
from GPS (catapultgps, reviewed by Dene Hills) and lives in `cricket_core.fields`:

- `gps_corrected_field` — the stock field for a bowler type, batter hand and phase, with the swaps
  GPS shows Australia actually makes;
- `field_menu` — the several real fields Australia sets in that cell, ranked by how often.

So a card gets, per phase, the GPS-corrected field, and the menu's most-set field where it differs.
Neither is adjusted to the individual player, and every option says so. Both are how AUSTRALIA sets
fields: on their bowlers' cards that is a reference for the type, not a read of what that bowler's
captain does.
"""
from cricket_core import fields as F
from cricket_core.lookups import FIELD_POS, field_coords

# the coach view's bowler groups -> cricket_core's two vocabularies
SIMPLE = {"right_pace": "Right Fast", "left_pace": "Left Fast", "off_spin": "Off Spin",
          "left_orthodox": "Left Orthodox", "leg_spin": "Leg Break", "left_unorthodox": "Left Unorthodox"}
MENU = {"right_pace": "RA pace", "left_pace": "LA pace", "off_spin": "Off spin",
        "left_orthodox": "SLA orthodox", "leg_spin": "Leg spin", "left_unorthodox": "SLA unorthodox"}
PHASES = {"ODI": (("odi", "pp1", "Powerplay"), ("odi", "middle", "Middle overs"), ("odi", "death", "Death")),
          "T20": (("t20", "powerplay", "Powerplay"), ("t20", "middle", "Middle overs"), ("t20", "death", "Death"))}


_CHECKED = False


def _need_gps():
    """Refuse rather than fall back. Without catapultgps's field_corrections.csv and field_menu.json,
    gps_corrected_field quietly returns the hand-written stock draft and field_menu returns nothing,
    so a card would claim GPS evidence it does not have. The build box had neither on 29-10-2026."""
    global _CHECKED
    if _CHECKED:
        return
    from cricket_core import gps
    if not gps.load_field_corrections() or not gps.load_field_menu():
        raise RuntimeError(f"GPS field files missing in {gps.data_dir()} (field_corrections.csv, "
                           "field_menu.json) — copy them from catapultgps/data before building white-ball fields")
    _CHECKED = True


def _fmt(fmt):
    f = str(fmt or "").upper()
    return "T20" if f.startswith("T20") else ("ODI" if f == "ODI" else None)


def _pts(names):
    """Position names -> the planner's fielders (batter-relative angle and radius), keeper left out."""
    out = []
    for n in names or []:
        if n == "Keeper":
            continue
        p = FIELD_POS.get(n) or field_coords(n)
        out.append({"angle": round(float(p["angle"]), 1), "radius": round(float(p["radius"]), 3), "label": n})
    return out if len(out) == 9 else []


def phase_fields(fmt, group, hand, menu=True):
    """[{slot, label, fielders, spare, spare_name, adjusted, notes, basis}] for one bowler type and
    batter hand, in phase order. Empty for a Test series or a type cricket_core cannot resolve."""
    fmt = _fmt(fmt)
    if not fmt or group not in SIMPLE:
        return []
    _need_gps()
    out = []
    for key, phase, word in PHASES[fmt]:
        gps = F.gps_corrected_field(key, SIMPLE[group], hand, phase)
        pts = _pts(gps)
        if pts:
            out.append({"label": word, "fielders": pts, "basis":
                        "The stock field for the type in this phase, with the changes GPS shows Australia makes "
                        "(not adjusted to this player)."})
        if not menu:
            continue
        top = next(iter(F.field_menu(key, MENU[group], hand, phase)), None)
        mpts = _pts([p["label"] for p in (top or {}).get("positions", [])]) if top else []
        if mpts and sorted(f["label"] for f in mpts) != sorted(f["label"] for f in pts):
            pct = top.get("freq_pct")
            out.append({"label": f"{word} · most set", "fielders": mpts, "basis":
                        f"Australia's most-set field in this cell, from GPS: {top['name']}"
                        + (f", set {pct:.0f}% of the time" if pct is not None else "")
                        + " (not adjusted to this player)."})
    for i, c in enumerate(out):
        c.update({"slot": "option1" if i == 0 else f"c{i + 1}", "spare": None, "spare_name": "",
                  "adjusted": False, "notes": []})
    return out


def middle_field(fmt, group, hand):
    """The planner's Option 1 for a batter: the GPS-corrected middle-overs field."""
    fs = phase_fields(fmt, group, hand, menu=False)
    return fs[1]["fielders"] if len(fs) > 1 else (fs[0]["fielders"] if fs else [])
