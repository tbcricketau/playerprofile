"""
report_style.py — the SINGLE source of styling + metric-card formatting for every scouting
report (Test / ODI / T20, bowling + batting). Change the look HERE and all reports update.

Usage in a report:
    from report_style import REPORT_CSS, theme_ctx, card, f_speed, f_econ, f_avg, f_int
    ...
    html = Template(_TEMPLATE).render(css=REPORT_CSS, c=theme_ctx(), cards=[...], ...)
    # and in the template's <head>:  <style> @page {...} {{ css }} {...section-specific CSS...} </style>

Colours mirror the Opta light theme (ludis_cricket.theme / CLAUDE.md).
"""

import math

BG_PAGE, BG_PANEL = "#F5F7FA", "#FFFFFF"
TEXT_PRI, TEXT_SEC = "#1a1a2e", "#6b7280"
ACCENT, DANGER = "#003087", "#b91c1c"
BORDER = "rgba(0,0,0,0.10)"
FONT_STACK = 'Inter, -apple-system, "Segoe UI", sans-serif'


def theme_ctx() -> dict:
    """Colour dict for `c` in templates (inline {{c.ACCENT}} etc.)."""
    return dict(BG_PAGE=BG_PAGE, BG_PANEL=BG_PANEL, TEXT_PRI=TEXT_PRI, TEXT_SEC=TEXT_SEC,
                ACCENT=ACCENT, DANGER=DANGER, BORDER=BORDER, FONT_STACK=FONT_STACK)


# ── Canonical metric-card formatting (identical numbers in every report) ─────────────
def f_speed(v):  return f"{v:.0f} km/h" if isinstance(v, (int, float)) else "—"
def f_econ(v):   return f"{v:.2f}" if isinstance(v, (int, float)) else "—"
def f_avg(v):    return f"{v:.1f}" if isinstance(v, (int, float)) else "—"
def f_len(v):    return f"{v:.1f} m" if isinstance(v, (int, float)) else "—"
def f_int(v):    return f"{int(v):,}" if isinstance(v, (int, float)) else "—"
def f_pct(v):    return f"{v:.0f}%" if isinstance(v, (int, float)) else "—"


def card(label, value, sub=""):
    """One metric card. Matches the .card .lab/.val/.csub markup in REPORT_CSS, so every report's
    cards are structurally + visually identical."""
    return {"lab": label, "val": value, "sub": sub}


