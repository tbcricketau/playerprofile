"""
t20_report.py — T20 bowler scouting report (template v0.1).

Reuses the shared report_style (identical cards/CSS to Test/ODI) and the ODI report's variation
tables. T20-specific: phases (Powerplay 1–6 / Middle 7–15 / Death 16–20), league-strength ADJUSTED
economy (the headline number is league-neutral; raw shown alongside), and a "where they've bowled"
panel (balls by league + that league's run-environment effect). Fingerprint + video come next once
T20 peer norms exist.
"""
import os
import datetime
import re

from jinja2 import Template

from t20_profile import build_t20_profile
from profile import build_line_zones
from photos import get_photo_data_uri
from report import _fig_uri, _html_to_pdf, _country_code, _fingerprint_cards, _file_url
from report_style import REPORT_CSS, theme_ctx, card, headline_cards, f_econ, TEXT_SEC
from odi_report import _variation_tables, _variation_read, _grid_figs
from cricket_core.charts import pitch_heatmap, beehive

REPORT_VERSION = "t20-1.0"


def _phase_read(P):
    ph = {p["phase"]: p for p in P["phases"]}
    if not ph:
        return ""
    top = max(P["phases"], key=lambda p: p["pct_balls"])
    who = P["name"].split(",")[-1].strip() if "," in P["name"] else P["name"]
    bits = [f"<b>{who}</b> bowls most in the <b>{top['phase'].lower()}</b> ({top['pct_balls']:.0f}% of their overs)"]
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


def _build_t20_player(P, pdf_path, subtitle, target_country=None):
    """T20 video playlists (wickets / powerplay / death / yorkers / slower balls) via the shared
    white-ball builder + clip resolver; writes a modal player + returns {player, lists, playlists}.
    Best-effort — never breaks the report if video/SSO is unavailable."""
    try:
        from cricket_core.video import get_fairplay_sas, build_player_html, write_playlists
        from playlists import build_odi_playlists          # white-ball generic (T20 phase names match)
        get_fairplay_sas(ttl_hours=72)
        built = build_odi_playlists(P, cap=8, target_country=target_country)
        pls, meta = built["playlists"], built.get("meta")
        write_playlists(pdf_path[:-4] + ".playlists.json", pls, meta=meta)
        if not pls:
            return {"lists": {}}
        player_path = pdf_path[:-4] + ".player.html"
        build_player_html(pls, player_path, title=P["name"], subtitle=subtitle)
        return {"player": _file_url(player_path), "lists": {k: True for k in pls}, "playlists": pls}
    except Exception:
        return {"lists": {}}


