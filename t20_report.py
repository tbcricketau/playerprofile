"""
t20_report.py — T20 bowler scouting report (template v0.1).

Reuses the shared report_style (identical cards/CSS to Test/ODI) and the ODI report's variation
tables. T20-specific: phases (Powerplay 1–6 / Middle 7–15 / Death 16–20), league-strength ADJUSTED
economy (the headline number is league-neutral; raw shown alongside), and a "where he's bowled"
panel (balls by league + that league's run-environment effect). Fingerprint + video come next once
T20 peer norms exist.
"""
import os
import datetime
import re

from jinja2 import Template

from t20_profile import build_t20_profile
from photos import get_photo_data_uri
from report import _fig_uri, _html_to_pdf, _country_code
from report_style import REPORT_CSS, theme_ctx, card, headline_cards, f_econ, TEXT_SEC
from odi_report import _variation_tables, _variation_read

REPORT_VERSION = "t20-0.1"


def _phase_read(P):
    ph = {p["phase"]: p for p in P["phases"]}
    if not ph:
        return ""
    top = max(P["phases"], key=lambda p: p["pct_balls"])
    who = P["name"].split(",")[-1].strip() if "," in P["name"] else P["name"]
    bits = [f"<b>{who}</b> bowls most in the <b>{top['phase'].lower()}</b> ({top['pct_balls']:.0f}% of his overs)"]
    if "Death" in ph:
        bits.append(f"and goes at <b>{ph['Death']['econ_adj']:.2f}</b> at the death (league-adjusted)")
    return " ".join(bits) + "."


def _cards(P):
    """The shared 8-card row, but the Economy card shows the league-ADJUSTED economy (raw as sub)."""
    hp = {**P, "economy": P["economy_adj"]}          # headline economy = league-neutral
    out = []
    for lab, val, sub in headline_cards(hp):
        if lab == "Economy" and P["economy"] is not None:
            sub = f"raw {P['economy']:.2f} · lg-adj"
        out.append(card(lab, val, sub))
    return out


