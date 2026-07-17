"""
odi_profile.py — ODI bowler profile (phase-centric, economy-forward). Builds on the shared
Test enrichment (`profile.process_rows`, `data_loaders.load_bowler_deliveries(fmt="ODI")`) and
adds the ODI structure:

  • Phases (by role, era-robust): Powerplay (1-10) / Middle (11-40) / Death (41-50).
  • Ball-change ERA tag by match_date (see memory `odi-ball-rules`): two-ball era (C, Oct-2011→
    1-Jul-2025) vs the new pick-one-ball era (D, from 2-Jul-2025). The death deep-dive splits by
    era because the ball condition (hard newish vs old reverse-swinging) is completely different.
  • Variations from `ball_movement` (lookup 2812: Slower ball / Offcutter / Legcutter / …),
    backfilled with an off-pace-speed heuristic where the ball is uncoded.

No peer/fingerprint percentiles yet — those need an ODI-bowler norm build in referencebuilder.
"""
from collections import Counter, defaultdict

from data_loaders import load_bowler_deliveries, load_bowler_info
import statistics
from profile import (process_rows, _safe_float, _quantile, _SHORT_BUCKETS, _fingerprint, recent_fingerprint_vals,
                    _pctl_of, load_phase_profiles)
from cricket_core.lookups import (PACE_TYPES as _PACE_TYPES, SPIN_TYPES as _SPIN_TYPES,
                                   BOWLER_TYPE_OVERRIDE as _BT_OVERRIDE)
from cricket_core.lookups import team_flag
from cricket_core.charts import LENGTH_ZONES_PACE   # authoritative pace length bands

_LENGTH_BANDS = [lab for _lo, _hi, lab in LENGTH_ZONES_PACE]   # Yorker/Full … Short (in order)


def _length_band(m):
    if m is None:
        return None
    for lo, hi, lab in LENGTH_ZONES_PACE:
        if lo <= m < hi:
            return lab
    return "Short" if m is not None and m >= 15 else None

# ── Phases (by over number) ─────────────────────────────────────────────────────────
PHASES = ("Powerplay", "Middle", "Death")


def _phase(over_n):
    if over_n is None:
        return None
    if over_n <= 10:
        return "Powerplay"
    if over_n >= 41:
        return "Death"
    return "Middle"


# ── Ball-change era (by match_date) — see memory odi-ball-rules ──────────────────────
def _era(match_date):
    if not match_date:
        return None
    if match_date < "2007-10-01":
        return "A"          # 1 ball, umpire discretion
    if match_date < "2011-10-01":
        return "B"          # 1 ball, swap after over 34
    if match_date < "2025-07-02":
        return "C"          # 2 new balls (one each end) — the modern default
    return "D"              # 2 balls to over 34, then pick one for 35-50


_ERA_LABEL = {"A": "1-ball (pre-2007)", "B": "1-ball + swap (2007-11)",
              "C": "two new balls (2011-Jul25)", "D": "two→one from ov35 (Jul25+)"}

# Variation types (lookup 2812) that count as genuine slower-ball / cutter variations for pace.
_SLOWER_VARIATIONS = {"Slower ball", "Offcutter", "Legcutter", "Knuckle Ball", "Back of Hand"}
_SEAM_TYPES = {"Seam in", "Seam away", "Offcutter", "Legcutter"}


def _num(rows, key):
    return [r[key] for r in rows if r.get(key) is not None]


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _bowler_runs(r):
    """Runs charged to the bowler on a delivery: off the bat + wides + no-balls (byes/leg-byes
    are not the bowler's)."""
    return (r.get("bat_score_n") or 0.0) + (r.get("wide_runs_n") or 0.0) + (r.get("noball_runs_n") or 0.0)


def _is_boundary(r):
    return (r.get("bat_score_n") or 0.0) in (4.0, 6.0)


