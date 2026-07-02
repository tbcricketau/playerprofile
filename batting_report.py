"""
batting_report.py — render a one-batter scouting PDF (Test / red-ball).

First pass: headline + the novel share-of-runs "match impact" metric, how they
score (shot groups, areas, wagon), how they fare vs each bowler type + weaknesses,
and how they get out.  Reuses report.py's Chromium PDF machinery and the Opta theme.

    from batting_report import render_batting_report
    render_batting_report("940135")           # Steve Smith
"""
import datetime
import os
import re

from jinja2 import Template

from version import REPORT_VERSION
from batter_profile import build_batter_profile
from photos import get_photo_data_uri
from ludis_cricket.charts import wagon_wheel_zones
from report import (
    _fig_uri, _html_to_pdf, _country_code,
    BG_PAGE, BG_PANEL, TEXT_PRI, TEXT_SEC, ACCENT, DANGER, BORDER,
)


def _fmt(v, spec=".0f", suffix=""):
    if v is None:
        return "—"
    try:
        return f"{float(v):{spec}}{suffix}"
    except (TypeError, ValueError):
        return "—"


def _cards(P: dict) -> list:
    s = P.get("share") or {}
    return [
        ("Runs", _fmt(P["runs"]), f"{P['n_out']} dismissals"),
        ("Average", _fmt(P["average"], ".1f"), f"SR {_fmt(P['strike_rate'], '.1f')}"),
        ("Innings", _fmt(s.get("innings")), "batted"),
        ("Share of team runs", _fmt(s.get("team_share_career"), ".1f", "%"), "career, off the bat"),
        ("Carries the innings", _fmt(s.get("carried_rate"), ".0f", "%"), "innings with ≥25% of team"),
    ]


def _impact_read(P: dict) -> str:
    s = P.get("share")
    if not s:
        return ""
    tc, tm = s["team_share_career"], s["team_share_median"]
    lead = (f"Makes <b>{tc:.1f}%</b> of his team's runs over a career (typical innings "
            f"{tm:.1f}%), and <b>{_fmt(s['match_share_career'], '.1f', '%')}</b> of all runs in his matches")
    carry = (f"; carries the innings (≥25% of the team's runs) {s['carried_rate']:.0f}% of the time"
             + (f", and dominates (≥40%) {s['big_rate']:.0f}%" if s["big_rate"] >= 3 else ""))
    return lead + carry + "."


def _vs_rows(P: dict) -> list:
    out = []
    for label, key in (("Pace", "pace"), ("Spin", "spin")):
        v = P["vs"].get(key)
        if not v:
            continue
        out.append((label, _fmt(v["avg"], ".1f"), _fmt(v["sr"], ".1f"),
                    _fmt(v["false_pct"], ".1f", "%"), _fmt(v["dismissal_per100"], ".2f"),
                    f"{v['balls']:,}"))
    # detailed types under each
    for t, v in sorted(P["vs_detail"].items(), key=lambda kv: -kv[1]["balls"]):
        out.append(("  " + t, _fmt(v["avg"], ".1f"), _fmt(v["sr"], ".1f"),
                    _fmt(v["false_pct"], ".1f", "%"), _fmt(v["dismissal_per100"], ".2f"),
                    f"{v['balls']:,}"))
    return out


def _vs_read(P: dict) -> str:
    vs = P["vs"]
    if "pace" not in vs or "spin" not in vs:
        return ""
    p, s = vs["pace"], vs["spin"]
    if not (p["avg"] and s["avg"]):
        return ""
    if P["weakness"] == "spin":
        return (f"Noticeably weaker against spin (averages {s['avg']:.0f} vs {p['avg']:.0f} against pace; "
                f"falser shot {s['false_pct']:.0f}% vs {p['false_pct']:.0f}%) — attack him with spin.")
    if P["weakness"] == "pace":
        return (f"Stronger against spin ({s['avg']:.0f}) than pace ({p['avg']:.0f}); "
                f"pace — especially the quicks — is the more productive line of attack.")
    return f"Handles both similarly (pace {p['avg']:.0f}, spin {s['avg']:.0f})."


def _shot_rows(P: dict) -> list:
    return [(g["name"], f"{g['runs']:.0f}", f"{g['runs_pct']:.0f}%", str(g["balls"]), str(g["outs"]))
            for g in P["shot_groups"]]


def _dir_read(P: dict) -> str:
    d = P.get("dir_pct")
    if not d:
        return ""
    top = max(d, key=d.get)
    side = {"off": "the off side", "leg": "the leg side", "straight": "straight down the ground"}[top]
    return f"Scores most of his runs through {side} ({d[top]:.0f}%; off {d['off']:.0f}% · leg {d['leg']:.0f}% · straight {d['straight']:.0f}%)."


def _dismissal_read(P: dict) -> str:
    dis, n = P["dismissals"], P["n_dismissals"]
    if not n:
        return ""
    top = dis.most_common(1)[0]
    bt = P["dismissal_bowler_type"].most_common(1)
    btxt = f"; most often to {bt[0][0].lower()} ({bt[0][1]})" if bt else ""
    return f"Most often out <b>{top[0].lower()}</b> ({top[1] / n * 100:.0f}% of dismissals){btxt}."


