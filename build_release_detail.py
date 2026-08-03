"""build_release_detail.py — where on the crease a bowler releases from, and what it returns, split
by BATTER HAND and OVER/ROUND. Built for the bowler who asks for it (Cummins): `players.json` gets
`"release_detail": true` and the pack renders the table.

Why the split matters: `release_line_unmirrored` is ABSOLUTE (mm from middle stump), so over- and
round-the-wicket sit on opposite signs and pooling them is meaningless. Bands are the house
close / medium / wide (<45cm, 45-75cm, >75cm from the stumps).

Release tracking is modern-era, so this is a recent-career read rather than a full-career one — the
seasons covered are recorded in the output and shown on the page.

Run:  .\\venv\\Scripts\\python.exe build_release_detail.py --opp bangladesh
Out:  data/release_detail.json
"""
import argparse
import datetime
import json
import os

from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.video import clip_stem
from cricket_core.config import international_series_sql
from config import DATA_SCHEMA

HERE = os.path.dirname(os.path.abspath(__file__))
# false-shot shot_quality ids (same set the batting side uses)
_FALSE_SQ = "('2','3','4','6','10','14','17','21','25','26','28')"
# Average and strike rate are runs-per-WICKET and balls-per-wicket, so they exist the moment there
# is a wicket — don't withhold a number that's plainly computable, because a "—" next to "5 wkts"
# reads as a broken calculation. Balls and Wkts sit in the same row, so the reader can judge how
# much weight to give it; cells under LOW_WKTS are just softened, not hidden.
_MIN_WKTS = 1
_LOW_WKTS = 5           # below this the figure is shown but visually de-emphasised
_MIN_BALLS_ECON = 30
_YEARS = 3              # recent form only — the full career sample is too big to act on
_CLIPS_PER_CELL = 5
_ABS = "ABS(TRY_CAST(D.release_line_unmirrored AS FLOAT))"


