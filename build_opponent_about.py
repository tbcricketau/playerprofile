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

from cricket_core.config import project_path, international_series_sql
from cricket_core.warehouse import set_conn_cursor, run_query
from config import DATA_SCHEMA
from report import build_profile
from batter_profile import build_batter_profile

HERE = os.path.dirname(os.path.abspath(__file__))
_AREA = {"off": "through the off side", "leg": "through the leg side", "straight": "down the ground"}

# Below this many Test balls in the relevant role, fall back to the player's ALL-FORMAT record for
# the format-ROBUST facts only (CROSSFORMAT_TRANSLATION.md: pace/line/length/shot translate; average,
# strike rate, economy, wicket-rate do NOT — so the fallback never quotes those).
TEST_FLOOR = 300
_TEST = (f"M.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
         f"WHERE name IN {international_series_sql('Test')})")
# false-shot ids (lookup 2811), matching the batting profile's convention
_FALSE_SQ = {"2", "3", "4", "6", "10", "14", "17", "21", "25", "26", "28"}


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


def _q(conn, cur, sql):
    return run_query(sql, conn, cur)


def _test_balls(conn, cur, bid, role):
    """Legal Test balls the player has bowled ('bowl') or faced ('bat')."""
    col = "bowler_id" if role == "bowl" else "striker_id"
    r = _q(conn, cur, f"SELECT COUNT(*) n FROM [{DATA_SCHEMA}].[Deliveries] D "
                      f"JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id "
                      f"WHERE D.{col}='{bid}' AND D.legal_ball=1 AND {_TEST}")
    return int(float(r[0]["n"] or 0)) if r else 0


def _mode(rows, key):
    from collections import Counter
    c = Counter(r[key] for r in rows if r.get(key) not in (None, "None", ""))
    return c.most_common(1)[0][0] if c else None


def allfmt_bowler_facts(conn, cur, bid, type_label, LEN, LIN):
    """Format-robust bowler facts from ALL formats (type, pace, stock line/length) — labelled.
    No economy/average/wicket-rate (those don't translate across formats)."""
    rows = _q(conn, cur, f"""SELECT TRY_CONVERT(float, D.ball_speed) spd,
        D.pitch_length_group_pace_1_id len, D.pitch_line_group_pace_id lin,
        D.bowler_pace_spin_id ps
        FROM [{DATA_SCHEMA}].[Deliveries] D WHERE D.bowler_id='{bid}' AND D.legal_ball=1""")
    if len(rows) < 150:
        return None
    is_pace = _mode(rows, "ps") == "1"
    spds = [float(r["spd"]) for r in rows if r.get("spd") not in (None, "None", "")]
    facts = []
    if is_pace and len(spds) >= 60:
        facts.append(f"{type_label} — averages {sum(spds)/len(spds):.0f} km/h.")
    else:
        facts.append(f"{type_label}.")
    ln, li = LEN.get(_mode(rows, "len")), LIN.get(_mode(rows, "lin"))
    if ln and li:
        facts.append(f"Usually {ln.lower()} in the {li.lower() if 'line' not in li.lower() else li.lower()}.")
    facts.append("Limited Test record — the above is from all formats they've played.")
    return {"type": type_label, "is_pace": is_pace, "facts": facts, "order": len(rows), "source": "all-formats"}


def allfmt_batter_facts(conn, cur, bid, hand, STK, SQ):
    """Format-robust batter facts from ALL formats (main shot, scoring side, pace/spin false-shot)
    — labelled. No average / strike rate (they don't translate)."""
    rows = _q(conn, cur, f"""SELECT D.stroke_id, D.shot_quality_id sq, D.bowler_pace_spin_id ps,
        TRY_CONVERT(int, D.bat_score) runs, D.hit_to_angle ang
        FROM [{DATA_SCHEMA}].[Deliveries] D WHERE D.striker_id='{bid}' AND D.legal_ball=1""")
    if len(rows) < 200:
        return None
    facts = []
    # main scoring shot (by runs)
    from collections import Counter
    sc = Counter()
    for r in rows:
        s = STK.get(r["stroke_id"])
        if s and s not in ("None", "No Shot", "Leave"):
            sc[s] += int(r["runs"] or 0)
    if sc:
        facts.append(f"Main scoring shot is the {sc.most_common(1)[0][0].lower()}.")
    # false-shot vs pace vs spin
    def false_rate(psval):
        sub = [r for r in rows if r["ps"] == psval and r.get("sq") not in (None, "None", "")]
        if len(sub) < 80:
            return None
        return 100.0 * sum(1 for r in sub if str(r["sq"]) in _FALSE_SQ) / len(sub)
    fp, fs = false_rate("1"), false_rate("2")
    if fp is not None and fs is not None:
        weaker = "spin" if fs > fp + 1.5 else ("pace" if fp > fs + 1.5 else None)
        if weaker:
            facts.append(f"Plays {'pace' if weaker=='spin' else 'spin'} more securely — "
                         f"more false shots against {weaker}.")
    facts.append("Limited Test record — the above is from all formats they've played.")
    return {"hand": hand, "facts": facts, "order": len(rows), "source": "all-formats",
            "facts_pace": facts, "facts_spin": facts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    args = ap.parse_args()

    p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{args.opp}.json")
    store = json.load(open(p, encoding="utf-8"))
    bowlers = {c["bowler_id"]: (c["bowler"], c.get("bowler_type", "")) for c in store["we_bat"]}
    batters = {c["batter_id"]: (c["batter"], c.get("bat_hand", "")) for c in store["they_bat"]}

    conn, cur = set_conn_cursor()
    LEN = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2819")}
    LIN = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2823")}
    STK = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=24")}
    SQ = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2811")}

    out = {"opp": args.opp, "bowlers": {}, "batters": {}}
    for bid, (nm, ty) in bowlers.items():
        try:
            if _test_balls(conn, cur, bid, "bowl") >= TEST_FLOOR:
                out["bowlers"][bid] = {"name": nm, **distil_bowler(build_profile(bid, hand="All"), ty or "Bowler")}
                tag = ""
            else:                                        # thin Test record -> all-format fallback
                fb = allfmt_bowler_facts(conn, cur, bid, ty or "Bowler", LEN, LIN)
                if not fb:
                    continue
                out["bowlers"][bid] = {"name": nm, **fb}
                tag = " [all-formats fallback]"
            print(f"  bowler {nm}: {len(out['bowlers'][bid]['facts'])} facts{tag}")
        except Exception as e:
            print(f"  ! bowler {nm}: {type(e).__name__}: {e}")
    for bid, (nm, hand) in batters.items():
        try:
            if _test_balls(conn, cur, bid, "bat") >= TEST_FLOOR:
                out["batters"][bid] = {"name": nm, **distil_batter(build_batter_profile(bid), hand)}
                tag = ""
            else:
                fb = allfmt_batter_facts(conn, cur, bid, hand, STK, SQ)
                if not fb:
                    continue
                out["batters"][bid] = {"name": nm, **fb}
                tag = " [all-formats fallback]"
            print(f"  batter {nm}: {len(out['batters'][bid]['facts'])} facts{tag}")
        except Exception as e:
            print(f"  ! batter {nm}: {type(e).__name__}: {e}")
    conn.close()

    dst = os.path.join(HERE, "data", f"opponent_about_{args.opp}.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {dst}: {len(out['bowlers'])} bowlers, {len(out['batters'])} batters")


if __name__ == "__main__":
    main()
