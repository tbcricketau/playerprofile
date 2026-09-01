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
import time

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
 .fld{color:#1a1a2e}
 /* inline label — a fixed label gutter left too little width for the value in a narrow column */
 .fl{padding:1px 0;font-size:13px;line-height:1.45}
 .fl .k{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:#9aa4b2;
   font-weight:650;margin-right:5px}
 .fl .v{font-size:13px}
 .note{color:#9ca3af;font-size:12px;margin-top:16px}
 h2.ov2{font-size:16px;color:#003087;margin:26px 0 2px}
 .sub2{color:#6b7280;font-size:13px;margin:0 0 6px}
 h1 .sub{display:block;font-size:14px;color:#6b7280;font-weight:400;margin-top:4px}
</style>"""


def _field_images(P, group, img_dir, bid):
    """Render each suggested field to a PNG file so the pack can open it as an overlay. Files, not
    data-URIs — one <img> per batter per phase would add megabytes of base64 to every bowling pack.
    Labels stay the descriptive ones (Early / Once set / Bouncer plan), matching the reports."""
    sub = {"is_lhb": P.get("is_lhb"), "batter_id": P.get("batter_id"),
           "raw": P.get("raw"), "caught_positions": P.get("caught_positions")}
    wanted, short_ball = [], None
    for phase, title in (("early", "Early — first 30 balls"), ("set", "Once set")):
        try:
            fs = field_engine.build_field(sub, group, phase)
        except Exception:
            fs = None
        if not fs:
            continue
        short_ball = short_ball or fs.get("short_ball")
        wanted.append((title, fs["field"]))
        if fs.get("alt"):
            wanted.append((f"{title} — alternative", fs["alt"]["field"]))
    if short_ball:
        wanted.append(("Bouncer plan", short_ball["field"]))
    os.makedirs(img_dir, exist_ok=True)
    out = []
    for i, (title, field) in enumerate(wanted):
        try:
            png = field_engine.field_diagram(field, P.get("is_lhb"), title="").to_image(
                format="png", width=340, height=340, scale=2)
        except Exception as e:
            print(f"     ! field image {title}: {type(e).__name__}: {str(e)[:40]}")
            continue
        fn = f"{group}_{bid}_{i}.png"       # group-qualified: the pack flattens all groups into one dir
        open(os.path.join(img_dir, fn), "wb").write(png)
        out.append({"label": title, "file": fn})
    return out


def _field_parts(P, group):
    """The field as three separate answers, because running them together behind dots hid what each
    one was: SET the orthodox field for this type, MOVE the one change the evidence supports, SPARE
    the fielder returning least. The reasoning behind each stays in the batter's own report."""
    sub = {"is_lhb": P.get("is_lhb"), "batter_id": P.get("batter_id"),
           "raw": P.get("raw"), "caught_positions": P.get("caught_positions")}
    try:
        f = field_engine.build_field(sub, group, "set")
    except Exception:
        f = None
    if not f:
        return None
    base = ""
    if f.get("base_note"):
        # the note carries its reasoning after an em dash — keep the variant name only
        base = str(f["base_note"]).split("—")[0].strip().rstrip(".")
    moves = [field_engine.pretty_position(x["position"])
             for x in (f.get("field") or []) if x.get("tag") == "change"]
    fl = (f.get("floating") or [None])[0]
    spare = field_engine.pretty_position(fl["position"]) if fl and fl.get("position") else ""
    if not (base or moves or spare):
        return None
    return {"set": base or "standard field",
            "move": ", ".join(moves) if moves else "",
            "spare": spare}


_MIN_OUTS_FOR_BPD = 4      # below this, a balls-per-dismissal figure is noise — show the count instead
_MIN_SHORT_BALLS = 40


from batter_profile import _PACE_SUBS, _SPIN_SUBS       # the canonical sub-type lists


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


def build(opp, group, only=None, fmt="Test"):
    """`only` = batter ids to (re)build, merging into the existing overview and leaving every other
    row as it was. Adding one player to a squad shouldn't re-profile the whole opposition."""
    about = json.load(open(os.path.join(HERE, "data", f"opponent_about_{opp}.json"), encoding="utf-8"))
    batters = about.get("batters", {})
    label = (MACRO_GROUPS.get(group) or BOWLER_GROUPS.get(group) or (None, group))[1]
    rows = []
    kept = []
    if only:
        prev = os.path.join(HERE, "data", f"overview_{group}_{opp}.json")
        kept = [r for r in json.load(open(prev, encoding="utf-8")).get("rows", [])
                if r.get("bid") not in only]
        batters = {b: m for b, m in batters.items() if b in only}
        print(f"merge mode: rebuilding {', '.join(m.get('name', b) for b, m in batters.items())} "
              f"— keeping {len(kept)} existing row(s)")
    for bid, meta in sorted(batters.items(), key=lambda kv: -(kv[1].get("order") or 0)):
        name = (meta.get("name") or bid).strip()
        # Retry: the warehouse connection drops intermittently, and a failed build must NOT be
        # written as a zero — "no record vs X" is a claim about the player, not about our pipeline.
        P, err = None, None
        for attempt in range(3):
            try:
                P = build_batter_profile(bid, group=group, fmt=fmt)
                break
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:60]}"
                if attempt < 2:
                    time.sleep(8)
        if P is None:
            print(f"  ! {name}: FAILED after 3 tries — {err}")
            rows.append({"bid": bid, "name": name, "sub": meta.get("hand", ""), "balls": 0,
                         "plan": None, "field": None, "threat": None, "error": True})
            continue
        balls = int(P.get("n_balls") or 0)
        thin = balls < MIN_BALLS
        # A spin sub-type carries almost no straight balls of its own (the arm ball / flipper /
        # undercutter is ~2% of spin, and splits away to nothing per type), so the movement clause
        # has nothing to compare against and never fires. Pool the straight reference from the whole
        # spin record; the turn DIRECTION still comes from this bowler's actual type.
        baseline = None
        if group in _SPIN_SUBS and not thin:
            try:
                baseline = build_batter_profile(bid, group="spin", fmt=fmt).get("dims")
            except Exception as e:
                print(f"     ! spin baseline for {name}: {type(e).__name__}")
        rows.append({"bid": bid, "name": name,
                     "sub": " · ".join(x for x in (meta.get("hand"), meta.get("role")) if x),
                     "balls": balls,
                     "plan": None if thin else plan_sentence(P, baseline=baseline),
                     "field": None if thin else _field_parts(P, group),
                     "fields": [] if thin else _field_images(
                         P, group, os.path.join(HERE, "reports", "fields", opp, group), bid),
                     "threat": _threat(P) if balls else None})
        # Short balls from ONE pace sub-type are too few to rate, so fall back to the batter's
        # whole pace record for that column and say so — an unanswered bouncer question is worse
        # than a wider-but-labelled one.
        t = rows[-1]["threat"]
        if t and not t["short"] and group in _PACE_SUBS:
            try:
                s = _short_read(build_batter_profile(bid, group="pace", fmt=fmt))
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
            f'<tr><th>Batter</th><th>Plan for {html.escape(label)}</th>'
            f'<th>Field options</th></tr>']
    for r in rows:
        if r["balls"] < MIN_BALLS:
            if r.get("error"):
                cell = ('<td colspan=2 class=thin>Profile could not be built — this is a pipeline '
                        'failure, not a gap in their record.</td>')
            elif r["balls"]:
                cell = (f'<td colspan=2 class=thin>Only {r["balls"]} balls faced vs '
                        f'{html.escape(label)} — too little to set a plan from.</td>')
            else:
                cell = f'<td colspan=2 class=thin>No record vs {html.escape(label)}.</td>'
        else:
            pre = f"Plan for {label}: "          # the header names the type — don't repeat it per row
            pl = r["plan"]
            if pl and pl.startswith(pre):
                pl = pl[len(pre):]
                pl = pl[:1].upper() + pl[1:]
            fp = r.get("field")
            if fp:
                fcell = "".join(
                    f'<div class=fl><span class=k>{k}</span><span class=v>{html.escape(v)}</span></div>'
                    for k, v in (("Set", fp.get("set")), ("Move", fp.get("move")),
                                 ("Spare", fp.get("spare"))) if v)
            else:
                fcell = '<span class=thin>Too few balls to set a field.</span>'
            cell = (f'<td>{pl or "<span class=thin>No clear length/line target.</span>"}</td>'
                    f'<td class=fld>{fcell}</td>')
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

    body.append('<p class=note><b>Set</b> — the orthodox field for this bowling type and phase. '
                '<b>Move</b> — the one change their record supports, from where their catches have '
                'actually been taken. <b>Spare</b> — the fielder returning least, so the first to '
                'relocate if you need someone elsewhere.</p>')
    body.append(f'<p class=note>Plan and field come from the same functions as the individual reports. '
                f'A batter needs {MIN_BALLS}+ balls vs {html.escape(label)} to carry a plan. '
                f'Field placements are the evidenced moves off the stock field — the reasoning behind '
                f'each one is in that batter\'s report.</p>')

    # Sanity check: a pace/spin sub-type can never exceed its macro group, and a batter with balls
    # against the macro but zero against BOTH sub-types means a build failed rather than a real gap.
    # Compare against the macro dataset if it's already been built.
    macro = "spin" if group in _SPIN_SUBS else ("pace" if group in _PACE_SUBS else None)
    if macro:
        mp = os.path.join(HERE, "data", f"overview_{macro}_{opp}.json")
        if os.path.exists(mp):
            mrows = {r["bid"]: r.get("balls") or 0 for r in json.load(open(mp, encoding="utf-8"))["rows"]}
            for r in rows:
                mb = mrows.get(r["bid"], 0)
                # only when the macro sample is real: a batter with 3 balls vs spin can legitimately
                # have 0 vs one sub-type, and a warning that cries wolf is one you stop reading
                if (r.get("balls") or 0) == 0 and mb >= 20:
                    print(f"  !! {r['name']}: 0 balls vs {group} but {mb} vs {macro} — "
                          f"suspect a failed build, NOT a real absence")

    # Don't let a bad run replace a good file. A warehouse drop mid-build fails every remaining
    # profile, and writing that over a previously-good dataset turns a transient outage into
    # persistent wrong data — which is how a good left_orthodox set was lost on 2026-08-04.
    n_err = sum(1 for r in rows if r.get("error"))
    if n_err and (only or n_err >= max(2, len(rows) // 3)):
        # in merge mode ANY failure aborts — one player is the whole run, so a failure is total
        raise SystemExit(
            f"ABORTING: {n_err}/{len(rows)} profile builds failed — almost certainly the warehouse "
            f"dropped, not a real absence of data. overview_{group}_{opp}.json left as it was; "
            f"re-run when the connection is back.")
    if only:
        rows = kept + rows          # merge; build_player_site sorts by batting order at render

    # structured rows so the packs can render the same content inline (with headshots) rather than
    # linking out to this page
    json.dump({"opp": opp, "group": group, "label": label, "min_balls": MIN_BALLS, "rows": rows},
              open(os.path.join(HERE, "data", f"overview_{group}_{opp}.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    out = os.path.join(HERE, "reports", f"overview_{group}_{opp}.html")
    open(out, "w", encoding="utf-8").write(
        _page(f"{label.capitalize()} meeting overview", _CSS + "".join(body),
              up=("index.html", "Series")))
    print(f"wrote {out} · {len(rows)} batters, {sum(1 for r in rows if r['plan'])} with a plan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    ap.add_argument("--group", default="pace", help="pace · spin · left_pace · right_pace · off_spin …")
    ap.add_argument("--only", default="", help="comma-separated batter ids — rebuild just these "
                                               "and merge, keeping every other row")
    ap.add_argument("--fmt", default="Test", choices=("Test", "ODI", "T20I"),
                    help="which format's internationals to profile (default: Test)")
    a = ap.parse_args()
    build(a.opp, a.group, only=[x.strip() for x in a.only.split(",") if x.strip()] or None,
          fmt=a.fmt)


if __name__ == "__main__":
    main()