def _phase_stats(rows):
    """Aggregate one bowler-phase (list of rows). Economy-forward."""
    legal = [r for r in rows if r["is_legal"]]
    nb = len(legal)
    if not nb:
        return None
    runs = sum(_bowler_runs(r) for r in rows)          # all rows (extras land on illegal balls too)
    wkts = sum(1 for r in legal if r["is_wicket"])      # (run-outs excluded — bowler_dismissal only)
    fours_sixes = sum(1 for r in legal if _is_boundary(r))
    dots = sum(1 for r in legal if _bowler_runs(r) == 0)
    return {
        "balls": nb, "overs": nb / 6.0, "runs": runs, "wickets": wkts,
        "economy": runs / (nb / 6.0),
        "average": runs / wkts if wkts else None,
        "strike_rate": nb / wkts if wkts else None,
        "boundary_pct": fours_sixes / nb * 100,
        "dot_pct": dots / nb * 100,
        "avg_speed": _mean(_num(legal, "ball_speed_n")),
        "avg_length": _mean([r["pitch_length_m"] for r in legal
                             if r.get("pitch_length_m") is not None and -1 <= r["pitch_length_m"] <= 16]),
    }


def _var_type(r, off_pace_kph):
    """The slower-ball / cutter VARIATION type for a pace delivery, or None. Coded ball_movement
    (lookup 2812) first; else infer a slower ball where the pace is well off his stock and the
    ball is uncoded. (Swing types are movement, not variations — handled separately.)"""
    bm = r.get("ball_movement")
    if bm in _SLOWER_VARIATIONS:
        return bm
    if off_pace_kph and r.get("ball_speed_n") is not None and r["ball_speed_n"] < off_pace_kph \
            and bm in (None, "None", "No movement", ""):
        return "Slower ball (off-pace)"
    return None


def _variations(rows, off_pace_kph):
    """Variation analysis for pace: overall mix, WHAT he bowls per phase, and HOW each variation
    is bowled (length band). All over legal balls."""
    legal = [r for r in rows if r["is_legal"]]
    nb = len(legal)
    var_rows = [(r, _var_type(r, off_pace_kph)) for r in legal]
    var_rows = [(r, v) for r, v in var_rows if v]
    coded = sum(1 for r in legal if r.get("ball_movement") not in (None, "None", "No movement", ""))
    mix = Counter(v for _, v in var_rows)
    phase_totals = Counter(r["phase"] for r in legal if r.get("phase"))
    by_phase = defaultdict(Counter)      # {variation: {phase: count}}
    by_length = defaultdict(Counter)     # {variation: {length band: count}}
    for r, v in var_rows:
        if r.get("phase"):
            by_phase[v][r["phase"]] += 1
        b = _length_band(r.get("pitch_length_m"))
        if b:
            by_length[v][b] += 1
    return {
        "rows": [{"type": t, "count": c, "pct": c / nb * 100} for t, c in mix.most_common()],
        "coded_pct": coded / nb * 100 if nb else 0,
        "slower_pct": len(var_rows) / nb * 100 if nb else 0,
        "phase_totals": dict(phase_totals),
        "by_phase": {v: dict(c) for v, c in by_phase.items()},
        "by_length": {v: dict(c) for v, c in by_length.items()},
    }


def _yorker_full(r):
    """Yorker / very full: pitched up near the crease (small length from the stumps)."""
    m = r.get("pitch_length_m")
    return m is not None and m < 1.5


def _death_deepdive(death_rows, off_pace_kph):
    """Death overs (41-50) for pace — split by ball-change era (C vs D matters most here)."""
    def block(rows):
        legal = [r for r in rows if r["is_legal"]]
        nb = len(legal)
        if not nb:
            return None
        runs = sum(_bowler_runs(r) for r in rows)
        yk = sum(1 for r in legal if _yorker_full(r))
        sl = sum(1 for r in legal if (r.get("ball_movement") in _SLOWER_VARIATIONS)
                 or (off_pace_kph and r.get("ball_speed_n") and r["ball_speed_n"] < off_pace_kph))
        return {"balls": nb, "economy": runs / (nb / 6.0),
                "boundary_pct": sum(1 for r in legal if _is_boundary(r)) / nb * 100,
                "yorker_pct": yk / nb * 100, "slower_pct": sl / nb * 100,
                "wickets": sum(1 for r in legal if r["is_wicket"])}
    by_era = {}
    for era in ("C", "D"):
        b = block([r for r in death_rows if r["era"] == era])
        if b and b["balls"] >= 30:
            by_era[era] = {**b, "label": _ERA_LABEL[era]}
    return {"overall": block(death_rows), "by_era": by_era}