def render_t20_report(bowler_id: str, out_dir: str = "reports/t20",
                      with_playlists: bool = True, target_country: str | None = "Australia") -> str:
    P = build_t20_profile(str(bowler_id))
    if P.get("empty"):
        raise ValueError(f"No T20 data for bowler {bowler_id}")

    legal = [r for r in P["raw"] if r["is_legal"]]
    figs = _grid_figs(legal, P.get("off_pace_kph")) if P["is_pace"] else {}

    nm = P["name"]
    surname, first = ([x.strip() for x in nm.split(",", 1)] if "," in nm
                      else (nm.split()[-1], " ".join(nm.split()[:-1])))
    who = "_".join(re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_") for x in (first, surname) if x) or f"bowler_{bowler_id}"
    btype = "pace" if P["is_pace"] else ("spin" if P["is_spin"] else "bowling")
    out_path = os.path.abspath(os.path.join(out_dir, f"{who}_bowling_{btype}_t20.pdf"))
    os.makedirs(out_dir, exist_ok=True)

    video = (_build_t20_player(P, out_path, subtitle=f"{P['name']} — T20 bowling scout",
                               target_country=target_country) if with_playlists else {})
    ctx = {
        "P": P, "figs": figs, "code": _country_code(P["team"]),
        "photo_uri": get_photo_data_uri(P["bowler_id"]),
        "cards": _cards(P), "phase_read": _phase_read(P),
        "fingerprint_cards": _fingerprint_cards(P), "video": video,
        "variation_read": _variation_read(P) if P["is_pace"] else None,
        "var_tables": _variation_tables(P) if P["is_pace"] else None,
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "css": REPORT_CSS, "c": theme_ctx(), "TEXT_SEC": TEXT_SEC,
    }
    html = Template(_TEMPLATE).render(**ctx)
    if video.get("playlists"):
        from cricket_core.video import inline_player_snippet
        snippet = "<!--PLAYER_SNIPPET_START-->" + inline_player_snippet(video["playlists"]) + "<!--PLAYER_SNIPPET_END-->"
        html = html.replace("</body>", snippet + "</body>")
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
  .grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; align-items: start; }
  .grid4 .fig { text-align: center; }
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
  <div class="cap" style="text-align:left">Economy &amp; strike-rate are pooled across every T20 league they've played, then put on a <b>league-neutral</b> baseline — each league's run environment (rated by how hard it is to bowl there, controlling for who bowls) is removed, so an IPL over and a Super Smash over count the same. Their raw economy is shown alongside. Their run-environment shift here is <b>{{ '%+.2f'|format(P.env) }}</b> rpo.</div>

  {% if fingerprint_cards %}
  <h2>Bowling Fingerprint <span class="sub" style="font-weight:400">(percentile vs T20 peers)</span></h2>
  <div class="fpgrid">
    {% for f in fingerprint_cards %}
    <div class="fpcard">
      <div class="lab">{{f.label}}</div>
      <div class="pct" style="color:{{f.colour}}">{{f.pct_txt}}</div>
      <img src="{{f.img}}">
      <div class="sub">{{f.disp}} · {{f.peer}}</div>
    </div>
    {% endfor %}
  </div>
  <div class="cap" style="text-align:left">Percentile within same-type <b>T20</b> peers (grey = the peer distribution, line = this bowler). Release/crease vs hand × pace/spin; movement/speed/repeatability vs pace/spin. These are skill/physical traits, so — unlike economy — they carry across leagues without a strength adjustment. <b>Repeatability</b> = length consistency over their stock band (high = more metronomic).</div>
  {% endif %}

  <h2>Phase Profile <span class="sub" style="font-weight:400">(Powerplay 1–6 · Middle 7–15 · Death 16–20)</span>{% if video.lists.wickets %}<a class="vlink" data-pl="wickets" href="{{video.player}}#wickets">▶ wickets</a>{% endif %}</h2>
  {% if phase_read %}<div class="read">{{phase_read|safe}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Phase</th><th>% of overs</th><th>Overs</th><th>Economy</th><th>Adj econ</th><th>Wkts</th><th>SR</th><th>Boundary %</th><th>Dot %</th>{% if P.is_pace %}<th>Avg speed</th>{% endif %}</tr>
    {% for p in P.phases %}
    <tr class="{{ 'hl' if p.phase == 'Death' else '' }}">
      <td class="lab">{{p.phase}}</td><td>{{p.pct_balls|round|int}}%</td><td>{{p.overs|round(1)}}</td>
      <td>{{p.economy|round(2)}}</td>
      <td><b>{{p.econ_adj|round(2)}}</b>{% if p.econ_pctl is not none %}<span class="adj" style="color:{% if p.econ_pctl >= 60 %}{{c.ACCENT}}{% elif p.econ_pctl <= 33 %}#9aa3b2{% else %}{{TEXT_SEC}}{% endif %}">P{{p.econ_pctl}}</span>{% endif %}</td>
      <td>{{p.wickets}}{% if p.wkt_pctl is not none %}<span class="adj" style="color:{% if p.wkt_pctl >= 60 %}{{c.ACCENT}}{% elif p.wkt_pctl <= 33 %}#9aa3b2{% else %}{{TEXT_SEC}}{% endif %}">P{{p.wkt_pctl}}</span>{% endif %}</td>
      <td>{{ p.strike_rate|round(1) if p.strike_rate else '—' }}</td>
      <td>{{p.boundary_pct|round|int}}%</td><td>{{p.dot_pct|round|int}}%</td>
      {% if P.is_pace %}<td>{{ p.avg_speed|round|int if p.avg_speed else '—' }}</td>{% endif %}
    </tr>{% endfor %}
  </table>
  <div class="cap" style="text-align:left">Blue <b>P##</b> = percentile vs T20 {{ 'pace' if P.is_pace else 'spin' }} peers in that phase, on the <b>league-adjusted</b> economy (higher = harder to score off) and wicket rate (grey = bottom third). So the badge answers "is their death economy good <em>for the death, across leagues</em>?", not just the raw figure.</div>

  {% if P.deepdive and P.deepdive.overall %}
  {% set o = P.deepdive.overall %}
  <h2>Length &amp; Variation Deep-Dive <span class="sub" style="font-weight:400">(yorkers, bouncers &amp; slower balls — how often, what line)</span>{% if video.lists.slower_balls %}<a class="vlink" data-pl="slower_balls" href="{{video.player}}#slower_balls">▶ slower balls</a>{% endif %}</h2>
  <div style="font-weight:700;font-size:10.5px;margin:4px 0 3px">How often, by phase <span class="sub" style="font-weight:400">— % of that phase's legal balls</span></div>
  <table class="mtab" style="max-width:700px">
    <tr><th>Phase</th><th>Yorker / full</th><th>Bouncer / short</th><th>Slower ball</th><th>Slower yorker</th><th>Slower bouncer</th><th>Econ</th></tr>
    {% for p in P.deepdive.phases %}
    <tr class="{{ 'hl' if p.phase == 'Death' else '' }}"><td class="lab">{{p.phase}}</td>
      <td>{{p.yorker_pct|round|int}}%</td><td>{{p.bouncer_pct|round|int}}%</td><td>{{p.slower_pct|round|int}}%</td>
      <td>{{p.slower_yorker.pct|round(1)}}%</td><td>{{p.slower_bouncer.pct|round(1)}}%</td><td>{{p.economy|round(2)}}</td></tr>
    {% endfor %}
    <tr style="font-weight:700"><td class="lab">Overall</td><td>{{o.yorker_pct|round|int}}%</td><td>{{o.bouncer_pct|round|int}}%</td><td>{{o.slower_pct|round|int}}%</td><td>{{o.slower_yorker.pct|round(1)}}%</td><td>{{o.slower_bouncer.pct|round(1)}}%</td><td>{{o.economy|round(2)}}</td></tr>
  </table>
  <div class="grid2">
    <div class="dd"><h3>Yorker line{% if video.lists.yorkers %}<a class="vlink tiny" data-pl="yorkers" href="{{video.player}}#yorkers">▶</a>{% endif %}</h3>
      {% if o.yorker_line.bands %}{% for b in o.yorker_line.bands %}<div class="row"><span>{{b.band}}</span><b>{{b.pct|round|int}}%</b></div>{% endfor %}
      <div class="cap" style="text-align:left;margin-top:3px">Full balls only ({{o.yorker_line.n}}), by pitch line.{% if o.slower_yorker.n >= 6 %} Slower-ball yorkers <b>{{o.slower_yorker.pct|round(1)}}%</b> ({{o.slower_yorker.n}}){% if o.slower_yorker.line.top_band %}, mostly {{o.slower_yorker.line.top_band|lower}}{% endif %}{% if video.lists.slower_yorkers %} <a class="vlink tiny" data-pl="slower_yorkers" href="{{video.player}}#slower_yorkers">▶</a>{% endif %}.{% endif %}</div>
      {% else %}<div class="sub" style="font-size:9.5px">Too few full balls to read ({{o.yorker_line.n}}).</div>{% endif %}</div>
    <div class="dd"><h3>Bouncer line{% if video.lists.bouncers %}<a class="vlink tiny" data-pl="bouncers" href="{{video.player}}#bouncers">▶</a>{% endif %}</h3>
      {% if o.bouncer_line.bands %}{% for b in o.bouncer_line.bands %}<div class="row"><span>{{b.band}}</span><b>{{b.pct|round|int}}%</b></div>{% endfor %}
      <div class="cap" style="text-align:left;margin-top:3px">Short balls only ({{o.bouncer_line.n}}), line at the stumps.{% if o.slower_bouncer.n >= 6 %} Slower-ball bouncers <b>{{o.slower_bouncer.pct|round(1)}}%</b> ({{o.slower_bouncer.n}}){% if o.slower_bouncer.line.top_band %}, mostly {{o.slower_bouncer.line.top_band|lower}}{% endif %}{% if video.lists.slower_bouncers %} <a class="vlink tiny" data-pl="slower_bouncers" href="{{video.player}}#slower_bouncers">▶</a>{% endif %}.{% endif %}</div>
      {% else %}<div class="sub" style="font-size:9.5px">Too few bouncers to read ({{o.bouncer_line.n}}).</div>{% endif %}</div>
  </div>
  {% endif %}

  {% if P.vs_hand %}
  <h2>Match-ups <span class="sub" style="font-weight:400">(each hand, split over vs round the wicket)</span></h2>
  <table class="mtab" style="max-width:680px">
    <tr><th>Batter</th><th>Balls</th><th>Round %</th><th>Economy</th><th>Wkts</th><th>Average</th><th>SR</th><th>Boundary %</th></tr>
    {% for lab, s in P.vs_hand.items() %}
    <tr class="hl"><td class="lab">{{lab}}</td><td>{{s.balls}}</td><td><b>{{ s.round_pct|round|int if s.round_pct is not none else '—' }}%</b></td><td>{{s.economy|round(2)}}</td><td>{{s.wickets}}</td>
      <td>{{ s.average|round(1) if s.average else '—' }}</td><td>{{ s.strike_rate|round(1) if s.strike_rate else '—' }}</td><td>{{s.boundary_pct|round|int}}%</td></tr>
    {% for ang, sub in [("· over the wkt", s.over), ("· round the wkt", s.round)] %}
    {% if sub and sub.balls >= 30 %}<tr><td class="lab" style="padding-left:14px;font-weight:400;color:{{c.TEXT_SEC}}">{{ang}}</td><td>{{sub.balls}}</td><td></td><td>{{sub.economy|round(2)}}</td><td>{{sub.wickets}}</td>
      <td>{{ sub.average|round(1) if sub.average else '—' }}</td><td>{{ sub.strike_rate|round(1) if sub.strike_rate else '—' }}</td><td>{{sub.boundary_pct|round|int}}%</td></tr>{% endif %}
    {% endfor %}
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left">Round % = share of their balls to that hand bowled from round the wicket. Sub-rows split each hand over vs round (shown when ≥30 balls).</div>
  {% endif %}

  <h2>Where They Bowl <span class="sub" style="font-weight:400">(pitch map + beehive · over vs round · stock vs slower)</span></h2>
  {% for plabel, pk in [("On pace (stock speed)", "on"), ("Off pace (slower balls)", "off")] %}
  <div style="font-weight:700;font-size:10px;margin:8px 0 2px;color:{{c.ACCENT}}">{{plabel}}</div>
  <div class="grid4">
    {% for side, sk in [("Over", "over"), ("Round", "round")] %}
    {% for kind, suf in [("pitch", "pitch"), ("at stumps", "bee")] %}
    <div class="fig">{% if figs[pk~"_"~sk~"_"~suf] %}<img class="chart" src="{{figs[pk~"_"~sk~"_"~suf]}}"><div class="cap">{{side}} — {{kind}}{% if suf == "pitch" %} · {{figs[pk~"_"~sk~"_pct"]}}% of balls{% endif %}</div>{% else %}<div class="cap" style="padding:26px 4px;color:{{c.TEXT_SEC}}">{{side}} — {{kind}}<br>— too few —</div>{% endif %}</div>
    {% endfor %}
    {% endfor %}
  </div>
  {% endfor %}
  <div class="cap" style="text-align:left">The % on each pitch map is that slice's share of all legal balls (e.g. over the wicket, on pace). Off pace = slower-ball variations.</div>

  <h2>Where They've Played <span class="sub" style="font-weight:400">(the body of work behind the adjusted numbers)</span></h2>
  <table class="mtab" style="max-width:620px">
    <tr><th>League</th><th>Balls</th><th>Overs</th><th>Raw econ</th><th>Wkts</th><th>League run-env</th></tr>
    {% for w in P.where_bowled %}
    <tr><td class="lab">{{w.league}}</td><td>{{w.balls}}</td><td>{{ (w.balls/6)|round|int }}</td><td>{{w.econ|round(2)}}</td><td>{{w.wkts}}</td>
      <td><span class="adj" style="color:{% if w.eff >= 0.15 %}{{c.ACCENT}}{% elif w.eff <= -0.15 %}#9aa3b2{% else %}{{TEXT_SEC}}{% endif %}">{{ '%+.2f'|format(w.eff) }}</span> rpo</td></tr>
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left">League run-env = runs/over that league adds (+) or removes (−) vs the T20 mean, adjusting for who bowls (referencebuilder <code>t20_league_strength.csv</code>). A + league (e.g. IPL) is a tougher place to bowl, so economy there is worth more.</div>

  <div class="note">
    All major men's T20 leagues pooled ({{P.n_leagues}} for them). Phase = Powerplay 1–6 / Middle 7–15 / Death 16–20.
    Economy charges wides + no-balls. Adjusted = raw − league run-environment. {{version}} · {{build_date}}.
  </div>

</div></body></html>
"""
