"""
team_review.py — standalone team batting review using the share-of-runs metric.

Ranks a team's batters over a period by how much of the batting they do (share of
the team's runs), alongside average, strike rate, form vs pace/spin, and their most
common dismissal.  Built for "Australia — Test batting since 2021" but parameterised.

    from team_review import render_team_review
    render_team_review("Australia M", since="2021-01-01", title="Australia — Test Batting Review")
"""
import datetime
import os
import re
import statistics
from collections import defaultdict

import plotly.graph_objects as go
from jinja2 import Template

from version import REPORT_VERSION
from ludis_cricket.warehouse import set_conn_cursor, run_query
from config import DATA_SCHEMA as S
from report import (
    _fig_uri, _html_to_pdf,
    BG_PAGE, BG_PANEL, TEXT_PRI, TEXT_SEC, ACCENT, DANGER, BORDER,
)

_TEST = "('2','3','4','5','6')"


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def compute_team_review(team_name: str, since: str = "2021-01-01", min_runs: int = 200) -> dict:
    conn, cur = set_conn_cursor()
    where = (f"M.match_length_id IN {_TEST} AND T.team_name = '{team_name}' "
             f"AND M.match_date >= '{since}'")

    # A — team innings totals (off the bat)
    A = run_query(f"""
        SELECT D.match_id, D.match_innings, SUM(CAST(D.bat_score AS int)) team_bat
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id=M.match_id
        JOIN [{S}].[Teams] T ON D.team_batting_id=T.team_id
        WHERE {where} GROUP BY D.match_id, D.match_innings""", conn, cur)
    team = {(r["match_id"], r["match_innings"]): int(r["team_bat"]) for r in A if int(r["team_bat"]) > 0}
    n_matches = len({m for m, _ in team})
    n_innings = len(team)
    team_runs = sum(team.values())

    # B — per batter per innings
    B = run_query(f"""
        SELECT D.striker_id, MAX(P.name) nm, D.match_id, D.match_innings,
               SUM(CAST(D.bat_score AS int)) his,
               SUM(CASE WHEN D.legal_ball='1' THEN 1 ELSE 0 END) balls,
               MAX(CASE WHEN D.striker_dismissed='1' THEN 1 ELSE 0 END) out_,
               MAX(CAST(D.striker_batting_position AS int)) pos
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id=M.match_id
        JOIN [{S}].[Teams] T ON D.team_batting_id=T.team_id
        LEFT JOIN [{S}].[Players] P ON D.striker_id=P.player_id
        WHERE {where} AND D.striker_id IS NOT NULL
        GROUP BY D.striker_id, D.match_id, D.match_innings""", conn, cur)

    # C — per batter vs pace / spin (avg)
    C = run_query(f"""
        SELECT D.striker_id,
               CASE WHEN D.bowler_style_id IN ('1','2','3') THEN 'pace' ELSE 'spin' END kind,
               SUM(CAST(D.bat_score AS int)) runs,
               SUM(CASE WHEN D.striker_dismissed='1' THEN 1 ELSE 0 END) outs
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id=M.match_id
        JOIN [{S}].[Teams] T ON D.team_batting_id=T.team_id
        WHERE {where} AND D.striker_id IS NOT NULL AND D.bowler_style_id IS NOT NULL
        GROUP BY D.striker_id, CASE WHEN D.bowler_style_id IN ('1','2','3') THEN 'pace' ELSE 'spin' END""", conn, cur)
    conn.close()

    vs = defaultdict(dict)
    for r in C:
        o = int(r["outs"])
        vs[r["striker_id"]][r["kind"]] = _f(r["runs"]) / o if o else None

    bat = defaultdict(lambda: {"nm": "", "runs": 0, "balls": 0, "outs": 0, "shares": [], "pos": []})
    for r in B:
        b, ba = int(r["his"]), int(r["balls"])
        if ba == 0 and b == 0:
            continue
        d = bat[r["striker_id"]]
        d["nm"] = r["nm"]
        d["runs"] += b
        d["balls"] += ba
        d["outs"] += int(r["out_"])
        p = r.get("pos")
        if str(p).strip().lstrip("-").isdigit():
            d["pos"].append(int(p))
        tb = team.get((r["match_id"], r["match_innings"]))
        if tb:
            d["shares"].append(b / tb * 100)

    # career share = sum(his innings runs) / sum(team totals of those innings)
    numer, denom = defaultdict(float), defaultdict(float)
    for r in B:
        b, ba = int(r["his"]), int(r["balls"])
        tb = team.get((r["match_id"], r["match_innings"]))
        if tb and (ba > 0 or b > 0):
            numer[r["striker_id"]] += b
            denom[r["striker_id"]] += tb

    rows = []
    for sid, d in bat.items():
        if d["runs"] < min_runs or not d["shares"]:
            continue
        inns = len(d["shares"])
        rows.append({
            "id": sid, "name": _clean_name(d["nm"]),
            "inns": inns, "runs": d["runs"], "balls": d["balls"], "outs": d["outs"],
            "avg": d["runs"] / d["outs"] if d["outs"] else None,
            "sr": d["runs"] / d["balls"] * 100 if d["balls"] else None,
            "share_career": numer[sid] / denom[sid] * 100 if denom[sid] else 0.0,
            "share_median": statistics.median(d["shares"]),
            "carried": sum(1 for s in d["shares"] if s >= 25) / inns * 100,
            "vs_pace": vs[sid].get("pace"), "vs_spin": vs[sid].get("spin"),
            "pos": round(statistics.median(d["pos"])) if d["pos"] else None,
        })
    rows.sort(key=lambda r: -r["share_career"])
    return {"team": team_name, "since": since, "n_matches": n_matches,
            "n_innings": n_innings, "team_runs": team_runs, "rows": rows}


