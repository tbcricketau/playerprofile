"""
field_engine.py — justified field settings for a batter × bowler group × innings phase,
built from what the batter DOES (no fielder-placement data needed). See FIELD_PLAN.md.

Three evidence layers, each carrying the stat that justifies every fielder:
  1. Run flow      — 10 batter-relative sectors from hit_to_angle (~100% of scoring balls):
                     runs/100 balls + boundary share → where to save runs / post deep riders.
  2. Expected catch — his false-shot mix by stroke × the cohort's stroke→catch-position
                     distribution (referencebuilder/data/catch_position_norms.csv) → where his
                     mishits carry → the catchers. His OWN observed catches
                     (batter_field_profile.csv) are kept for the backtest.
  3. Phase weight  — first 30 balls: wicket-biased (more catchers); once set: run-biased.

Output: an ordered field (keeper + 9) where each fielder has a role (catch/save) and a
one-line justification, plus a backtest ("under N of his M caught dismissals vs this group").

Batter-relative angle convention (matches cricket_core.lookups.field_coords):
  br_angle = hit_to_angle if RHB else -hit_to_angle ;  +ve = OFF side, 0 = straight.
"""
import csv
import os
from collections import Counter, defaultdict

from cricket_core.lookups import FIELD_POS, field_coords

_REF = r"c:\Projects\referencebuilder\data"
_COHORT_CSV = os.path.join(_REF, "catch_position_norms.csv")
_PROFILE_CSV = os.path.join(_REF, "batter_field_profile.csv")

# Batter-relative sectors (+off). Behind square handled by the wide fine buckets.
_SECTORS = [
    ("third man",  115, 165), ("point",       70, 115), ("cover",   35, 70),
    ("mid-off",     10,  35), ("straight",   -10,  10), ("mid-on",  -35, -10),
    ("midwicket",  -70, -35), ("square leg",-115, -70), ("fine leg",-165,-115),
]
# sector -> (ring position name, deep position name) from FIELD_POS
_SECTOR_POS = {
    "third man":  ("Third man", "Deep third man"),
    "point":      ("Point", "Deep point"),
    "cover":      ("Cover", "Deep cover"),
    "mid-off":    ("Mid-off", "Long-off"),
    "straight":   ("Mid-on", "Long-on"),
    "mid-on":     ("Mid-on", "Long-on"),
    "midwicket":  ("Midwicket", "Deep midwicket"),
    "square leg": ("Square leg", "Deep square leg"),
    "fine leg":   ("Fine leg", "Deep fine leg"),
}
_FMT = "test"
_CACHE = {}


def _load_csv(path):
    if path not in _CACHE:
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        _CACHE[path] = rows
    return _CACHE[path]


# Fall back to a broader cohort when a narrow group has no catch norms (e.g. left-arm
# wrist spin is rare → borrow the general spin cordon; missing pace → general pace).
_GROUP_FALLBACK = {
    "left_unorthodox": "spin", "left_orthodox": "spin", "off_spin": "spin", "leg_spin": "spin",
    "right_pace": "pace", "left_pace": "pace",
}


def _cohort_catch_dist(group):
    """{stroke_family: {position: share%}} for this bowler group (Tests). Falls back to the
    broader spin/pace cohort, then 'all', if the specific group has no rows."""
    for g in (group, _GROUP_FALLBACK.get(group), "all"):
        if not g:
            continue
        out = defaultdict(dict)
        for r in _load_csv(_COHORT_CSV):
            if r["format"] == _FMT and r["bowler_group"] == g:
                out[r["stroke_family"]][r["position"]] = float(r["share"])
        if out:
            return out
    return defaultdict(dict)


def _batter_field(batter_id, group):
    """His observed positions vs this group: {position: {balls, runs, saved, catches}}."""
    out = {}
    for r in _load_csv(_PROFILE_CSV):
        if r["format"] == _FMT and r["batter_id"] == str(batter_id) and r["bowler_group"] == group:
            out[r["position"]] = {"balls": int(r["balls_fielded"]), "runs": int(r["runs_conceded"]),
                                  "saved": int(r["runs_saved"]), "catches": int(r["catches"])}
    return out


def _br_angle(r, is_lhb):
    a = r.get("hit_ang_n")
    if a is None:
        return None
    return a if not is_lhb else -a


def _sector_of(angle):
    if angle is None:
        return None
    for name, lo, hi in _SECTORS:
        if lo <= angle < hi:
            return name
    return "fine leg" if angle < 0 else "third man"     # very fine edges fold into the ends


def run_flow(rows, is_lhb):
    """Per sector: balls, runs, boundary runs, runs/100, boundary share. Scoring balls only
    place; every legal ball counts toward the denominator."""
    agg = defaultdict(lambda: {"balls": 0, "runs": 0.0, "bdry": 0.0})
    legal = 0
    for r in rows:
        if not r["is_legal"]:
            continue
        legal += 1
        if r["runs"] <= 0:
            continue
        s = _sector_of(_br_angle(r, is_lhb))
        if not s:
            continue
        agg[s]["balls"] += 1
        agg[s]["runs"] += r["runs"]
        if r["runs"] in (4.0, 6.0):
            agg[s]["bdry"] += r["runs"]
    out = {}
    for s, v in agg.items():
        out[s] = {**v, "runs_per100": v["runs"] / legal * 100 if legal else 0,
                  "bdry_share": v["bdry"] / v["runs"] * 100 if v["runs"] else 0,
                  "runs_share": v["runs"]}
    tot = sum(v["runs"] for v in out.values()) or 1
    for v in out.values():
        v["runs_share"] = v["runs"] / tot * 100
    return out, legal


