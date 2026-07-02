"""
crease_investigation.py — one-off investigation into bowler release point / crease use.

Pulls the release-tracking columns for international Test pace bowlers and answers:
  * coverage — when did release tracking start, how complete is it?
  * what each release_* column actually is (which are usable)
  * does a taller release point produce more bounce (and wickets)?
  * does crease width (how wide of the stumps they release) drive outcomes, or is it
    tactical (angle-creation)?  Controlled look at over-the-wicket vs RHB.

Renders reports/crease_release_investigation.pdf.  Run:
    .\venv\Scripts\python.exe crease_investigation.py
"""
import datetime
import statistics

import plotly.graph_objects as go
from jinja2 import Template

from ludis_cricket.warehouse import set_conn_cursor, run_query
from ludis_cricket.config import DATA_SCHEMA as S, international_series_sql
from ludis_cricket.pdf import fig_uri, html_to_pdf
from ludis_cricket.theme import (
    BG_PAGE, BG_PANEL, TEXT_PRI, TEXT_SEC, ACCENT, DANGER, BORDER, GRID,
)

_INTL = f"M.series_id IN (SELECT series_id FROM [{S}].[Series] WHERE name IN {international_series_sql('Test')})"
_PACE = "D.bowler_style_id IN ('1','2','3')"
_FALSE_IDS = "('2','21','25','26','3','4','5','6','7','10','28','14','27')"  # missed/play-miss/edges/mistimed
_LABEL = {"880149": "Hazlewood", "1300076": "Cummins", "1300007": "Starc",
          "2710059": "Boland", "1300063": "Pattinson", "940117": "Anderson"}


def _f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _pearson(xs, ys):
    n = len(xs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx and sy else 0.0


def compute():
    conn, cur = set_conn_cursor()

    coverage = run_query(f"""
        SELECT YEAR(M.match_date) yr, COUNT(*) n,
          100.0*SUM(CASE WHEN D.release_line_unmirrored IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*) line,
          100.0*SUM(CASE WHEN D.release_speed IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*) spd
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id=M.match_id
        WHERE {_INTL} AND {_PACE} AND D.legal_ball='1'
        GROUP BY YEAR(M.match_date) ORDER BY YEAR(M.match_date)""", conn, cur)

    perb = run_query(f"""
        SELECT D.bowler_id, MAX(P.name) nm, COUNT(*) n,
          AVG(CAST(D.release_height AS float)) rh,
          AVG(ABS(CAST(D.release_line_unmirrored AS float))) crease,
          AVG(CASE WHEN CAST(D.at_stumps_height AS float) BETWEEN 0 AND 2000 THEN CAST(D.at_stumps_height AS float) END) ash,
          100.0*SUM(CASE WHEN D.bowler_dismissal='1' THEN 1 ELSE 0 END)/COUNT(*) wpc
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id=M.match_id
        LEFT JOIN [{S}].[Players] P ON D.bowler_id=P.player_id
        WHERE {_INTL} AND {_PACE} AND D.legal_ball='1'
          AND D.release_height BETWEEN 1500 AND 2400 AND ABS(CAST(D.release_line_unmirrored AS float))<=1500
        GROUP BY D.bowler_id HAVING COUNT(*)>=400""", conn, cur)

    buckets = run_query(f"""
        SELECT CASE WHEN ABS(CAST(D.release_line_unmirrored AS float))<450 THEN '1'
                    WHEN ABS(CAST(D.release_line_unmirrored AS float))<750 THEN '2' ELSE '3' END b,
          COUNT(*) balls,
          AVG(-CAST(D.at_stumps_line AS float)/10.0) at_stumps_cm,
          100.0*SUM(CASE WHEN D.shot_quality_id IN {_FALSE_IDS} THEN 1 ELSE 0 END)
               /NULLIF(SUM(CASE WHEN D.shot_quality_id IS NOT NULL THEN 1 ELSE 0 END),0) false_pc,
          100.0*SUM(CASE WHEN D.bowler_dismissal='1' THEN 1 ELSE 0 END)/COUNT(*) wpc
        FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON D.match_id=M.match_id
        WHERE {_INTL} AND {_PACE} AND D.legal_ball='1' AND D.over_the_wicket='1' AND D.striker_hand_id='1'
          AND ABS(CAST(D.release_line_unmirrored AS float))<=1500
        GROUP BY CASE WHEN ABS(CAST(D.release_line_unmirrored AS float))<450 THEN '1'
                      WHEN ABS(CAST(D.release_line_unmirrored AS float))<750 THEN '2' ELSE '3' END
        ORDER BY b""", conn, cur)
    conn.close()

    perb = [{"id": r["bowler_id"], "nm": (r["nm"] or "").split(",")[0], "n": int(r["n"]),
             "rh": _f(r["rh"]), "crease": _f(r["crease"]), "ash": _f(r["ash"]), "wpc": _f(r["wpc"])}
            for r in perb]
    perb = [b for b in perb if all(b[k] is not None for k in ("rh", "crease", "ash", "wpc"))]
    return {"coverage": coverage, "perb": perb, "buckets": buckets}


# ── charts ──────────────────────────────────────────────────────────────────────
def _coverage_chart(coverage):
    rows = [r for r in coverage if int(r["n"]) > 200]
    yrs = [int(r["yr"]) for r in rows]
    line = [_f(r["line"], 0) for r in rows]
    spd = [_f(r["spd"], 0) for r in rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=yrs, y=line, name="Release point (line/height/angle)", marker_color=ACCENT))
    fig.add_trace(go.Bar(x=yrs, y=spd, name="Release speed", marker_color="#b8860b"))
    fig.update_layout(barmode="overlay", paper_bgcolor=BG_PANEL, plot_bgcolor=BG_PANEL,
                      font=dict(color=TEXT_PRI, family="Inter, sans-serif", size=11),
                      margin=dict(l=8, r=8, t=40, b=8), height=300,
                      legend=dict(orientation="h", y=1.15, x=0, font=dict(size=10)),
                      xaxis=dict(gridcolor=GRID, zeroline=False, dtick=2),
                      yaxis=dict(title="% of Test pace balls tracked", gridcolor=GRID, range=[0, 105]))
    fig.data[1].opacity = 0.9
    return fig


