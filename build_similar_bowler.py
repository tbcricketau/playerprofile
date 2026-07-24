"""build_similar_bowler.py — for each of OUR bowlers that names a `similar_bowler` in players.json,
build a playlist of how that reference bowler went against the opposition batters (a proxy for the
matchup when our bowler's own footage vs these batters is thin — e.g. Sajid Khan for Nathan Lyon).

Writes data/similar_bowler_{opp}.json: {our_bowler_pid: {name, clips:[{delivery_id, clip_stem}, …]}}.
Illustrative-first (wickets, then false shots, then recency), a generous pool; build_player_site
resolves against storage and caps the shown playlist. Opposition batters come from opponent_about.

Run:  .\\venv\\Scripts\\python.exe build_similar_bowler.py --opp bangladesh
"""
import argparse
import json
import os

from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.video import clip_stem
from config import DATA_SCHEMA

HERE = os.path.dirname(os.path.abspath(__file__))
# false-shot shot_quality ids (mirror build_opponent_about._FALSE_SQ)
_FALSE_SQ = "('2','3','4','6','10','14','17','21','25','26','28')"
POOL = 40   # generous stem pool; the pack resolves + caps the shown playlist (~20)


def _clips_vs(conn, cur, bowler_id, batter_ids):
    inlist = "('" + "','".join(batter_ids) + "')"
    rows = run_query(f"""
        SELECT D.delivery_id, D.video_file_name, D.match_id, M.match_length_id,
               S.name season, SR.gender_id
        FROM [{DATA_SCHEMA}].[Deliveries] D
        JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id = M.match_id
        LEFT JOIN [{DATA_SCHEMA}].[Seasons] S ON M.season_id = S.season_id
        LEFT JOIN [{DATA_SCHEMA}].[Series] SR ON M.series_id = SR.series_id
        WHERE D.bowler_id = '{bowler_id}' AND D.striker_id IN {inlist} AND D.legal_ball = '1'
          AND D.video_file_name IS NOT NULL
        ORDER BY D.bowler_dismissal DESC,
                 CASE WHEN D.shot_quality_id IN {_FALSE_SQ} THEN 1 ELSE 0 END DESC,
                 M.match_date DESC""", conn, cur)
    out = []
    for r in rows:
        cs = clip_stem(r.get("season"), r.get("gender_id"), r.get("match_length_id"),
                       r.get("match_id"), r.get("video_file_name"))
        if cs:
            out.append({"delivery_id": r["delivery_id"], "clip_stem": cs})
        if len(out) >= POOL:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    args = ap.parse_args()
    players = json.load(open(os.path.join(HERE, "players.json"), encoding="utf-8"))
    about = json.load(open(os.path.join(HERE, "data", f"opponent_about_{args.opp}.json"), encoding="utf-8"))
    batter_ids = list(about.get("batters", {}).keys())

    conn, cur = set_conn_cursor()
    out = {}
    for pid, rec in players.items():
        sb = rec.get("similar_bowler")
        if not sb:
            continue
        clips = _clips_vs(conn, cur, str(sb["id"]), batter_ids)
        out[pid] = {"name": sb["name"], "clips": clips}
        print(f"  {rec.get('name', pid)} <- {sb['name']}: {len(clips)} clip stems")
    conn.close()

    dst = os.path.join(HERE, "data", f"similar_bowler_{args.opp}.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {dst}: {len(out)} bowlers")


if __name__ == "__main__":
    main()
