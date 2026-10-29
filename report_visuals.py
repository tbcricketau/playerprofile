"""Pictures for the web scouting report's batting page (report_web.py), Tom's 16-10-2026 ask for more
visuals and fewer tables. Each returns markup to drop into a section; report_web puts it on a
Chart / Table switch with the table it summarises, so the exact numbers stay one click away.

    danger_map(rows, lhb, is_spin)   length by pitching line, drawn on the strip, shaded by BPD
    stumps_view(sets, lhb)           where the ball passed the stumps, shaded by BPD
    catch_map(rows, lhb)             where they were caught, on a ground plan, and how they got out
    type_bars(P)                     the average against each bowler type, as bars

Shading is BPD (balls per dismissal) against the batter's own BPD for the same balls, so a cell reads
"out quicker than usual" or "lasts longer than usual" whatever the batter's overall level. Bowler at the
bottom, striker at the top, off side on the viewer's left for a right-hander (root CLAUDE.md).
Stdlib only.
"""
import html
import math

from batter_profile import _split_stats

E = lambda s: html.escape(str(s), quote=True)

# the hub's greens and the report's danger red
INK, MUTED = "#122219", "#5a6b61"
FIELD, FIELD_EDGE, STRIP, STRIP_EDGE = "#bad39a", "#a3c47f", "#f2efbf", "#e2dca0"
THIN = "#e9ece8"
FONT_D = "Barlow Condensed, Barlow, sans-serif"
FONT = "Barlow, Segoe UI, sans-serif"

# the key: BPD in a cell against the batter's own BPD on the same balls
BANDS = ((0.5, "#b5452f", "#fff", "Out much quicker than usual (under half their BPD)"),
         (0.8, "#e3896c", INK, "Out quicker than usual"),
         (1.25, "#f6f1d0", INK, "About usual"),
         (9e9, "#9cc47e", INK, "Last longer than usual"))
NO_OUTS = ("#6fa35a", "#fff", "No dismissals")

LENGTHS = ("Full", "Good length", "Back of a length", "Short")
LINES = ("wide outside off", "outside off", "in the channel", "on the stumps", "down the leg side")
LINE_HEAD = {"wide outside off": "Wide off", "outside off": "Off", "in the channel": "Channel",
             "on the stumps": "Stumps", "down the leg side": "Leg"}


def _bpd(s):
    return s["balls"] / s["outs"] if s.get("outs") else None


def _shade(s, usual, min_balls):
    """(fill, ink) for a cell, or None when it is too thin to say."""
    if s["balls"] < min_balls:
        return None
    if not s["outs"]:
        return NO_OUTS[:2]
    b = _bpd(s)
    r = b / usual if usual else 1.0
    for cut, fill, ink, _l in BANDS:
        if r < cut:
            return fill, ink
    return BANDS[-1][1:3]


def key(usual_word, extra=""):
    """The colour key under a picture, as HTML so it wraps at any width."""
    sw = lambda fill, t: (f"<span class='k'><i style='background:{fill}'></i>{E(t)}</span>")
    items = [sw(f, l) for _c, f, _i, l in BANDS] + [sw(NO_OUTS[0], NO_OUTS[2]), sw(THIN, "Under 20 balls")]
    return (f"<div class='vkey'>{''.join(items)}</div>"
            f"<p class='note'>Shaded by BPD (balls per dismissal) against their usual BPD {E(usual_word)}. {extra}</p>")


def _svg(w, h, body, label):
    return (f"<svg class='vx' viewBox='0 0 {w} {h}' role='img' aria-label='{E(label)}' "
            f"style='font-family:{FONT}'>{body}</svg>")