def expected_catches(rows, group):
    """His false-shot count by stroke × cohort stroke→position distribution → expected
    relative catches per position, plus the dominant stroke feeding each position."""
    cohort = _cohort_catch_dist(group)
    false_by_stroke = defaultdict(int)
    for r in rows:
        if r.get("has_shot_q") and r.get("is_false_shot") and r.get("stroke_family"):
            false_by_stroke[r["stroke_family"]] += 1
    exp = defaultdict(float)
    feed = defaultdict(lambda: defaultdict(float))
    for stroke, nfalse in false_by_stroke.items():
        for pos, share in cohort.get(stroke, {}).items():
            exp[pos] += nfalse * share / 100.0
            feed[pos][stroke] += nfalse * share / 100.0
    dom = {p: (max(feed[p], key=feed[p].get) if feed[p] else None) for p in exp}
    return exp, dom, false_by_stroke


def _n_catchers(phase, is_spin, false_rate):
    """Non-keeper dedicated catchers. More early and when he plays falser; realistic caps."""
    base = 3 if phase == "early" else 2
    if is_spin:
        base = 3 if phase == "early" else 1     # bat-pad + slip early, one catcher set
    if false_rate is not None and false_rate >= 20 and phase == "early":
        base += 1
    return max(1, min(4, base))


# ── Assembly v2: GPS-corrected stock base + ≤3 evidenced, legality-checked deviations ──
# (FIELD_PLAN §5). The run-flow / expected-catch value model above stays; only the assembly
# changes — start from the stock template, deviate on strong per-batter reasoning.
_TRIGGER_CSV = os.path.join(_REF, "field_trigger_norms.csv")
_STROKE_CSV = os.path.join(_REF, "batter_stroke_norms.csv")

# report fine group -> the bowler_type string the stock scenario() expects
_GROUP_TO_TYPE = {
    "right_pace": "Right Fast", "left_pace": "Left Fast", "pace": "Right Fast",
    "off_spin": "Off Spin", "leg_spin": "Leg Break", "spin": "Off Spin",
    "left_orthodox": "Left Orthodox", "left_unorthodox": "Left Unorthodox",
}

# stock fielder name -> run-flow sector (so a deviation can drop his least-used stock post)
_NAME_SECTOR = {}
for _sec, (_ring, _deep) in _SECTOR_POS.items():
    _NAME_SECTOR[_ring] = _sec
    _NAME_SECTOR[_deep] = _sec
_NAME_SECTOR.update({
    "Backward point": "point", "Deep backward point": "point", "Silly point": "point",
    "Extra cover": "cover", "Deep extra cover": "cover",
    "Long-off": "mid-off", "Long-on": "mid-on", "Silly mid-on": "mid-on",
    "Backward square leg": "square leg", "Deep backward square leg": "square leg", "Short leg": "square leg",
    "Slip 1": "third man", "Slip 2": "third man", "Slip 3": "third man", "Slip 4": "third man",
    "Gully": "third man", "Third man": "third man", "Deep third man": "third man", "Leg slip": "fine leg",
})
# the cordon / close catchers — protected from being dropped by a run-saving deviation
_CORDON = {"Slip 1", "Slip 2", "Slip 3", "Slip 4", "Gully", "Leg slip", "Short leg",
           "Silly point", "Silly mid-on", "Bat pad", "Keeper", "Wicketkeeper"}


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trigger_row(batter_id, coarse_group, phase):
    for r in _load_csv(_TRIGGER_CSV):
        if (r.get("format") == _FMT and r.get("batter_id") == str(batter_id)
                and r.get("group") == coarse_group and r.get("phase") == phase):
            return r
    return {}


def _stroke_row(batter_id, coarse_group, family):
    for r in _load_csv(_STROKE_CSV):
        if (r.get("format") == _FMT and r.get("batter_id") == str(batter_id)
                and r.get("bowler_group") == coarse_group and r.get("family") == family):
            return r
    return {}