_YORKER_MAX_M = 2.0                      # yorker / very-full length (m)
_YORKER_LINE_ORDER = ["Wide (the hole)", "Off / channel", "At the stumps", "Leg stump / straight"]


def _yorker_line_band(m):
    """Batter-relative pitch line (neg = off) → yorker line band. Answers 'wide hole vs
    leg-stump yorker'. Boundaries in stump widths (~0.114 m each) off middle."""
    if m < -0.40:
        return "Wide (the hole)"          # wide outside off — the wide yorker
    if m < -0.15:
        return "Off / channel"            # off stump to 4th-5th
    if m <= 0.15:
        return "At the stumps"
    return "Leg stump / straight"


def _yorker_line_split(rows):
    """Line split of yorker/very-full balls. `bands` is None if the sample is too thin to read."""
    ys = [r for r in rows if r["is_legal"] and r.get("pitch_length_m") is not None
          and r["pitch_length_m"] < _YORKER_MAX_M and r.get("pitch_line_m") is not None]
    n = len(ys)
    c = Counter(_yorker_line_band(r["pitch_line_m"]) for r in ys)
    return {"n": n, "thin": n < 15,
            "bands": ([{"band": b, "pct": c.get(b, 0) / n * 100, "count": c.get(b, 0)}
                       for b in _YORKER_LINE_ORDER] if n >= 6 else None)}


# ── Bouncer line + unified pace deep-dive (yorker/bouncer/slower, per phase + overall) ──
_BOUNCER_LINE_ORDER = ["Wide (outside off)", "At the body / head", "Down the leg side"]


def _is_bouncer(r):
    """Short / banged-in delivery (the bouncer length band)."""
    return _length_band(r.get("pitch_length_m")) == "Short"


def _bouncer_line_band(m):
    """Where a bouncer passes the stump line (at_stumps_line_m, neg = off): head/body vs wide."""
    if m < -0.25:
        return "Wide (outside off)"
    if m <= 0.20:
        return "At the body / head"
    return "Down the leg side"


def _line_bands(balls, band_fn, key, order, min_show=6, thin_below=15):
    """Generic stump/pitch-line split of a ball set (yorker line, bouncer line)."""
    vals = [r for r in balls if r["is_legal"] and r.get(key) is not None]
    n = len(vals)
    c = Counter(band_fn(r[key]) for r in vals)
    top = max(c.items(), key=lambda kv: kv[1])[0] if c else None
    return {"n": n, "thin": n < thin_below, "top_band": top,
            "bands": ([{"band": b, "pct": c.get(b, 0) / n * 100, "count": c.get(b, 0)} for b in order]
                      if n >= min_show else None)}


