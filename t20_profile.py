"""
t20_profile.py — T20 bowler profile (phase-centric, league-strength adjusted).

Unlike Test/ODI, the T20 pack pools ALL major men's leagues (data_loaders fmt="T20"), because a
bowler's T20 body of work is spread across the IPL, BBL, Blast, internationals, etc. Those leagues
have very different run environments, so every economy/strike-rate is put on a NEUTRAL baseline
using the league-strength rating (referencebuilder/t20_league_strength.csv, built by
build_t20_league_strength.py): adjusted = raw − (his balls-weighted mean league effect). See memory
t20-league-strength.

Reuses the ODI profile's aggregation helpers; only the phase split (Powerplay 1–6 / Middle 7–15 /
Death 16–20) and the league adjustment are T20-specific.
"""
import csv
import os
from collections import Counter, defaultdict

from data_loaders import load_bowler_deliveries, load_bowler_info
from profile import process_rows, _quantile, _fingerprint
from odi_profile import (_phase_stats, _variations, _bowler_runs, _num, _mean,
                         _deepdive_all, _hand_over_round)
from ludis_cricket.lookups import (PACE_TYPES as _PACE_TYPES, SPIN_TYPES as _SPIN_TYPES,
                                   BOWLER_TYPE_OVERRIDE as _BT_OVERRIDE, team_flag)

T20_PHASES = ("Powerplay", "Middle", "Death")
_STRENGTH_CSV = r"c:\Ludis\referencebuilder\data\t20_league_strength.csv"
_STRENGTH = None


