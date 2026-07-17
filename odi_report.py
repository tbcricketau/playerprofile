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
from cricket_core.charts import pitch_heatmap, beehive
from report import _fig_uri, _html_to_pdf, _country_code, _fingerprint_cards, _fingerprint_headline, _file_url
from report_style import REPORT_CSS, theme_ctx, card, headline_cards, f_speed, f_econ, f_avg, f_int, TEXT_SEC

REPORT_VERSION = "odi-1.2"


def _phase_read(P):
    ph = {p["phase"]: p for p in P["phases"]}
    if not ph:
        return ""
    top = max(P["phases"], key=lambda p: p["pct_balls"])
    bits = [f"<b>{P['name'].split(',')[-1].strip() if ',' in P['name'] else P['name']}</b> bowls most in the "
            f"<b>{top['phase'].lower()}</b> ({top['pct_balls']:.0f}% of their overs)"]
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
    return (f"Around <b>{v['slower_pct']:.0f}%</b> of their balls are slower-ball variations "
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
    from cricket_core.charts import LENGTH_ZONES_PACE
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
        from cricket_core.video import get_fairplay_sas, build_player_html, write_playlists
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


def _grid_figs(legal, off_pace):
    """The 8 small Where-They-Bowl charts: over/round × on-pace/off-pace, each a pitch map + a beehive
    (fonts scaled down to match the thumbnail size). Off pace = a slower-ball variation
    (odi_profile._var_type). Also returns `{pk}_{sk}_pct` = that subset's % of all legal balls; cells
    with < 25 balls are skipped."""
    from odi_profile import _var_type
    lz = build_line_zones("All")
    figs = {}
    tot = len(legal) or 1
    for pk, offp in (("on", False), ("off", True)):
        for sk, rnd in (("over", False), ("round", True)):
            rows = [r for r in legal if ((_var_type(r, off_pace) is not None) == offp) and (r.get("is_round") == rnd)]
            figs[f"{pk}_{sk}_pct"] = round(len(rows) / tot * 100)
            if len(rows) < 25:
                continue
            try:
                figs[f"{pk}_{sk}_pitch"] = _fig_uri(pitch_heatmap(rows, value="count", title="", font_scale=0.62), w=224, h=240)
                figs[f"{pk}_{sk}_bee"] = _fig_uri(beehive(rows, metric="count", title="", line_zones=lz, font_scale=0.62), w=214, h=232)
            except Exception:
                pass
    return figs


def render_odi_report(bowler_id: str, out_dir: str = "reports/odi",
                      with_playlists: bool = True, target_country: str | None = "Australia") -> str:
    P = build_odi_profile(str(bowler_id))
    if P.get("empty"):
        raise ValueError(f"No ODI data for bowler {bowler_id}")
    legal = [r for r in P["raw"] if r["is_legal"]]

    figs = _grid_figs(legal, P.get("off_pace_kph")) if P["is_pace"] else {}

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
        "photo_uri": get_photo_data_uri(P["bowler_id"], fmt="odi", name=P.get("name")),
        "phase_read": _phase_read(P), "variation_read": _variation_read(P),
        "var_tables": _variation_tables(P) if P["is_pace"] else None,
        "fingerprint_cards": _fingerprint_cards(P), "fingerprint_headline": _fingerprint_headline(P), "video": video,
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "css": REPORT_CSS, "c": theme_ctx(),
    }
    html = Template(_TEMPLATE).render(**ctx)
    if video.get("playlists"):
        # in-page lightbox: ▶ opens the playlist as a modal over the report (same tab); the PDF
        # keeps the href fallback to the standalone player.html (snippet is display:none in print).
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
    @bottom-left { content: "{{P.name}} · ODI bowling scout"; font-family: Inter, sans-serif; font-size: 8px; color: {{c.TEXT_SEC}}; margin-left: 10mm; } }
  {{ css }}
  .page { padding: 14px 16px; }
  h1 { font-size: 21px; }
  .pk { font-size: 8.5px; font-weight: 700; margin-left: 2px; }
  .grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; align-items: start; }
  .grid4 .fig { text-align: center; }
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
  {% if fingerprint_headline %}<div class="read" style="margin-bottom:6px">{{fingerprint_headline}}</div>{% endif %}
  <div class="fpgrid">
    {% for f in fingerprint_cards %}
    <div class="fpcard">
      <div class="lab">{{f.label}}</div>
      <div class="pct" style="color:{{f.colour}}">{{f.pct_txt}}{% if f.recent_txt %} <span style="color:#d9822b;font-size:12px">&rarr; {{f.recent_txt}}</span>{% endif %}</div>
      <img src="{{f.img}}">
      <div class="sub">{{f.disp}} · {{f.peer}}</div>
    </div>
    {% endfor %}
  </div>
  <div class="cap" style="text-align:left"><b style="color:#003087">Solid line = career</b>, <b style="color:#d9822b">dotted = last 3 years</b>. Percentile within same-type <b>ODI</b> peers (grey = the peer distribution, line = this bowler). Release/crease vs hand × pace/spin; movement/speed/repeatability vs pace/spin. <b>Crease variation</b> = how much they shift their release point sideways across the crease ball to ball (high = varies a lot, low = same spot every ball). <b>Repeatability</b> = length consistency over their stock-length band, so deliberate yorkers/bouncers don't count as poor control (high = tighter, more metronomic than peers). A marker at the very edge = beyond the typical peer range on that trait.</div>
  {% endif %}

  <h2>Phase Profile <span class="sub" style="font-weight:400">(where they bowl &amp; how they go there)</span>{% if video.lists.wickets %}<a class="vlink" data-pl="wickets" href="{{video.player}}#wickets">▶ wickets</a>{% endif %}</h2>
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

  <div class="note">
    ODI internationals only. Ball-change eras in this sample:
    {% for e, v in P.eras.items() %}{{v.label}} {{v.pct|round|int}}%{{ "; " if not loop.last }}{% endfor %}.
    Phase = Powerplay 1–10 / Middle 11–40 / Death 41–50. Economy charges wides + no-balls to the bowler.
    {{version}} · {{build_date}}.
  </div>

</div></body></html>
"""
