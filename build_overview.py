"""build_overview.py — the per-batter MEETING OVERVIEW: one row per opposition batter with the
bowling plan and the field placements that plan implies, for a given bowler type. The bowlers' ask
(Boland) was the pace version; the same table scoped to `left_pace` answers Starc's, and any other
group works the same way.

Rows come from the same functions the reports use — `batting_report.plan_sentence` for the plan and
`field_engine.build_field` for the placements — so the table and the batter's own report never
disagree. Batters with too little against the type are listed with what they have, not a made-up row.

Run:  .\\venv\\Scripts\\python.exe build_overview.py --opp bangladesh --group pace
Out:  reports/overview_{group}_{opp}.html   (publish_site copies it + links it from the series index)
"""
import argparse
import html
import json
import os

from batter_profile import build_batter_profile, BOWLER_GROUPS, MACRO_GROUPS
from batting_report import plan_sentence
import field_engine
from site_render import page as _page

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_BALLS = 60          # below this vs the type, we show the count and skip the plan/field
_CSS = """<style>
 .owrap{overflow-x:auto;border:1px solid #e5e7eb;border-radius:10px;background:#fff;margin:10px 0 22px}
 table.ov{border-collapse:collapse;font-size:13px;width:100%;min-width:720px}
 table.ov th{font-weight:600;color:#fff;background:#003087;padding:8px 10px;text-align:left;white-space:nowrap}
 table.ov td{padding:9px 10px;border-bottom:1px solid #f1f3f7;vertical-align:top}
 table.ov tr:last-child td{border-bottom:none}
 table.ov td.bat{font-weight:600;color:#1a1a2e;white-space:nowrap}
 table.ov td.bat span{display:block;font-weight:400;color:#6b7280;font-size:12px}
 .thin{color:#9ca3af;font-style:italic}
 .fld{color:#1a1a2e} .fld em{color:#6b7280;font-style:normal}
 .note{color:#9ca3af;font-size:12px;margin-top:16px}
 h2.ov2{font-size:16px;color:#003087;margin:26px 0 2px}
 .sub2{color:#6b7280;font-size:13px;margin:0 0 6px}
 h1 .sub{display:block;font-size:14px;color:#6b7280;font-weight:400;margin-top:4px}
</style>"""


def _fielding_cell(P, group):
    """The placements this plan implies: the stock base, then the evidenced moves off it, then the
    fielder worth relocating. Positions only — the justification lives in the batter's report."""
    sub = {"is_lhb": P.get("is_lhb"), "batter_id": P.get("batter_id"),
           "raw": P.get("raw"), "caught_positions": P.get("caught_positions")}
    try:
        f = field_engine.build_field(sub, group, "set")
    except Exception:
        f = None
    if not f:
        return None
    bits = []
    if f.get("base_note"):
        # the note carries its own reasoning after an em dash — the table wants the variant name
        # only, since the justification sits in the batter's report
        base = str(f["base_note"]).split("—")[0].strip().rstrip(".")
        if base:
            bits.append(f"<em>{html.escape(base)}</em>")
    moves = [x["position"] for x in (f.get("field") or []) if x.get("tag") == "change"]
    if moves:
        bits.append(", ".join(html.escape(m) for m in moves))
    fl = (f.get("floating") or [None])[0]
    if fl and fl.get("position"):
        bits.append(f"<em>spare: {html.escape(str(fl['position']))}</em>")
    return " · ".join(bits) if bits else None


_MIN_OUTS_FOR_BPD = 4      # below this, a balls-per-dismissal figure is noise — show the count instead
_MIN_SHORT_BALLS = 40


_PACE_SUBS = ("left_pace", "right_pace")


def _short_read(P):
    """False-shot rate against the short ball, or None if the sample is too small to quote."""
    short = next((d for d in (P.get("dims", {}).get("length") or [])
                  if str(d.get("bucket", "")).lower() == "short"), None)
    if not short or short.get("balls", 0) < _MIN_SHORT_BALLS or short.get("false_pct") is None:
        return None
    return f"{short['false_pct']:.0f}% false ({short['balls']} balls)"


def _threat(P):
    """How they score and get out against this type. Rate metrics (false shot, scoring area) settle
    at these sample sizes; dismissal-based ones don't, so BPD is withheld under a few dismissals and
    the raw count shown instead."""
    raw = P.get("raw") or []
    sq = [r for r in raw if r.get("has_shot_q")]
    false_pct = 100 * sum(1 for r in sq if r.get("is_false_shot")) / len(sq) if sq else None
    n_out = int(P.get("n_out") or 0)
    dirp = P.get("dir_pct") or {}
    area = max(dirp.items(), key=lambda kv: kv[1]) if dirp else None
    short = next((d for d in (P.get("dims", {}).get("length") or [])
                  if str(d.get("bucket", "")).lower() == "short"), None)
    dis = P.get("dismissals") or {}
    top = max(dis.items(), key=lambda kv: kv[1]) if dis else None
    return {
        "balls": int(P.get("n_balls") or 0), "n_out": n_out,
        "bpd": (P["n_balls"] / n_out) if n_out >= _MIN_OUTS_FOR_BPD and P.get("n_balls") else None,
        "false_pct": false_pct,
        "area": (f"{area[0]} ({area[1]:.0f}% of runs)") if area else None,
        # false-shot rate only — a short-ball sample of 40-90 balls carries 0-2 dismissals, so any
        # BPD off it would be noise dressed as a number
        "short": _short_read(P),
        "top_out": (f"{top[0]} ({100 * top[1] / sum(dis.values()):.0f}%)") if top and sum(dis.values()) else None,
    }