def _deepdive(rows, off_pace):
    """One pace deep-dive block (a phase, or overall): economy/wkts/boundary/dot, new-ball swing,
    plus YORKER and BOUNCER frequency + line, and the slower-ball yorker / slower-ball bouncer
    split (with their lines). Merges the old variation + yorker sections into one."""
    legal = [r for r in rows if r["is_legal"]]
    nb = len(legal)
    if not nb:
        return None
    runs = sum(_bowler_runs(r) for r in rows)
    yorkers = [r for r in legal if _yorker_full(r)]
    bouncers = [r for r in legal if _is_bouncer(r)]
    slower = [r for r in legal if _var_type(r, off_pace)]
    sl_york = [r for r in yorkers if _var_type(r, off_pace)]
    sl_bounce = [r for r in bouncers if _var_type(r, off_pace)]
    moved = [r for r in legal if r.get("swing_dir") in ("in", "out")]
    inn = sum(1 for r in moved if r["swing_dir"] == "in")

    def pct(x):
        return len(x) / nb * 100
    return {
        "balls": nb, "economy": runs / (nb / 6.0),
        "wickets": sum(1 for r in legal if r["is_wicket"]),
        "wkt_rate": sum(1 for r in legal if r["is_wicket"]) / nb * 100,
        "boundary_pct": sum(1 for r in legal if _is_boundary(r)) / nb * 100,
        "dot_pct": sum(1 for r in legal if _bowler_runs(r) == 0) / nb * 100,
        "avg_speed": _mean(_num(legal, "ball_speed_n")),
        "swing_seen_pct": len(moved) / nb * 100,
        "swing_in_pct": inn / len(moved) * 100 if moved else None,
        "swing_out_pct": (len(moved) - inn) / len(moved) * 100 if moved else None,
        "yorker_pct": pct(yorkers), "bouncer_pct": pct(bouncers), "slower_pct": pct(slower),
        "yorker_line": _line_bands(yorkers, _yorker_line_band, "pitch_line_m", _YORKER_LINE_ORDER),
        "bouncer_line": _line_bands(bouncers, _bouncer_line_band, "at_stumps_line_m", _BOUNCER_LINE_ORDER),
        "slower_yorker": {"pct": pct(sl_york), "n": len(sl_york),
                          "line": _line_bands(sl_york, _yorker_line_band, "pitch_line_m", _YORKER_LINE_ORDER)},
        "slower_bouncer": {"pct": pct(sl_bounce), "n": len(sl_bounce),
                           "line": _line_bands(sl_bounce, _bouncer_line_band, "at_stumps_line_m", _BOUNCER_LINE_ORDER)},
    }


def _deepdive_all(raw, off_pace, phases):
    """Overall + per-phase deep-dives (pace) — the overall block first, then each phase."""
    out = {"overall": _deepdive(raw, off_pace), "phases": []}
    for ph in phases:
        blk = _deepdive([r for r in raw if r["phase"] == ph], off_pace)
        if blk:
            out["phases"].append({"phase": ph, **blk})
    return out


def _hand_over_round(rows):
    """vs LHB / vs RHB, each split over vs round the wicket + the round-the-wicket share of that
    hand (e.g. 40% of his balls to LHB are round the wicket)."""
    out = {}
    for lab, is_lhb in (("vs LHB", True), ("vs RHB", False)):
        hand = [r for r in rows if r["is_lhb"] == is_lhb]
        s = _phase_stats(hand)
        if not s or s["balls"] < 40:
            continue
        known = [r for r in hand if r["is_legal"] and r.get("is_round") is not None]
        round_n = sum(1 for r in known if r["is_round"])
        out[lab] = {**s, "round_pct": round_n / len(known) * 100 if known else None,
                    "over": _phase_stats([r for r in hand if r.get("is_round") is False]),
                    "round": _phase_stats([r for r in hand if r.get("is_round") is True])}
    return out


def _powerplay_deepdive(pp_rows):
    """Powerplay (1-10) for pace — new-ball swing + wicket threat + length."""
    legal = [r for r in pp_rows if r["is_legal"]]
    nb = len(legal)
    if not nb:
        return None
    runs = sum(_bowler_runs(r) for r in pp_rows)
    moved = [r for r in legal if r.get("swing_dir") in ("in", "out")]
    inn = sum(1 for r in moved if r["swing_dir"] == "in")
    hard = sum(1 for r in legal if r.get("pitch_length_m") is not None and 6.0 <= r["pitch_length_m"] <= 8.5)
    return {"balls": nb, "economy": runs / (nb / 6.0),
            "wickets": sum(1 for r in legal if r["is_wicket"]),
            "wkt_rate": sum(1 for r in legal if r["is_wicket"]) / nb * 100,
            "swing_in_pct": inn / len(moved) * 100 if moved else None,
            "swing_out_pct": (len(moved) - inn) / len(moved) * 100 if moved else None,
            "swing_seen_pct": len(moved) / nb * 100,
            "hard_length_pct": hard / nb * 100,
            "avg_speed": _mean(_num(legal, "ball_speed_n"))}


