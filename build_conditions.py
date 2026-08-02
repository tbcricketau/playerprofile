"""build_conditions.py — how the opposition's batters have gone in SEAM-AND-BOUNCE conditions:
Tests played in New Zealand, South Africa and England, the closest available benchmark to what
they'll face in Australia. Asked for by Hazlewood ("anywhere outside spin conditions — is there a
trend?").

Each batter's record in those countries is set against their overall Test record, because the
comparison is the point: the away number alone says little, the gap says a lot. Batters who have
never toured there are named as such rather than dropped, since an unknown is a finding too.

Run:  .\\venv\\Scripts\\python.exe build_conditions.py --opp bangladesh
Out:  data/conditions_{opp}.json  +  reports/conditions_{opp}.html
"""
import argparse
import html
import json
import os

from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.config import international_series_sql
from config import DATA_SCHEMA
from site_render import page as _page

HERE = os.path.dirname(os.path.abspath(__file__))
REF_CONDITIONS = ("New Zealand", "South Africa", "England")   # the seam-and-bounce benchmark
_FALSE_SQ = "('2','3','4','6','10','14','17','21','25','26','28')"
_MIN_BALLS = 150        # below this the away average is too unstable to read as a trend

CSS = """<style>
 .cwrap{overflow-x:auto;border:1px solid #e5e7eb;border-radius:10px;background:#fff;margin:10px 0 20px}
 table.cd{border-collapse:collapse;font-size:13px;width:100%;min-width:680px}
 table.cd th{font-weight:600;color:#fff;background:#003087;padding:8px 10px;text-align:left;white-space:nowrap}
 table.cd td{padding:8px 10px;border-bottom:1px solid #f1f3f7;font-variant-numeric:tabular-nums}
 table.cd td.bat{font-weight:600;color:#1a1a2e;white-space:nowrap}
 .dn{color:#b91c1c;font-weight:600} .up{color:#15803d;font-weight:600}
 .thin{color:#9ca3af;font-style:italic}
 .lead{background:#eef3fb;border:1px solid #d5dced;border-radius:10px;padding:12px 14px;margin:10px 0 18px;font-size:14px;line-height:1.6}
 .note{color:#9ca3af;font-size:12px;margin-top:16px;line-height:1.5}
 h1 .sub{display:block;font-size:14px;color:#6b7280;font-weight:400;margin-top:4px}
</style>"""


