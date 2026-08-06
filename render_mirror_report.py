"""Render a scouting report from a mirror-sourced profile artefact.

A **consumer**: it reads a published artefact (`artefact.load`) and renders a document. It does
no analysis and touches no data source — that is the profile's job. This is the seam from
`../FUTURE_PROJECTS.md` §"should playerprofile split?" working end to end, with the profile
coming from the cricket21 mirror rather than the warehouse.

    python render_mirror_report.py --name "Amite Hasan" --role batter
    python render_mirror_report.py --all

Writes `reports/<slug>_mirror.html` and a PDF beside it (both gitignored).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import artefact
from report_style import REPORT_CSS

ROOT = Path(__file__).parent
OUT = ROOT / "reports"

# The two uncapped players in Bangladesh's Test squad.
TARGETS = [("Amite Hasan", "batter"), ("Musfik Hasan", "bowler")]

# A dismissal count this low makes an average unstable; say so rather than implying precision.
THIN_DISMISSALS = 15


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _bar_table(mix: dict, caption: str, note: str = "") -> str:
    if not mix:
        return ""
    total = sum(mix.values()) or 1
    rows = []
    for label, n in mix.items():
        pct = 100 * n / total
        rows.append(
            f"<tr><td>{_esc(label)}</td>"
            f"<td class='num'>{n}</td><td class='num'>{pct:.0f}%</td>"
            f"<td class='barcell'><span class='bar' style='width:{pct:.1f}%'></span></td></tr>")
    return (f"<h3>{_esc(caption)}</h3>"
            + (f"<p class='note'>{_esc(note)}</p>" if note else "")
            + "<table class='t'><thead><tr><th>Band</th><th class='num'>Balls</th>"
              "<th class='num'>Share</th><th></th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def _cards(items) -> str:
    out = []
    for label, value, sub in items:
        out.append(f"<div class='card'><div class='clabel'>{_esc(label)}</div>"
                   f"<div class='cval'>{_esc(value)}</div>"
                   f"<div class='csub'>{_esc(sub)}</div></div>")
    return f"<div class='cards'>{''.join(out)}</div>"


def _batter_body(P: dict) -> str:
    n, runs, outs = P["n_balls"], P["runs"], P["dismissals"] or 0
    bpd = round(n / outs, 1) if outs else None
    ps = P.get("vs_pace_spin") or {}
    pace, spin = ps.get("pace"), ps.get("spin")

    cards = _cards([
        ("Matches", P["matches"], "first-class"),
        ("Runs", f"{runs:,}", f"from {n:,} balls"),
        ("Average", P["average"] or "—", f"{outs} dismissals"),
        ("BPD", bpd or "—", "balls per dismissal"),
        ("Strike rate", P["strike_rate"] or "—", "runs per 100 balls"),
    ])

    # The pace/spin read, hedged to the dismissal counts behind it.
    read = ""
    if pace and spin:
        thin = min(pace["dismissals"], spin["dismissals"]) < THIN_DISMISSALS
        faster = "pace" if (pace["sr"] or 0) > (spin["sr"] or 0) else "spin"
        slower = "spin" if faster == "pace" else "pace"
        rows = "".join(
            f"<tr><td>{lbl}</td><td class='num'>{d['balls']}</td><td class='num'>{d['runs']}</td>"
            f"<td class='num'>{d['dismissals']}</td><td class='num'>{d['avg'] or '—'}</td>"
            f"<td class='num'>{round(d['balls']/d['dismissals'],1) if d['dismissals'] else '—'}</td>"
            f"<td class='num'>{d['sr'] or '—'}</td></tr>"
            for lbl, d in (("Pace", pace), ("Spin", spin)))
        read = (
            "<h3>Against pace and spin</h3>"
            "<table class='t'><thead><tr><th>Type</th><th class='num'>Balls</th>"
            "<th class='num'>Runs</th><th class='num'>Dismissals</th><th class='num'>Average</th>"
            "<th class='num'>BPD</th><th class='num'>SR</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            f"<p>They score faster against {faster} (SR {ps[faster]['sr']}) than against "
            f"{slower} (SR {ps[slower]['sr']}), and the averages sit "
            f"{'close together' if abs((pace['avg'] or 0)-(spin['avg'] or 0)) < 8 else 'apart'} "
            f"({pace['avg']} vs {spin['avg']}).</p>")
        if thin:
            read += ("<p class='warn'>Both splits rest on around ten dismissals each. An average "
                     "on that many outs moves a long way on one or two innings, so treat the gap "
                     "as unresolved rather than as a weakness to bowl at. The strike rates, which "
                     "rest on hundreds of balls, are the firmer half of this table.</p>")
    return cards + read


def _bowler_body(P: dict) -> str:
    n, runs, wkts = P["n_balls"], P["runs"], P["wickets"] or 0
    cards = _cards([
        ("Matches", P["matches"], "first-class"),
        ("Balls bowled", f"{n:,}", f"{runs} runs conceded"),
        ("Wickets", wkts, "in the mirrored record"),
        ("Economy", P["economy"] or "—", "runs per over"),
        ("Bowl SR", P["bowl_strike_rate"] or "—", "balls per wicket"),
    ])
    body = ("<h3>What the record says</h3>"
            f"<p>Across {P['matches']} first-class matches they have conceded "
            f"{P['economy']} an over, which is containing, while taking a wicket every "
            f"{P['bowl_strike_rate']} balls, which is a long time between strikes. Together "
            f"those describe a bowler who has held an end rather than broken partnerships, "
            f"on this evidence.</p>")
    if wkts < 10:
        body += ("<p class='warn'>This is a small sample: "
                 f"{wkts} wickets from {n:,} balls. A bowling average built on {wkts} wickets "
                 "carries very little weight, and it is quoted here for completeness rather than "
                 "as a reliable measure. The economy rate and the length mix are the parts of "
                 "this report worth planning against.</p>")
    return cards + body


def render(name: str, role: str) -> Path:
    pid = f"c21:{name.replace(' ', '_')}"
    env = artefact.load(role, pid)
    P = env["profile"]
    cov = P["coverage"]

    comps = "".join(
        f"<tr><td>{_esc(c['comp'])}</td><td>{_esc(c['format'])}</td>"
        f"<td class='num'>{c['balls']}</td></tr>" for c in P["competitions"])

    body = _batter_body(P) if role == "batter" else _bowler_body(P)

    length_note = ("Where the ball pitched — how far down the pitch it bounced."
                   if role == "batter" else
                   "Where they pitched it — how far down the pitch the ball bounced.")
    line_note = ("Pitching line, not where the ball passed the stumps."
                 if role == "batter" else
                 "Pitching line, not where the ball passed the stumps.")

    dis = P.get("dismissal_counts") or {}
    dis_html = ""
    if dis:
        rows = "".join(f"<tr><td>{_esc(k)}</td><td class='num'>{v}</td></tr>"
                       for k, v in dis.items())
        dis_html = ("<h3>How they have been dismissed</h3>" if role == "batter"
                    else "<h3>How their wickets have come</h3>") + \
                   f"<table class='t'><thead><tr><th>Type</th><th class='num'>Count</th></tr>" \
                   f"</thead><tbody>{rows}</tbody></table>"

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{_esc(name)} — first-class record</title>
<style>{REPORT_CSS}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}}
.card{{background:#fff;border:1px solid rgba(0,0,0,.10);border-radius:8px;padding:10px 14px;min-width:120px}}
.clabel{{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em}}
.cval{{font-size:22px;font-weight:600;color:#1a1a2e}}
.csub{{font-size:11px;color:#6b7280}}
table.t{{width:100%;border-collapse:collapse;margin:8px 0 16px}}
table.t th,table.t td{{padding:6px 8px;border-bottom:1px solid rgba(0,0,0,.08);text-align:left}}
table.t th{{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#6b7280}}
.num{{text-align:right}}
.barcell{{width:40%}} .bar{{display:block;height:9px;background:#003087;border-radius:2px}}
.note{{font-size:12px;color:#6b7280;margin:2px 0 6px}}
.warn{{background:#fff8e1;border-left:3px solid #c99700;padding:8px 12px;font-size:13px}}
.src{{font-size:11px;color:#6b7280;border-top:1px solid rgba(0,0,0,.10);margin-top:22px;padding-top:8px}}
</style></head><body><div class="wrap">
<h1>{_esc(name)}</h1>
<p class="sub">Uncapped — first-class record. Prepared for the Bangladesh Test series.</p>
{body}
{_bar_table(P.get('pitch_length_mix'), 'Length', length_note)}
{_bar_table(P.get('pitch_line_mix'), 'Pitching line', line_note)}
{dis_html}
<h3>Where this comes from</h3>
<table class='t'><thead><tr><th>Competition</th><th>Format</th><th class='num'>Balls</th></tr>
</thead><tbody>{comps}</tbody></table>
<p class="src"><b>Source and limits.</b> {_esc(P['source'])} — the warehouse holds no Bangladesh
domestic cricket, so this record comes from the Cricket-21 mirror.
{cov['balls_tracked']:,} of {P['n_balls']:,} balls carry pitching coordinates
({cov['tracked_pct']}%), and {cov['balls_with_video']:,} have vision available
({cov['video_pct']}%). {_esc(cov['note'])} Ball-tracking here is line and length only, so there
is no beehive, no release point and no swing or seam movement in this report.</p>
</div></body></html>"""

    OUT.mkdir(parents=True, exist_ok=True)
    slug = name.lower().replace(" ", "_")
    out = OUT / f"{slug}_mirror.html"
    out.write_text(html, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--role", choices=["batter", "bowler"])
    ap.add_argument("--all", action="store_true", help="render both uncapped BAN players")
    ap.add_argument("--pdf", action="store_true", help="also render a PDF")
    args = ap.parse_args()

    targets = TARGETS if args.all else [(args.name, args.role)]
    for name, role in targets:
        path = render(name, role)
        print(f"  {name} ({role}) -> {path}")
        if args.pdf:
            from cricket_core.pdf import html_to_pdf
            pdf = path.with_suffix(".pdf")
            html_to_pdf(path.read_text(encoding="utf-8"), str(pdf))
            print(f"    pdf -> {pdf}")


if __name__ == "__main__":
    main()
