"""
build_h2h.py — real head-to-head footage between our squad and the opposition, for VISION
(SCOUTING_REBUILD.md: head-to-head is evidence, not statistics — these balls power playlists).

Format fallback (Tom, 2026-07-17): a Test series pack prefers Test footage, but if there's none
of a pairing in Tests we fall back to ODI, then T20I, then domestic T20 (BBL, …) — whatever
exists — and LABEL the format so a player opening the clip knows it's e.g. "T20I", not an error.
"Footage exists" = the delivery has a resolvable clip stem. Newest `MAX_BALLS` of the chosen
format per pairing.

Run:  .\\venv\\Scripts\\python.exe build_h2h.py --opp bangladesh
Out:  data/h2h_{opp}.json   {"our_batting": [...], "our_bowling": [...]}
"""
import argparse
import json
import os
from collections import defaultdict

from config import DATA_SCHEMA
from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.config import project_path
from cricket_core.video import clip_stem
from cricket_core.formats import match_format

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_BALLS = 20                                          # house rule: 10-20 most recent per pairing

# format preference: a Test pack wants Test footage first, then the closest available.
_FMT_PRIORITY = ["Test", "ODI", "T20I", "T20", "List A", "The Hundred", "FC", "T10"]
_FMT_LABEL = {"Test": "Test", "ODI": "ODI", "T20I": "T20I", "T20": "domestic T20",
              "List A": "List A", "The Hundred": "The Hundred", "FC": "first-class", "T10": "T10"}
HOW = {"4": "Bowled", "5": "Caught", "6": "LBW", "7": "Hit Wicket", "8": "Stumped", "9": "Run Out"}


def _pull(conn, cur, striker_ids, bowler_ids):
    """All balls (any format) striker∈A vs bowler∈B, newest first, with the fields to build a
    clip stem and classify the format."""
    sl = ",".join(f"'{i}'" for i in striker_ids)
    bl = ",".join(f"'{i}'" for i in bowler_ids)
    q = f"""SELECT D.striker_id, D.bowler_id, D.delivery_id, D.match_id,
        CONVERT(varchar(10), M.match_date, 120) d,
        D.bat_score, D.striker_dismissed, D.how_out_id, D.legal_ball,
        D.video_file_name, M.match_length_id, S.name season, SR.gender_id, SR.name series_name
    FROM [{DATA_SCHEMA}].[Deliveries] D
    JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id
    LEFT JOIN [{DATA_SCHEMA}].[Seasons] S ON M.season_id=S.season_id
    LEFT JOIN [{DATA_SCHEMA}].[Series] SR ON M.series_id=SR.series_id
    WHERE D.striker_id IN ({sl}) AND D.bowler_id IN ({bl})
    ORDER BY M.match_date DESC, D.match_innings DESC,
             TRY_CONVERT(int, D.[over]) DESC, TRY_CONVERT(int, D.ball_in_over) DESC"""
    return run_query(q, conn, cur)


def _fmt(r):
    try:
        return match_format(r.get("series_name"), r.get("match_length_id"))
    except Exception:
        return None


def _rowify(raw, cap=MAX_BALLS):
    """Per (striker, bowler): group by format, keep only balls with a clip stem, pick the highest
    -priority format present, and take the newest `cap` of it. Returns {pair: (fmt, [balls])}."""
    by_pair = defaultdict(lambda: defaultdict(list))    # (s,b) -> fmt -> [ball]
    for r in raw:
        stem = clip_stem(r["season"], r["gender_id"], r["match_length_id"],
                         r.get("match_id"), r["video_file_name"])
        if not stem:
            continue                                    # no footage -> not useful for vision
        fmt = _fmt(r)
        if fmt not in _FMT_PRIORITY:
            continue
        out = r["striker_dismissed"] in ("1", "True", "true")
        by_pair[(r["striker_id"], r["bowler_id"])][fmt].append({
            "delivery_id": r["delivery_id"], "date": r["d"],
            "runs": int(float(r["bat_score"] or 0)),
            "wicket": HOW.get(r["how_out_id"]) if out else None, "clip_stem": stem})
    chosen = {}
    for pair, byfmt in by_pair.items():
        for fmt in _FMT_PRIORITY:
            if byfmt.get(fmt):
                chosen[pair] = (fmt, byfmt[fmt][:cap])   # rows already newest-first
                break
    return chosen


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
    a = _rowify(_pull(conn, cur, our_bat, opp_bowl))     # our batters facing their bowlers
    b = _rowify(_pull(conn, cur, opp_bat, our_bowl))     # their batters facing our bowlers
    conn.close()

    def pack(chosen):
        rows = []
        for (s, bo), (fmt, v) in chosen.items():
            rows.append({"striker_id": s, "bowler_id": bo, "format": fmt,
                         "format_label": _FMT_LABEL.get(fmt, fmt), "balls": len(v),
                         "clips": len(v), "deliveries": v})
        return rows

    out = {"opp": args.opp, "cap": MAX_BALLS,
           "our_batting": pack(a), "our_bowling": pack(b)}
    p = os.path.join(HERE, "data", f"h2h_{args.opp}.json")
    json.dump(out, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    def summ(rows):
        from collections import Counter
        return dict(Counter(r["format"] for r in rows))
    print(f"our batters × their bowlers: {len(out['our_batting'])} pairings {summ(out['our_batting'])}")
    print(f"their batters × our bowlers: {len(out['our_bowling'])} pairings {summ(out['our_bowling'])}")
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
