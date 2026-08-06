"""Build a player profile from the cricket21 mirror, in the same artefact shape.

The warehouse holds no Bangladesh domestic cricket, so the two uncapped players in BAN's Test
squad have no profile from our usual source. `cricket21` mirrors their first-class record
locally (59 matches / 89,243 deliveries); this reads that mirror and produces the **same
artefact envelope** as `artefact.publish()` does for a warehouse profile.

That is the profile/rendering seam doing its job: two different sources, one artefact contract,
and a rendering that does not care which produced it.

    python profile_from_mirror.py --name "Amite Hasan" --role batter
    python profile_from_mirror.py --name "Musfik Hasan" --role bowler

**What this profile carries and what it does not.** The mirror has line/length coordinates
(calibrated to warehouse scale), pace/spin, outcomes, dismissals and a per-ball clip URL. It has
**no Hawk-Eye release/stump data** for domestic matches (those fields are null at source) and no
ball speed where there was no speed gun. So there is no beehive, no release point and no swing
here — the profile says so rather than implying coverage it lacks.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import statistics as st
from collections import Counter
from pathlib import Path

import artefact

MIRROR = Path(os.environ.get(
    "CRICKET21_MIRROR",
    str(Path(__file__).parent.parent / "cricket21" / "data" / "cricket21_mirror.sqlite")))

# Calibrated pitch_length is warehouse-scale (mm down the pitch from the batter's stumps).
LENGTH_BANDS = [(0, 2000, "Yorker/Full toss"), (2000, 4000, "Full"), (4000, 6000, "Good"),
                (6000, 8000, "Back of a length"), (8000, 99999, "Short")]
LINE_BANDS = [(-9999, -400, "Down leg"), (-400, -100, "On the pads"), (-100, 150, "At the stumps"),
              (150, 500, "4th stump"), (500, 900, "6th stump"), (900, 9999, "Wide outside off")]


def _band(v, bands):
    if v is None:
        return None
    for lo, hi, label in bands:
        if lo <= v < hi:
            return label
    return None


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _pct(n, d):
    return round(100 * n / d, 1) if d else None


def build(name: str, role: str, mirror: Path = MIRROR) -> dict:
    if not mirror.exists():
        raise FileNotFoundError(f"No cricket21 mirror at {mirror}. Run its importer first.")
    conn = sqlite3.connect(mirror)
    conn.row_factory = sqlite3.Row
    col = "striker_name" if role == "batter" else "bowler_name"
    balls = _rows(conn, f"SELECT * FROM deliveries WHERE {col}=? ORDER BY match_id, match_innings, ball_seq", (name,))
    comps = _rows(conn, f"""SELECT m.competition_name comp, m.format, COUNT(*) balls
                            FROM deliveries d JOIN matches m ON d.match_id=m.match_id
                            WHERE d.{col}=? GROUP BY m.competition_name, m.format ORDER BY comp""", (name,))
    conn.close()
    if not balls:
        raise SystemExit(f"No deliveries for {name!r} as {role} in the mirror.")

    n = len(balls)
    runs = sum(b["bat_score"] or 0 for b in balls) if role == "batter" else sum(b["total_runs"] or 0 for b in balls)
    outs = sum(1 for b in balls if b["striker_dismissed"])
    wkts = sum(1 for b in balls if b["how_out"] and b["how_out"] not in ("Run Out", "Runout"))
    matches = len({b["match_id"] for b in balls})
    with_video = sum(1 for b in balls if b["video_available"] == 1)
    tracked = [b for b in balls if b["pitch_length"] is not None]

    # pace/spin split (1 = pace, 2 = spin in the mirror)
    def split(key):
        out = {}
        for lbl, code in (("pace", "1"), ("spin", "2")):
            sub = [b for b in balls if str(b["pace_spin"]) == code]
            if not sub:
                continue
            r = sum((b["bat_score"] if role == "batter" else b["total_runs"]) or 0 for b in sub)
            d = sum(1 for b in sub if (b["striker_dismissed"] if role == "batter" else
                                       (b["how_out"] and b["how_out"] not in ("Run Out", "Runout"))))
            out[lbl] = {"balls": len(sub), "runs": r, "dismissals": d,
                        "avg": round(r / d, 1) if d else None,
                        "sr": round(100 * r / len(sub), 1) if role == "batter" else None,
                        "econ": round(6 * r / len(sub), 2) if role == "bowler" else None}
        return out

    lengths = Counter(filter(None, (_band(b["pitch_length"], LENGTH_BANDS) for b in tracked)))
    lines = Counter(filter(None, (_band(b["pitch_line"], LINE_BANDS) for b in tracked)))
    dismissals = Counter(b["how_out"] for b in balls
                         if b["how_out"] and (b["striker_dismissed"] if role == "batter" else True))
    speeds = [b["ball_speed"] for b in balls if b["ball_speed"]]

    P = {
        "player_id": f"c21:{name.replace(' ', '_')}",
        "name": name,
        "role": role,
        "source": "cricket21 mirror",
        "competitions": comps,
        "matches": matches, "n_balls": n, "runs": runs,
        "dismissals": outs if role == "batter" else None,
        "wickets": wkts if role == "bowler" else None,
        "average": round(runs / outs, 1) if (role == "batter" and outs) else (
            round(runs / wkts, 1) if (role == "bowler" and wkts) else None),
        "strike_rate": round(100 * runs / n, 1) if role == "batter" else None,
        "economy": round(6 * runs / n, 2) if role == "bowler" else None,
        "bowl_strike_rate": round(n / wkts, 1) if (role == "bowler" and wkts) else None,
        "boundary_pct": _pct(sum(1 for b in balls if b["is_four"] or b["is_six"]), n),
        "dot_pct": _pct(sum(1 for b in balls if not (b["total_runs"] or 0)), n),
        "vs_pace_spin": split("pace_spin"),
        "pitch_length_mix": dict(lengths.most_common()),
        "pitch_line_mix": dict(lines.most_common()),
        "dismissal_counts": dict(dismissals.most_common()),
        "ball_speed": {"n": len(speeds), "mean": round(st.mean(speeds), 1) if speeds else None},
        "coverage": {
            "balls_tracked": len(tracked), "tracked_pct": _pct(len(tracked), n),
            "balls_with_video": with_video, "video_pct": _pct(with_video, n),
            "has_hawkeye_release": False, "has_beehive": False,
            "note": "Domestic first-class: line/length + shot data only. No Hawk-Eye release or "
                    "stump-line fields at source, and ball speed only where a gun was present.",
        },
    }
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--role", choices=["batter", "bowler"], required=True)
    args = ap.parse_args()
    P = build(args.name, args.role)
    path = artefact.publish(P, kind=args.role)
    c = P["coverage"]
    print(f"{P['name']} ({P['role']}) — {P['matches']} matches, {P['n_balls']} balls")
    if args.role == "batter":
        print(f"  {P['runs']} runs, {P['dismissals']} outs, avg {P['average']}, SR {P['strike_rate']}")
    else:
        print(f"  {P['wickets']} wkts, econ {P['economy']}, avg {P['average']}, SR {P['bowl_strike_rate']}")
    print(f"  vs pace/spin: {P['vs_pace_spin']}")
    print(f"  lengths: {P['pitch_length_mix']}")
    print(f"  tracked {c['tracked_pct']}% | video {c['video_pct']}%")
    print(f"  artefact -> {path}")


if __name__ == "__main__":
    main()
