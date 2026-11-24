"""build_swing_split.py — which way an opposition pace bowler swings the new ball, to each hand.

    venv/bin/python build_swing_split.py --slug england-t20i-home-2026

Tom, 18-11-2026: the notes should say whether a bowler can swing it both ways (Sonny Baker can).
His three calls (atq, same day):

- ALWAYS SHOW THE SPLIT. No bar for "both ways": every pace bowler with enough balls gets their in
  and away shares to each hand, and the reader judges.
- PACKS AND SCOUTING. A fact on the bowler's row in the hub packs (the line for our batter's hand)
  and on Scouting's Their bowlers cards. Not the web reports.
- ALL CRICKET. Every tracked ball in any format, so the same figure shows on a bowler's ODI and
  T20I cards, and the line says "all formats".

Two things make the figure mean what it says, both Tom's correction to a first count over whole
innings (Baker read 13% away to right-handers there, 28% here):

- NEW BALL ONLY. A bowler looks to swing it both ways while the ball will swing. Overs 1-20 of a
  first-class innings, 1-10 of a one-day innings, 1-6 of a T20 innings (NEW_BALL).
- OF THE BALLS THAT SWUNG. The share is of deliveries the coders labelled in-swing or out-swing
  (`movement_in_air_group_swing_id`, lookup 2827: 100 in, 200 none, 300 out, batter-relative).
  "No swing" balls are out of the denominator.

Only tracked balls carry a label, so coverage decides who gets a line: under MIN_SWUNG swinging new
balls to a hand and that hand has none (Henry Crocombe 17, Eddie Jack 0 on 18-11-2026).

Writes `data/swing_split_<opp>.json`, a sidecar, so nothing in the about file or the bowler plans
is rewritten. build_hub_packs.py and build_coach_site.py read it. Reads the warehouse.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MIN_SWUNG = 40
# the last over of the new ball, by the warehouse's match_length_id: 2-6 are multi-day, 7 is T20,
# anything else is read as a one-day innings
NEW_BALL = {"red": 20, "t20": 6, "one_day": 10}
LABEL = "New-ball swing"

_AGE = (f"CASE WHEN M.match_length_id IN ('2','3','4','5','6') THEN {NEW_BALL['red']} "
        f"WHEN M.match_length_id = '7' THEN {NEW_BALL['t20']} ELSE {NEW_BALL['one_day']} END")


def counts(ids):
    """{bowler: {"RHB"|"LHB": {"in", "out", "none"}}} over every new-ball delivery with a label."""
    from cricket_core.warehouse import set_conn_cursor, run_query
    from config import DATA_SCHEMA as S
    out = {}
    if not ids:
        return out
    idl = ",".join(f"'{p}'" for p in ids)
    conn, cur = set_conn_cursor()
    rows = run_query(f"""
        SELECT D.bowler_id b, D.striker_hand_id h, D.movement_in_air_group_swing_id g, COUNT(*) n
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id = M.match_id
        WHERE D.bowler_id IN ({idl}) AND D.legal_ball = '1' AND D.bowler_style_id IN ('1','2','3')
          AND D.movement_in_air_group_swing_id IS NOT NULL
          AND TRY_CONVERT(int, D.[over]) <= {_AGE}
        GROUP BY D.bowler_id, D.striker_hand_id, D.movement_in_air_group_swing_id""", conn, cur)
    conn.close()
    word = {"100": "in", "200": "none", "300": "out"}
    hand = {"1": "RHB", "2": "LHB"}
    for r in rows:
        k, h = word.get(str(r["g"]).split(".")[0]), hand.get(str(r["h"]).split(".")[0])
        if k and h:
            c = out.setdefault(str(r["b"]), {}).setdefault(h, {"in": 0, "out": 0, "none": 0})
            c[k] += int(r["n"])
    return out


def text(c):
    """"72% in, 28% away (147 balls that swung, all formats)", or "" under the floor."""
    swung = (c or {}).get("in", 0) + (c or {}).get("out", 0)
    if swung < MIN_SWUNG:
        return ""
    inn = int(100.0 * c["in"] / swung + 0.5)
    return f"{inn}% in, {100 - inn}% away ({swung} balls that swung, all formats)"


def load(opp):
    """{bowler id: {"RHB": text, "LHB": text}} for the readers, {} without the file."""
    p = os.path.join(HERE, "data", f"swing_split_{opp}.json")
    if not os.path.exists(p):
        return {}
    b = (json.load(open(p, encoding="utf-8")) or {}).get("bowlers") or {}
    return {bid: {h: (v.get(h) or {}).get("text") or "" for h in ("RHB", "LHB")} for bid, v in b.items()}


def build(slug):
    from build_coach_site import _opp_key, _about
    bowlers, _batters = _about(slug)
    got = counts([str(b) for b in bowlers])
    out = {"slug": slug, "built": datetime.date.today().isoformat(), "min_swung": MIN_SWUNG,
           "new_ball": NEW_BALL, "bowlers": {}}
    for bid, meta in bowlers.items():
        c = got.get(str(bid))
        if not c or meta.get("is_pace") is False:
            # a pace bowler never tracked, or a spinner. A spinner's arm ball is coded as swing
            # too: Ajaz Patel read "100% in" on 106 balls in the first New Zealand build.
            continue
        row = {h: dict(c.get(h) or {"in": 0, "out": 0, "none": 0}) for h in ("RHB", "LHB")}
        for h in row:
            row[h]["text"] = text(row[h])
        out["bowlers"][str(bid)] = row
        print(f"  {meta.get('name') or bid:20} RHB {row['RHB']['text'] or 'too few'} · "
              f"LHB {row['LHB']['text'] or 'too few'}", flush=True)
    path = os.path.join(HERE, "data", f"swing_split_{_opp_key(slug)}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {os.path.relpath(path, HERE)} ({len(out['bowlers'])} bowlers)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="the squad slug, as in series.json")
    build(ap.parse_args().slug)


if __name__ == "__main__":
    main()