def _clean_name(nm):
    nm = (nm or "").strip()
    return nm


def _share_chart(rows: list) -> go.Figure:
    top = rows[:14][::-1]
    names = [r["name"].split(",")[0] for r in top]
    vals = [r["share_career"] for r in top]
    colors = [ACCENT if v >= 12 else (TEXT_SEC if v >= 8 else "#b0b6c0") for v in vals]
    fig = go.Figure(go.Bar(x=vals, y=names, orientation="h",
                           marker_color=colors,
                           text=[f"{v:.1f}%" for v in vals], textposition="outside",
                           cliponaxis=False))
    fig.update_layout(
        paper_bgcolor=BG_PANEL, plot_bgcolor=BG_PANEL,
        font=dict(color=TEXT_PRI, family="Inter, sans-serif", size=12),
        margin=dict(l=8, r=40, t=10, b=24), height=430,
        xaxis=dict(title="Share of team runs (%)", showgrid=True, gridcolor="rgba(0,0,0,0.07)", zeroline=False),
        yaxis=dict(showgrid=False),
    )
    return fig


def _reads(R: dict) -> list:
    rows = R["rows"]
    out = []
    top4 = rows[:4]
    if len(top4) >= 4:
        s = sum(r["share_career"] for r in top4)
        out.append(f"The top four — {', '.join(r['name'].split(',')[0] for r in top4)} — make "
                   f"<b>{s:.0f}%</b> of {R['team'].split(' M')[0]}'s runs between them.")
    reg = [r for r in rows if r["inns"] >= 20]
    if reg:
        best_avg = max(reg, key=lambda r: r["avg"] or 0)
        out.append(f"Most productive regular: <b>{best_avg['name'].split(',')[0]}</b> "
                   f"(avg {best_avg['avg']:.0f}, {best_avg['share_career']:.1f}% of team runs).")
        carry = max(reg, key=lambda r: r["carried"])
        out.append(f"Carries the innings most often: <b>{carry['name'].split(',')[0]}</b> — "
                   f"{carry['carried']:.0f}% of innings he makes ≥25% of the team's runs.")
        weak_pace = [r for r in reg if r["vs_pace"] and r["vs_spin"] and r["vs_pace"] < r["vs_spin"] * 0.75]
        weak_spin = [r for r in reg if r["vs_pace"] and r["vs_spin"] and r["vs_spin"] < r["vs_pace"] * 0.75]
        if weak_spin:
            out.append("Vulnerable to spin: " + ", ".join(
                f"{r['name'].split(',')[0]} (spin {r['vs_spin']:.0f} vs pace {r['vs_pace']:.0f})"
                for r in weak_spin[:3]) + ".")
        # concerns = frontline batters (median position <= 7) averaging under 35
        conc = [r for r in reg if r["avg"] and r["avg"] < 35 and (r["pos"] or 99) <= 7]
        if conc:
            out.append("Frontline batters under pressure (avg &lt; 35): " + ", ".join(
                f"{r['name'].split(',')[0]} ({r['avg']:.0f})" for r in sorted(conc, key=lambda r: r["avg"])[:4]) + ".")
    return out


