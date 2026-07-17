"""
build_opponent_about.py — distil each opposition player's SCOUTING profile into a few plain
facts for the player packs. Players want "what is this bowler/batter about?", not a simulation
(Tom, 2026-07-16) — the full scouting reports have it but are too detailed, so we condense.

For each opposition bowler: type + pace, stock ball, where the wickets come, movement.
For each opposition batter: how they score, pace vs spin, how they get out, early vs set.

Source = the same profile builders the scouting reports use (report.build_profile /
batter_profile.build_batter_profile). Cached to data/opponent_about_{opp}.json; read by
build_player_site. Opponents come from the series matchup store's rosters.

Run:  .\\venv\\Scripts\\python.exe build_opponent_about.py --opp bangladesh
"""
import argparse
import json
import os
import warnings

warnings.filterwarnings("ignore")

from cricket_core.config import project_path
from report import build_profile
from batter_profile import build_batter_profile

HERE = os.path.dirname(os.path.abspath(__file__))
_AREA = {"off": "through the off side", "leg": "through the leg side", "straight": "down the ground"}


def distil_bowler(P, type_label):
    facts = []
    if P.get("is_pace") and P.get("avg_spd"):
        facts.append(f"{type_label} — averages {P['avg_spd']:.0f} km/h, tops {P['max_spd_99']:.0f}.")
    else:
        facts.append(f"{type_label}.")
    bt = P.get("ball_types") or {}
    st = bt.get("stock")
    if st and st.get("phrase"):
        facts.append(f"Stock ball: {st['phrase']} ({st['pct']:.0f}% of what they bowl).")
    dlen, dline = P.get("danger_length"), P.get("danger_line")
    if dlen and dlen.get("length"):
        where = f", around {dline['line'].lower()}" if dline and dline.get("line") else ""
        facts.append(f"Takes most of their wickets {dlen['length'].lower()}{where}.")
    if P.get("is_pace") and st and (st.get("swing_mag") or 0) >= 0.6:
        facts.append("Gets the ball to swing — watch the ball in the air.")
    return {"type": type_label, "is_pace": bool(P.get("is_pace")),
            "facts": facts, "order": int(P.get("n_balls") or 0)}


def distil_batter(P, hand):
    facts = []
    sg = P.get("shot_groups") or []
    dp = P.get("dir_pct") or {}
    if sg:
        top = sg[0]["name"].lower()
        if dp:
            area = _AREA[max(dp, key=dp.get)]
            facts.append(f"Scores mainly {area}; go-to shot is the {top}.")
        else:
            facts.append(f"Main scoring shot is the {top}.")
    w = P.get("weakness")
    if w == "spin":
        facts.append("Weaker against spin than pace.")
    elif w == "pace":
        facts.append("Handles spin well — pace is the more likely way through.")
    dis = P.get("dismissals")
    n = P.get("n_dismissals") or 0
    if dis and n:
        mode, c = dis.most_common(1)[0]
        facts.append(f"Most often out {mode.lower()} ({c / n * 100:.0f}% of dismissals).")
    ph = P.get("phase") or {}
    e, s = ph.get("early"), ph.get("set")
    if e and s and e.get("dismissal_per100") and s.get("dismissal_per100"):
        if e["dismissal_per100"] >= 1.4 * s["dismissal_per100"]:
            facts.append("Vulnerable early — worth attacking in their first 30 balls.")

    # type-scoped facts (a pace bowler's pack shows only pace; a spinner's only spin)
    vs = P.get("vs") or {}

    def type_facts(t):
        v = vs.get(t)
        if not v or not v.get("avg"):
            return []
        line = f"Vs {t}: averages {v['avg']:.0f} at a strike rate of {v['sr']:.0f}"
        if v.get("false_pct"):
            line += f", false-shot {v['false_pct']:.0f}%"
        out = [line + "."]
        sg = P.get("shot_groups") or []
        if sg:
            out.append(f"Main scoring shot is the {sg[0]['name'].lower()}.")
        return out

    return {"hand": hand, "facts": facts, "order": int(P.get("runs") or 0),
            "facts_pace": type_facts("pace"), "facts_spin": type_facts("spin")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    args = ap.parse_args()

    p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{args.opp}.json")
    store = json.load(open(p, encoding="utf-8"))
    bowlers = {c["bowler_id"]: (c["bowler"], c.get("bowler_type", "")) for c in store["we_bat"]}
    batters = {c["batter_id"]: (c["batter"], c.get("bat_hand", "")) for c in store["they_bat"]}

    out = {"opp": args.opp, "bowlers": {}, "batters": {}}
    for bid, (nm, ty) in bowlers.items():
        try:
            P = build_profile(bid, hand="All")
            out["bowlers"][bid] = {"name": nm, **distil_bowler(P, ty or "Bowler")}
            print(f"  bowler {nm}: {len(out['bowlers'][bid]['facts'])} facts")
        except Exception as e:
            print(f"  ! bowler {nm}: {type(e).__name__}: {e}")
    for bid, (nm, hand) in batters.items():
        try:
            P = build_batter_profile(bid)
            out["batters"][bid] = {"name": nm, **distil_batter(P, hand)}
            print(f"  batter {nm}: {len(out['batters'][bid]['facts'])} facts")
        except Exception as e:
            print(f"  ! batter {nm}: {type(e).__name__}: {e}")

    dst = os.path.join(HERE, "data", f"opponent_about_{args.opp}.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {dst}: {len(out['bowlers'])} bowlers, {len(out['batters'])} batters")


if __name__ == "__main__":
    main()