def build(opp, group):
    about = json.load(open(os.path.join(HERE, "data", f"opponent_about_{opp}.json"), encoding="utf-8"))
    batters = about.get("batters", {})
    label = (MACRO_GROUPS.get(group) or BOWLER_GROUPS.get(group) or (None, group))[1]
    rows = []
    for bid, meta in sorted(batters.items(), key=lambda kv: -(kv[1].get("order") or 0)):
        name = (meta.get("name") or bid).strip()
        try:
            P = build_batter_profile(bid, group=group)
        except Exception as e:
            print(f"  ! {name}: {type(e).__name__}: {str(e)[:60]}")
            rows.append({"name": name, "sub": meta.get("hand", ""), "balls": 0,
                         "plan": None, "field": None})
            continue
        balls = int(P.get("n_balls") or 0)
        thin = balls < MIN_BALLS
        rows.append({"name": name,
                     "sub": " · ".join(x for x in (meta.get("hand"), meta.get("role")) if x),
                     "balls": balls,
                     "plan": None if thin else plan_sentence(P),
                     "field": None if thin else _fielding_cell(P, group),
                     "threat": _threat(P) if balls else None})
        # Short balls from ONE pace sub-type are too few to rate, so fall back to the batter's
        # whole pace record for that column and say so — an unanswered bouncer question is worse
        # than a wider-but-labelled one.
        t = rows[-1]["threat"]
        if t and not t["short"] and group in _PACE_SUBS:
            try:
                s = _short_read(build_batter_profile(bid, group="pace"))
                if s:
                    t["short"] = f"{s} — vs all pace"
            except Exception:
                pass
        print(f"  {name:22} balls={balls:5} plan={'y' if rows[-1]['plan'] else '-'} "
              f"field={'y' if rows[-1]['field'] else '-'}")

    body = [f'<h1>{html.escape(label.capitalize())} meeting overview'
            f'<span class="sub">One row per batter — the plan against {html.escape(label)}, and the '
            f'field placements it implies. Same numbers as each batter\'s own report.</span></h1>',
            '<div class=owrap><table class=ov>',
            '<tr><th>Batter</th><th>Bowling plan</th><th>Key field placements</th></tr>']
    for r in rows:
        if r["balls"] < MIN_BALLS:
            cell = (f'<td colspan=2 class=thin>Only {r["balls"]} balls faced vs {html.escape(label)} '
                    f'— too little to set a plan from.</td>') if r["balls"] else \
                   f'<td colspan=2 class=thin>No record vs {html.escape(label)}.</td>'
        else:
            cell = (f'<td>{r["plan"] or "<span class=thin>No clear length/line target.</span>"}</td>'
                    f'<td class=fld>{r["field"] or "<span class=thin>Too few balls to set a field.</span>"}</td>')
        body.append(f'<tr><td class=bat>{html.escape(r["name"])}'
                    f'<span>{html.escape(r["sub"] or "")}</span></td>{cell}</tr>')
    body.append('</table></div>')

    # second table — how they score and get out against this type
    body.append(f'<h2 class=ov2>How they score and get out vs {html.escape(label)}</h2>'
                f'<p class=sub2>False-shot rate and scoring area settle at these sample sizes. '
                f'Balls per dismissal needs {_MIN_OUTS_FOR_BPD}+ dismissals to mean anything, so below '
                f'that the raw count is shown instead.</p>'
                '<div class=owrap><table class=ov>'
                '<tr><th>Batter</th><th>Balls</th><th>BPD</th><th>False shot</th>'
                '<th>Scores mostly</th><th>Vs the short ball</th><th>Most often out</th></tr>')
    for r in rows:
        t = r["threat"]
        if not t:
            body.append(f'<tr><td class=bat>{html.escape(r["name"])}</td>'
                        f'<td colspan=6 class=thin>No record vs {html.escape(label)}.</td></tr>')
            continue
        if r["balls"] < MIN_BALLS:            # rates off a handful of balls would read as fact
            body.append(f'<tr><td class=bat>{html.escape(r["name"])}</td><td>{t["balls"]}</td>'
                        f'<td colspan=5 class=thin>Too few balls vs {html.escape(label)} to rate.</td></tr>')
            continue
        bpd = f'{t["bpd"]:.0f}' if t["bpd"] else f'<span class=thin>{t["n_out"]} out</span>'
        body.append(
            f'<tr><td class=bat>{html.escape(r["name"])}</td>'
            f'<td>{t["balls"]}</td><td>{bpd}</td>'
            f'<td>{f"{t['false_pct']:.1f}%" if t["false_pct"] is not None else "<span class=thin>—</span>"}</td>'
            f'<td>{html.escape(t["area"]) if t["area"] else "<span class=thin>—</span>"}</td>'
            f'<td>{html.escape(t["short"]) if t["short"] else "<span class=thin>too few</span>"}</td>'
            f'<td>{html.escape(t["top_out"]) if t["top_out"] else "<span class=thin>—</span>"}</td></tr>')
    body.append('</table></div>')

    body.append(f'<p class=note>Plan and field come from the same functions as the individual reports. '
                f'A batter needs {MIN_BALLS}+ balls vs {html.escape(label)} to carry a plan. '
                f'Field placements are the evidenced moves off the stock field — the reasoning behind '
                f'each one is in that batter\'s report.</p>')

    out = os.path.join(HERE, "reports", f"overview_{group}_{opp}.html")
    open(out, "w", encoding="utf-8").write(
        _page(f"{label.capitalize()} meeting overview", _CSS + "".join(body),
              up=("index.html", "Series")))
    print(f"wrote {out} · {len(rows)} batters, {sum(1 for r in rows if r['plan'])} with a plan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    ap.add_argument("--group", default="pace", help="pace · spin · left_pace · right_pace · off_spin …")
    a = ap.parse_args()
    build(a.opp, a.group)


if __name__ == "__main__":
    main()