def _league_effects() -> dict:
    """{competition (Series.name): econ_effect_rpo} from the league-strength rating, memoised."""
    global _STRENGTH
    if _STRENGTH is None:
        _STRENGTH = {}
        if os.path.exists(_STRENGTH_CSV):
            with open(_STRENGTH_CSV, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        _STRENGTH[r["competition"]] = {"eff": float(r["econ_effect_rpo"]),
                                                       "league": r["league"], "thin": r["thin"] == "1"}
                    except (KeyError, ValueError):
                        pass
    return _STRENGTH


_PHASE_NORM_CSV = r"c:\Ludis\referencebuilder\data\bowler_t20_phase_profile.csv"
_PHASE_NORM = None


def _phase_norms() -> dict:
    """(bowler_id, pace_spin, phase) -> precomputed league-ADJUSTED econ/wkt percentiles, memoised."""
    global _PHASE_NORM
    if _PHASE_NORM is None:
        _PHASE_NORM = {}
        if os.path.exists(_PHASE_NORM_CSV):
            with open(_PHASE_NORM_CSV, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    _PHASE_NORM[(r["bowler_id"], r["pace_spin"], r["phase"])] = r
    return _PHASE_NORM


def _t20_phase(over_n):
    if over_n is None:
        return None
    if over_n <= 6:
        return "Powerplay"
    if over_n >= 16:
        return "Death"
    return "Middle"


def _env(legal: list) -> float:
    """His run-environment: balls-weighted mean league effect over a set of legal balls (rpo)."""
    effs = [r["lg_eff"] for r in legal if r.get("lg_eff") is not None]
    return sum(effs) / len(effs) if effs else 0.0


def _where_bowled(raw: list) -> list:
    """Balls by league, with each league's strength effect — the 'where he earned it' panel."""
    by = defaultdict(lambda: {"balls": 0, "runs": 0.0, "wkts": 0, "eff": 0.0})
    for r in raw:
        if not r["is_legal"]:
            continue
        k = r.get("league") or r.get("competition") or "?"
        by[k]["balls"] += 1
        by[k]["runs"] += _bowler_runs(r)
        by[k]["wkts"] += 1 if r["is_wicket"] else 0
        by[k]["eff"] = r.get("lg_eff", 0.0)          # constant within a league
    out = [{"league": lg, "balls": v["balls"], "econ": v["runs"] / (v["balls"] / 6.0),
            "wkts": v["wkts"], "eff": v["eff"]} for lg, v in by.items()]
    out.sort(key=lambda d: -d["balls"])
    return out


def _phase_block(rows: list, nb: int) -> dict | None:
    s = _phase_stats(rows)
    if not s:
        return None
    legal = [r for r in rows if r["is_legal"]]
    env = _env(legal)
    s["econ_adj"] = s["economy"] - env
    s["env"] = env
    s["pct_balls"] = len(legal) / nb * 100 if nb else 0
    return s


def build_t20_profile(bowler_id: str) -> dict:
    raw = process_rows(load_bowler_deliveries(str(bowler_id), fmt="T20"))
    if not raw:
        return {"bowler_id": str(bowler_id), "name": f"Bowler {bowler_id}", "empty": True}

    eff = _league_effects()
    bt_fix = _BT_OVERRIDE.get(str(bowler_id))
    for r in raw:
        if bt_fix:
            r["bowler_type_simple"] = bt_fix
        r["phase"] = _t20_phase(r.get("over_n"))
        r["era"] = None                          # T20 has no ball-change era; keeps _death_deepdive happy
        info_lg = eff.get(r.get("competition"))
        r["lg_eff"] = info_lg["eff"] if info_lg else 0.0
        r["league"] = info_lg["league"] if info_lg else (r.get("competition") or "?")

    info = load_bowler_info(str(bowler_id), fmt="T20I") or {}
    name = (info.get("player_name") or f"Bowler {bowler_id}").strip()
    team = (info.get("team_name") or "").strip()
    flag = team_flag(team)[0] if team else ""

    legal = [r for r in raw if r["is_legal"]]
    primary_type = Counter(r["bowler_type_simple"] for r in legal).most_common(1)[0][0] if legal else "Unknown"
    is_pace = primary_type in _PACE_TYPES
    is_spin = primary_type in _SPIN_TYPES
    hand = "Left" if primary_type.startswith("Left") else "Right"

    med_speed = _quantile(sorted(_num(legal, "ball_speed_n")), 0.5) if is_pace else None
    off_pace = med_speed - 12 if med_speed else None

    nb = len(legal)
    runs = sum(_bowler_runs(r) for r in raw)
    wkts = sum(1 for r in legal if r["is_wicket"])
    speeds = sorted(_num(legal, "ball_speed_n"))
    env = _env(legal)
    raw_econ = runs / (nb / 6.0) if nb else None

    phases = []
    for ph in T20_PHASES:
        blk = _phase_block([r for r in raw if r["phase"] == ph], nb)
        if blk:
            phases.append(dict(phase=ph, **blk))

    # league-ADJUSTED economy/wicket percentiles vs T20 phase peers (precomputed in the norm)
    pn = _phase_norms()
    ps = "pace" if is_pace else ("spin" if is_spin else None)
    for ph in phases:
        row = pn.get((str(bowler_id), ps, ph["phase"])) if ps else None
        _pv = lambda k: (int(float(row[k])) if row and row.get(k) not in (None, "") else None)
        ph["econ_pctl"] = _pv("econ_pctl")
        ph["wkt_pctl"] = _pv("wkt_pctl")
        ph["peer_n"] = _pv("peer_n")

    return {
        "bowler_id": str(bowler_id), "name": name, "team": team, "flag": flag,
        "primary_type": primary_type, "is_pace": is_pace, "is_spin": is_spin, "hand": hand,
        "raw": raw,
        # headline — raw + league-neutral adjusted economy
        "matches": len({r["match_id"] for r in raw}), "balls": nb, "overs": nb / 6.0,
        "wickets": wkts, "runs": runs,
        "economy": raw_econ, "economy_adj": (raw_econ - env) if raw_econ is not None else None,
        "env": env,
        "average": runs / wkts if wkts else None, "strike_rate": nb / wkts if wkts else None,
        "avg_speed": _mean(speeds), "top_speed": _quantile(speeds, 0.99) if speeds else None,
        # canonical keys for the shared headline_cards() row
        "n_balls": nb, "n_wkts": wkts, "bowl_avg": runs / wkts if wkts else None,
        "avg_spd": _mean(speeds), "max_spd_99": _quantile(speeds, 0.99) if speeds else None,
        # sections
        "fingerprint": _fingerprint(str(bowler_id), is_pace, is_spin, fmt="T20"),
        "phases": phases,
        "variations": _variations(raw, off_pace),
        "deepdive": _deepdive_all(raw, off_pace, T20_PHASES) if is_pace else None,
        "vs_hand": _hand_over_round(raw),
        "where_bowled": _where_bowled(raw),
        "off_pace_kph": off_pace, "n_leagues": len({r["league"] for r in legal}),
    }


if __name__ == "__main__":
    import warnings; warnings.filterwarnings("ignore")
    for bid, who in [("2580072", "Ellis"), ("1300007", "Starc")]:
        P = build_t20_profile(bid)
        print(f"\n=== {who}: {P['name']} ({P['primary_type']}) — {P['matches']} T20s, {P['balls']} balls, "
              f"{P['wickets']}w ===")
        print(f"  economy raw {P['economy']:.2f} -> adjusted {P['economy_adj']:.2f} "
              f"(env {P['env']:+.2f}, {P['n_leagues']} leagues)")
        for ph in P["phases"]:
            print(f"  {ph['phase']:<10} {ph['pct_balls']:>4.0f}% | econ {ph['economy']:.2f} -> adj {ph['econ_adj']:.2f} | {ph['wickets']}w")
        print("  where:", ", ".join(f"{w['league']} {w['balls']}" for w in P["where_bowled"]))