def render_team_review(team_name: str = "Australia M", since: str = "2021-01-01",
                       title: str = "", out_dir: str = "reports") -> str:
    R = compute_team_review(team_name, since)
    if not title:
        title = f"{team_name.replace(' M', '')} — Test Batting Review"
    table = []
    for r in R["rows"]:
        table.append((
            r["name"], (str(r["pos"]) if r["pos"] else "—"), r["inns"], r["runs"],
            f"{r['avg']:.1f}" if r["avg"] else "—",
            f"{r['sr']:.1f}" if r["sr"] else "—",
            f"{r['share_career']:.1f}%", f"{r['share_median']:.1f}%", f"{r['carried']:.0f}%",
            f"{r['vs_pace']:.0f}" if r["vs_pace"] else "—",
            f"{r['vs_spin']:.0f}" if r["vs_spin"] else "—",
        ))
    ctx = {
        "title": title, "R": R,
        "since_txt": datetime.date.fromisoformat(since).strftime("%b %Y"),
        "team_runs": f"{R['team_runs']:,}",
        "chart": _fig_uri(_share_chart(R["rows"]), w=560, h=430),
        "table": table, "reads": _reads(R),
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "c": dict(BG_PAGE=BG_PAGE, BG_PANEL=BG_PANEL, TEXT_PRI=TEXT_PRI, TEXT_SEC=TEXT_SEC,
                  ACCENT=ACCENT, DANGER=DANGER, BORDER=BORDER),
    }
    html = Template(_TEMPLATE).render(**ctx)
    slug = re.sub(r"[^a-z0-9]+", "_", re.sub(r"\s+M$", "", team_name).lower()).strip("_")
    out_path = os.path.abspath(os.path.join(out_dir, f"{slug}_test_batting_review_since_{since[:4]}.pdf"))
    os.makedirs(out_dir, exist_ok=True)
    _html_to_pdf(html, out_path)
    return out_path


_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  @page { size: A4; }
  * { box-sizing: border-box; }
  html, body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: Inter, -apple-system, "Segoe UI", sans-serif; color: {{c.TEXT_PRI}};
         background: {{c.BG_PAGE}}; margin: 0; font-size: 11px; }
  .page { padding: 10px 8px; }
  h1 { font-size: 22px; margin: 0; }
  .sub { color: {{c.TEXT_SEC}}; font-size: 11px; margin-top: 2px; }
  .ver { float: right; text-align: right; font-size: 8.5px; color: {{c.TEXT_SEC}}; }
  h2 { font-size: 13px; color: {{c.ACCENT}}; border-bottom: 2px solid {{c.ACCENT}};
       padding-bottom: 3px; margin: 16px 0 8px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
  .sbox { background: {{c.BG_PANEL}}; border: 1px solid {{c.BORDER}}; border-radius: 8px; padding: 10px 12px; }
  .sbox ul { margin: 0; padding-left: 15px; } .sbox li { margin-bottom: 5px; line-height: 1.4; }
  img.chart { width: 100%; border: 1px solid {{c.BORDER}}; border-radius: 8px; background:#fff; }
  .cap { font-size: 8.5px; color: {{c.TEXT_SEC}}; font-style: italic; text-align:center; margin-top:3px; }
  table { width: 100%; border-collapse: collapse; font-size: 10px; margin-top: 6px; }
  th, td { border: 1px solid {{c.BORDER}}; padding: 3px 6px; text-align: center; }
  th { background: #eef1f6; color: {{c.TEXT_SEC}}; font-weight: 600; }
  td.lab { text-align: left; font-weight: 600; }
  tr:nth-child(-n+5) td { background: #f4f8ff; }
</style></head>
<body><div class="page">
  <div class="ver">v{{version}}<br>{{build_date}}</div>
  <h1>{{title}}</h1>
  <div class="sub">Test cricket, since {{since_txt}} · {{R.n_matches}} matches · {{R.n_innings}} innings · {{team_runs}} team runs off the bat.
     <b>Share</b> = a batter's runs ÷ the team's off-the-bat runs (career = volume-weighted; median = typical innings;
     carry = % of innings he makes ≥25% of the team).</div>

  <div class="grid">
    <div>
      <h2>Who carries the batting</h2>
      <img class="chart" src="{{chart}}">
      <div class="cap">Share of the team's runs, career (volume-weighted), top run-scorers.</div>
    </div>
    <div>
      <h2>The story</h2>
      <div class="sbox"><ul>
        {% for t in reads %}<li>{{t|safe}}</li>{% endfor %}
      </ul></div>
    </div>
  </div>

  <h2>Full batting review</h2>
  <table>
    <tr><th>Batter</th><th>Pos</th><th>Inns</th><th>Runs</th><th>Avg</th><th>SR</th>
        <th>Team % (career)</th><th>Median %</th><th>Carry %</th><th>vs Pace</th><th>vs Spin</th></tr>
    {% for name, pos, inns, runs, avg, sr, sc, sm, carry, vp, vs in table %}
    <tr><td class="lab">{{name}}</td><td>{{pos}}</td><td>{{inns}}</td><td>{{runs}}</td><td>{{avg}}</td><td>{{sr}}</td>
        <td>{{sc}}</td><td>{{sm}}</td><td>{{carry}}</td><td>{{vp}}</td><td>{{vs}}</td></tr>
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left">Rows shaded blue = top five by share. vs Pace / vs Spin = batting average against that bowling type. Scope: matches batted by the senior Australia men's side since {{since_txt}} (min 200 runs to appear).</div>
</div></body></html>
"""