def _narrative(P: dict) -> dict:
    themes, strengths, weak = [], [], []
    hand = "left-hand bat" if P["is_lhb"] else "right-hand bat"
    themes.append(f"{hand}, averaging {_fmt(P['average'], '.1f')} at a strike rate of {_fmt(P['strike_rate'], '.1f')}.")
    s = P.get("share")
    if s:
        themes.append(f"Carries a big share of the batting — {s['team_share_career']:.1f}% of team runs.")
    if P.get("dir_pct"):
        d = P["dir_pct"]
        top = max(d, key=d.get)
        themes.append(f"Scores mainly through {'the off side' if top=='off' else 'the leg side' if top=='leg' else 'the V'} ({d[top]:.0f}%).")
    if P["shot_groups"]:
        g = P["shot_groups"][0]
        strengths.append(f"Main scoring shot is the {g['name'].lower()} ({g['runs_pct']:.0f}% of runs).")
    vsr = _vs_read(P)
    if vsr:
        (weak if P["weakness"] == "spin" else strengths).append(vsr)
    if P["dismissals"]:
        weak.append(_dismissal_read(P))
    return {"themes": themes, "strengths": strengths, "weak": weak}


def render_batting_report(batter_id: str, out_dir: str = "reports") -> str:
    P = build_batter_profile(batter_id)
    figs = {}
    try:
        figs["wagon"] = _fig_uri(
            wagon_wheel_zones(P["raw"], metric="runs", title="", n_sectors=8, is_lhb=P["is_lhb"]),
            w=500, h=430)
    except Exception:
        figs["wagon"] = ""

    ctx = {
        "P": P, "code": _country_code(P["team"]),
        "photo_uri": get_photo_data_uri(P["batter_id"]),
        "hand_label": "LHB" if P["is_lhb"] else "RHB",
        "cards": _cards(P), "impact_read": _impact_read(P),
        "vs_rows": _vs_rows(P), "vs_read": _vs_read(P),
        "shot_rows": _shot_rows(P), "dir_read": _dir_read(P),
        "dismissal_read": _dismissal_read(P),
        "dismissals": P["dismissals"].most_common(6),
        "narrative": _narrative(P), "figs": figs,
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "c": dict(BG_PAGE=BG_PAGE, BG_PANEL=BG_PANEL, TEXT_PRI=TEXT_PRI, TEXT_SEC=TEXT_SEC,
                  ACCENT=ACCENT, DANGER=DANGER, BORDER=BORDER),
    }
    html = Template(_TEMPLATE).render(**ctx)

    def _slug(s):
        return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    nm = P["name"]
    if "," in nm:
        surname, first = (x.strip() for x in nm.split(",", 1))
    else:
        parts = nm.split()
        first, surname = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", nm)
    who = "_".join(x for x in (_slug(first), _slug(surname)) if x) or f"batter_{batter_id}"
    hand_tag = "lhb" if P["is_lhb"] else "rhb"
    out_path = os.path.abspath(os.path.join(out_dir, f"{who}_batting_test_{hand_tag}.pdf"))
    os.makedirs(out_dir, exist_ok=True)
    _html_to_pdf(html, out_path)
    return out_path


