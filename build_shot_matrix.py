"""build_shot_matrix.py — the series UNORTHODOX-SHOT matrix: per opposition batter, how often they
play each cross-batted / innovative shot, split vs pace and vs spin. Two tables (Pace, Spin), rows =
shots, columns = batters, cells = % of that batter's legal balls (vs that bowling type) played as
that shot. Rebuilt off OUR warehouse (stroke lookup type 24) — coarser than some external sources,
so only the shots we can cleanly separate are shown.

Run:  .\\venv\\Scripts\\python.exe build_shot_matrix.py --opp bangladesh
Out:  data/shot_matrix_{opp}.json  +  reports/shot_matrix_{opp}.html  (publish_site links it)
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
_INTL_TEST = (f"M.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
              f"WHERE name IN {international_series_sql('Test')})")
# unorthodox shots we can separate in stroke lookup 24 (id -> label). No 'upper cut' / 'paddle
# scoop vs sweep' split in our vocab (those collapse into Cut / Paddle), so they're not shown.
SHOTS = [("9", "Conventional sweep"), ("15", "Slog sweep"), ("18", "Reverse sweep"),
         ("26", "Paddle"), ("17", "Ramp / scoop"), ("27", "Switch hit")]
_PACE = "('1','2','3')"
_SPIN = "('4','5')"
MIN_BALLS = 40                                   # a batter needs this many vs the type to show a column

CSS = """<style>
 .mwrap{overflow-x:auto;border:1px solid #e5e7eb;border-radius:10px;background:#fff;padding:10px;margin:10px 0 22px}
 table.mx{border-collapse:collapse;font-size:12px;min-width:640px}
 table.mx th{font-weight:600;color:#6b7280;padding:5px 8px;border-bottom:1px solid #e5e7eb;text-align:center;white-space:nowrap}
 table.mx th.rowh{text-align:left}
 table.mx td{padding:5px 8px;text-align:center;border-bottom:1px solid #f1f3f7;font-variant-numeric:tabular-nums;white-space:nowrap}
 table.mx td.rowh{text-align:left;font-weight:600;color:#1a1a2e;white-space:nowrap}
 h2.mx{font-size:16px;color:#003087;margin:18px 0 2px} .sub{color:#6b7280;font-size:13px;margin:0 0 6px}
 .note{color:#9ca3af;font-size:12px;margin-top:18px}
</style>"""


def _shade(pct):
    if pct is None or pct <= 0:
        return "#ffffff"
    frac = min(pct / 12.0, 1.0)                  # 12%+ = full green
    r = int(255 + (198 - 255) * frac); g = int(255 + (231 - 255) * frac); b = int(255 + (193 - 255) * frac)
    return f"rgb({r},{g},{b})"


def _query(conn, cur, batter_ids):
    inlist = "('" + "','".join(batter_ids) + "')"
    when = " ".join(
        f"SUM(CASE WHEN D.bowler_style_id IN {grp} AND D.stroke_id='{sid}' THEN 1 ELSE 0 END) AS {tag}{sid},"
        for tag, grp in (("p", _PACE), ("s", _SPIN)) for sid, _ in SHOTS)
    return run_query(f"""
        SELECT D.striker_id AS bid,
            SUM(CASE WHEN D.bowler_style_id IN {_PACE} THEN 1 ELSE 0 END) AS pace_balls,
            SUM(CASE WHEN D.bowler_style_id IN {_SPIN} THEN 1 ELSE 0 END) AS spin_balls,
            {when.rstrip(',')}
        FROM [{DATA_SCHEMA}].[Deliveries] D
        JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id = M.match_id
        WHERE {_INTL_TEST} AND D.legal_ball = '1' AND D.striker_id IN {inlist}
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
    rows = _query(conn, cur, list(batters.keys()))
    conn.close()

    # a single column order across both tables: most-established (most Test balls faced) first
    total = {r["bid"]: _f(r.get("pace_balls")) + _f(r.get("spin_balls")) for r in rows}

    data = {"pace": [], "spin": []}
    for tw, tag, bcol in (("pace", "p", "pace_balls"), ("spin", "s", "spin_balls")):
        for r in rows:
            balls = _f(r.get(bcol))
            if balls < MIN_BALLS:
                continue
            meta = batters.get(r["bid"], {})
            entry = {"batter": (meta.get("name") or r["bid"]).strip(), "bid": r["bid"],
                     "balls": int(balls)}
            for sid, label in SHOTS:
                entry[label] = round(_f(r.get(f"{tag}{sid}")) / balls * 100, 1)
            data[tw].append(entry)
        data[tw].sort(key=lambda e: -total.get(e["bid"], 0))     # most-faced batters first
    json.dump(data, open(os.path.join(HERE, "data", f"shot_matrix_{opp}.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    def _table(title, entries):
        head = "<tr><th class=rowh>Shot</th>" + "".join(
            f"<th>{html.escape(e['batter'])}</th>" for e in entries) + "</tr>"
        body = []
        for _sid, label in SHOTS:
            tds = [f"<td class=rowh>{html.escape(label)}</td>"]
            for e in entries:
                v = e[label]
                tds.append(f'<td style="background:{_shade(v)}">{v:.1f}%</td>' if v > 0 else "<td>–</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        return (f'<h2 class=mx>{html.escape(title)}</h2>'
                f'<p class=sub>% of each batter\'s legal balls (vs {title.split()[0].lower()}) played as that shot.</p>'
                f'<div class=mwrap><table class=mx>{head}{"".join(body)}</table></div>')

    body = (CSS + "<h1>Unorthodox shot options</h1>"
            "<p class=sub>How often each opposition batter plays the cross-batted / innovative shots — "
            "vs pace and vs spin. From our warehouse (ball-by-ball era); a batter needs "
            f"{MIN_BALLS}+ balls vs the type to show.</p>"
            + _table("Pace shot options", data["pace"])
            + _table("Spin shot options", data["spin"])
            + '<p class=note>Shots limited to those our stroke coding separates (no upper-cut or '
              'paddle-scoop/sweep split). Data since the ball-by-ball era.</p>')
    out = os.path.join(HERE, "reports", f"shot_matrix_{opp}.html")
    open(out, "w", encoding="utf-8").write(_page("Unorthodox shot options", body, up=("index.html", "Series")))
    print(f"wrote {out} · pace {len(data['pace'])} batters, spin {len(data['spin'])} batters")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    build(ap.parse_args().opp)


if __name__ == "__main__":
    main()
