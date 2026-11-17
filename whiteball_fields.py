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

A card offers three fields, Powerplay, Middle overs and Death, and each STARTS FROM THE MOST-SET
field (Tom, 17-11-2026: "the default field should be the most set field, as that one was generally
more correct"). The GPS-corrected field is the start only in a phase with no most-set field of its
own. A phase's field sits in the slot its corrected field had in the full list of six (the first is
always "option1", which is where the planner files a card's first field), and a coach's field
saved in any slot still shows (the pages show a saved field whose slot is no longer seeded).

England ODI is the exception and stays as it was built (Tom, 17-11: "no changes made to the current
England ODI packs"): the three GPS-corrected fields (his 10-11 call), with its pace bowlers starting
from the three he set on Gus Atkinson's card (`data/default_fields_<opp>.json`, `with_defaults`).
`CORRECTED_START` names such a series. Every builder says which series it is building
(`for_series`), and asking for fields without one raises, so the wrong start is never a default.

Not built yet (Tom, atq 17-11): a card for a player who has fields and coach notes from an earlier
series of the same format starts from those, shown and marked with the series they came from, and
written nowhere until a coach saves. docs/PLAYER_PACK_REDESIGN.md.
"""
import json
import os

from cricket_core import fields as F
from cricket_core.lookups import FIELD_POS, field_coords

# the coach view's bowler groups -> cricket_core's two vocabularies
SIMPLE = {"right_pace": "Right Fast", "left_pace": "Left Fast", "off_spin": "Off Spin",
          "left_orthodox": "Left Orthodox", "leg_spin": "Leg Break", "left_unorthodox": "Left Unorthodox"}
MENU = {"right_pace": "RA pace", "left_pace": "LA pace", "off_spin": "Off spin",
        "left_orthodox": "SLA orthodox", "leg_spin": "Leg spin", "left_unorthodox": "SLA unorthodox"}
PHASES = {"ODI": (("odi", "pp1", "Powerplay"), ("odi", "middle", "Middle overs"), ("odi", "death", "Death")),
          "T20": (("t20", "powerplay", "Powerplay"), ("t20", "middle", "Middle overs"), ("t20", "death", "Death"))}
# series that start from the GPS-corrected field, as they were built (see the docstring)
CORRECTED_START = {"england_odi"}
_SERIES = None


def for_series(opp):
    """Say which series' fields are being built (its opp key). Call it once at a builder's start."""
    global _SERIES
    _SERIES = str(opp)
PACE = ("right_pace", "left_pace")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


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
    if _SERIES is None:
        raise RuntimeError("whiteball_fields.for_series(<opp key>) was not called: the starting fields "
                           "differ by series (England ODI starts from the corrected field)")
    _need_gps()
    out = []
    for key, phase, word in PHASES[fmt]:
        gps = F.gps_corrected_field(key, SIMPLE[group], hand, phase)
        pts = _pts(gps)
        if pts:
            out.append({"label": word, "phase": word, "kind": "corrected", "fielders": pts, "basis":
                        "The stock field for the type in this phase, with the changes GPS shows Australia makes "
                        "(not adjusted to this player)."})
        if not menu:
            continue
        top = next(iter(F.field_menu(key, MENU[group], hand, phase)), None)
        mpts = _pts([p["label"] for p in (top or {}).get("positions", [])]) if top else []
        if mpts and sorted(f["label"] for f in mpts) != sorted(f["label"] for f in pts):
            pct = top.get("freq_pct")
            out.append({"label": f"{word} · most set", "phase": word, "kind": "most_set", "fielders": mpts, "basis":
                        f"Australia's most-set field in this cell, from GPS: {top['name']}"
                        + (f", set {pct:.0f}% of the time" if pct is not None else "")
                        + " (not adjusted to this player)."})
    # slots are numbered over the whole list, alternatives included, so dropping them moves no field
    for i, c in enumerate(out):
        c.update({"slot": "option1" if i == 0 else f"c{i + 1}", "spare": None, "spare_name": "",
                  "adjusted": False, "notes": []})
    if menu:
        if _SERIES in CORRECTED_START:
            out = [c for c in out if c["kind"] == "corrected"]
        else:
            # One field a phase: the most-set field under the phase's own name, the corrected field
            # only where the phase has no most-set field. It sits in the PHASE's slot, the one its
            # corrected field was numbered into, so the first field is always "option1": the planner
            # files a card's first field there whatever slot it carries, and a most-set field left
            # in its own slot (c2) was saved by the planner under option1 and read by the cards
            # under c2 (found in review, 17-11-2026, before any upload).
            slot_of = {c["phase"]: c["slot"] for c in out if c["kind"] == "corrected"}
            has = {c["phase"] for c in out if c["kind"] == "most_set"}
            out = [dict(c, label=c["phase"], slot=slot_of.get(c["phase"], c["slot"])) for c in out
                   if c["kind"] == "most_set" or c["phase"] not in has]
    for c in out:
        c.pop("phase", None), c.pop("kind", None)
    return out


def series_defaults(opp):
    """{hand: {phase label: fielders}} for a series' pace bowlers, or {} when it names none."""
    path = os.path.join(DATA, f"default_fields_{opp}.json")
    if not os.path.exists(path):
        return {}
    return (json.load(open(path, encoding="utf-8")).get("pace") or {})


def with_defaults(cats, opp, group, hand):
    """A pace bowler's phase fields with the series' own starting fields in place of the estimates,
    each in the slot its phase was seeded into. A spinner's, or a series with none, are unchanged."""
    d = series_defaults(opp).get(hand) if group in PACE else None
    if not d:
        return cats
    out = []
    for c in cats:
        own = d.get(c["label"])
        if own:
            c = dict(c, fielders=[dict(p) for p in own], basis=(
                "The series' starting field for pace in this phase, set by the coaches on "
                f"{d.get('_from') or 'one card'} (not adjusted to this bowler)."))
        out.append(c)
    return out


def middle_field(fmt, group, hand):
    """The planner's Option 1 for a batter: the GPS-corrected middle-overs field."""
    fs = phase_fields(fmt, group, hand, menu=False)
    return fs[1]["fielders"] if len(fs) > 1 else (fs[0]["fielders"] if fs else [])