def _rules(P, group, phase, is_spin):
    """Evaluate R1–R8 (FIELD_PLAN §4) from the cohort norms; return the fired rules
    (percentile >= 75). Each: id, pctl, value, add [candidate positions], why, protect."""
    bid, coarse = P["batter_id"], ("spin" if is_spin else "pace")
    fired = []

    def fire(rid, pctl, val, add, why, protect=True):
        if pctl is None or val is None or pctl < 75:
            return
        fired.append({"id": rid, "pctl": pctl, "value": val, "add": add,
                      "why": why, "protect": protect, "strength": pctl})

    def _sr(cg, fam):
        s = _stroke_row(bid, cg, fam)
        return _fnum(s.get("runs_pct_pctl")), _fnum(s.get("runs_pct"))

    if is_spin:                                          # R1 lap/sweep (vs spin)
        p, v = _sr("spin", "Sweep")
        fire("R1", p, v, ["Deep backward square leg", "Deep square leg"],
             f"He sweeps/laps {v:.0f}% of his runs vs spin (P{p:.0f}) — protect deep backward square." if v else "")
        # R8 charger — stumped-prone or a slogger vs spin → keep the straight boundary back even early
        stumped = sum(1 for r in P["raw"] if r.get("is_out") and r.get("how_out") == "Stumped")
        sp, sv = _sr("spin", "Slog")
        if stumped >= 2 or (sp is not None and sp >= 75):
            strength = sp if (sp is not None and sp >= 75) else 80.0
            why = ((f"He's been stumped {stumped}× vs spin" if stumped >= 2
                    else f"He slogs {sv:.0f}% of his runs vs spin (P{sp:.0f})")
                   + " — he uses his feet, so keep the straight boundary back even early.")
            fired.append({"id": "R8", "pctl": strength, "value": float(stumped),
                          "add": ["Long-on", "Long-off"], "why": why,
                          "protect": True, "strength": strength})
    else:                                                # R4 cut (vs pace)
        p, v = _sr("pace", "Cut")
        fire("R4", p, v, ["Deep point", "Third man"],
             f"Cuts carry {v:.0f}% of his runs vs pace (P{p:.0f}) — deep point saver." if v else "")

    p, v = _sr(coarse, "Pull/Hook")                      # R5 pull/hook
    fire("R5", p, v, ["Deep square leg", "Deep backward square leg"],
         f"Pulls/hooks {v:.0f}% of his runs (P{p:.0f}) — deep square leg back." if v else "")

    p, v = _sr(coarse, "Work/Nudge")                     # R7 leg-side nudge
    fire("R7", p, v, ["Backward square leg", "Deep square leg"],
         f"He works {v:.0f}% of his runs to leg (P{p:.0f}) — squarer leg-side saver." if v else "")

    if phase == "early":                                 # R2 square early
        t = _trigger_row(bid, coarse, "early")
        p, v = _fnum(t.get("square_share_pctl")), _fnum(t.get("square_share"))
        fire("R2", p, v, ["Deep point", "Backward point"],
             f"{v:.0f}% of his early runs go square of the wicket (P{p:.0f}) — square saver early." if v else "")
        if not is_spin:                                  # R6 edge-prone starter (cordon rule)
            t6 = _trigger_row(bid, "all", "early")
            p6, v6 = _fnum(t6.get("false_pct_pctl")), _fnum(t6.get("false_pct"))
            fire("R6", p6, v6, ["Slip 3", "Slip 2", "Gully"],
                 f"He plays a false shot at {v6:.0f}% over his first 30 (P{p6:.0f}) — extra catcher while he starts." if v6 else "",
                 protect=False)
    else:                                                # R3 down-ground (set)
        t = _trigger_row(bid, coarse, "set")
        p, v = _fnum(t.get("straight_share_pctl")), _fnum(t.get("straight_share"))
        fire("R3", p, v, ["Long-on", "Long-off"],
             f"{v:.0f}% of his runs go straight down the ground (P{p:.0f}) — straight boundary back." if v else "")

    return fired


def _least_valuable(names, flow, protect_cordon, exclude):
    """The stock fielder whose run-flow sector the batter scores LEAST in (drop candidate)."""
    worst, worst_share = None, 1e9
    for nm in names:
        if nm in exclude or (protect_cordon and nm in _CORDON):
            continue
        share = flow.get(_NAME_SECTOR.get(nm), {}).get("runs_share", 0.0)
        if share < worst_share:
            worst_share, worst = share, nm
    return worst


# ── Part 2: fielder value + the 'floating' fielder (FIELD logic v3 §2) ─────────────────
# Every fielder's importance = what his presence prevents: a run-SAVER by the runs flowing through
# his sector (run_flow), a CATCHER by the batter's expected edges to his position (expected_catches).
# The lowest-value fielder(s) — clearly below their role's average — are the FLOATING fielders: worth
# knowing even when we don't move them, since they're the spares to shift as the game asks.
# field position name -> the key the cohort catch-norms use (expected_catches / exp)
_NORM_KEY = {
    "Slip 1": "Slip: 1st", "Slip 2": "Slip: 2nd", "Slip 3": "Slip: 3rd", "Slip 4": "Slip: 4th",
    "Leg slip": "Fine leg: leg slip", "Leg gully": "Fine leg: leg gully", "Fly slip": "Slip: fly slip",
    "Silly point": "Point: silly", "Short leg": "Square leg: short leg",
}
# the cordon we NEVER float (they hold their spot for the edge); situational catchers we may.
_CORE_CORDON = {"Keeper", "Slip 1", "Slip 2", "Gully"}
_SITU_CATCH = {"Slip 3", "Slip 4", "Leg slip", "Leg gully", "Short leg", "Silly point", "Fly slip"}
_FLOAT_SUGGEST = {           # a situational catcher that sees little → its natural re-use
    "Leg slip": "short leg / bat-pad", "Slip 3": "gully or a run-saver", "Slip 4": "gully or a run-saver",
    "Short leg": "square of the wicket", "Silly point": "backward point", "Fly slip": "a run-saver",
    "Leg gully": "finer or squarer",
}