# ── 1. danger map ───────────────────────────────────────────────────────────────────────────────
def danger_map(rows, lhb, is_spin=False, min_balls=20):
    """Length by pitching line on the strip, stumps at the top. Columns are equal width (to scale the
    channel is a sliver), off side on the left for a right-hander."""
    rows = [r for r in rows if r.get("is_legal") and r.get("length_band") and r.get("line_region")]
    if len(rows) < 120:
        return ""
    usual = _bpd(_split_stats(rows))
    cells = {}
    for r in rows:
        cells.setdefault((r["length_band"], r["line_region"]), []).append(r)
    lines = list(LINES) if not lhb else list(reversed(LINES))
    lengths = [l for l in LENGTHS if any(k[0] == l for k in cells)]
    W, top, cw, ch, lx = 600, 74, 92, 92, 128
    x0 = lx
    H = top + ch * len(lengths) + 40
    o = [f"<rect width='{W}' height='{H}' fill='{FIELD}'/>",
         f"<rect x='{x0 - 8}' y='{top - 46}' width='{cw * 5 + 16}' height='{ch * len(lengths) + 62}' fill='{STRIP}' "
         f"stroke='{STRIP_EDGE}'/>"]
    # stumps and crease over the stumps column, at the top
    sx = x0 + cw * lines.index("on the stumps") + cw / 2
    o.append(f"<line x1='{x0 - 8}' y1='{top - 14}' x2='{x0 + cw * 5 + 8}' y2='{top - 14}' stroke='#fff' stroke-width='3'/>")
    for k in (-1, 0, 1):
        o.append(f"<circle cx='{sx + k * 9}' cy='{top - 32}' r='3.4' fill='{INK}'/>")
    # column heads, above the strip
    for i, ln in enumerate(lines):
        o.append(f"<text x='{x0 + cw * i + cw / 2}' y='18' text-anchor='middle' font-size='13' font-weight='700' "
                 f"font-family=\"{FONT_D}\" fill='{INK}' letter-spacing='.04em'>{E(LINE_HEAD[ln].upper())}</text>")
    lowest = None
    for j, lb in enumerate(lengths):
        y = top + ch * j
        o.append(f"<text x='{lx - 14}' y='{y + ch / 2 + 5}' text-anchor='end' font-size='14' font-weight='700' "
                 f"font-family=\"{FONT_D}\" fill='{INK}'>{E(lb.upper())}</text>")
        for i, ln in enumerate(lines):
            x = x0 + cw * i
            s = _split_stats(cells.get((lb, ln), []))
            sh = _shade(s, usual, min_balls)
            fill, ink = sh or (THIN, MUTED)
            o.append(f"<rect x='{x + 2}' y='{y + 2}' width='{cw - 4}' height='{ch - 4}' rx='4' fill='{fill}' "
                     f"opacity='{0.94 if sh else 0.8}'/>")
            if not sh:
                o.append(f"<text x='{x + cw / 2}' y='{y + ch / 2 + 5}' text-anchor='middle' font-size='13' "
                         f"fill='{MUTED}'>{s['balls'] or '–'}</text>")
                continue
            big = f"{_bpd(s):.0f}" if s["outs"] else "–"
            o.append(f"<text x='{x + cw / 2}' y='{y + ch / 2 - 2}' text-anchor='middle' font-size='30' font-weight='700' "
                     f"font-family=\"{FONT_D}\" fill='{ink}'>{big}</text>")
            o.append(f"<text x='{x + cw / 2}' y='{y + ch / 2 + 18}' text-anchor='middle' font-size='12' fill='{ink}' "
                     f"opacity='.9'>{s['outs']} out · {s['balls']} balls</text>")
            if s["outs"] >= 2 and (lowest is None or _bpd(s) < lowest[0]):
                lowest = (_bpd(s), x, y)
    if lowest:
        _b, x, y = lowest
        o.append(f"<rect x='{x + 1}' y='{y + 1}' width='{cw - 2}' height='{ch - 2}' rx='5' fill='none' "
                 f"stroke='#e9b311' stroke-width='4'/>")
    o.append(f"<text x='{x0 + cw * 2.5}' y='{H - 12}' text-anchor='middle' font-size='12' fill='{MUTED}'>"
             f"▲ bowler</text>")
    word = "against spin" if is_spin else "against pace"
    return (_svg(W, H, "".join(o), "Balls per dismissal by length and pitching line")
            + key(f"{word} ({usual:.0f})" if usual else word,
                  "The number is the BPD, with dismissals and balls under it. The gold box is the lowest BPD on two "
                  "dismissals or more."))