def _height_bounce_scatter(perb):
    xs = [b["rh"] / 10 for b in perb]           # cm
    ys = [b["ash"] / 10 for b in perb]          # cm at stumps
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers",
                             marker=dict(size=7, color=ACCENT, opacity=0.5),
                             text=[b["nm"] for b in perb], hoverinfo="text"))
    # label notable bowlers
    for b in perb:
        if b["id"] in _LABEL:
            fig.add_trace(go.Scatter(x=[b["rh"] / 10], y=[b["ash"] / 10], mode="markers+text",
                                     marker=dict(size=9, color=DANGER), text=[_LABEL[b["id"]]],
                                     textposition="top center", textfont=dict(size=9), showlegend=False))
    fig.update_layout(paper_bgcolor=BG_PANEL, plot_bgcolor=BG_PANEL, showlegend=False,
                      font=dict(color=TEXT_PRI, family="Inter, sans-serif", size=11),
                      margin=dict(l=8, r=8, t=10, b=8), height=380,
                      xaxis=dict(title="Release height (cm)", gridcolor=GRID, zeroline=False),
                      yaxis=dict(title="Bounce — height past the stumps (cm)", gridcolor=GRID, zeroline=False))
    return fig


def _bucket_chart(buckets):
    lab = {"1": "Tight (<45cm)", "2": "Standard (45–75)", "3": "Wide (>75cm)"}
    order = sorted(buckets, key=lambda r: r["b"])
    x = [lab[r["b"]] for r in order]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=x, y=[_f(r["false_pc"]) for r in order], name="False-shot %",
                         marker_color=ACCENT, text=[f"{_f(r['false_pc']):.1f}%" for r in order], textposition="outside"))
    fig.add_trace(go.Bar(x=x, y=[_f(r["wpc"]) * 8 for r in order], name="Wickets per 100 (×8 scale)",
                         marker_color=DANGER, text=[f"{_f(r['wpc']):.2f}" for r in order], textposition="outside"))
    fig.update_layout(barmode="group", paper_bgcolor=BG_PANEL, plot_bgcolor=BG_PANEL,
                      font=dict(color=TEXT_PRI, family="Inter, sans-serif", size=11),
                      margin=dict(l=8, r=8, t=40, b=8), height=320,
                      legend=dict(orientation="h", y=1.15, x=0, font=dict(size=10)),
                      xaxis=dict(title="Release distance from middle stump (over the wicket, vs RHB)"),
                      yaxis=dict(gridcolor=GRID, zeroline=False, showticklabels=False))
    return fig