def _floating(names, flow, exp):
    """The 'floating' fielder(s): a RING saver in a sector the batter barely scores in, and/or a
    SITUATIONAL catcher seeing far fewer edges than the cordon. Core cordon + deep riders are never
    floated (they hold their spot for the edge / the boundary). Returns [{position, kind, value, why}]."""
    def role(n):
        return (FIELD_POS.get(n) or field_coords(n)).get("role")
    out = []
    ring = [(n, flow.get(_NAME_SECTOR.get(n), {}).get("runs_share", 0.0))
            for n in names if n not in _CORDON and n != "Keeper" and role(n) == "ring"]
    if len(ring) >= 2:
        ring.sort(key=lambda t: t[1])
        n, v = ring[0]
        mean = sum(s for _, s in ring) / len(ring)
        if mean > 0 and v <= 0.6 * mean:            # scores clearly little where he stands
            out.append({"position": n, "kind": "save", "value": round(v, 1),
                        "why": f"They score only {v:.0f}% of their runs where {n.lower()} stands — the "
                               f"spare run-saver to move as the game asks."})
    situ = [(n, float(exp.get(_NORM_KEY.get(n, n), 0.0))) for n in names if n in _SITU_CATCH]
    if situ:
        cordon = [float(exp.get(_NORM_KEY.get(n, n), 0.0)) for n in names if n in _CORE_CORDON and n != "Keeper"]
        cmean = sum(cordon) / len(cordon) if cordon else 0
        situ.sort(key=lambda t: t[1])
        n, v = situ[0]
        if cmean > 0 and v <= 0.5 * cmean:          # sees far fewer edges than the slips/gully
            sug = _FLOAT_SUGGEST.get(n)
            tail = f" — float to {sug} as needed" if sug else ""
            out.append({"position": n, "kind": "catch", "value": round(v, 1),
                        "why": f"{n} sees few of their edges ({v:.1f} vs {cmean:.1f} for the cordon){tail}."})
    return out


# ── Part 3: 'better suited elsewhere' — dismissal-evidence rule + floating-aware drop ──
# The R1–R8 rules (below) fire evidenced MOVES from cohort norms; R9 adds a rule from the batter's
# ACTUAL dismissals — where his caught mishits have really carried (Carey's leg slip in the Ashes).
# Small-n, so gated at >= 2 caught dismissals and only when it points to a non-stock catcher.
_DIS_SITU = {           # norm catch-key -> the situational catcher to post there
    "Fine leg: leg slip": "Leg slip", "Square leg: short leg": "Short leg", "Point: silly": "Silly point",
    "Slip: 3rd": "Slip 3", "Slip: 4th": "Slip 4", "Fine leg: leg gully": "Leg gully",
}
_DIS_FRIENDLY = {"Slip 3": "third slip", "Slip 4": "fourth slip", "Leg slip": "leg slip",
                 "Short leg": "short leg", "Silly point": "silly point", "Leg gully": "leg gully"}
# min actual catches to post a catcher: a leg-side close catch is rare enough that 2 is a plan;
# an extra slip is more routine, so needs 3.
_DIS_MIN = {"Leg slip": 2, "Short leg": 2, "Leg gully": 2, "Silly point": 2, "Slip 3": 3, "Slip 4": 3}


def _dismissal_evidence(by_pos, current_names, type_label="this type"):
    """R9 — from where his CAUGHT dismissals were ACTUALLY taken (Counter of catch positions, coarse
    pace/spin): if a situational catcher he isn't already given has claimed him >= 2 times AND a clear
    share of his located catches, post it. This is the Carey-leg-slip signal — the outcome, not a model."""
    total = sum(by_pos.values())
    if total < 3:                                  # too few located catches to read a pattern
        return None
    best = None                                     # a situational catcher: >= 2 catches AND >= 10%
    for normkey, fieldname in _DIS_SITU.items():
        if fieldname in current_names:
            continue
        n = by_pos.get(normkey, 0)
        share = n / total
        # per-position minimum (rare leg-side spot = 2, extra slip = 3), plus a small share floor so
        # a fluke in a huge sample doesn't trigger it.
        if n >= _DIS_MIN.get(fieldname, 3) and share >= 0.05 and (best is None or n > best[1]):
            best = (fieldname, n, share)
    if not best:
        return None
    fieldname, n, share = best
    friendly = _DIS_FRIENDLY.get(fieldname, fieldname.lower())
    return {"id": "R9", "pctl": 90.0, "value": share, "add": [fieldname], "protect": False, "strength": 90.0,
            "why": f"Caught at {friendly} {n}× vs {type_label}."}


def _pick_drop(names, flow, floating, protect, add):
    """Which fielder the deviation moves. A DEEP rider pushes ITS OWN ring fielder back — you never
    have two on the same line (adding long-on drops mid-on, keeping mid-off up). Otherwise prefer a
    designated FLOATING fielder (Part 2's spare) — even a cordon one — else the least-used run-saver."""
    if (FIELD_POS.get(add) or field_coords(add))["role"] == "deep":
        sec = _NAME_SECTOR.get(add)
        for n in names:                              # the same-sector RING fielder (mid-on for long-on)
            if n != add and _NAME_SECTOR.get(n) == sec \
                    and (FIELD_POS.get(n) or field_coords(n))["role"] != "deep":
                return n
    for fn in floating:
        if fn in names and fn != add:
            return fn
    return _least_valuable(names, flow, protect, exclude={add})


def _field_dicts(names, changes, base_changes):
    """Turn a list of fielder names into the render dicts (position, angle, radius, role, kind,
    tag, why), tagging the ones that came from a deviation."""
    out = []
    for nm in names:
        c = FIELD_POS.get(nm) or field_coords(nm)
        ch = next((x for x in changes if x["add_pos"] == nm), None)
        out.append({"position": nm, "angle": c["angle"], "radius": c["radius"], "role": c["role"],
                    "kind": "catch" if c["role"] == "catch" else "save",
                    "tag": "change" if ch else "stock",
                    "why": (ch["why"] if ch else _stock_why(nm, base_changes))})
    return out