def _rows(conn, cur, ids):
    S = DATA_SCHEMA
    intl = (f"M.series_id IN (SELECT series_id FROM [{S}].[Series] "
            f"WHERE name IN {international_series_sql('Test')})")
    cin = ",".join(f"'{c}'" for c in REF_CONDITIONS)
    # venue ids fetched first — a subquery isn't allowed inside SUM(CASE …)
    vids = [str(r["venue_id"]) for r in run_query(
        f"""SELECT V.venue_id FROM [{S}].[Venues] V
            JOIN [{S}].[Countries] C ON V.country_id = C.country_id
            WHERE C.name IN ({cin})""", conn, cur)]
    sena = ("M.venue_id IN (" + ",".join(f"'{v}'" for v in vids) + ")") if vids else "1=0"
    inl = "','".join(ids)
    return run_query(f"""
        SELECT D.striker_id AS pid,
          COUNT(*) AS balls_all,
          SUM(CASE WHEN D.batter_dismissal='1' THEN 1 ELSE 0 END) AS outs_all,
          SUM(TRY_CAST(D.bat_score AS FLOAT)) AS runs_all,
          SUM(CASE WHEN D.shot_quality_id IN {_FALSE_SQ} THEN 1 ELSE 0 END) AS fls_all,
          SUM(CASE WHEN D.shot_quality_id IS NOT NULL AND D.shot_quality_id<>'' THEN 1 ELSE 0 END) AS sq_all,
          SUM(CASE WHEN {sena} THEN 1 ELSE 0 END) AS balls_s,
          SUM(CASE WHEN {sena} AND D.batter_dismissal='1' THEN 1 ELSE 0 END) AS outs_s,
          SUM(CASE WHEN {sena} THEN TRY_CAST(D.bat_score AS FLOAT) ELSE 0 END) AS runs_s,
          SUM(CASE WHEN {sena} AND D.shot_quality_id IN {_FALSE_SQ} THEN 1 ELSE 0 END) AS fls_s,
          SUM(CASE WHEN {sena} AND D.shot_quality_id IS NOT NULL AND D.shot_quality_id<>'' THEN 1 ELSE 0 END) AS sq_s,
          COUNT(DISTINCT CASE WHEN {sena} THEN D.match_id END) AS matches_s
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id = M.match_id
        WHERE {intl} AND D.legal_ball='1' AND D.striker_id IN ('{inl}')
        GROUP BY D.striker_id""", conn, cur)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build(opp):
    about = json.load(open(os.path.join(HERE, "data", f"opponent_about_{opp}.json"), encoding="utf-8"))
    batters = about.get("batters", {})
    conn, cur = set_conn_cursor()
    raw = _rows(conn, cur, list(batters))
    conn.close()
    d = {r["pid"]: r for r in raw}

    out, tot_r, tot_o, tot_b = [], 0.0, 0, 0
    for bid, meta in sorted(batters.items(), key=lambda kv: -(kv[1].get("order") or 0)):
        r = d.get(bid)
        name = (meta.get("name") or bid).strip()
        if not r:
            out.append({"name": name, "matches": 0, "balls": 0}); continue
        bs, os_, rs = int(_f(r["balls_s"])), int(_f(r["outs_s"])), _f(r["runs_s"])
        ba, oa, ra = int(_f(r["balls_all"])), int(_f(r["outs_all"])), _f(r["runs_all"])
        tot_r += rs; tot_o += os_; tot_b += bs
        out.append({
            "name": name, "hand": meta.get("hand", ""), "role": meta.get("role", ""),
            "matches": int(_f(r["matches_s"])), "balls": bs, "outs": os_,
            "avg": round(rs / os_, 1) if os_ >= 3 and bs >= _MIN_BALLS else None,
            "avg_all": round(ra / oa, 1) if oa else None,
            "false": round(100 * _f(r["fls_s"]) / _f(r["sq_s"]), 1) if _f(r["sq_s"]) >= 80 else None,
            "false_all": round(100 * _f(r["fls_all"]) / _f(r["sq_all"]), 1) if _f(r["sq_all"]) >= 80 else None,
        })

    squad_avg = round(tot_r / tot_o, 1) if tot_o else None
    json.dump({"opp": opp, "countries": list(REF_CONDITIONS), "squad_avg": squad_avg,
               "squad_balls": tot_b, "squad_outs": tot_o, "batters": out},
              open(os.path.join(HERE, "data", f"conditions_{opp}.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    rated = [b for b in out if b.get("avg") is not None]
    none_ = [b for b in out if b["matches"] == 0]
    below = [b for b in rated if b["avg_all"] and b["avg"] < b["avg_all"]]
    lead = (f'Across the squad these batters average <b>{squad_avg}</b> in New Zealand, South Africa '
            f'and England ({tot_b:,} balls, {tot_o} dismissals). '
            f'{len(below)} of the {len(rated)} with a readable sample average less there than they do '
            f'in Tests overall.')
    if none_:
        lead += (f' <b>{", ".join(html.escape(b["name"]) for b in none_)}</b> '
                 f'{"has" if len(none_) == 1 else "have"} never played a Test in those countries, so '
                 f'there is nothing to read either way.')

    body = [CSS,
            '<h1>Seam-and-bounce conditions'
            '<span class="sub">Tests played in New Zealand, South Africa and England — the closest '
            'benchmark we have to Australian conditions. Each batter\'s record there, set against '
            'their overall Test record.</span></h1>',
            f'<div class=lead>{lead}</div>',
            '<div class=cwrap><table class=cd>'
            '<tr><th>Batter</th><th>Tests</th><th>Balls</th><th>Avg there</th>'
            '<th>Avg overall</th><th>Difference</th><th>False shot</th></tr>']
    for b in out:
        if not b["matches"]:
            body.append(f'<tr><td class=bat>{html.escape(b["name"])}</td>'
                        f'<td colspan=6 class=thin>Never played a Test in these countries.</td></tr>')
            continue
        if b["avg"] is None:
            body.append(f'<tr><td class=bat>{html.escape(b["name"])}</td><td>{b["matches"]}</td>'
                        f'<td>{b["balls"]}</td>'
                        f'<td colspan=4 class=thin>{b["outs"]} dismissals — too few to average.</td></tr>')
            continue
        diff = (b["avg"] - b["avg_all"]) if b["avg_all"] else None
        dcell = (f'<span class="{"dn" if diff < 0 else "up"}">{diff:+.1f}</span>'
                 if diff is not None else '<span class=thin>—</span>')
        fcell = (f'{b["false"]}%' + (f' <span class=thin>(overall {b["false_all"]}%)</span>'
                                     if b["false_all"] is not None else '')) \
            if b["false"] is not None else '<span class=thin>—</span>'
        body.append(f'<tr><td class=bat>{html.escape(b["name"])}</td><td>{b["matches"]}</td>'
                    f'<td>{b["balls"]}</td><td>{b["avg"]}</td>'
                    f'<td>{b["avg_all"] if b["avg_all"] else "—"}</td><td>{dcell}</td><td>{fcell}</td></tr>')
    body.append('</table></div>')
    body.append(f'<p class=note>Averages need {_MIN_BALLS}+ balls and 3+ dismissals in those countries '
                f'to be shown. A negative difference means they average less there than across their '
                f'Test career. These are small away samples — read them as a direction, not a '
                f'settled number.</p>')

    dst = os.path.join(HERE, "reports", f"conditions_{opp}.html")
    open(dst, "w", encoding="utf-8").write(
        _page("Seam-and-bounce conditions", "".join(body), up=("index.html", "Series")))
    print(f"wrote {dst} · squad avg {squad_avg} · {len(rated)} rateable, {len(none_)} with no record")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    build(ap.parse_args().opp)


if __name__ == "__main__":
    main()
