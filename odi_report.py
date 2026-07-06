"""
odi_report.py — render a one-bowler ODI scouting PDF (phase-centric, economy-forward).

Reuses the Test report's Chromium PDF machinery (report._html_to_pdf, _fig_uri, theme) and the
shared charts (pitch_heatmap, beehive), but the structure is ODI: a Powerplay / Middle / Death
phase profile as the backbone, plus death + powerplay deep-dives, a variation mix (lookup 2812 +
off-pace backfill), match-ups by hand, and an era note (two-ball rule — see memory odi-ball-rules).

    from odi_report import render_odi_report
    render_odi_report("1300007")   # Mitchell Starc
"""
import datetime
import os

from jinja2 import Template

from odi_profile import build_odi_profile
from profile import build_line_zones
from photos import get_photo_data_uri
from ludis_cricket.charts import pitch_heatmap, beehive
from report import _fig_uri, _html_to_pdf, _country_code, _fingerprint_cards, _file_url
from report_style import REPORT_CSS, theme_ctx, card, headline_cards, f_speed, f_econ, f_avg, f_int, TEXT_SEC

REPORT_VERSION = "odi-1.2"


def _phase_read(P):
    ph = {p["phase"]: p for p in P["phases"]}
    if not ph:
        return ""
    top = max(P["phases"], key=lambda p: p["pct_balls"])
    bits = [f"<b>{P['name'].split(',')[-1].strip() if ',' in P['name'] else P['name']}</b> bowls most in the "
            f"<b>{top['phase'].lower()}</b> ({top['pct_balls']:.0f}% of his overs)"]
    if "Death" in ph:
        d = ph["Death"]
        bits.append(f"and goes at <b>{d['economy']:.2f}</b> at the death vs "
                    f"{ph['Powerplay']['economy']:.2f} in the powerplay" if "Powerplay" in ph
                    else f"and concedes <b>{d['economy']:.2f}</b> at the death")
    return " ".join(bits) + "."


def _variation_read(P):
    v = P["variations"]
    if not v["rows"]:
        return ""
    lead = v["rows"][0]
    return (f"Around <b>{v['slower_pct']:.0f}%</b> of his balls are slower-ball variations "
            f"(most often the {lead['type'].lower()}). "
            f"<span style='color:{TEXT_SEC}'>{v['coded_pct']:.0f}% of balls carry a coded delivery type; "
            f"the rest are inferred from pace.</span>")


def _variation_tables(P):
    """Two cross-tabs for the report: WHAT variations per phase (% of the phase's balls) and HOW
    each is bowled (length %). Only variation types with a meaningful sample are shown."""
    v = P["variations"]
    pt = v["phase_totals"]
    phases = [p for p in ("Powerplay", "Middle", "Death") if pt.get(p)]
    types = [r["type"] for r in v["rows"] if r["count"] >= 6]
    phase_tbl = [{"type": t, "all": next(r["pct"] for r in v["rows"] if r["type"] == t),
                  "cells": [(v["by_phase"].get(t, {}).get(p, 0) / pt[p] * 100) for p in phases]}
                 for t in types]
    from ludis_cricket.charts import LENGTH_ZONES_PACE
    bands = [lab for _lo, _hi, lab in LENGTH_ZONES_PACE]
    length_tbl = []
    for t in types:
        bl = v["by_length"].get(t, {})
        tot = sum(bl.values()) or 1
        length_tbl.append({"type": t, "n": tot,
                           "cells": [bl.get(b, 0) / tot * 100 for b in bands]})
    return {"phases": phases, "phase_tbl": phase_tbl, "bands": bands, "length_tbl": length_tbl}


def _build_odi_player(P, pdf_path, subtitle, target_country=None):
    """Build ODI video playlists (wickets / powerplay / death / yorkers / slower balls), write a
    modal player next to the PDF, and return {player, lists, playlists} for the report's ▶ links.
    Best-effort — never breaks the report if video/SSO is unavailable."""
    try:
        from ludis_cricket.video import get_fairplay_sas, build_player_html, write_playlists
        from playlists import build_odi_playlists
        get_fairplay_sas(ttl_hours=72)          # long-lived SAS baked into the player
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


