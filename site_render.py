"""
site_render.py — the shared card + page shell for the scouting SITE (publish_site, the static
bundle) AND the local audit web app (webapp). Both render off this so the test app is identical to
the built app: bold name (no hyperlink), bowler type, a badge, then View report / ▶ Vision / PDF.

The only per-app difference is the badge (opposition site = likely-XI tier; audit app = a format
badge signifying a test report) and the hrefs (relative files vs Flask routes).
"""
import html as _html
import re

# Bowler type as printed in the report's sub-line (for the card's type label).
TYPE_RE = re.compile(r"(Right Fast|Left Fast|Right Medium|Left Medium|Off Spin|"
                     r"Left Orthodox|Leg Break|Left Unorthodox)")

# Badge → (section heading, short chip). Order = reading priority on the opposition site.
TIER_META = [("xi", "Most likely XI", "XI"),
             ("squad", "In the squad", "Squad"),
             ("fringe", "Fringe / outside chance", "Fringe"),
             ("reference", "Reference — our bowlers", "Ref"),
             ("test", "Test report", "TEST")]        # audit-app badge (no XI/squad in that env)
TIER_CHIP = {t: chip for t, _h, chip in TIER_META}


def report_card(title, btype, report_href, pdf_href=None, vision_href=None,
                badge=None, badge_class="squad", photo=None, initials=""):
    """One report row: headshot, bold name (not a link), bowler type + badge, then
    View report / ▶ Vision / PDF."""
    chip = f'<span class="tier {badge_class}">{_html.escape(badge)}</span>' if badge else ""
    if photo:
        av = f'<img class="rav" src="{photo}" alt="" loading="lazy">'
    elif initials:
        av = f'<span class="rav">{_html.escape(initials)}</span>'
    else:
        av = ""                                   # no headshot context (e.g. the local audit app)
    btns = f'<a class="btn" href="{report_href}">View report</a>'
    if vision_href:
        btns += f'<a class="btn ghost" href="{vision_href}">▶ Vision</a>'
    if pdf_href:
        btns += f'<a class="btn ghost" href="{pdf_href}">View as PDF</a>'
    return (f'<li>{av}<div class="rinfo"><b>{_html.escape(title)}</b>{chip}'
            + (f'<span class="rtype">{_html.escape(btype)}</span>' if btype else "")
            + "</div>" + btns + "</li>")


def group_heading(title, count, cls=""):
    return f'<h2 class="tierhead {cls}">{_html.escape(title)}<span>{count}</span></h2>'


SHELL = """<!doctype html><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{{title}}</title>
<style>
 :root{color-scheme:light}
 body{font:15px/1.5 Inter,-apple-system,Segoe UI,sans-serif;max-width:760px;margin:0 auto;padding:24px 16px 48px;color:#1a1a2e;background:#F5F7FA}
 .crumb{font-size:13px;margin-bottom:14px} .crumb a{color:#6b7280;text-decoration:none} .crumb a:hover{color:#003087}
 h1{color:#003087;font-size:22px;margin:2px 0 2px} .lead{color:#6b7280;margin:0 0 16px}
 ul.cards{list-style:none;padding:0;margin:0}
 ul.cards li{padding:13px 15px;border:1px solid #e5e7eb;border-radius:10px;margin:8px 0;background:#fff;display:flex;align-items:center;gap:10px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
 ul.cards a{color:#003087;text-decoration:none;font-weight:600;flex:1} ul.cards a:hover b{text-decoration:underline}
 ul.cards b{display:block} .sub{display:block;color:#6b7280;font-size:12px;font-weight:400;margin-top:2px}
 .n{color:#6b7280;font-size:12px;white-space:nowrap} .pdf{flex:0 0 auto;font-size:12px;background:#eef1f6;padding:3px 9px;border-radius:6px;font-weight:600}
 ul.reports{list-style:none;padding:0;margin:0}
 ul.reports li{padding:12px 15px;border:1px solid #e5e7eb;border-radius:10px;margin:8px 0;background:#fff;display:flex;align-items:center;gap:12px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
 ul.reports .rav{width:44px;height:44px;border-radius:50%;object-fit:cover;background:#eef1f6;flex:0 0 auto;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;color:#9aa4b2}
 ul.reports .rinfo{flex:1;min-width:0} ul.reports .rinfo b{font-size:15px;color:#1a1a2e} ul.reports .rtype{display:block;color:#6b7280;font-size:13px;margin-top:1px}
 .tier{display:inline-block;margin-left:8px;font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;vertical-align:middle}
 .tier.xi{background:#dcfce7;color:#15803d} .tier.squad{background:#e0e7ff;color:#3730a3} .tier.fringe{background:#eef2f6;color:#64748b} .tier.reference{background:#fef3c7;color:#92400e} .tier.test{background:#e0e7ff;color:#3730a3}
 h2.tierhead{font-size:14px;color:#1a1a2e;margin:22px 0 8px;display:flex;align-items:center;gap:8px;padding-left:8px;border-left:3px solid #cbd5e1}
 h2.tierhead:first-of-type{margin-top:10px} h2.tierhead.xi{border-left-color:#15803d} h2.tierhead.squad{border-left-color:#3730a3} h2.tierhead.fringe{border-left-color:#94a3b8} h2.tierhead.test{border-left-color:#003087}
 h2.tierhead span{font-size:12px;font-weight:600;color:#6b7280;background:#eef1f6;border-radius:999px;padding:1px 8px}
 ul.reports a.btn{flex:0 0 auto;font-size:13px;font-weight:600;text-decoration:none;padding:7px 14px;border-radius:7px;background:#003087;color:#fff;white-space:nowrap}
 ul.reports a.btn.ghost{background:#eef1f6;color:#003087;border:1px solid #d5dced}
 @media(max-width:520px){ul.reports li{flex-wrap:wrap} ul.reports .rinfo{flex:1 0 100%;margin-bottom:6px}}
 .empty{color:#6b7280;font-style:italic} .note{color:#9ca3af;font-size:12px;margin-top:22px}
</style>
<div class="crumb">{{crumb}}</div>
{{body}}
"""


def page(title, body, up=None):
    crumb = f'<a href="{up[0]}">← {_html.escape(up[1])}</a>' if up else ""
    return (SHELL.replace("{{title}}", _html.escape(title))
                 .replace("{{crumb}}", crumb).replace("{{body}}", body))
