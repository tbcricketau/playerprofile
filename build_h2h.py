"""
build_h2h.py — real head-to-head meetings between our squad and the opposition, for VISION
(SCOUTING_REBUILD.md: head-to-head is evidence, not statistics — these balls power playlists
and one-line context; the numbers in reports come from the simulation).

For every (our player × opposition player) pairing in the matchup store, pulls their actual
Test deliveries (same format only), most recent first, capped at MAX_BALLS, with clip stems
for the video player. Consumed by the player packs ("Your vision vs Bangladesh"), the series
match-up matrix page, and the opposition reports' "vs our squad" strips.

Run:  .\\venv\\Scripts\\python.exe build_h2h.py --opp bangladesh
Out:  data/h2h_{opp}.json   {"our_batting": [...], "our_bowling": [...]}  (one row per ball)
"""
import argparse
import json
import os

from config import DATA_SCHEMA
from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.config import international_series_sql, project_path
from cricket_core.video import clip_stem

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_BALLS = 20          # house rule: 10-20 most recent balls per pairing

_TEST = (f"M.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
         f"WHERE name IN {international_series_sql('Test')})")


def _pull(conn, cur, striker_ids, bowler_ids):
    """All Test balls striker∈A vs bowler∈B, newest first, with the caption + clip fields."""
    sl = ",".join(f"'{i}'" for i in striker_ids)
    bl = ",".join(f"'{i}'" for i in bowler_ids)
    q = f"""SELECT D.striker_id, D.bowler_id, D.delivery_id, D.match_id,
        CONVERT(varchar(10), M.match_date, 120) d,
        D.bat_score, D.striker_dismissed, D.how_out_id, D.legal_ball,
        D.video_file_name, M.match_length_id, S.name season, SR.gender_id
    FROM [{DATA_SCHEMA}].[Deliveries] D
    JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id
    LEFT JOIN [{DATA_SCHEMA}].[Seasons] S ON M.season_id=S.season_id
    LEFT JOIN [{DATA_SCHEMA}].[Series] SR ON M.series_id=SR.series_id
    WHERE {_TEST} AND D.striker_id IN ({sl}) AND D.bowler_id IN ({bl})
    ORDER BY M.match_date DESC, D.match_innings DESC,
             TRY_CONVERT(int, D.[over]) DESC, TRY_CONVERT(int, D.ball_in_over) DESC"""
    return run_query(q, conn, cur)


HOW = {"4": "Bowled", "5": "Caught", "6": "LBW", "7": "Hit Wicket", "8": "Stumped", "9": "Run Out"}


def _rowify(raw, cap=MAX_BALLS):
    """Group by pairing, keep the newest `cap` balls each, attach clip stems."""
    from collections import defaultdict
    pairs = defaultdict(list)
    for r in raw:
        key = (r["striker_id"], r["bowler_id"])
        if len(pairs[key]) >= cap:
            continue
        out = r["striker_dismissed"] in ("1", "True", "true")
        pairs[key].append({
            "delivery_id": r["delivery_id"], "date": r["d"],
            "runs": int(float(r["bat_score"] or 0)),
            "wicket": HOW.get(r["how_out_id"]) if out else None,
            "clip_stem": clip_stem(r["season"], r["gender_id"], r["match_length_id"],
                                   r.get("match_id"), r["video_file_name"]),
        })
    return pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--opp", default="bangladesh")
    args = ap.parse_args()

    store_p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{args.opp}.json")
    store = json.load(open(store_p, encoding="utf-8"))
    our_bat = sorted({c["batter_id"] for c in store["we_bat"]})
    opp_bowl = sorted({c["bowler_id"] for c in store["we_bat"]})
    opp_bat = sorted({c["batter_id"] for c in store["they_bat"]})
    our_bowl = sorted({c["bowler_id"] for c in store["they_bat"]})

    conn, cur = set_conn_cursor()
    a = _pull(conn, cur, our_bat, opp_bowl)      # our batters facing their bowlers
    b = _pull(conn, cur, opp_bat, our_bowl)      # their batters facing our bowlers
    conn.close()

    def pack(pairs):
        return [{"striker_id": k[0], "bowler_id": k[1], "balls": len(v),
                 "runs": sum(x["runs"] for x in v),
                 "wickets": sum(1 for x in v if x["wicket"]),
                 "clips": sum(1 for x in v if x["clip_stem"]),
                 "deliveries": v} for k, v in pairs.items()]

    out = {"opp": args.opp, "cap": MAX_BALLS,
           "our_batting": pack(_rowify(a)), "our_bowling": pack(_rowify(b))}
    p = os.path.join(HERE, "data", f"h2h_{args.opp}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    n_a, n_b = len(out["our_batting"]), len(out["our_bowling"])
    print(f"our batters × their bowlers: {n_a} pairings with meetings; "
          f"their batters × our bowlers: {n_b}")
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