def _fork_alt(fired, changes, names, base_names, flow, base_floating, phase, base_changes):
    """Part 4 — a SECOND option only on a genuine fork: a strong (P80+) evidenced move the primary
    couldn't fit. Build the alternative by reverting the weakest applied change and applying it.
    Returns {field, why} or None (the usual case — one field per phase)."""
    applied = {c["id"] for c in changes}
    leftover = [r for r in sorted(fired, key=lambda r: -r["strength"])
                if r["pctl"] >= 80 and r["id"] not in applied]
    if not leftover:
        return None
    rule = leftover[0]
    add = next((a for a in rule["add"] if a not in base_names), None)
    if add is None:
        return None
    weakest = min(changes, key=lambda c: c["strength"])
    alt_names = [weakest["drop_pos"] if n == weakest["add_pos"] else n for n in names]   # revert weakest
    drop = _pick_drop(alt_names, flow, base_floating, rule["protect"], add)
    if drop is None or drop == add:
        return None
    cand = [add if n == drop else n for n in alt_names]
    if not _legal(cand, phase) or set(cand) == set(names):
        return None
    alt_changes = [c for c in changes if c["id"] != weakest["id"]] + [{**rule, "add_pos": add, "drop_pos": drop}]
    return {"field": _field_dicts(cand, alt_changes, base_changes),
            "why": f"Alternative — {rule['why']}"}


def _legal(names, phase):
    from cricket_core import fields
    if len(set(names)) != 9:
        return False
    lim = fields.OUT_LIMIT.get(_FMT, {}).get(phase, 9)
    if sum(1 for n in names if fields._is_out(n)) > lim:
        return False
    if sum(1 for n in names if fields._behind_square_leg(n)) > 2:
        return False
    return True


_SHORT_BALL_WHY = {
    "Slip 1": "One slip kept for the top / outside edge.",
    "Short leg": "Catcher in front of square for the fend or glove off the hip.",
    "Gully": "The steer or fend that flies squarer of the wicket.",
    "Deep backward square": "Deep behind square for the top-edged pull.",
    "Deep fine leg": "Deep behind square for the hook.",
}


def _short_ball_field(is_lhb, note):
    """The named short-ball / bumper-plan field (cricket_core.fields.SHORT_BALL): one slip, a
    front-of-square catcher, and the two Law-max behind-square riders — shown as an alternative
    field for heavy pullers/hookers (R5)."""
    from cricket_core import fields
    out = []
    for nm in fields.SHORT_BALL:
        c = FIELD_POS.get(nm) or field_coords(nm)
        out.append({"position": nm, "angle": c["angle"], "radius": c["radius"],
                    "role": c["role"], "kind": "catch" if c["role"] == "catch" else "save",
                    "tag": "change", "why": _SHORT_BALL_WHY.get(nm, "Ring saver for the bumper plan.")})
    return {"field": out, "note": note}


# ── Part 1: stock-field VARIANTS + best-fit selection (FIELD logic v3 §1) ─────────────
# A small library of orthodox stock alternatives per (scenario, phase): each a legal 9-fielder
# field a real captain sets, differing in run-side emphasis. We pick the one whose fielders best
# cover where THIS batter scores (run_flow); the <=3 evidenced deviations then act on that base.
# First entry per cell = the balanced default (== the stock). Test run-saving only for now — the
# new-ball cordon is standard, and white-ball keeps the single GPS-corrected stock.
_STOCK_VARIANTS = {
    "pace_same": {
        "defend": [
            ("balanced", ["Slip 1", "Slip 2", "Gully", "Point", "Cover", "Mid-off", "Mid-on", "Midwicket", "Fine leg"]),
            ("off-side / square", ["Slip 1", "Slip 2", "Gully", "Backward point", "Point", "Cover", "Mid-off", "Mid-on", "Midwicket"]),
            ("leg-side", ["Slip 1", "Gully", "Point", "Cover", "Mid-off", "Mid-on", "Midwicket", "Square leg", "Fine leg"]),
        ],
    },
    "pace_across": {
        "defend": [
            ("balanced", ["Slip 1", "Gully", "Backward point", "Cover", "Mid-off", "Mid-on", "Midwicket", "Fine leg", "Third man"]),
            ("off-side / square", ["Slip 1", "Gully", "Backward point", "Point", "Cover", "Mid-off", "Mid-on", "Midwicket", "Third man"]),
            ("leg-side", ["Slip 1", "Gully", "Backward point", "Cover", "Mid-off", "Mid-on", "Midwicket", "Square leg", "Fine leg"]),
        ],
    },
}


# run-flow sectors that make up each scoring axis (batter-relative: +off, straight, −leg)
_AXIS_OFF = ("point", "cover", "mid-off")
_AXIS_LEG = ("midwicket", "square leg", "fine leg")
_AXIS_STRAIGHT = ("straight", "mid-on")
_SKEW = 7.0    # one axis must lead the others by this many run-share points to leave balanced


def _run_axes(flow):
    f = lambda secs: sum(flow.get(s, {}).get("runs_share", 0.0) for s in secs)
    return f(_AXIS_OFF), f(_AXIS_LEG), f(_AXIS_STRAIGHT)