def _cells(conn, cur, bowler_id, since):
    S = DATA_SCHEMA
    intl = (f"M.series_id IN (SELECT series_id FROM [{S}].[Series] "
            f"WHERE name IN {international_series_sql('Test')})")
    ang = "CASE WHEN D.over_the_wicket='1' THEN 'over' ELSE 'round' END"
    hand = "CASE WHEN D.striker_hand_id='2' THEN 'LHB' ELSE 'RHB' END"
    band = (f"CASE WHEN {_ABS}<450 THEN 'close' WHEN {_ABS}<750 THEN 'medium' ELSE 'wide' END")
    scope = (f"{intl} AND D.legal_ball = '1' AND D.bowler_id = '{bowler_id}' "
             f"AND D.release_line_unmirrored IS NOT NULL AND {_ABS} <= 1500 "
             f"AND M.match_date >= '{since}'")
    rows = run_query(f"""
        SELECT {ang} AS angle, {hand} AS hand, {band} AS band,
               COUNT(*) AS balls,
               SUM(CASE WHEN D.bowler_dismissal='1' THEN 1 ELSE 0 END) AS wkts,
               SUM(TRY_CAST(D.bat_score AS FLOAT) + ISNULL(TRY_CAST(D.wide_runs AS FLOAT),0)
                   + ISNULL(TRY_CAST(D.noball_runs AS FLOAT),0)) AS runs,
               SUM(CASE WHEN D.shot_quality_id IN {_FALSE_SQ} THEN 1 ELSE 0 END) AS fls,
               SUM(CASE WHEN D.shot_quality_id IS NOT NULL AND D.shot_quality_id <> '' THEN 1 ELSE 0 END) AS sq,
               MIN(M.match_date) AS first_m, MAX(M.match_date) AS last_m
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id = M.match_id
        WHERE {scope}
        GROUP BY {ang}, {hand}, {band}""", conn, cur)

    # example balls per cell — wickets first, then false shots, then most recent, so the 5 shown
    # are the ones worth watching rather than an arbitrary five
    vids = run_query(f"""
        SELECT {ang} AS angle, {hand} AS hand, {band} AS band,
               D.delivery_id, D.video_file_name, D.match_id, M.match_length_id,
               S2.name AS season, SR.gender_id,
               D.bowler_dismissal, D.shot_quality_id, M.match_date
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id = M.match_id
        LEFT JOIN [{S}].[Seasons] S2 ON M.season_id = S2.season_id
        LEFT JOIN [{S}].[Series] SR ON M.series_id = SR.series_id
        WHERE {scope} AND D.video_file_name IS NOT NULL
        ORDER BY D.bowler_dismissal DESC,
                 CASE WHEN D.shot_quality_id IN {_FALSE_SQ} THEN 1 ELSE 0 END DESC,
                 M.match_date DESC""", conn, cur)
    by_cell = {}
    for r in vids:
        k = (r["angle"], r["hand"], r["band"])
        bucket = by_cell.setdefault(k, [])
        if len(bucket) >= _CLIPS_PER_CELL:
            continue
        cs = clip_stem(r.get("season"), r.get("gender_id"), r.get("match_length_id"),
                       r.get("match_id"), r.get("video_file_name"))
        if cs:
            bucket.append({"delivery_id": r["delivery_id"], "clip_stem": cs})

    out, span = [], []
    for r in rows:
        b = int(r["balls"] or 0)
        w = int(r["wkts"] or 0)
        runs = float(r["runs"] or 0)
        sq = int(r["sq"] or 0)
        for d in (r.get("first_m"), r.get("last_m")):
            if d:
                span.append(str(d)[:4])
        out.append({
            "angle": r["angle"], "hand": r["hand"], "band": r["band"],
            "balls": b, "wkts": w, "runs": round(runs),
            "avg": round(runs / w, 1) if w >= _MIN_WKTS else None,
            "sr": round(b / w) if w >= _MIN_WKTS else None,
            "econ": round(runs / (b / 6), 2) if b >= _MIN_BALLS_ECON else None,
            "low": w < _LOW_WKTS,          # shown, but softened — few wickets behind it
            "false_pct": round(100 * int(r["fls"] or 0) / sq, 1) if sq >= 60 else None,
            "clips": by_cell.get((r["angle"], r["hand"], r["band"]), []),
        })
    out.sort(key=lambda c: (c["angle"], c["hand"], ("close", "medium", "wide").index(c["band"])))
    return out, (f"{min(span)}–{max(span)}" if span else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    args = ap.parse_args()
    players = json.load(open(os.path.join(HERE, "players.json"), encoding="utf-8"))
    want = {pid: rec for pid, rec in players.items() if rec.get("release_detail")}
    if not want:
        print("no players flagged `release_detail` in players.json — nothing to do")
        return
    since = (datetime.date.today() - datetime.timedelta(days=365 * _YEARS)).isoformat()
    conn, cur = set_conn_cursor()
    out = {}
    for pid, rec in want.items():
        cells, span = _cells(conn, cur, pid, since)
        out[pid] = {"name": rec.get("name", pid), "seasons": span, "cells": cells,
                    "low_wkts": _LOW_WKTS, "years": _YEARS, "since": since}
        shown = sum(1 for c in cells if c["avg"] is not None)
        print(f"  {rec.get('name', pid)}: {len(cells)} cells ({shown} with a rateable sample), "
              f"{span} (since {since})")
        for c in cells:
            print(f"     {c['angle']:5} {c['hand']:3} {c['band']:6} balls={c['balls']:5} "
                  f"wkts={c['wkts']:3} avg={c['avg']} SR={c['sr']} clips={len(c['clips'])}")
    conn.close()
    dst = os.path.join(HERE, "data", "release_detail.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {dst}: {len(out)} bowler(s)")


if __name__ == "__main__":
    main()