def render_t20_report(bowler_id: str, out_dir: str = "reports/t20") -> str:
    P = build_t20_profile(str(bowler_id))
    if P.get("empty"):
        raise ValueError(f"No T20 data for bowler {bowler_id}")

    ctx = {
        "P": P, "code": _country_code(P["team"]),
        "photo_uri": get_photo_data_uri(P["bowler_id"]),
        "cards": _cards(P), "phase_read": _phase_read(P),
        "variation_read": _variation_read(P) if P["is_pace"] else None,
        "var_tables": _variation_tables(P) if P["is_pace"] else None,
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "css": REPORT_CSS, "c": theme_ctx(), "TEXT_SEC": TEXT_SEC,
    }
    nm = P["name"]
    surname, first = ([x.strip() for x in nm.split(",", 1)] if "," in nm
                      else (nm.split()[-1], " ".join(nm.split()[:-1])))
    who = "_".join(re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_") for x in (first, surname) if x) or f"bowler_{bowler_id}"
    btype = "pace" if P["is_pace"] else ("spin" if P["is_spin"] else "bowling")
    out_path = os.path.abspath(os.path.join(out_dir, f"{who}_bowling_{btype}_t20.pdf"))
    os.makedirs(out_dir, exist_ok=True)
    html = Template(_TEMPLATE).render(**ctx)
    with open(out_path[:-4] + ".html", "w", encoding="utf-8") as f:
        f.write(html)
    _html_to_pdf(html, out_path)
    return out_path


_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  @page { size: A4; margin: 0 0 9mm 0;
    @bottom-right { content: counter(page) " / " counter(pages); font-family: Inter, sans-serif; font-size: 8px; color: {{c.TEXT_SEC}}; margin-right: 10mm; }
    @bottom-left { content: "{{P.name}} · T20 bowling scout"; font-family: Inter, sans-serif; font-size: 8px; color: {{c.TEXT_SEC}}; margin-left: 10mm; } }
  {{ css }}
  .page { padding: 14px 16px; }
  h1 { font-size: 21px; }
  .adj { font-size: 8.5px; font-weight: 700; margin-left: 2px; }
</style></head><body><div class="page">

  <div class="header">
    {% if photo_uri %}<img src="{{photo_uri}}">{% else %}<div class="ph">🏏</div>{% endif %}
    <div>
      <h1>{{P.name}} {% if code %}<span class="flag">{{code}}</span>{% endif %}</h1>
      <div class="sub">{{P.primary_type}} · T20 bowling scout
        <span class="pill">{{P.matches}} T20s · {{P.overs|round|int}} overs · {{P.n_leagues}} leagues</span></div>
    </div>
    <div class="ver">{{version}}<br>{{build_date}}</div>
  </div>

  <div class="cards">
    {% for cd in cards %}<div class="card"><div class="lab">{{cd.lab}}</div><div class="val">{{cd.val}}</div>{% if cd.sub %}<div class="csub">{{cd.sub}}</div>{% endif %}</div>{% endfor %}
  </div>
  <div class="cap" style="text-align:left">Economy &amp; strike-rate are pooled across every T20 league he's played, then put on a <b>league-neutral</b> baseline — each league's run environment (rated by how hard it is to bowl there, controlling for who bowls) is removed, so an IPL over and a Super Smash over count the same. His raw economy is shown alongside. His run-environment shift here is <b>{{ '%+.2f'|format(P.env) }}</b> rpo.</div>

  <h2>Phase Profile <span class="sub" style="font-weight:400">(Powerplay 1–6 · Middle 7–15 · Death 16–20)</span></h2>
  {% if phase_read %}<div class="read">{{phase_read|safe}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Phase</th><th>% of overs</th><th>Overs</th><th>Economy</th><th>Adj econ</th><th>Wkts</th><th>SR</th><th>Boundary %</th><th>Dot %</th>{% if P.is_pace %}<th>Avg speed</th>{% endif %}</tr>
    {% for p in P.phases %}
    <tr class="{{ 'hl' if p.phase == 'Death' else '' }}">
      <td class="lab">{{p.phase}}</td><td>{{p.pct_balls|round|int}}%</td><td>{{p.overs|round(1)}}</td>
      <td>{{p.economy|round(2)}}</td><td><b>{{p.econ_adj|round(2)}}</b></td><td>{{p.wickets}}</td>
      <td>{{ p.strike_rate|round(1) if p.strike_rate else '—' }}</td>
      <td>{{p.boundary_pct|round|int}}%</td><td>{{p.dot_pct|round|int}}%</td>
      {% if P.is_pace %}<td>{{ p.avg_speed|round|int if p.avg_speed else '—' }}</td>{% endif %}
    </tr>{% endfor %}
  </table>

  {% if var_tables and var_tables.phase_tbl %}
  <h2>Variations <span class="sub" style="font-weight:400">(slower balls &amp; cutters — what &amp; where)</span></h2>
  {% if variation_read %}<div class="read">{{variation_read|safe}}</div>{% endif %}
  <table class="mtab" style="max-width:640px">
    <tr><th>Variation</th>{% for p in var_tables.phases %}<th>{{p}}</th>{% endfor %}<th>All overs</th></tr>
    {% for row in var_tables.phase_tbl %}
    <tr><td class="lab">{{row.type}}</td>{% for cc in row.cells %}<td>{{cc|round|int}}%</td>{% endfor %}<td>{{row.all|round|int}}%</td></tr>
    {% endfor %}
  </table>
  {% endif %}

  <h2>Where He's Bowled <span class="sub" style="font-weight:400">(the body of work behind the adjusted numbers)</span></h2>
  <table class="mtab" style="max-width:620px">
    <tr><th>League</th><th>Balls</th><th>Overs</th><th>Raw econ</th><th>Wkts</th><th>League run-env</th></tr>
    {% for w in P.where_bowled %}
    <tr><td class="lab">{{w.league}}</td><td>{{w.balls}}</td><td>{{ (w.balls/6)|round|int }}</td><td>{{w.econ|round(2)}}</td><td>{{w.wkts}}</td>
      <td><span class="adj" style="color:{% if w.eff >= 0.15 %}{{c.ACCENT}}{% elif w.eff <= -0.15 %}#9aa3b2{% else %}{{TEXT_SEC}}{% endif %}">{{ '%+.2f'|format(w.eff) }}</span> rpo</td></tr>
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left">League run-env = runs/over that league adds (+) or removes (−) vs the T20 mean, adjusting for who bowls (referencebuilder <code>t20_league_strength.csv</code>). A + league (e.g. IPL) is a tougher place to bowl, so economy there is worth more.</div>

  <div class="note">
    All major men's T20 leagues pooled ({{P.n_leagues}} for him). Phase = Powerplay 1–6 / Middle 7–15 / Death 16–20.
    Economy charges wides + no-balls. Adjusted = raw − league run-environment. {{version}} · {{build_date}}.
  </div>

</div></body></html>
"""