_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  @page { size: A4; }
  * { box-sizing: border-box; }
  html, body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: Inter, -apple-system, "Segoe UI", sans-serif; color: {{c.TEXT_PRI}};
         background: {{c.BG_PAGE}}; margin: 0; padding: 0; font-size: 11px; }
  .page { padding: 6px 4px; }
  h1 { font-size: 24px; margin: 0; }
  h2 { font-size: 14px; color: {{c.ACCENT}}; border-bottom: 2px solid {{c.ACCENT}};
       padding-bottom: 3px; margin: 20px 0 9px; }
  .sub { color: {{c.TEXT_SEC}}; font-size: 11px; }
  .flag { font-size: 12px; font-weight: 700; color: #fff; background: {{c.ACCENT}};
          padding: 2px 7px; border-radius: 6px; vertical-align: middle; letter-spacing:.05em; }
  .header { display: flex; gap: 16px; align-items: center; }
  .header img { width: 84px; height: 84px; object-fit: cover; border-radius: 10px; }
  .ph { width: 84px; height: 84px; border-radius: 10px; background: #1e2530; color:#555;
        display:flex; align-items:center; justify-content:center; font-size: 34px; }
  .ver { margin-left: auto; align-self: flex-start; text-align: right; font-size: 8.5px; color: {{c.TEXT_SEC}}; line-height: 1.3; }
  .cards { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 10px; }
  .card { background: {{c.BG_PANEL}}; border: 1px solid {{c.BORDER}}; border-radius: 8px;
          padding: 8px 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
  .card .lab { color: {{c.TEXT_SEC}}; font-size: 9px; text-transform: uppercase; letter-spacing:.04em; }
  .card .val { font-size: 18px; font-weight: 700; margin-top: 2px; }
  .card .csub { color: {{c.TEXT_SEC}}; font-size: 9px; margin-top: 2px; }
  .summary { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-top: 10px; }
  .sbox { background: {{c.BG_PANEL}}; border: 1px solid {{c.BORDER}}; border-radius: 8px; padding: 10px 12px; }
  .sbox h3 { margin: 0 0 6px; font-size: 11px; text-transform: uppercase; letter-spacing:.05em; }
  .sbox ul { margin: 0; padding-left: 15px; } .sbox li { margin-bottom: 4px; line-height: 1.35; }
  .read { font-size: 10.5px; margin: 0 0 7px; line-height: 1.4; }
  .impact { font-weight: 700; border-left: 3px solid {{c.ACCENT}}; padding: 6px 10px; background: {{c.BG_PANEL}};
            border-radius: 0 8px 8px 0; }
  .grid2 { display: grid; grid-template-columns: 1.2fr 1fr; gap: 12px; align-items: start; }
  .mtab { width: 100%; border-collapse: collapse; font-size: 10px; }
  .mtab th, .mtab td { border: 1px solid {{c.BORDER}}; padding: 3px 6px; text-align: center; }
  .mtab th { background: #eef1f6; color: {{c.TEXT_SEC}}; font-weight: 600; }
  .mtab td.lab { text-align: left; font-weight: 600; }
  img.wag { width: 96%; display: block; margin: 0 auto; border: 1px solid {{c.BORDER}}; border-radius: 8px; background:#fff; }
  .cap { font-size: 8.5px; color: {{c.TEXT_SEC}}; font-style: italic; text-align:center; margin-top: 3px; }
</style></head>
<body><div class="page">

  <div class="header">
    {% if photo_uri %}<img src="{{photo_uri}}">{% else %}<div class="ph">🏏</div>{% endif %}
    <div>
      <h1>{{P.name}} {% if code %}<span class="flag">{{code}}</span>{% endif %}</h1>
      <div class="sub">{{P.team}} · {{hand_label}} · Batting profile (Test)</div>
    </div>
    <div class="ver">v{{version}}<br>{{build_date}}</div>
  </div>

  <div class="cards">
    {% for lab, val, sub in cards %}
      <div class="card"><div class="lab">{{lab}}</div><div class="val">{{val}}</div>
      {% if sub %}<div class="csub">{{sub}}</div>{% endif %}</div>
    {% endfor %}
  </div>

  <div class="summary">
    <div class="sbox"><h3 style="color:{{c.ACCENT}}">Common themes</h3><ul>
      {% for t in narrative.themes %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
    <div class="sbox"><h3 style="color:#15803d">Strengths</h3><ul>
      {% for t in narrative.strengths %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
    <div class="sbox"><h3 style="color:{{c.DANGER}}">Weaknesses / how to get him</h3><ul>
      {% for t in narrative.weak %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
  </div>

  {% if impact_read %}
  <h2>Match Impact <span class="sub" style="font-weight:400">(share of runs)</span></h2>
  <div class="read impact">{{impact_read|safe}}</div>
  <div class="cap" style="text-align:left">Share = the batter's off-the-bat runs ÷ his team's off-the-bat runs (career = volume-weighted; typical = median per innings). Match share is vs both teams' runs.</div>
  {% endif %}

  <h2>Against Each Bowler Type</h2>
  {% if vs_read %}<div class="read impact">{{vs_read|safe}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Bowler type</th><th>Average</th><th>Strike rate</th><th>False-shot %</th><th>Dismissals / 100</th><th>Balls</th></tr>
    {% for lab, avg, sr, fs, dis, balls in vs_rows %}
    <tr><td class="lab">{{lab}}</td><td>{{avg}}</td><td>{{sr}}</td><td>{{fs}}</td><td>{{dis}}</td><td>{{balls}}</td></tr>
    {% endfor %}
  </table>

  <h2>How He Scores</h2>
  <div class="grid2">
    <div>
      {% if dir_read %}<div class="read">{{dir_read|safe}}</div>{% endif %}
      <table class="mtab">
        <tr><th>Shot group</th><th>Runs</th><th>% runs</th><th>Balls</th><th>Dismissals</th></tr>
        {% for name, runs, rpct, balls, outs in shot_rows %}
        <tr><td class="lab">{{name}}</td><td>{{runs}}</td><td>{{rpct}}</td><td>{{balls}}</td><td>{{outs}}</td></tr>
        {% endfor %}
      </table>
    </div>
    <div>
      {% if figs.wagon %}<img class="wag" src="{{figs.wagon}}"><div class="cap">Where he scores — runs by area (mirrored for a left-hander).</div>{% endif %}
    </div>
  </div>

  <h2>How He Gets Out</h2>
  {% if dismissal_read %}<div class="read">{{dismissal_read|safe}}</div>{% endif %}
  <table class="mtab" style="max-width:420px">
    <tr><th>Mode</th><th>Count</th><th>%</th></tr>
    {% for mode, cnt in dismissals %}
    <tr><td class="lab">{{mode}}</td><td>{{cnt}}</td><td>{{ (cnt / P.n_dismissals * 100) | round | int }}%</td></tr>
    {% endfor %}
  </table>

</div></body></html>
"""