# ── The canonical headline metric-card row (identical across Test / ODI / T20, bowling) ──
def _fmt(v, spec=".1f", unit="", fallback="—"):
    """Mirror of profile.fmt — kept local so report_style has no upstream import."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return fallback
    return f"{v:{spec}}{unit}"


def _pct(v, dp=0):
    return _fmt(v, f".{dp}f", "%")


def headline_cards(P: dict) -> list:
    """The 8 top metric cards every BOWLING report shows, as (label, value, sub) tuples —
    the convention the report templates already iterate. Reads these profile keys (any may be
    None): n_balls, n_wkts, economy, bowl_avg, strike_rate, avg_spd, max_spd_99, avg_len_m,
    short_pct, round_pct, round_lhb, round_rhb.  Change the top-card look/labels HERE and every
    bowling report (Test / ODI / T20) updates together."""
    rl, rr = P.get("round_lhb"), P.get("round_rhb")
    split = (f"LHB {_pct(rl)} · RHB {_pct(rr)}"
             if (rl is not None or rr is not None) else "no data")
    nb, nw = P.get("n_balls"), P.get("n_wkts")
    return [
        ("Balls",         f"{nb:,}" if nb is not None else "—", ""),
        ("Wickets",       f"{nw}" if nw is not None else "—", ""),
        ("Economy",       _fmt(P.get("economy")), ""),
        ("Bowling Avg",   _fmt(P.get("bowl_avg")), ""),
        ("Strike Rate",   _fmt(P.get("strike_rate")), ""),
        ("Avg speed",     f"{_fmt(P.get('avg_spd'))} kph", f"P99 {_fmt(P.get('max_spd_99'))}"),
        ("Avg length",    f"{_fmt(P.get('avg_len_m'), '.2f')} m", f"Short {_pct(P.get('short_pct'))}"),
        ("Round the wkt", _pct(P.get("round_pct")), split),
    ]


# ── The shared stylesheet — colours baked in (no Jinja placeholders needed) ──────────
REPORT_CSS = f"""
  * {{ box-sizing: border-box; }}
  html, body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  body {{ font-family: {FONT_STACK}; color: {TEXT_PRI}; background: {BG_PAGE};
         margin: 0; padding: 0; font-size: 11px; }}
  .page {{ padding: 4px 2px; }}
  h1 {{ font-size: 24px; margin: 0; }}
  h2 {{ font-size: 14px; color: {ACCENT}; border-bottom: 2px solid {ACCENT};
       padding-bottom: 3px; margin: 22px 0 9px; page-break-after: avoid; }}
  h3 {{ font-size: 12px; margin: 0 0 6px; }}
  .sub {{ color: {TEXT_SEC}; font-size: 11px; }}
  .flag {{ font-size: 12px; font-weight: 700; color: #fff; background: {ACCENT};
          padding: 2px 7px; border-radius: 6px; vertical-align: middle; letter-spacing: .05em; }}
  .header {{ display: flex; gap: 16px; align-items: center; }}
  .header img {{ width: 84px; height: 84px; object-fit: cover; border-radius: 10px; }}
  .ph {{ width: 84px; height: 84px; border-radius: 10px; background: #1e2530; color:#555;
        display:flex; align-items:center; justify-content:center; font-size: 34px; }}
  .ver {{ margin-left: auto; align-self: flex-start; text-align: right; font-size: 8.5px;
         color: {TEXT_SEC}; line-height: 1.3; letter-spacing: .02em; }}
  /* metric cards — one canonical component for every format */
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 10px; }}
  .cards.c5 {{ grid-template-columns: repeat(5, 1fr); }}
  .tcards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 7px; margin-top: 10px; }}
  .tcards .card .val {{ font-size: 15px; }}
  .card {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px;
          padding: 8px 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }}
  .card .lab {{ color: {TEXT_SEC}; font-size: 9px; text-transform: uppercase; letter-spacing:.04em; }}
  .card .val {{ font-size: 18px; font-weight: 700; margin-top: 2px; }}
  .card .csub {{ color: {TEXT_SEC}; font-size: 9px; margin-top: 2px; }}
  /* narrative + layout */
  .read {{ font-size: 10px; color: {TEXT_PRI}; margin: 0 0 7px; line-height: 1.35; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: start; }}
  .grid3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }}
  .summary {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }}
  .sbox {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px; }}
  .sbox h3 {{ margin: 0 0 6px; font-size: 11px; text-transform: uppercase; letter-spacing:.05em; }}
  .sbox ul {{ margin: 0; padding-left: 15px; }} .sbox li {{ margin-bottom: 4px; line-height: 1.35; }}
  /* fingerprint cards */
  .fpgrid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 8px; }}
  .fpcard {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 8px 4px; text-align: center; }}
  .fpcard .lab {{ font-size: 9.5px; font-weight: 600; color: {TEXT_PRI}; }}
  .fpcard .pct {{ font-size: 22px; font-weight: 800; line-height: 1.05; }}
  .fpcard img {{ width: 100%; height: 42px; display: block; }}
  .fpcard .sub {{ font-size: 8px; color: {TEXT_SEC}; }}
  /* charts */
  img.chart {{ width: 100%; border: 1px solid {BORDER}; border-radius: 8px; background: #fff; }}
  img.pmap {{ width: 90%; display: block; margin: 0 auto; }}
  img.bee  {{ width: 78%; display: block; margin: 0 auto; }}
  img.wag  {{ width: 88%; display: block; margin: 0 auto; }}
  .fig {{ }}
  .ct {{ font-size: 12.5px; font-weight: 700; text-align: center; color: {TEXT_PRI}; margin: 0 0 2px; }}
  .cap {{ font-size: 8.5px; color: {TEXT_SEC}; font-style: italic; text-align: center; margin: 2px 4px 0; line-height: 1.25; }}
  /* tables — one canonical table style (.mtab) */
  .mtab {{ width: 100%; border-collapse: collapse; font-size: 10px; }}
  .mtab th, .mtab td {{ border: 1px solid {BORDER}; padding: 3px 6px; text-align: center; }}
  .mtab th {{ background: #eef1f6; color: {TEXT_SEC}; font-weight: 600; }}
  .mtab td.lab {{ text-align: left; font-weight: 600; }}
  .mtab tr.weakrow td {{ background: #eef3fb; font-weight: 600; }}
  .mtab tr.weakrow td.lab {{ color: {ACCENT}; }}
  .mtab tr.hl td {{ background: #fdf4f1; }}
  /* danger / callout cards + deep-dive cards */
  .dcard {{ border-radius: 8px; padding: 8px 10px; border: 1px solid {BORDER}; background: {BG_PANEL}; page-break-inside: avoid; }}
  .dcard.warn {{ background: #fdf1f1; border-color: #f2c9c9; }}
  .dcard .dh {{ font-size: 9px; text-transform: uppercase; letter-spacing:.06em; color: {DANGER}; }}
  .dcard.plain .dh {{ color: {TEXT_SEC}; }}
  .dcard .db {{ font-size: 14px; font-weight: 700; margin: 3px 0; }}
  .dcard .ds {{ font-size: 10px; color: {TEXT_SEC}; }}
  .dd {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px; }}
  .dd .row {{ display: flex; justify-content: space-between; font-size: 11px; padding: 2px 0; border-bottom: 1px dotted {BORDER}; }}
  .dd .row b {{ color: {ACCENT}; }}
  /* misc */
  a.vlink {{ display:inline-block; font-size:9px; font-weight:700; color:#fff; background:{ACCENT};
            text-decoration:none; padding:2px 8px; border-radius:5px; margin-left:6px; vertical-align:middle; }}
  a.vlink.tiny {{ padding:0 5px; margin-left:4px; font-size:8px; border-radius:4px; }}
  .pills span, .pill {{ display:inline-block; background:#eef1f6; color:{TEXT_SEC}; border-radius: 10px; padding: 2px 8px; margin: 2px 3px 0 0; font-size:9px; }}
  .foot, .note {{ margin-top: 8px; color: {TEXT_SEC}; font-size: 9px; border-top: 1px solid {BORDER}; padding-top: 5px; }}
  .pbreak {{ page-break-before: always; }}
  .avoid {{ page-break-inside: avoid; }}
  .lead {{ color: {TEXT_SEC}; }}
"""