def _select_variant(scenario, phase, flow, base_names):
    """Pick the orthodox stock variant matching the batter's dominant scoring axis. Only leaves the
    balanced stock when one side CLEARLY leads (>= _SKEW run-share points) — an even scorer keeps the
    balanced field (we don't shift fielders without a real skew). Returns {name, field, why} or None."""
    variants = dict(_STOCK_VARIANTS.get(scenario, {}).get(phase) or [])
    if not variants or not flow:
        return None
    off, leg, straight = _run_axes(flow)
    if leg - max(off, straight) >= _SKEW and "leg-side" in variants:
        return {"name": "leg-side", "field": variants["leg-side"], "axes": (off, leg, straight),
                "why": f"Strong through the leg side ({leg:.0f}% of their runs vs {off:.0f}% off) "
                       f"— a squarer leg-side ring, one slip out."}
    if off - max(leg, straight) >= _SKEW and "off-side / square" in variants:
        return {"name": "off-side / square", "field": variants["off-side / square"], "axes": (off, leg, straight),
                "why": f"Scores square and through the off ({off:.0f}% vs {leg:.0f}% leg) "
                       f"— an extra fielder square on the off, one leg-sider out."}
    return None                           # even scorer → balanced stock


def build_field(P, group, phase):
    """Assembly v2 — the GPS-corrected stock field ± the top (<=3) evidenced deviations.
    Returns {phase, group, group_label, n_catchers, false_rate, legal, field:[{position, angle,
    radius, role, kind, tag: 'stock'|'change', why}], changes:[...], base_note, backtest}."""
    from cricket_core import fields
    is_lhb = P["is_lhb"]
    is_spin = group in ("off_spin", "leg_spin", "left_orthodox", "left_unorthodox", "spin")
    rows = [r for r in P["raw"] if (r["is_early"] if phase == "early" else not r["is_early"])]
    if sum(1 for r in rows if r["is_legal"]) < 80:
        return None

    hand = "LHB" if is_lhb else "RHB"
    btype = _GROUP_TO_TYPE.get(group, "Off Spin" if is_spin else "Right Fast")
    stock_phase = "attack" if phase == "early" else "defend"
    base_names, base_changes = fields.gps_corrected_field(_FMT, btype, hand, stock_phase, with_changes=True)
    if not base_names:
        return None

    flow, legal = run_flow(rows, is_lhb)
    # Part 1: pick the best-fit orthodox stock variant for this batter's run flow, then deviate
    # from THAT base (not a fixed template). Test only; balanced/no-variant keeps the stock base.
    scenario = fields.scenario(btype, hand)
    stock_fit = _select_variant(scenario, stock_phase, flow, base_names) if _FMT == "test" else None
    if stock_fit and _legal(stock_fit["field"], stock_phase):
        base_names = stock_fit["field"]
    else:
        stock_fit = None
    exp, _dom, _ = expected_catches(rows, group)
    observed = _batter_field(P["batter_id"], group)
    shotq = sum(1 for r in rows if r.get("has_shot_q"))
    false_rate = (sum(1 for r in rows if r.get("is_false_shot")) / shotq * 100) if shotq else None

    # apply the top <=3 fired rules, each swap re-validated for legality. R9 (actual-dismissal
    # evidence) joins the cohort-norm rules; each move drops the FLOATING fielder where there is one.
    fired = _rules(P, group, phase, is_spin)
    cpos = (P.get("caught_positions") or {}).get("spin" if is_spin else "pace", Counter())
    r9 = _dismissal_evidence(cpos, base_names, _group_label(group))   # coarse caught record
    if r9:
        fired.append(r9)
    base_floating = [f["position"] for f in _floating(base_names, flow, exp)]
    names, changes = list(base_names), []
    for rule in sorted(fired, key=lambda r: -r["strength"]):
        if len(changes) >= 3:
            break
        add = next((a for a in rule["add"] if a not in names), None)
        if add is None:
            continue                                        # that saver is already in the stock
        # Tests: a NON-stock boundary rider (long-on etc.) needs VERY strong evidence — you only
        # post one against a genuinely aggressive boundary hitter (caveat #1). Stock riders are free.
        is_deep = (FIELD_POS.get(add) or field_coords(add))["role"] == "deep"
        if _FMT == "test" and is_deep and add not in base_names and rule["pctl"] < 85:
            continue
        drop = _pick_drop(names, flow, base_floating, rule["protect"], add)
        if drop is None:
            continue
        cand = [add if n == drop else n for n in names]
        if _legal(cand, stock_phase):
            names = cand
            changes.append({**rule, "add_pos": add, "drop_pos": drop})

    base_set = set(base_names)
    field = []
    for nm in names:
        c = FIELD_POS.get(nm) or field_coords(nm)
        ch = next((x for x in changes if x["add_pos"] == nm), None)
        field.append({"position": nm, "angle": c["angle"], "radius": c["radius"],
                      "role": c["role"], "kind": "catch" if c["role"] == "catch" else "save",
                      "tag": "change" if ch else "stock",
                      "why": (ch["why"] if ch else _stock_why(nm, base_changes))})

    n_catch = sum(1 for f in field if f["kind"] == "catch")
    if stock_fit:
        base_note = f"{stock_fit['name']} stock field — {stock_fit['why']}"
    else:
        base_note = ("GPS-corrected stock field" if base_changes not in ("none", "", None)
                     else "stock field")
    # Part 4: the bouncer plan is a STANDARD Test-pace option now, not only for heavy pullers —
    # the note says honestly whether it's a genuine wicket-taking plan for THIS batter or a holding
    # field (Tom's hunch: for most batters the bumper field is standard, not a wicket-taker).
    short_ball = None
    if not is_spin and _FMT == "test":
        pull_p = _fnum((_stroke_row(P["batter_id"], "pace", "Pull/Hook") or {}).get("runs_pct_pctl"))
        common = ("One slip, a catcher in front of square, and the two legal leg-side riders "
                  "(deep backward square + deep fine leg).")
        if pull_p is not None and pull_p >= 80:
            sb_note = f"A genuine plan — heavy puller/hooker (P{pull_p:.0f} vs pace). " + common
        elif pull_p is not None and pull_p >= 60:
            sb_note = f"He pulls a fair amount (P{pull_p:.0f}) — the bumper can buy a top-edge. " + common
        else:
            sb_note = ("A standard bumper field — he isn't a heavy puller"
                       + (f" (P{pull_p:.0f})" if pull_p is not None else "")
                       + ", so this is a holding / surprise option, not a wicket-taking plan. " + common)
        short_ball = _short_ball_field(is_lhb, sb_note)

    # Part 4: a SECOND field only on a genuine FORK — a strong (P80+) evidenced move the primary
    # couldn't fit (3-change budget / a clash). Swap the weakest applied change back for it.
    alt = _fork_alt(fired, changes, names, base_names, flow, base_floating, stock_phase, base_changes) \
        if (changes and not is_spin) else None

    floating = _floating(names, flow, exp)          # Part 2: the spare / low-value fielder(s)
    return {"phase": phase, "group": group, "group_label": _group_label(group),
            "n_catchers": n_catch, "false_rate": false_rate, "legal": legal,
            "field": field, "changes": [c["why"] for c in changes],
            "base_note": base_note, "base_changes": base_changes, "short_ball": short_ball,
            "stock_fit": stock_fit, "floating": floating, "alt": alt,
            "backtest": _backtest(names, base_names, flow, exp, observed)}