# ── 2. stumps view ──────────────────────────────────────────────────────────────────────────────
S_LINES = (("Wide outside off", -9.0, -0.40), ("Outside off", -0.40, -0.15), ("Stumps", -0.15, 0.15),
           ("Leg side", 0.15, 9.0))
S_HEIGHTS = (("Head high", 1.25, 2.5), ("Over stumps", 0.75, 1.25), ("Top half", 0.38, 0.75),
             ("Bottom half", 0.0, 0.38))
S_HEAD = ("Wide off", "Off", "Stumps", "Leg")


def _stumps_panel(rows, lhb, title, min_balls, ox):
    cells, n = {}, 0
    for r in rows:
        ln, ht = r.get("at_stumps_line_m"), r.get("at_stumps_height_m")
        if ln is None or ht is None or ht <= 0 or ht > 2.5 or abs(ln) > 3:
            continue
        n += 1
        a = next(i for i, (_l, lo, hi) in enumerate(S_LINES) if lo <= ln < hi)
        b = next(i for i, (_l, lo, hi) in enumerate(S_HEIGHTS) if lo <= ht < hi)
        cells.setdefault((b, a), []).append(r)
    tracked = [r for v in cells.values() for r in v]
    if n < 120:
        return "", None
    usual = _bpd(_split_stats(tracked))
    order = list(range(4)) if not lhb else list(reversed(range(4)))   # off side on the left for RHB
    cw, ch, top = 64, 60, 30
    o = [f"<text x='{ox + cw * 2}' y='18' text-anchor='middle' font-size='14' font-weight='700' "
         f"font-family=\"{FONT_D}\" fill='{INK}' letter-spacing='.05em'>{E(title.upper())}</text>"]
    for b in range(4):
        for k, a in enumerate(order):
            x, y = ox + cw * k, top + ch * b
            s = _split_stats(cells.get((b, a), []))
            sh = _shade(s, usual, min_balls)
            fill, ink = sh or (THIN, MUTED)
            o.append(f"<rect x='{x + 1.5}' y='{y + 1.5}' width='{cw - 3}' height='{ch - 3}' rx='3' fill='{fill}' "
                     f"opacity='{0.92 if sh else 0.75}'/>")
            if sh:
                big = f"{_bpd(s):.0f}" if s["outs"] else "–"
                o.append(f"<text x='{x + cw / 2}' y='{y + ch / 2 + 2}' text-anchor='middle' font-size='22' "
                         f"font-weight='700' font-family=\"{FONT_D}\" fill='{ink}'>{big}</text>"
                         f"<text x='{x + cw / 2}' y='{y + ch / 2 + 17}' text-anchor='middle' font-size='10' "
                         f"fill='{ink}'>{s['outs']} · {s['balls']}</text>")
    # the stumps: a white frame round the two areas that would hit them, so no number is covered
    k = order.index(2)
    o.append(f"<rect x='{ox + cw * k}' y='{top + ch * 2}' width='{cw}' height='{ch * 2}' rx='4' fill='none' "
             f"stroke='#fff' stroke-width='3.5'/>")
    for kk, a in enumerate(order):
        o.append(f"<text x='{ox + cw * kk + cw / 2}' y='{top + ch * 4 + 16}' text-anchor='middle' font-size='11.5' "
                 f"font-weight='700' font-family=\"{FONT_D}\" fill='{INK}' letter-spacing='.04em'>"
                 f"{E(S_HEAD[a].upper())}</text>")
    return "".join(o), usual


