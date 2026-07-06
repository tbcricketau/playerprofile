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
from profile import build_line_zones
from photos import get_photo_data_uri
from report import _fig_uri, _html_to_pdf, _country_code, _fingerprint_cards, _file_url
from report_style import REPORT_CSS, theme_ctx, card, headline_cards, f_econ, TEXT_SEC
from odi_report import _variation_tables, _variation_read
from ludis_cricket.charts import pitch_heatmap, beehive

REPORT_VERSION = "t20-1.0"


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


def _build_t20_player(P, pdf_path, subtitle, target_country=None):
    """T20 video playlists (wickets / powerplay / death / yorkers / slower balls) via the shared
    white-ball builder + clip resolver; writes a modal player + returns {player, lists, playlists}.
    Best-effort — never breaks the report if video/SSO is unavailable."""
    try:
        from ludis_cricket.video import get_fairplay_sas, build_player_html, write_playlists
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
    lz = build_line_zones("All")
    figs = {}
    try:
        figs["pitch"] = _fig_uri(pitch_heatmap(legal, value="count", title=""), w=430, h=440)
        figs["beehive"] = _fig_uri(beehive(legal, metric="wickets", title="", line_zones=lz), w=380, h=400)
    except Exception:
        pass

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
        from ludis_cricket.video import inline_player_snippet
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
  <div class="cap" style="text-align:left">Percentile within same-type <b>T20</b> peers (grey = the peer distribution, line = this bowler). Release/crease vs hand × pace/spin; movement/speed/repeatability vs pace/spin. These are skill/physical traits, so — unlike economy — they carry across leagues without a strength adjustment. <b>Repeatability</b> = length consistency over his stock band (high = more metronomic).</div>
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
  <div class="cap" style="text-align:left">Blue <b>P##</b> = percentile vs T20 {{ 'pace' if P.is_pace else 'spin' }} peers in that phase, on the <b>league-adjusted</b> economy (higher = harder to score off) and wicket rate (grey = bottom third). So the badge answers "is his death economy good <em>for the death, across leagues</em>?", not just the raw figure.</div>

  {% if P.is_pace and (P.powerplay or P.death) %}
  <h2>Phase Deep-Dives</h2>
  <div class="grid2">
    {% if P.powerplay %}<div class="dd"><h3>Powerplay (overs 1–6){% if video.lists.powerplay %}<a class="vlink tiny" data-pl="powerplay" href="{{video.player}}#powerplay">▶</a>{% endif %}</h3>
      <div class="row"><span>Economy</span><b>{{P.powerplay.economy|round(2)}}</b></div>
      <div class="row"><span>Wickets ({{ (P.powerplay.wkt_rate)|round(1) }}/100)</span><b>{{P.powerplay.wickets}}</b></div>
      {% if P.powerplay.swing_in_pct is not none %}<div class="row"><span>Swings (in / out)</span><b>{{P.powerplay.swing_in_pct|round|int}}% / {{P.powerplay.swing_out_pct|round|int}}%</b></div>{% endif %}
      <div class="row"><span>Hard length (6–8.5m)</span><b>{{P.powerplay.hard_length_pct|round|int}}%</b></div>
      <div class="row"><span>Avg speed</span><b>{{ P.powerplay.avg_speed|round|int if P.powerplay.avg_speed else '—' }} kph</b></div>
    </div>{% endif %}
    {% if P.death and P.death.overall %}<div class="dd"><h3>Death (overs 16–20){% if video.lists.death %}<a class="vlink tiny" data-pl="death" href="{{video.player}}#death">▶</a>{% endif %}</h3>
      <div class="row"><span>Economy</span><b>{{P.death.overall.economy|round(2)}}</b></div>
      <div class="row"><span>Yorker / very full</span><b>{{P.death.overall.yorker_pct|round|int}}%</b></div>
      <div class="row"><span>Slower-ball variations</span><b>{{P.death.overall.slower_pct|round|int}}%</b></div>
      <div class="row"><span>Boundary %</span><b>{{P.death.overall.boundary_pct|round|int}}%</b></div>
    </div>{% endif %}
  </div>
  {% endif %}

  {% if P.yorker_line and (P.yorker_line.death.bands or P.yorker_line.overall.bands) %}
  <div style="font-weight:700;font-size:10.5px;margin:10px 0 3px">Yorker line
    <span class="sub" style="font-weight:400">— where he aims the full ball ("leg-stump yorker vs the wide hole")</span>{% if video.lists.yorkers %}<a class="vlink tiny" data-pl="yorkers" href="{{video.player}}#yorkers">▶</a>{% endif %}</div>
  <table class="mtab" style="max-width:660px">
    <tr><th>When full</th><th>Wide (hole)</th><th>Off / channel</th><th>At the stumps</th><th>Leg / straight</th><th>Balls</th></tr>
    {% for lbl, s in [("Death (16–20)", P.yorker_line.death), ("All overs", P.yorker_line.overall)] %}
    {% if s.bands %}<tr><td class="lab">{{lbl}}{% if s.thin %} <span class="sub" style="font-weight:400">· small n</span>{% endif %}</td>
      {% for b in s.bands %}<td>{{b.pct|round|int}}%</td>{% endfor %}<td>{{s.n}}</td></tr>{% endif %}
    {% endfor %}
  </table>
  {% endif %}

  {% if var_tables and var_tables.phase_tbl %}
  <h2>Variations <span class="sub" style="font-weight:400">(slower balls &amp; cutters — what &amp; where)</span>{% if video.lists.slower_balls %}<a class="vlink" data-pl="slower_balls" href="{{video.player}}#slower_balls">▶ slower balls</a>{% endif %}</h2>
  {% if variation_read %}<div class="read">{{variation_read|safe}}</div>{% endif %}
  <table class="mtab" style="max-width:640px">
    <tr><th>Variation</th>{% for p in var_tables.phases %}<th>{{p}}</th>{% endfor %}<th>All overs</th></tr>
    {% for row in var_tables.phase_tbl %}
    <tr><td class="lab">{{row.type}}</td>{% for cc in row.cells %}<td>{{cc|round|int}}%</td>{% endfor %}<td>{{row.all|round|int}}%</td></tr>
    {% endfor %}
  </table>
  {% endif %}

  <h2>Where He Bowls</h2>
  <div class="grid2">
    {% if figs.pitch %}<div class="fig"><img class="chart" src="{{figs.pitch}}"><div class="cap">Pitch map — where he lands the ball (all deliveries).</div></div>{% endif %}
    {% if figs.beehive %}<div class="fig"><img class="chart" src="{{figs.beehive}}"><div class="cap">At the stumps — where wicket balls pass the stumps.</div></div>{% endif %}
  </div>

  {% if P.vs_hand %}
  <h2>Match-ups</h2>
  <table class="mtab" style="max-width:640px">
    <tr><th>Batter</th><th>Balls</th><th>Economy</th><th>Wkts</th><th>Average</th><th>SR</th><th>Boundary %</th></tr>
    {% for lab, s in P.vs_hand.items() %}
    <tr><td class="lab">{{lab}}</td><td>{{s.balls}}</td><td>{{s.economy|round(2)}}</td><td>{{s.wickets}}</td>
      <td>{{ s.average|round(1) if s.average else '—' }}</td><td>{{ s.strike_rate|round(1) if s.strike_rate else '—' }}</td><td>{{s.boundary_pct|round|int}}%</td></tr>{% endfor %}
  </table>
  {% endif %}

  <h2>Where He's Played <span class="sub" style="font-weight:400">(the body of work behind the adjusted numbers)</span></h2>
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