def _stock_why(name, base_changes):
    """Orthodoxy line for a stock fielder; flag if it came from the GPS correction."""
    if base_changes and base_changes not in ("none", "") and name in base_changes:
        return "Standard post — GPS shows AUS actually man this here."
    return "Standard stock position."


def _backtest(names, base_names, flow, exp, observed):
    """Deviated field vs the untouched stock base (FIELD_PLAN §5). Catch cover = share of his
    expected mishit-carry sitting at catch positions; boundary cover = share of his boundary runs
    whose sector has a deep rider. Reports both the field's numbers and the delta vs stock."""
    def _cover(field_names):
        catch_pos = {n for n in field_names if (FIELD_POS.get(n) or field_coords(n))["role"] == "catch"}
        tot_exp = sum(exp.values()) or 1
        cc = sum(v for p, v in exp.items() if p in catch_pos) / tot_exp * 100
        deep_secs = {_NAME_SECTOR.get(n) for n in field_names
                     if (FIELD_POS.get(n) or field_coords(n))["role"] == "deep"}
        tot_b = sum(v["bdry"] for v in flow.values()) or 1
        bc = sum(v["bdry"] for s, v in flow.items() if s in deep_secs) / tot_b * 100
        return cc, bc

    cc, bc = _cover(names)
    base_cc, base_bc = _cover(base_names)
    total_catches = sum(v["catches"] for v in observed.values())
    catch_pos = {f for f in names if (FIELD_POS.get(f) or field_coords(f))["role"] == "catch"}
    covered_catches = sum(v["catches"] for p, v in observed.items() if p in catch_pos)
    return {"exp_catch_covered_pct": cc, "bdry_covered_pct": bc,
            "exp_catch_gain": cc - base_cc, "bdry_gain": bc - base_bc,
            "catches_covered": covered_catches, "catches_total": total_catches}


_GROUP_LABELS = {
    "right_pace": "right-arm pace", "left_pace": "left-arm pace", "pace": "pace",
    "off_spin": "off spin", "leg_spin": "leg spin", "left_orthodox": "left-arm orthodox",
    "left_unorthodox": "left-arm wrist spin", "spin": "spin", "all": "all bowling",
}


def _group_label(g):
    return _GROUP_LABELS.get(g, g)


def _sector_phrase(s):
    return {"third man": "to third man", "point": "square on the off",
            "cover": "through cover", "mid-off": "down the ground on the off",
            "straight": "straight down the ground", "mid-on": "down the ground on the leg",
            "midwicket": "through midwicket", "square leg": "square on the leg",
            "fine leg": "fine on the leg"}.get(s, f"to {s}")


_SLIP_CODE = {"1st": "S1", "2nd": "S2", "3rd": "S3", "4th": "S4", "5th": "S5", "6th": "S6",
              "1": "S1", "2": "S2", "3": "S3", "4": "S4", "5": "S5", "6": "S6"}


def _short_label(pos):
    """Compact code for a close catcher so the cordon doesn't stack long labels. Handles both
    the lookup-33 form ('Slip: 2nd') and the canonical name ('Slip 2')."""
    p = (pos or "").strip()
    low = p.lower()
    if low.startswith("slip"):
        tail = low.split(":", 1)[1].strip() if ":" in low else low.replace("slip", "").strip()
        return _SLIP_CODE.get(tail, "slip")
    if low == "gully":
        return "gully"
    if ":" in p:                       # "Square leg: short leg" -> "short leg"
        return p.split(":", 1)[1].strip()
    return p