def render(out_path="reports/crease_release_investigation.pdf"):
    D = compute()
    perb = D["perb"]
    r_hb = _pearson([b["rh"] for b in perb], [b["ash"] for b in perb])
    r_hw = _pearson([b["rh"] for b in perb], [b["wpc"] for b in perb])
    r_cw = _pearson([b["crease"] for b in perb], [b["wpc"] for b in perb])
    tall = sorted(perb, key=lambda b: -b["rh"])
    q = max(3, len(perb) // 4)
    top, bot = tall[:q], tall[-q:]

    def qmean(rows, k):
        return statistics.mean(b[k] for b in rows)

    bk = {r["b"]: r for r in D["buckets"]}
    ctx = {
        "n_bowlers": len(perb),
        "r_hb": f"{r_hb:+.2f}", "r_hw": f"{r_hw:+.2f}", "r_cw": f"{r_cw:+.2f}",
        "tall_h": f"{qmean(top,'rh')/10:.0f}", "tall_b": f"{qmean(top,'ash')/10:.0f}", "tall_w": f"{qmean(top,'wpc'):.2f}",
        "short_h": f"{qmean(bot,'rh')/10:.0f}", "short_b": f"{qmean(bot,'ash')/10:.0f}", "short_w": f"{qmean(bot,'wpc'):.2f}",
        "cov_chart": fig_uri(_coverage_chart(D["coverage"]), w=720, h=300),
        "scatter": fig_uri(_height_bounce_scatter(perb), w=720, h=380),
        "bucket_chart": fig_uri(_bucket_chart(D["buckets"]), w=720, h=320),
        "b_tight_false": f"{_f(bk['1']['false_pc']):.1f}", "b_wide_false": f"{_f(bk['3']['false_pc']):.1f}",
        "b_tight_wpc": f"{_f(bk['1']['wpc']):.2f}", "b_wide_wpc": f"{_f(bk['3']['wpc']):.2f}",
        "b_tight_line": f"{_f(bk['1']['at_stumps_cm']):.0f}", "b_wide_line": f"{_f(bk['3']['at_stumps_cm']):.0f}",
        "build_date": datetime.date.today().strftime("%d %b %Y"),
        "c": dict(BG_PAGE=BG_PAGE, BG_PANEL=BG_PANEL, TEXT_PRI=TEXT_PRI, TEXT_SEC=TEXT_SEC,
                  ACCENT=ACCENT, DANGER=DANGER, BORDER=BORDER),
    }
    html = Template(_TEMPLATE).render(**ctx)
    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    html_to_pdf(html, os.path.abspath(out_path))
    return os.path.abspath(out_path)


_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  @page { size: A4; }
  * { box-sizing: border-box; }
  html, body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: Inter, -apple-system, "Segoe UI", sans-serif; color: {{c.TEXT_PRI}};
         background: {{c.BG_PAGE}}; margin: 0; font-size: 11px; }
  .page { padding: 12px 10px; }
  h1 { font-size: 21px; margin: 0; }
  h2 { font-size: 13px; color: {{c.ACCENT}}; border-bottom: 2px solid {{c.ACCENT}}; padding-bottom: 3px; margin: 16px 0 8px; }
  .sub { color: {{c.TEXT_SEC}}; font-size: 11px; margin-top: 2px; }
  .ver { float: right; text-align: right; font-size: 8.5px; color: {{c.TEXT_SEC}}; }
  .read { font-size: 10.5px; line-height: 1.45; margin: 0 0 7px; }
  .key { font-weight: 700; border-left: 3px solid {{c.ACCENT}}; padding: 6px 10px; background: {{c.BG_PANEL}}; border-radius: 0 8px 8px 0; margin: 4px 0 8px; }
  img.chart { width: 100%; border: 1px solid {{c.BORDER}}; border-radius: 8px; background:#fff; }
  .cap { font-size: 8.5px; color: {{c.TEXT_SEC}}; font-style: italic; margin-top: 3px; }
  table { width: 100%; border-collapse: collapse; font-size: 10px; margin-top: 4px; }
  th, td { border: 1px solid {{c.BORDER}}; padding: 3px 6px; text-align: center; }
  th { background: #eef1f6; color: {{c.TEXT_SEC}}; font-weight: 600; } td.lab { text-align: left; font-weight: 600; }
  ul { margin: 4px 0; padding-left: 16px; } li { margin-bottom: 4px; line-height: 1.4; }
  .pbreak { page-break-before: always; }
</style></head>
<body><div class="page">
  <div class="ver">Investigation<br>{{build_date}}</div>
  <h1>Bowler release point &amp; crease use</h1>
  <div class="sub">How Test pace bowlers use the crease and their release point — what the ball-tracking release data can tell us. International Tests only.</div>

  <h2>1 · What data exists, and when</h2>
  <div class="read">Release-point tracking (crease position, release height, release angle) only begins in
    <b>2014</b> and becomes near-complete from <b>2019</b> (~99% by 2022). Release <i>speed</i> is a separate,
    sparse feed (2020+, ~15%). So all release analysis is a <b>modern-era</b> story — earlier careers have no release data.</div>
  <img class="chart" src="{{cov_chart}}">
  <div class="cap">Share of international Test pace balls with release data, by year.</div>
  <div class="read" style="margin-top:8px">Of the six <code>release_*</code> columns, three are usable:
    <b>release_line_unmirrored</b> = crease position (mm from middle stump, absolute — over/round flip the sign);
    <b>release_height</b> ≈ 2.0 m (the release-point height); <b>release_angle</b> ≈ −8° (downward angle).
    <b>release_width</b> has a murky sign convention (use line instead), and <b>release_length</b> is sentinel garbage (−32768).</div>

  <h2>2 · A taller release means more bounce (and a few more wickets)</h2>
  <div class="key">Across {{n_bowlers}} Test pace bowlers, release height correlates with bounce at the stumps
    (r = {{r_hb}}) and, weakly, with wicket rate (r = {{r_hw}}). The tallest-release quartile releases from {{tall_h}} cm,
    gets the ball {{tall_b}} cm past the stumps and takes {{tall_w}} wickets per 100 balls; the shortest-release
    quartile: {{short_h}} cm release, {{short_b}} cm bounce, {{short_w}} per 100.</div>
  <img class="chart" src="{{scatter}}">
  <div class="cap">Each dot is a bowler (≥400 tracked balls); red points labelled. Release height vs how high the ball passes the stumps.</div>

  <h2 class="pbreak">3 · Crease width is tactical, not a wicket driver — but the angle matters</h2>
  <div class="read">How <i>wide</i> of the stumps a bowler releases barely relates to their wicket rate across bowlers
    (r = {{r_cw}}) — it's a stylistic/angle choice, not a quality signal. But <b>within a matchup it changes the angle and the
    chances created.</b> Over the wicket to right-handers:</div>
  <img class="chart" src="{{bucket_chart}}">
  <div class="cap">Over-the-wicket pace vs RHB, split by release distance from the middle stump. Wickets-per-100 scaled ×8 to sit alongside false-shot %.</div>
  <div class="key">Releasing <b>wide</b> of the crease brings the ball back straighter (ends up {{b_wide_line}} cm off the stumps
    vs {{b_tight_line}} cm from a tight release) and creates <b>more</b> — false-shot {{b_wide_false}}% vs {{b_tight_false}}% tight,
    and {{b_wide_wpc}} wickets per 100 vs {{b_tight_wpc}} tight (~14% more).</div>

  <h2>Findings &amp; recommendations</h2>
  <ul>
    <li><b>Report scope is right:</b> release data is modern-era only — show it with an <code>n=</code> / era caveat, never as a career-long trait.</li>
    <li><b>Add release height</b> to the bowler profile as a "bounce" indicator — it's the release dimension that actually predicts bounce (r&nbsp;={{r_hb}}) and slightly, wickets. Pairs with the existing bounce percentile.</li>
    <li><b>Keep crease width as a tactical read</b>, not a quality metric. The valuable angle is <i>within</i> a matchup: wide-of-the-crease over the wicket to RHB is measurably more productive than tight.</li>
    <li><b>Use <code>release_line_unmirrored</code></b> for crease position (verified); ignore <code>release_width</code> (murky) and <code>release_length</code> (garbage).</li>
    <li>Over vs round the wicket sit on opposite sides of the stumps by construction — this is the mechanical cause of the big over/round line shift the profile already flags.</li>
  </ul>
</div></body></html>
"""


if __name__ == "__main__":
    print("->", render())