def _hand_split(rows):
    out = {}
    for lab, is_lhb in (("vs LHB", True), ("vs RHB", False)):
        s = _phase_stats([r for r in rows if r["is_lhb"] == is_lhb])
        if s:
            out[lab] = s
    return out


def build_odi_profile(bowler_id: str) -> dict:
    raw = process_rows(load_bowler_deliveries(str(bowler_id), fmt="ODI"))
    if not raw:
        return {"bowler_id": str(bowler_id), "name": f"Bowler {bowler_id}", "empty": True}

    bt_fix = _BT_OVERRIDE.get(str(bowler_id))
    for r in raw:
        if bt_fix:
            r["bowler_type_simple"] = bt_fix
        r["phase"] = _phase(r.get("over_n"))
        r["era"] = _era(r.get("match_date"))

    info = load_bowler_info(str(bowler_id), fmt="ODI") or {}
    name = (info.get("player_name") or f"Bowler {bowler_id}").strip()
    team = (info.get("team_name") or "").strip()
    flag = team_flag(team)[0] if team else ""

    legal = [r for r in raw if r["is_legal"]]
    primary_type = Counter(r["bowler_type_simple"] for r in legal).most_common(1)[0][0] if legal else "Unknown"
    is_pace = primary_type in _PACE_TYPES
    is_spin = primary_type in _SPIN_TYPES
    hand = "Left" if primary_type.startswith("Left") else "Right"

    # off-pace threshold: ~12 km/h under his median stock pace (pace only)
    med_speed = _quantile(sorted(_num(legal, "ball_speed_n")), 0.5) if is_pace else None
    off_pace = med_speed - 12 if med_speed else None

    nb = len(legal)
    runs = sum(_bowler_runs(r) for r in raw)
    wkts = sum(1 for r in legal if r["is_wicket"])
    speeds = sorted(_num(legal, "ball_speed_n"))

    # ── headline extras for the shared headline_cards() row (defined exactly as the Test build) ──
    _lengths = [r["pitch_length_m"] for r in legal if r.get("pitch_length_m") is not None]
    avg_len_m = statistics.median(_lengths) if _lengths else None          # median: bad/neg lengths wreck the mean
    short_pct = (sum(1 for r in legal if r.get("pitch_length_group_m") in _SHORT_BUCKETS) / nb * 100) if nb else 0.0
    _kr = [r for r in legal if r.get("is_round") is not None]
    round_pct = sum(1 for r in _kr if r["is_round"]) / len(_kr) * 100 if _kr else None
    _rl = [r for r in _kr if r["is_lhb"]]
    _rr = [r for r in _kr if not r["is_lhb"]]
    round_lhb = sum(1 for r in _rl if r["is_round"]) / len(_rl) * 100 if _rl else None
    round_rhb = sum(1 for r in _rr if r["is_round"]) / len(_rr) * 100 if _rr else None

    phases = []
    for ph in PHASES:
        s = _phase_stats([r for r in raw if r["phase"] == ph])
        if s:
            phases.append({"phase": ph, "pct_balls": s["balls"] / nb * 100, **s})

    # Peer-benchmark each phase vs modern-era ODI peers of the same pace/spin, so the reader knows
    # if an economy/wicket-rate is good *for that phase* (economy: lower = better -> inverted so a
    # high percentile = elite; wicket rate: higher = better).
    _pnorm = load_phase_profiles("ODI")
    _ps = "pace" if is_pace else "spin"
    for ph in phases:
        _pe = [_safe_float(r["economy"]) for r in _pnorm
               if r.get("pace_spin") == _ps and r.get("phase") == ph["phase"]]
        _pe = [x for x in _pe if x is not None]
        _pw = [_safe_float(r["wkt_rate"]) for r in _pnorm
               if r.get("pace_spin") == _ps and r.get("phase") == ph["phase"]]
        _pw = [x for x in _pw if x is not None]
        _raw_e = _pctl_of(ph["economy"], _pe) if len(_pe) >= 8 else None
        ph["econ_pctl"] = round(100 - _raw_e) if _raw_e is not None else None
        _wr = ph["wickets"] / ph["balls"] * 100 if ph["balls"] else None
        _raw_w = _pctl_of(_wr, _pw) if len(_pw) >= 8 else None
        ph["wkt_pctl"] = round(_raw_w) if _raw_w is not None else None
        ph["peer_n"] = len(_pe)

    eras = {}
    for era in ("A", "B", "C", "D"):
        e_legal = [r for r in legal if r["era"] == era]
        if e_legal:
            eras[era] = {"label": _ERA_LABEL[era], "balls": len(e_legal),
                         "pct": len(e_legal) / nb * 100}

    death_rows = [r for r in raw if r["phase"] == "Death"]
    pp_rows = [r for r in raw if r["phase"] == "Powerplay"]

    return {
        "bowler_id": str(bowler_id), "name": name, "team": team, "flag": flag,
        "primary_type": primary_type, "is_pace": is_pace, "is_spin": is_spin, "hand": hand,
        "raw": raw,
        # headline (full ODI record)
        "matches": len({r["match_id"] for r in raw}), "balls": nb, "overs": nb / 6.0,
        "wickets": wkts, "runs": runs, "economy": runs / (nb / 6.0) if nb else None,
        "average": runs / wkts if wkts else None, "strike_rate": nb / wkts if wkts else None,
        "avg_speed": _mean(speeds), "top_speed": _quantile(speeds, 0.99) if speeds else None,
        # canonical keys for the shared headline_cards() builder (identical row to Test / T20)
        "n_balls": nb, "n_wkts": wkts, "bowl_avg": runs / wkts if wkts else None,
        "avg_spd": _mean(speeds), "max_spd_99": _quantile(speeds, 0.99) if speeds else None,
        "avg_len_m": avg_len_m, "short_pct": short_pct,
        "round_pct": round_pct, "round_lhb": round_lhb, "round_rhb": round_rhb,
        # sections
        "fingerprint": _fingerprint(str(bowler_id), is_pace, is_spin, fmt="ODI", recent_vals=recent_fingerprint_vals(raw, is_spin)),
        "phases": phases,
        "variations": _variations(raw, off_pace),
        "deepdive": _deepdive_all(raw, off_pace, PHASES) if is_pace else None,
        "vs_hand": _hand_over_round(raw),
        "eras": eras,
        "off_pace_kph": off_pace, "med_speed_kph": med_speed,
    }