def render_odi_report(bowler_id: str, out_dir: str = "reports/odi",
                      with_playlists: bool = True, target_country: str | None = "Australia") -> str:
    P = build_odi_profile(str(bowler_id))
    if P.get("empty"):
        raise ValueError(f"No ODI data for bowler {bowler_id}")
    legal = [r for r in P["raw"] if r["is_legal"]]
    lz = build_line_zones("All")

    figs = {}
    try:
        figs["pitch"] = _fig_uri(pitch_heatmap(legal, value="count", title=""), w=430, h=440)
        figs["pitch_wkts"] = _fig_uri(pitch_heatmap(legal, value="wickets", title=""), w=430, h=440)
        figs["beehive"] = _fig_uri(beehive(legal, metric="wickets", title="", line_zones=lz), w=380, h=400)
    except Exception:
        pass

    # Identical 8-card headline row to the Test pack — one canonical builder in report_style,
    # so Avg speed (with P99), length, round-the-wicket etc. match Test exactly.
    cards = [card(lab, val, sub) for (lab, val, sub) in headline_cards(P)]

    nm = P["name"]
    surname, first = ([x.strip() for x in nm.split(",", 1)] if "," in nm
                      else (nm.split()[-1], " ".join(nm.split()[:-1])))
    import re
    who = "_".join(re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_") for x in (first, surname) if x) or f"bowler_{bowler_id}"
    btype = "pace" if P["is_pace"] else ("spin" if P["is_spin"] else "bowling")
    out_path = os.path.abspath(os.path.join(out_dir, f"{who}_bowling_{btype}_odi.pdf"))
    os.makedirs(out_dir, exist_ok=True)

    video = (_build_odi_player(P, out_path, subtitle=f"{P['name']} — ODI bowling scout",
                               target_country=target_country) if with_playlists else {})
    ctx = {
        "P": P, "figs": figs, "cards": cards, "code": _country_code(P["team"]),
        "photo_uri": get_photo_data_uri(P["bowler_id"]),
        "phase_read": _phase_read(P), "variation_read": _variation_read(P),
        "var_tables": _variation_tables(P) if P["is_pace"] else None,
        "fingerprint_cards": _fingerprint_cards(P), "video": video,
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "css": REPORT_CSS, "c": theme_ctx(),
    }
    html = Template(_TEMPLATE).render(**ctx)
    if video.get("playlists"):
        # in-page lightbox: ▶ opens the playlist as a modal over the report (same tab); the PDF
        # keeps the href fallback to the standalone player.html (snippet is display:none in print).
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
    @bottom-left { content: "{{P.name}} · ODI bowling scout"; font-family: Inter, sans-serif; font-size: 8px; color: {{c.TEXT_SEC}}; margin-left: 10mm; } }
  {{ css }}
  .page { padding: 14px 16px; }
  h1 { font-size: 21px; }
  .pk { font-size: 8.5px; font-weight: 700; margin-left: 2px; }
