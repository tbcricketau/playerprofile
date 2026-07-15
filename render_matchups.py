"""
render_matchups.py — the series MATCH-UPS page: the one place the full simulated grid lives
(SCOUTING_REBUILD.md). Two colour-coded matrices — their batters × our bowlers, and our batters
× their bowlers — plus the structural read. Cells colour by advantage from OUR perspective;
cohort-only cells (batter never faced that type in Tests) render muted with a dot.

Run:  .\\venv\\Scripts\\python.exe render_matchups.py --opp bangladesh
Out:  reports/matchups_{opp}.html   (picked up by publish_site as a series-level card)
"""
import argparse
import html
import json
import os

from cricket_core.config import project_path
from site_render import page as _page

HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """<style>
 .mwrap{overflow-x:auto;border:1px solid #e5e7eb;border-radius:10px;background:#fff;padding:10px;margin:10px 0 22px}
 table.mx{border-collapse:collapse;font-size:12px;min-width:640px}
 table.mx th{font-weight:600;color:#6b7280;padding:4px 7px;border-bottom:1px solid #e5e7eb;text-align:center}
 table.mx th.rowh{text-align:left;white-space:nowrap}
 table.mx td{padding:4px 7px;text-align:center;border-bottom:1px solid #f1f3f7;font-variant-numeric:tabular-nums;white-space:nowrap}
 table.mx td.rowh{text-align:left;font-weight:600;color:#1a1a2e;white-space:nowrap}
 table.mx td.co{color:#9aa4b2}
 .legend{font-size:12px;color:#6b7280;margin:2px 0 8px}
 .lg{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin:0 3px 0 10px}
 .note{color:#9ca3af;font-size:12px;margin-top:18px}
 h2.mx{font-size:16px;color:#003087;margin:18px 0 2px}
 .sub{color:#6b7280;font-size:13px;margin:0 0 6px}
</style>"""


def _shade(frac):
    """0 = worst for us -> red; 1 = best for us -> green (light Opta-friendly ramp)."""
    if frac is None:
        return "#f6f7f9"
    r0, g0 = (254, 226), (220, 252)      # red-100 .. green-100 endpoints
    r = int(254 + (220 - 254) * frac)
    g = int(226 + (252 - 226) * frac)
    b = int(226 + (231 - 226) * frac)
    return f"rgb({r},{g},{b})"


def _matrix(cells, row_key, col_key, good_when_high):
    """cells -> (row names, col names, {(row,col): cell})."""
    rows, cols, grid = [], [], {}
    for c in cells:
        rn, cn = c[row_key], c[col_key]
        if rn not in rows:
            rows.append(rn)
        if cn not in cols:
            cols.append(cn)
        grid[(rn, cn)] = c
    return rows, cols, grid


def _table(title, sub, cells, row_key, col_key, good_when_high):
    rows, cols, grid = _matrix(cells, row_key, col_key, good_when_high)
    head = "<tr><th class=rowh></th>" + "".join(
        f"<th>{html.escape(c.split()[-1])}</th>" for c in cols) + "</tr>"
    body = []
    for rn in rows:
        tds = [f'<td class=rowh>{html.escape(rn)}'
               f' <span style="color:#9aa4b2;font-weight:400">{html.escape(next((grid[(rn,c)]["bat_hand"] for c in cols if (rn,c) in grid and row_key=="batter"), ""))}</span></td>']
        for cn in cols:
            c = grid.get((rn, cn))
            if not c or c["sim_avg"] is None:
                tds.append("<td>—</td>")
                continue
            frac = c["rank_in_bowler_col"] if row_key == "batter" else c["rank_in_batter_row"]
            if not good_when_high:
                frac = None if frac is None else 1 - frac
            cohort = c["confidence"] == "None"
            tip = (f'{c["batter"]} v {c["bowler"]} — sim avg {c["sim_avg"]}, SR {c["sim_sr"]}, '
                   f'{c["top_dismissal"]} · {c["danger"]} · confidence {c["confidence"]}')
            cls = ' class=co' if cohort else ""
            dot = "·" if cohort else ""
            tds.append(f'<td{cls} style="background:{_shade(frac)}" title="{html.escape(tip)}">'
                       f'{c["sim_avg"]:.0f}{dot}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<h2 class=mx>{html.escape(title)}</h2><p class=sub>{html.escape(sub)}</p>'
            f'<div class=mwrap><table class=mx>{head}{"".join(body)}</table></div>')


def _structural(cells):
    """One line per structural away-turner threat: bowler type class vs a hand we hold."""
    seen, lines = set(), []
    for c in cells:
        if not c.get("structural_threat"):
            continue
        key = (c["bowler"], c["bat_hand"])
        if key in seen:
            continue
        seen.add(key)
    by_bowler = {}
    for c in cells:
        if c.get("structural_threat"):
            by_bowler.setdefault((c["bowler"], c["bowler_type"], c["bat_hand"]), []).append(c["batter"])
    for (bow, btype, hand), bats in by_bowler.items():
        lines.append(f"<li><b>{html.escape(bow)}</b> ({html.escape(btype)}) turns the ball away from "
                     f"our {hand}s — structurally harder for {html.escape(', '.join(sorted(set(bats))))}.</li>")
    if not lines:
        return ""
    return ('<h2 class=mx>Structural spin match-ups</h2>'
            '<p class=sub>Turn direction vs hand — the one matchup class that holds up out of sample. '
            'A left/right pairing at the crease breaks these up.</p><ul>' + "".join(lines) + "</ul>")


def build(opp):
    p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{opp}.json")
    store = json.load(open(p, encoding="utf-8"))
    opp_title = store["opp"]
    body = [CSS,
            f"<h1>Match-ups — {html.escape(opp_title)}</h1>",
            '<p class="lead">Simulated matchups — a tool that plays each batter-v-bowler pairing out '
            'thousands of times from their full profiles. Green = advantage us, red = advantage them. '
            'A number with a dot (·) is a cohort read — that batter has not faced enough of that bowler '
            'type in Tests to profile personally. Hover any cell for the detail.</p>',
            _table(f"Their batters v our bowlers",
                   "Cell = the batter's simulated average against that bowler. Low (green) = the "
                   "bowler wins the matchup.",
                   store["they_bat"], "batter", "bowler", good_when_high=False),
            _table(f"Our batters v their bowlers",
                   "Cell = our batter's simulated average against that bowler. High (green) = our "
                   "batter on top.",
                   store["we_bat"], "batter", "bowler", good_when_high=True),
            _structural(store["we_bat"]),
            f'<p class=note>Simulation built {store["built"]} · {store["innings_per_pair"]} innings '
            'per pairing · profiles from all Test careers. Real head-to-head history is deliberately '
            'not averaged here (usually 10–30 balls — watch it instead, via each report\'s vision '
            'links).</p>']
    out = os.path.join(HERE, "reports", f"matchups_{opp}.html")
    open(out, "w", encoding="utf-8").write(
        _page(f"Match-ups — {opp_title}", "".join(body)))
    print(f"wrote {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    build(ap.parse_args().opp)