if __name__ == "__main__":
    import warnings; warnings.filterwarnings("ignore")
    for bid, who in [("1300007", "Starc"), ("2580072", "Ellis")]:
        P = build_odi_profile(bid)
        print(f"\n=== {who}: {P['name']} ({P['primary_type']}) — {P['matches']} ODIs, "
              f"{P['wickets']}w @ econ {P['economy']:.2f} | top {P['top_speed']:.0f} kph ===")
        for ph in P["phases"]:
            print(f"  {ph['phase']:<10} {ph['pct_balls']:>4.0f}% balls | econ {ph['economy']:.2f} | "
                  f"{ph['wickets']}w | bdry {ph['boundary_pct']:.0f}% | dot {ph['dot_pct']:.0f}% | "
                  f"avg spd {ph['avg_speed'] and round(ph['avg_speed'])}")
        v = P["variations"]
        print(f"  variations ({v['coded_pct']:.0f}% coded, slower {v['slower_pct']:.0f}%): "
              + ", ".join(f"{r['type']} {r['pct']:.0f}%" for r in v["rows"][:5]))
        if P["death"] and P["death"]["overall"]:
            d = P["death"]["overall"]
            print(f"  DEATH: econ {d['economy']:.2f} | yorker {d['yorker_pct']:.0f}% | "
                  f"slower {d['slower_pct']:.0f}% | bdry {d['boundary_pct']:.0f}% "
                  + ("| era-split: " + " ".join(f"{e}={b['economy']:.2f}econ" for e, b in P['death']['by_era'].items()) if P['death']['by_era'] else ""))
        print("  eras:", {e: f"{v['pct']:.0f}%" for e, v in P["eras"].items()})