</style></head><body><div class="page">

  <div class="header">
    {% if photo_uri %}<img src="{{photo_uri}}">{% else %}<div class="ph">🏏</div>{% endif %}
    <div>
      <h1>{{P.name}} {% if code %}<span class="flag">{{code}}</span>{% endif %}</h1>
      <div class="sub">{{P.primary_type}} · ODI bowling scout
        <span class="pill">{{P.matches}} ODIs · {{P.overs|round|int}} overs</span></div>
    </div>
    <div class="ver">{{version}}<br>{{build_date}}</div>
  </div>

  <div class="cards">
    {% for cd in cards %}<div class="card"><div class="lab">{{cd.lab}}</div><div class="val">{{cd.val}}</div>{% if cd.sub %}<div class="csub">{{cd.sub}}</div>{% endif %}</div>{% endfor %}
  </div>

  {% if fingerprint_cards %}
  <h2>Bowling Fingerprint <span class="sub" style="font-weight:400">(percentile vs ODI peers)</span></h2>
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
  <div class="cap" style="text-align:left">Percentile within same-type <b>ODI</b> peers (grey = the peer distribution, line = this bowler). Release/crease vs hand × pace/spin; movement/speed/repeatability vs pace/spin. <b>Crease variation</b> = how much he shifts his release point sideways across the crease ball to ball (high = varies a lot, low = same spot every ball). <b>Repeatability</b> = length consistency over his stock-length band, so deliberate yorkers/bouncers don't count as poor control (high = tighter, more metronomic than peers). A marker at the very edge = beyond the typical peer range on that trait.</div>
  {% endif %}

  <h2>Phase Profile <span class="sub" style="font-weight:400">(where he bowls &amp; how he goes there)</span>{% if video.lists.wickets %}<a class="vlink" data-pl="wickets" href="{{video.player}}#wickets">▶ wickets</a>{% endif %}</h2>
  {% if phase_read %}<div class="read">{{phase_read|safe}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Phase</th><th>% of overs</th><th>Overs</th><th>Economy</th><th>Wkts</th><th>Average</th><th>SR</th><th>Boundary %</th><th>Dot %</th>{% if P.is_pace %}<th>Avg speed</th>{% endif %}</tr>
    {% for p in P.phases %}
    <tr class="{{ 'hl' if p.phase == 'Death' else '' }}">
      <td class="lab">{{p.phase}}</td><td>{{p.pct_balls|round|int}}%</td><td>{{p.overs|round(1)}}</td>
      <td><b>{{p.economy|round(2)}}</b>{% if p.econ_pctl is not none %}<span class="pk" style="color:{% if p.econ_pctl >= 60 %}{{c.ACCENT}}{% elif p.econ_pctl <= 33 %}#9aa3b2{% else %}{{TEXT_SEC}}{% endif %}">P{{p.econ_pctl}}</span>{% endif %}</td>
      <td>{{p.wickets}}{% if p.wkt_pctl is not none %}<span class="pk" style="color:{% if p.wkt_pctl >= 60 %}{{c.ACCENT}}{% elif p.wkt_pctl <= 33 %}#9aa3b2{% else %}{{TEXT_SEC}}{% endif %}">P{{p.wkt_pctl}}</span>{% endif %}</td>
      <td>{{ p.average|round(1) if p.average else '—' }}</td><td>{{ p.strike_rate|round(1) if p.strike_rate else '—' }}</td>
      <td>{{p.boundary_pct|round|int}}%</td><td>{{p.dot_pct|round|int}}%</td>
      {% if P.is_pace %}<td>{{ p.avg_speed|round|int if p.avg_speed else '—' }}</td>{% endif %}
    </tr>{% endfor %}
  </table>
  <div class="cap" style="text-align:left">Blue <b>P##</b> = percentile vs modern-era ODI {{ 'pace' if P.is_pace else 'spin' }} peers in that phase (two-new-balls era, 2011+; economy inverted so <b>higher = harder to score off</b>, wickets = strike threat; grey = bottom third). So a high death-economy percentile means cheap <em>for the death</em>, where everyone leaks.</div>

  {% if P.is_pace and (P.powerplay or P.death) %}
  <h2>Phase Deep-Dives</h2>
  <div class="grid2">
    {% if P.powerplay %}<div class="dd"><h3>Powerplay (overs 1–10){% if video.lists.powerplay %}<a class="vlink tiny" data-pl="powerplay" href="{{video.player}}#powerplay">▶</a>{% endif %}</h3>
      <div class="row"><span>Economy</span><b>{{P.powerplay.economy|round(2)}}</b></div>
      <div class="row"><span>Wickets ({{ (P.powerplay.wkt_rate)|round(1) }}/100)</span><b>{{P.powerplay.wickets}}</b></div>
      {% if P.powerplay.swing_in_pct is not none %}<div class="row"><span>Swings (in / out)</span><b>{{P.powerplay.swing_in_pct|round|int}}% / {{P.powerplay.swing_out_pct|round|int}}%</b></div>{% endif %}
      <div class="row"><span>Hard length (6–8.5m)</span><b>{{P.powerplay.hard_length_pct|round|int}}%</b></div>
      <div class="row"><span>Avg speed</span><b>{{ P.powerplay.avg_speed|round|int if P.powerplay.avg_speed else '—' }} kph</b></div>
    </div>{% endif %}
    {% if P.death and P.death.overall %}<div class="dd"><h3>Death (overs 41–50){% if video.lists.death %}<a class="vlink tiny" data-pl="death" href="{{video.player}}#death">▶</a>{% endif %}</h3>
      <div class="row"><span>Economy</span><b>{{P.death.overall.economy|round(2)}}</b></div>
      <div class="row"><span>Yorker / very full</span><b>{{P.death.overall.yorker_pct|round|int}}%</b></div>
      <div class="row"><span>Slower-ball variations</span><b>{{P.death.overall.slower_pct|round|int}}%</b></div>
      <div class="row"><span>Boundary %</span><b>{{P.death.overall.boundary_pct|round|int}}%</b></div>
      {% for era, b in P.death.by_era.items() %}<div class="row"><span style="font-size:9.5px">econ · {{b.label}}</span><b>{{b.economy|round(2)}}</b></div>{% endfor %}
    </div>{% endif %}
  </div>
  {% if P.death and P.death.by_era|length > 1 %}<div class="cap" style="text-align:left">Death economy is split by ball-change era — under the two-ball rule the death ball is hard &amp; newish; from Jul-2025 the bowling side picks one older ball, so the conditions (and the numbers) differ.</div>{% endif %}
  {% endif %}

  {% if P.yorker_line and (P.yorker_line.death.bands or P.yorker_line.overall.bands) %}
  <div style="font-weight:700;font-size:10.5px;margin:10px 0 3px">Yorker line
    <span class="sub" style="font-weight:400">— where he aims the full ball ("leg-stump yorker vs the wide hole")</span>{% if video.lists.yorkers %}<a class="vlink tiny" data-pl="yorkers" href="{{video.player}}#yorkers">▶</a>{% endif %}</div>
  <table class="mtab" style="max-width:660px">
    <tr><th>When full</th><th>Wide (hole)</th><th>Off / channel</th><th>At the stumps</th><th>Leg / straight</th><th>Balls</th></tr>
    {% for ctx, s in [("Death (41–50)", P.yorker_line.death), ("All overs", P.yorker_line.overall)] %}
    {% if s.bands %}<tr><td class="lab">{{ctx}}{% if s.thin %} <span class="sub" style="font-weight:400">· small n</span>{% endif %}</td>
      {% for b in s.bands %}<td>{{b.pct|round|int}}%</td>{% endfor %}<td>{{s.n}}</td></tr>{% endif %}
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left">Yorker/very-full length only (&lt;2 m). Line is batter-relative — the wide "hole" is wide outside off; useful both to scout his death plan and to pick our own.</div>
  {% endif %}

  {% if var_tables and var_tables.phase_tbl %}
  <h2>Variations <span class="sub" style="font-weight:400">(slower balls &amp; cutters — what &amp; where)</span>{% if video.lists.slower_balls %}<a class="vlink" data-pl="slower_balls" href="{{video.player}}#slower_balls">▶ slower balls</a>{% endif %}</h2>
  {% if variation_read %}<div class="read">{{variation_read|safe}}</div>{% endif %}
  <div style="font-weight:700;font-size:10.5px;margin:4px 0 3px">What he bowls, by phase
    <span class="sub" style="font-weight:400">— % of that phase's balls</span></div>
  <table class="mtab" style="max-width:640px">
    <tr><th>Variation</th>{% for p in var_tables.phases %}<th>{{p}}</th>{% endfor %}<th>All overs</th></tr>
    {% for row in var_tables.phase_tbl %}
    <tr><td class="lab">{{row.type}}</td>{% for cc in row.cells %}<td>{{cc|round|int}}%</td>{% endfor %}<td>{{row.all|round|int}}%</td></tr>
    {% endfor %}
  </table>
  <div style="font-weight:700;font-size:10.5px;margin:10px 0 3px">How each variation is bowled
    <span class="sub" style="font-weight:400">— length, % of that variation</span></div>
  <table class="mtab">
    <tr><th>Variation</th>{% for b in var_tables.bands %}<th>{{ b.replace('Back of Length','Back of Len').replace('Yorker/Full','York/Full') }}</th>{% endfor %}<th>Balls</th></tr>
    {% for row in var_tables.length_tbl %}
    <tr><td class="lab">{{row.type}}</td>{% for cc in row.cells %}<td>{{cc|round|int}}%</td>{% endfor %}<td>{{row.n}}</td></tr>
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
    <tr><td class="lab">{{lab}}</td><td>{{s.balls}}</td><td><b>{{s.economy|round(2)}}</b></td><td>{{s.wickets}}</td>
      <td>{{ s.average|round(1) if s.average else '—' }}</td><td>{{ s.strike_rate|round(1) if s.strike_rate else '—' }}</td><td>{{s.boundary_pct|round|int}}%</td></tr>{% endfor %}
  </table>
  {% endif %}

  <div class="note">
    ODI internationals only. Ball-change eras in this sample:
    {% for e, v in P.eras.items() %}{{v.label}} {{v.pct|round|int}}%{{ "; " if not loop.last }}{% endfor %}.
    Phase = Powerplay 1–10 / Middle 11–40 / Death 41–50. Economy charges wides + no-balls to the bowler.
    {{version}} · {{build_date}}.
  </div>

</div></body></html>
"""