def stumps_view(sets, lhb, min_balls=20):
    """`sets` is [(title, rows)]: one panel each (v pace and v spin on the all-bowling page)."""
    panels, usuals, ox = [], [], 92
    for title, rows in sets:
        p, u = _stumps_panel(rows, lhb, title, min_balls, ox)
        if p:
            panels.append(p)
            usuals.append((title, u))
            ox += 64 * 4 + 28
    if not panels:
        return ""
    W, H = ox - 28 + 8, 30 + 60 * 4 + 46
    rowlab = "".join(f"<text x='84' y='{30 + 60 * b + 34}' text-anchor='end' font-size='12' font-weight='700' "
                     f"font-family=\"{FONT_D}\" fill='{INK}'>{E(t.upper())}</text>" for b, (t, _lo, _hi) in enumerate(S_HEIGHTS))
    side = "off side on the left" if not lhb else "off side on the right"
    foot = (f"<text x='{W / 2}' y='{H - 8}' text-anchor='middle' font-size='12' fill='{MUTED}'>"
            f"From the bowler's end · {side}</text>")
    body = f"<rect width='{W}' height='{H}' fill='{FIELD}'/>" + rowlab + "".join(panels) + foot
    uw = " · ".join(f"{t.lower()} {u:.0f}" for t, u in usuals if u)
    return (_svg(W, H, body, "Balls per dismissal by where the ball passed the stumps")
            + key(f"({uw})", "Each area shows the BPD, then dismissals · balls. The columns are where the ball "
                  "passed the stumps, from ball tracking. The white frame is the stumps."))


# ── 3. where they were caught ───────────────────────────────────────────────────────────────────
_HOW_ORDER = (("Bowled", "#7a2a1c"), ("LBW", "#b5452f"), ("Caught behind", "#e3896c"),
              ("Caught in the field", "#e9b311"), ("Other", "#9aa79f"))


def _how(r):
    h = r.get("how_out") or ""
    if h in ("Bowled", "LBW"):
        return h
    if h == "Caught":
        return {"behind": "Caught behind", "field": "Caught in the field"}.get(r.get("catch_group"), "Caught in the field")
    return "Other"