# ── Field diagram ────────────────────────────────────────────────────────────────
def field_diagram(fieldset, is_lhb, title=""):
    """Circular field map drawn from behind the bowler — bowler at the BOTTOM, striker at
    the top of the pitch, so the keeper/slip cordon renders at the top (house convention,
    matches wagon_wheel_zones). Off side on the left for a RHB (mirrored for LHB). All
    fielders one uniform colour; roles live in the justification table. Returns a go.Figure."""
    import math
    import plotly.graph_objects as go
    from cricket_core.theme import (BG_PANEL, BG_PITCH, ACCENT, DANGER, TEXT_PRI, TEXT_SEC)

    R = 1.0
    fig = go.Figure()
    # boundary + 30-yard ring
    th = [i / 120 * 2 * math.pi for i in range(121)]
    fig.add_trace(go.Scatter(x=[R * math.cos(t) for t in th], y=[R * math.sin(t) for t in th],
                             mode="lines", line=dict(color="#2e7d32", width=2), fill="toself",
                             fillcolor=BG_PITCH, hoverinfo="skip", showlegend=False))
    ring = 0.62
    fig.add_trace(go.Scatter(x=[ring * math.cos(t) for t in th], y=[ring * math.sin(t) for t in th],
                             mode="lines", line=dict(color="#2e7d32", width=1, dash="dot"),
                             hoverinfo="skip", showlegend=False))
    # Ground centred on the PITCH (not the striker): striker sits one half-pitch behind the
    # centre, bowler one ahead, so both straight boundaries are equidistant. Fielder radius
    # (batter-relative, 0 = at the bat, 1 = at the rope) is scaled per direction so radius=1
    # lands on the boundary — farther down the ground than behind the keeper, since the striker
    # is now off-centre. tb(θ) = distance striker→boundary along θ.
    mirror = -1 if not is_lhb else 1     # RHB off side to the left
    D = 0.14                             # half the pitch length, as a fraction of the boundary

    def place(radius, ang_deg):
        th = math.radians(ang_deg)
        tb = D * math.cos(th) + math.sqrt(max(0.0, 1 - (D * math.sin(th)) ** 2))
        d = radius * tb
        return mirror * d * math.sin(th), -D + d * math.cos(th)

    # pitch strip, centred: striker end at -D (renders top), bowler end at +D (renders bottom)
    fig.add_shape(type="rect", x0=-0.045, x1=0.045, y0=-D, y1=D,
                  fillcolor="#c8a25a", line=dict(color="#a07d3a", width=1), opacity=0.55)

    for f in fieldset:
        if f["position"] == "Keeper":
            continue                      # drawn as its own cue behind the striker
        x, y = place(f["radius"], f["angle"])
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers",
            marker=dict(size=10, color=ACCENT, line=dict(color="#ffffff", width=1.5),
                        symbol="circle"),
            hovertext=f"{f['position']} — {f['why']}", hoverinfo="text", showlegend=False))
        # Close catchers get a compact code (S1/S2/gully…) so the tight cordon doesn't stack
        # verbose labels; the full name + reason live in the justification table.
        is_close = f["radius"] <= 0.4 or f["position"].lower().startswith("slip")
        text = _short_label(f["position"]) if is_close else f["position"]
        lx, ly = place(min(f["radius"] + (0.13 if is_close else 0.12), 1.06), f["angle"])
        fig.add_annotation(x=lx, y=ly, text=text, showarrow=False,
                           font=dict(size=7.5 if is_close else 8, color=TEXT_PRI),
                           bgcolor="rgba(255,255,255,0.72)", borderpad=1)
    # striker (at the striker's end) + keeper standing back behind (labels on the leg side,
    # clear of the off-side cordon; separated vertically so they don't stack)
    sx, sy = place(0.0, 0)
    kx, ky = place(0.13, 180)
    fig.add_trace(go.Scatter(x=[sx], y=[sy], mode="markers",
                  marker=dict(size=10, color=TEXT_PRI, symbol="triangle-down"),
                  hovertext="Striker", hoverinfo="text", showlegend=False))
    fig.add_trace(go.Scatter(x=[kx], y=[ky], mode="markers",
                  marker=dict(size=10, color=ACCENT, line=dict(color="#ffffff", width=1.5),
                              symbol="circle"),
                  hovertext="Keeper", hoverinfo="text", showlegend=False))
    fig.add_annotation(x=-mirror * 0.135, y=sy + 0.02, text="striker", showarrow=False,
                       font=dict(size=8, color=TEXT_SEC))
    fig.add_annotation(x=-mirror * 0.145, y=ky, text="keeper", showarrow=False,
                       font=dict(size=8, color=TEXT_SEC))
    fig.add_annotation(x=0, y=D + 0.06, text="bowler ▲", showarrow=False,
                       font=dict(size=8, color=TEXT_SEC))
    hand = "LHB — off side right" if is_lhb else "RHB — off side left"
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=TEXT_PRI), x=0.5, xanchor="center"),
        paper_bgcolor=BG_PANEL, plot_bgcolor=BG_PANEL,
        margin=dict(l=6, r=6, t=28 if title else 6, b=16), showlegend=False,
        xaxis=dict(visible=False, range=[-1.15, 1.15], scaleanchor="y", scaleratio=1),
        # Reversed y-axis (house convention, same as wagon_wheel_zones): bowler renders at
        # the BOTTOM, striker at the top — so the keeper/slip cordon sits at the top.
        yaxis=dict(visible=False, range=[1.15, -1.15]),
        annotations=list(fig.layout.annotations) + [dict(
            x=0, y=1.12, text=hand, showarrow=False, font=dict(size=8, color=TEXT_SEC))])
    return fig