def catch_map(rows, lhb):
    """Each catch at its fielding position on a ground plan, sized by how many; a bar of how they got
    out beneath. Pitch centred, striker one half-pitch above the middle (field_engine.field_diagram)."""
    from cricket_core.lookups import field_coords
    outs = [r for r in rows if r.get("is_out") and r.get("how_out")]
    if len(outs) < 5:
        return ""
    spots = {}
    for r in outs:
        if r.get("how_out") == "Caught" and r.get("catch_position"):
            spots[r["catch_position"]] = spots.get(r["catch_position"], 0) + 1
    S, R, D = 460, 200, 0.14
    c = S / 2
    mirror = -1 if not lhb else 1

    def place(radius, ang):
        th = math.radians(ang)
        tb = D * math.cos(th) + math.sqrt(max(0.0, 1 - (D * math.sin(th)) ** 2))
        d = radius * tb
        return c + R * mirror * d * math.sin(th), c + R * (-D + d * math.cos(th))

    o = [f"<rect width='{S}' height='{S}' fill='#fff'/>",
         f"<circle cx='{c}' cy='{c}' r='{R}' fill='{FIELD}' stroke='{FIELD_EDGE}' stroke-width='2'/>",
         f"<ellipse cx='{c}' cy='{c}' rx='{R * 0.6:.0f}' ry='{R * 0.64:.0f}' fill='none' stroke='#fff' "
         f"stroke-width='1.4' stroke-dasharray='4 4'/>",
         f"<rect x='{c - 6}' y='{c - R * D:.0f}' width='12' height='{2 * R * D:.0f}' fill='{STRIP}' stroke='{STRIP_EDGE}'/>"]
    side = ("Off side", "Leg side") if not lhb else ("Leg side", "Off side")
    o.append(f"<text x='14' y='22' font-size='12' font-weight='700' font-family=\"{FONT_D}\" fill='{MUTED}' "
             f"letter-spacing='.05em'>{side[0].upper()}</text><text x='{S - 14}' y='22' text-anchor='end' font-size='12' "
             f"font-weight='700' font-family=\"{FONT_D}\" fill='{MUTED}' letter-spacing='.05em'>{side[1].upper()}</text>")
    mx = max(spots.values()) if spots else 1
    for pos, n in sorted(spots.items(), key=lambda kv: kv[1]):
        fc = field_coords(pos)
        radius = fc["radius"]
        if pos.lower().startswith("keeper"):
            radius = 0.17
        x, y = place(radius, fc["angle"])
        rr = 7 + 9 * math.sqrt(n / mx)
        o.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{rr:.1f}' fill='#b5452f' stroke='#fff' stroke-width='1.6'>"
                 f"<title>{E(pos)}: {n}</title></circle>")
        o.append(f"<text x='{x:.1f}' y='{y + 4.5:.1f}' text-anchor='middle' font-size='13' font-weight='700' "
                 f"font-family=\"{FONT_D}\" fill='#fff'>{n}</text>")
        if n >= 2 or len(spots) <= 8:
            name = pos.split(":")[-1].strip() if ":" in pos else pos
            name = {"regulation": pos.split(":")[0].strip(), "deep": "deep " + pos.split(":")[0].strip()}.get(name, name)
            o.append(f"<text x='{x:.1f}' y='{y - rr - 4:.1f}' text-anchor='middle' font-size='11' fill='{INK}' "
                     f"stroke='{FIELD}' stroke-width='3' paint-order='stroke'>{E(name.capitalize())}</text>")
    o.append(f"<text x='{c}' y='{S - 14}' text-anchor='middle' font-size='12' fill='{MUTED}'>▲ bowler</text>")
    # how they got out, as one bar
    counts = {}
    for r in outs:
        counts[_how(r)] = counts.get(_how(r), 0) + 1
    tot = sum(counts.values())
    segs = "".join(f"<span style='flex:{counts[k]};background:{col}' title='{E(k)}: {counts[k]}'></span>"
                   for k, col in _HOW_ORDER if counts.get(k))
    leg = "".join(f"<span class='k'><i style='background:{col}'></i>{E(k)} {counts[k]} ({counts[k] / tot * 100:.0f}%)</span>"
                  for k, col in _HOW_ORDER if counts.get(k))
    unplaced = sum(1 for r in outs if r.get("how_out") == "Caught" and not r.get("catch_position"))
    note = (f"<p class='note'>Each dot is a fielding position where they were caught, the number how many times. "
            + (f"{unplaced} catch{'es' if unplaced != 1 else ''} had no position recorded. " if unplaced else "")
            + "</p>")
    return (_svg(S, S, "".join(o), "Where they were caught").replace("class='vx'", "class='vx ground'")
            + f"<div class='hbar'>{segs}</div>"
            f"<div class='vkey'>{leg}</div>" + note)


# ── 4. bowler types as bars ─────────────────────────────────────────────────────────────────────
def type_bars(rows_by_type, career_avg, min_balls=300):
    """`rows_by_type` is [(label, stats)] with stats from _split_stats; a bar per type to the average,
    a mark at the career average, the lowest (on `min_balls` or more) shaded."""
    rows = [(l, s) for l, s in rows_by_type if s.get("avg") is not None]
    if len(rows) < 2:
        return ""
    mx = max(max(s["avg"] for _l, s in rows), career_avg or 0) * 1.08
    scored = [s["avg"] for _l, s in rows if s["balls"] >= min_balls]
    lo = min(scored) if scored else None
    mark = f"<b style='left:{career_avg / mx * 100:.1f}%'></b>" if career_avg else ""
    out = []
    for l, s in rows:
        thin = s["balls"] < min_balls
        cls = " lo" if lo is not None and s["avg"] == lo and not thin else (" thin" if thin else "")
        out.append(f"<div class='tb{cls}'><div class='n'>{l}</div><div class='bar'>"
                   f"<i style='width:{s['avg'] / mx * 100:.1f}%'></i>{mark}</div>"
                   f"<div class='v'>{s['avg']:.1f}<small>{s['balls']:,} balls</small></div></div>")
    return (f"<div class='tbars'>{''.join(out)}</div><p class='note'>Average against each type. The dark mark is "
            f"their career average{f' ({career_avg:.1f})' if career_avg else ''}. The red bar is the lowest on "
            f"{min_balls} balls or more. A faded bar is under {min_balls} balls.</p>")
