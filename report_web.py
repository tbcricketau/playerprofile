"""The scouting reports as web pages in the Coaches Hub's look (12-10-2026).

One page per player with a scope switch at the top (all batters / right-handers / left-handers for
a bowler; all bowling / one bowler type for a batter), sections in the order the round-2 mockup
settled (playerprofile/docs/PLAYER_PACK_REDESIGN.md, decision 7), the CricViz pictures drawn into
the page, the planner's coaches' notes and fields fetched when it opens, and the reels from the
coach bundle's clip lists.

The numbers come from the same helpers the A4 reports use (report.py, batting_report.py), so the
two never disagree; only the layout and the pictures are new. Served beside the A4 reports at
coach/<slug>/web/ until Scouting is switched over.

Pictures:
  * wicket pitch maps and beehives are CricViz SVG, inline (a few hundred dots at most)
  * the over/round pitch maps carry every ball, which is thousands of dots, so the dot view is a
    picture file (WebP) and the Density view is a light SVG drawn here
  * the release point and the play-and-miss grid are drawn here in the CricViz flat look

Stdlib only, apart from PIL for the WebP (it comes with python-pptx and is already in the venv).
"""
from __future__ import annotations

import html
import math

E = html.escape
REUSE_PICS = False      # True keeps an over/round picture already on disk (a rebuild of the words only)

# ── pitch-map density ─────────────────────────────────────────────────────────────────────────
# The strip geometry must match cricviz.pitch_map(metrics=False) exactly, so the density sits on
# the same strip the dot map draws. Those numbers are cricviz's own: the strip centred at half the
# width, 96% of the height spanning top_m..bottom_m.
_DENSITY_RAMP = ((0.00, (255, 246, 196, 0.0)), (0.15, (255, 230, 120, 0.55)), (0.40, (246, 170, 60, 0.75)),
                 (0.70, (226, 92, 52, 0.85)), (1.00, (168, 28, 40, 0.92)))


def _ramp(t):
    for (a, ca), (b, cb) in zip(_DENSITY_RAMP, _DENSITY_RAMP[1:]):
        if t <= b:
            k = (t - a) / (b - a) if b > a else 0
            r, g, bl, al = (ca[i] + (cb[i] - ca[i]) * k for i in range(4))
            return f"rgb({r:.0f},{g:.0f},{bl:.0f})", al
    r, g, bl, al = _DENSITY_RAMP[-1][1]
    return f"rgb({r},{g},{bl})", al


def density_svg(rows, *, lhb=False, bands=None, width=600, height=1000, top_m=-1.6, bottom_m=13.5,
                cell_m=0.1, blur=2) -> str:
    """Where the balls pitch as a smoothed heat map on the CricViz strip.

    Binned on a 10 cm grid and blurred with a small box kernel twice (close to a Gaussian), shaded
    on one yellow-to-red ramp from the busiest cell. Off side on the left for a right-hander, as
    the dot map."""
    from cricket_core import cricviz as cv
    bands = bands or cv.PACE_BANDS
    base = cv.pitch_map([], lhb=lhb, width=width, height=height, bands=bands, top_m=top_m,
                        bottom_m=bottom_m, metrics=False)
    span = bottom_m - top_m
    scale = (height * 0.96) / span
    y0 = height * 0.02
    cx = width * 0.5
    half_w = cv.PITCH_HALF_W_M * 1.3
    nx = int(round(2 * half_w / cell_m))
    ny = int(round(span / cell_m))
    grid = [[0.0] * nx for _ in range(ny)]
    sign = 1 if lhb else -1
    n = 0
    for r in rows:
        x, y = cv._mm(r.get("pitch_line")), cv._mm(r.get("pitch_length"))
        if x is None or y is None or abs(x) > half_w:
            continue
        y = max(top_m + 0.05, min(bottom_m - 0.05, y))
        i = min(ny - 1, int((y - top_m) / cell_m))
        j = min(nx - 1, int((sign * x + half_w) / cell_m))
        grid[i][j] += 1
        n += 1
    if n < 5:
        return base

    def box(g, kx, ky):
        h, w = len(g), len(g[0])
        out = [[0.0] * w for _ in range(h)]
        for i in range(h):                                  # along each row
            row, acc = g[i], 0.0
            pre = [0.0]
            for v in row:
                acc += v
                pre.append(acc)
            for j in range(w):
                a, b = max(0, j - kx), min(w, j + kx + 1)
                out[i][j] = (pre[b] - pre[a]) / (2 * kx + 1)
        res = [[0.0] * w for _ in range(h)]
        for j in range(w):                                  # then down each column
            acc, pre = 0.0, [0.0]
            for i in range(h):
                acc += out[i][j]
                pre.append(acc)
            for i in range(h):
                a, b = max(0, i - ky), min(h, i + ky + 1)
                res[i][j] = (pre[b] - pre[a]) / (2 * ky + 1)
        return res

    # length is coarser than line in the data (a ball pitches over a wider spread of lengths), so
    # smooth length twice as far as line
    g = box(box(grid, blur, 2 * blur), blur, 2 * blur)
    mx = max(max(r) for r in g) or 1
    # One pixel per cell, as a PNG inside the SVG: the browser smooths it as it scales it up, so a
    # 34 x 151 image reads as a continuous heat map at a few KB, where a rect per cell was 119 KB.
    import base64, io
    from PIL import Image
    img = Image.new("RGBA", (nx, ny), (0, 0, 0, 0))
    px = img.load()
    for i, row in enumerate(g):
        for j, v in enumerate(row):
            t = v / mx
            if t >= 0.03:
                col, al = _ramp(t)
                r_, g_, b_ = (int(c) for c in col[4:-1].split(","))
                px[j, i] = (r_, g_, b_, int(al * 255))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    heat = (f"<image href='{uri}' x='{cx - half_w * scale:.1f}' y='{y0:.1f}' width='{2 * half_w * scale:.1f}' "
            f"height='{span * scale:.1f}' preserveAspectRatio='none'/>")
    # the stumps on top again, so the heat never hides them
    stumps = "".join(f"<circle cx='{cx + k * cv.STUMP_HALF_M * scale:.1f}' cy='{y0 + (0 - top_m) * scale:.1f}' "
                     f"r='{max(1.6, scale * 0.045):.1f}' fill='{cv.INK}'/>" for k in (-1, 0, 1))
    return base.replace("</svg>", heat + stumps + "</svg>")


# ── small builders ────────────────────────────────────────────────────────────────────────────
def _n(v, dp=0, suffix=""):
    """A number for a table cell, a dash for nothing."""
    if v is None:
        return "–"
    try:
        return f"{v:,.{dp}f}{suffix}"
    except (TypeError, ValueError):
        return E(str(v))


def _cap(s):
    s = str(s or "")
    return s[:1].upper() + s[1:]


def _day(iso):
    """dd-mm-yyyy from an ISO date, as every reader-facing date in the estate."""
    s = str(iso or "")[:10]
    return f"{s[8:10]}-{s[5:7]}-{s[:4]}" if len(s) == 10 and s[4] == "-" else s


def sec(sid, title, sub, inner, extra=""):
    s = f"<span>{E(sub)}</span>" if sub else ""
    return f"<section class='sx' id='{sid}'><header><h2>{E(title)}{s}</h2>{extra}</header>{inner}</section>"


def table(heads, rows, hi=None, cls=""):
    """rows are lists of cell HTML (escape before passing); `hi` = row indexes to shade."""
    his = set() if hi is None else (set(hi) if isinstance(hi, (set, list, tuple)) else {hi})
    th = "".join(f"<th>{E(h)}</th>" for h in heads)
    trs = "".join(f"<tr{' class=hi' if i in his else ''}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                  for i, r in enumerate(rows))
    return f"<div class='tw'><table class='t {cls}'><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>"


def figs(items, cls=""):
    return f"<div class='figs {cls}'>" + "".join(
        f"<div class='fg'><div class='v'>{v}</div><div class='k'>{E(k)}</div></div>" for v, k in items if v is not None) + "</div>"


def facts(rows, title="The facts"):
    rows = [(k, v) for k, v in rows if v]
    if not rows:
        return ""
    return (f"<div class='fx'><div class='lbl'>{E(title)}</div><div class='facts'>"
            + "".join(f"<span class='k'>{E(k)}</span><span class='v'>{v}</span>" for k, v in rows) + "</div></div>")


def label(t):
    return f"<div class='lbl'>{E(t)}</div>"


def switch(items, on=0):
    """A row of toggles that shows one of the `.pane`s inside the nearest [data-switch] box."""
    return "<div class='tg'>" + "".join(
        f"<button type='button' class='{'on' if i == on else ''}' data-pane='{i}'>{E(t)}</button>"
        for i, t in enumerate(items)) + "</div>"


def panes(heads, bodies, title=""):
    """A label with toggles over two or more panes; with one pane, just the label and the pane."""
    if len(bodies) == 1:
        return f"<div>{label(title or heads[0])}{bodies[0]}</div>"
    ps = "".join(f"<div class='pane'{'' if i == 0 else ' hidden'}>{b}</div>" for i, b in enumerate(bodies))
    return f"<div data-switch><div class='bar-row'>{label(title)}{switch(heads)}</div>{ps}</div>"


def band_word(p):
    """The house percentile bands (root CLAUDE.md)."""
    if p is None:
        return ""
    return ("among the highest" if p >= 80 else "above average" if p >= 60 else "around average" if p >= 40
            else "below average" if p >= 20 else "among the lowest")


def pct_rows(fp):
    """The fingerprint as strips: the career mark solid, the last-three-years mark dotted gold."""
    out = []
    for f in fp or []:
        p = f.get("pctl")
        if p is None:
            continue
        p = max(0, min(100, round(p)))
        r = f.get("pctl_recent")
        r = None if r is None else max(0, min(100, round(r)))
        mk = f"<i style='left:{p}%'></i>" + (f"<i class='r' style='left:{r}%'></i>" if r is not None else "")
        trend = f" · last 3 years P{r}" if r is not None else ""
        out.append(f"<div class='pr'><div class='n'>{E(f.get('label') or '')}</div><div class='bar'>{mk}</div>"
                   f"<div class='w'><b class='v'>P{p}</b> {E(band_word(p))} · {E(str(f.get('disp') or ''))}{E(trend)}</div></div>")
    return "<div class='pcts'>" + "".join(out) + "</div>" if out else ""


def _inline_svg(svg, cls=""):
    """A CricViz SVG made to scale with its box."""
    return f"<div class='{cls}'>" + svg.replace("<svg ", "<svg preserveAspectRatio='xMidYMid meet' ", 1) + "</div>"


class Defs:
    """Drawings defined once per page and shown wherever they are needed.

    Each scope pane repeats the sections, and most drawings are the same in two or three of them
    (the release point is all batters in every pane; a hand's wicket balls show in the All pane and
    in that hand's pane). Inline, that tripled the page to 661 KB. Each drawing becomes a <symbol>
    in one hidden <svg> at the end of the page, and every place that shows it is a <use>."""

    def __init__(self):
        self.items = {}

    def use(self, key, svg, cls=""):
        import re
        vb = re.search(r"viewBox=['\"]([^'\"]+)['\"]", svg).group(1)
        st = re.search(r"<svg[^>]*\sstyle=['\"]([^'\"]*)['\"]", svg)
        lab = re.search(r"<svg[^>]*\saria-label=['\"]([^'\"]*)['\"]", svg)
        if key not in self.items:
            inner = svg[svg.index(">") + 1: svg.rindex("</svg>")]
            self.items[key] = f"<symbol id='{key}' viewBox='{vb}'>{inner}</symbol>"
        style = f" style=\"{st.group(1)}\"" if st else ""
        al = f" aria-label=\"{lab.group(1)}\"" if lab else ""
        return (f"<div class='{cls}'><svg viewBox='{vb}' preserveAspectRatio='xMidYMid meet' role='img'{style}{al}>"
                f"<use href='#{key}'/></svg></div>")

    def html(self):
        # not display:none: Chrome drops gradients defined inside an undisplayed <svg>
        return ("<svg aria-hidden='true' focusable='false' style='position:absolute;width:0;height:0;overflow:hidden'>"
                + "".join(self.items.values()) + "</svg>")


# ── bowler pictures ───────────────────────────────────────────────────────────────────────────
def wicket_pics(P, lhb, defs, key):
    """Where the wicket balls pitched and passed the stumps (CricViz). Returns (html, n)."""
    from cricket_core import cricviz as cv
    wk = [dict(r, striker_dismissed="1") for r in P["df"] if r.get("is_legal") and r.get("is_wicket")]
    if len(wk) < 5:
        return "<p class='note'>Too few wickets to draw.</p>", len(wk)
    bands = {"bands": cv.SPIN_BANDS} if P.get("is_spin") else {}
    pm = cv.pitch_map(wk, lhb=lhb, metrics=False, **bands)
    bh = cv.beehive(wk, lhb=lhb)
    return f"<div class='pics2'>{defs.use(key + '-pm', pm, 'pm')}{defs.use(key + '-bh', bh, 'bh')}</div>", len(wk)


def release_svg(rows, left_arm=False):
    """Release positions seen from behind the bowler, in the CricViz flat look: pale field, the
    stumps and both return creases, the 45 cm and 75 cm guides, a dot per ball (up to 1,400, an
    even sample), over the wicket in green and round in gold, and the average release height.
    Returns (html, n balls drawn)."""
    pts = [(r["release_line_n"] / 1000, r["release_height_n"] / 1000, r["is_round"]) for r in rows
           if r.get("is_legal") and r.get("release_line_n") is not None and r.get("release_height_n") is not None
           and r.get("is_round") is not None and abs(r["release_line_n"]) <= 1500
           and 500 < r["release_height_n"] < 2800]
    if len(pts) < 30:
        return "", 0
    n_all = len(pts)
    if len(pts) > 1400:
        step = len(pts) / 1400
        pts = [pts[int(i * step)] for i in range(1400)]
    over = [a for a, _, r in pts if not r]
    rnd = [a for a, _, r in pts if r]
    over_mean = sum(over) / len(over) if over else -(sum(rnd) / len(rnd))
    # a right-armer's over-the-wicket release is on the viewer's left from behind them
    want_left = not left_arm
    flip = -1 if (over_mean > 0) == want_left else 1
    W, Hh = 560, 340
    X = lambda m: W / 2 + flip * m * 150
    Y = lambda m: Hh - 30 - m * 115
    p = [f"<svg viewBox='0 0 {W} {Hh}' role='img' aria-label='Release points from behind the bowler'>",
         f"<rect width='{W}' height='{Hh}' fill='#b5d197'/>",
         f"<rect x='{W / 2 - 1.5 * 150}' y='{Y(2.7)}' width='{3 * 150}' height='{Y(0) - Y(2.7)}' fill='#f3efc0'/>"]
    for m, lab in ((0.45, "45 cm"), (0.75, "75 cm")):
        for s in (1, -1):
            p.append(f"<line x1='{X(s * m):.0f}' x2='{X(s * m):.0f}' y1='{Y(0)}' y2='{Y(2.7)}' stroke='#ffffff' "
                     f"stroke-dasharray='4 4' stroke-width='1.2'/>")
        p.append(f"<text x='{W / 2 + m * 150 + 4:.0f}' y='{Y(0) + 16}' font-size='11' fill='#3c5a46'>{lab}</text>")
    for s in (1, -1):
        p.append(f"<line x1='{X(s * 1.32):.0f}' x2='{X(s * 1.32):.0f}' y1='{Y(0)}' y2='{Y(2.7)}' stroke='#ffffff' stroke-width='2.5'/>")
    for dx in (-0.11, 0, 0.11):
        p.append(f"<rect x='{X(dx) - 2:.0f}' y='{Y(0.71):.0f}' width='4' height='{Y(0) - Y(0.71):.0f}' fill='#d8c08a' stroke='#b89a5c'/>")
    p.append(f"<line x1='0' x2='{W}' y1='{Y(0)}' y2='{Y(0)}' stroke='#ffffff' stroke-width='2'/>")
    for a, b, r in pts:
        p.append(f"<circle cx='{X(a):.1f}' cy='{Y(b):.1f}' r='3.2' fill='{'#e9b311' if r else '#0d5b3b'}' fill-opacity='.55'/>")
    avg_h = sum(b for _, b, _ in pts) / len(pts)
    p.append(f"<line x1='0' x2='{W}' y1='{Y(avg_h):.0f}' y2='{Y(avg_h):.0f}' stroke='#b5452f' stroke-dasharray='6 4' stroke-width='1.4'/>"
             f"<text x='8' y='{Y(avg_h) - 6:.0f}' font-size='12' font-weight='700' fill='#b5452f'>average release {avg_h:.2f} m</text>")
    if over:
        p.append(f"<text x='{X(over_mean):.0f}' y='22' font-size='14' font-weight='700' fill='#0d3b2a' text-anchor='middle'>OVER</text>")
    if len(rnd) >= 20:
        p.append(f"<text x='{X(sum(rnd) / len(rnd)):.0f}' y='22' font-size='14' font-weight='700' fill='#8a6a00' "
                 f"text-anchor='middle'>ROUND</text>")
    for m in (0.5, 1.0, 1.5, 2.0, 2.5):
        p.append(f"<text x='{W - 6}' y='{Y(m) + 4:.0f}' font-size='11' fill='#3c5a46' text-anchor='end'>{m:.1f} m</text>")
    p.append("</svg>")
    return "".join(p), n_all


_LINE_ORDER = ("wide outside off", "outside off", "channel", "mid and off", "in line", "leg and mid", "outside leg")
_LINE_WORDS = {"wide outside off": "Wide outside off", "channel": "The channel", "in line": "In line",
               "outside leg": "Outside leg", "outside off": "Outside off", "mid and off": "Middle and off",
               "leg and mid": "Leg and middle"}


def beaten_grid(beaten, spin=False):
    """The play-and-miss grid: pitch length in metres down, pitching line across, each cell the
    count and share, shaded on one green ramp, the busiest cell outlined in gold. A spinner's lines
    are the spin groups (outside off, middle and off, leg and middle, outside leg)."""
    col = "pitch_line_group_spin" if spin else "pitch_line_group_pace"
    cells = {}
    for r in beaten:
        L, g = r.get("pitch_length_m"), str(r.get(col) or "").strip()
        if L is None or not g or L < 0 or L >= 13:
            continue
        key = (int(L), g)
        cells[key] = cells.get(key, 0) + 1
    if sum(cells.values()) < 20:
        return "<p class='note'>Too few play-and-misses on tracked balls to draw.</p>"
    order = lambda g: next((i for i, k in enumerate(_LINE_ORDER) if k in g.lower()), 99)
    groups = sorted({g for _, g in cells}, key=order)
    mx = max(cells.values())
    tot = sum(cells.values())
    top = max(cells, key=cells.get)
    word = lambda g: _LINE_WORDS.get(g.lower(), g)
    th = "".join(f"<th>{E(word(g))}</th>" for g in groups)
    rows = []
    for L in range(0, 13):
        tds = []
        for g in groups:
            n = cells.get((L, g), 0)
            t = n / mx
            bg = f"rgba(13,91,59,{0.04 + 0.86 * t:.2f})" if n else "#fff"
            ink = "#fff" if t > 0.55 else "#122219"
            ring = "outline:2px solid #e9b311;outline-offset:-2px;" if (L, g) == top else ""
            tds.append(f"<td style='background:{bg};color:{ink};{ring}text-align:center'>{n if n else ''}"
                       + (f"<small style='display:block;opacity:.8'>{n / tot * 100:.0f}%</small>"
                          if n >= max(4, mx * 0.15) else "") + "</td>")
        rows.append(f"<tr><td>{L}-{L + 1} m</td>{''.join(tds)}</tr>")
    return (f"<div class='tw'><table class='t narrow'><thead><tr><th>Pitch length</th>{th}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            f"<p class='note'>{tot:,} play-and-misses on tracked balls. Busiest cell outlined in gold: "
            f"{top[0]}-{top[0] + 1} m, {E(word(top[1]).lower())} ({cells[top]}).</p>")


def speed_chart(df):
    """Median speed by spell, innings and day as dots on one km/h scale. Returns (html, groups)."""
    import statistics as st
    by = {}
    for r in df:
        v = r.get("ball_speed_n")
        if not r.get("is_legal") or v is None or v < 60:
            continue
        sp = str(r.get("bowler_spell") or "").strip()
        if sp.isdigit() and int(sp) >= 1:
            by.setdefault(("By spell", "Spell 5+" if int(sp) >= 5 else f"Spell {sp}"), []).append(v)
        ig = r.get("innings_group")
        if ig in ("1st Innings", "2nd Innings"):
            by.setdefault(("By innings", ig.replace("Innings", "innings")), []).append(v)
        d = r.get("match_day_n")
        if d and d >= 1:
            by.setdefault(("By day", f"Day {min(int(d), 5)}"), []).append(v)
    groups = []
    for g in ("By spell", "By innings", "By day"):
        items = sorted(((lab, st.median(vs), len(vs)) for (gg, lab), vs in by.items() if gg == g and len(vs) >= 60),
                       key=lambda t: t[0])
        if items:
            groups.append((g, items))
    if not groups:
        return "", []
    vals = [v for _, it in groups for _, v, _ in it]
    lo, hi = math.floor(min(vals) - 0.5), math.ceil(max(vals) + 0.5)
    if hi - lo < 4:
        hi = lo + 4
    W, rowh, left = 560, 26, 120
    rows = sum(len(it) for _, it in groups) + len(groups)
    Ht = rows * rowh + 28
    xs = lambda v: left + (v - lo) / (hi - lo) * (W - left - 30)
    p = [f"<svg viewBox='0 0 {W} {Ht}' role='img' aria-label='Median speed by spell, innings and day'>"]
    for v in range(lo, hi + 1):
        p.append(f"<line x1='{xs(v):.0f}' x2='{xs(v):.0f}' y1='8' y2='{Ht - 20}' stroke='rgba(13,59,42,.12)'/>"
                 f"<text x='{xs(v):.0f}' y='{Ht - 6}' font-size='11' text-anchor='middle' fill='#5a6b61'>{v}</text>")
    y = 18
    for name, items in groups:
        p.append(f"<text x='0' y='{y + 4}' font-size='11' font-weight='700' fill='#5a6b61' letter-spacing='.06em'>"
                 f"{E(name.upper())}</text>")
        y += rowh
        for lab, v, _n_ in items:
            p.append(f"<text x='12' y='{y + 4}' font-size='12.5' fill='#122219'>{E(lab)}</text>"
                     f"<line x1='{left}' x2='{xs(v):.0f}' y1='{y}' y2='{y}' stroke='#cfdcd3' stroke-width='2'/>"
                     f"<circle cx='{xs(v):.0f}' cy='{y}' r='6' fill='#0d5b3b'/>"
                     f"<text x='{xs(v) + 10:.0f}' y='{y + 4}' font-size='12' font-weight='700' fill='#122219'>{v:.1f}</text>")
            y += rowh
    p.append("</svg>")
    return "<div class='chart'>" + "".join(p) + "</div>", groups


def angle_map_png(rows, path, lhb, spin):
    """The dot view of an over/round pitch map: every ball, so a picture file rather than SVG.
    Rendered by CricViz to PNG and kept as WebP (a fifth of the size). Skips the work when the
    file is already there and newer than the rows' build (pass a fresh path to force it)."""
    import os
    from cricket_core import cricviz as cv
    from PIL import Image
    if REUSE_PICS and os.path.exists(path):
        return os.path.basename(path)
    marked = [dict(r, striker_dismissed="1" if r.get("is_wicket") else "0") for r in rows]
    bands = {"bands": cv.SPIN_BANDS} if spin else {}
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "rw_" + os.path.basename(path) + ".png")
    # the headless browser now and then hangs on one picture (seen 12-10-2026); a second try works
    for attempt in (1, 2):
        try:
            cv.render("pitch_map", marked, tmp, lhb=lhb, scale=2, **bands)
            break
        except Exception:
            if attempt == 2:
                raise
    im = Image.open(tmp)
    im.thumbnail((900, 1500))
    im.save(path, "WEBP", quality=82, method=6)
    os.remove(tmp)
    return os.path.basename(path)


# ── words ─────────────────────────────────────────────────────────────────────────────────────
def person(name):
    """'Rabada, Kagiso' -> 'Kagiso Rabada' (the warehouse keeps surname first)."""
    s = str(name or "").strip()
    if "," in s:
        a, b = (x.strip() for x in s.split(",", 1))
        return f"{b} {a}".strip()
    return s


def team_word(team):
    """'South Africa M' -> 'South Africa' (the warehouse tags the men's and women's sides)."""
    s = str(team or "").strip()
    return s[:-2] if s.endswith((" M", " W")) else s


def type_word(pt):
    """'Right Fast' -> 'Right-arm pace', 'Right Off Spin' -> 'Off spin'."""
    s = str(pt or "").lower()
    arm = "Left-arm" if s.startswith("left") else "Right-arm"
    if "off" in s:
        return "Off spin"
    if "leg" in s:
        return "Leg spin"
    if "orthodox" in s:
        return "Left-arm orthodox"
    if "wrist" in s or "chinaman" in s:
        return "Left-arm wrist spin"
    if "spin" in s:
        return f"{arm} spin"
    return f"{arm} pace"


def _len_word(length):
    from profile import _LEN_PHRASE
    return _LEN_PHRASE.get(length, str(length or "").lower())


def _zone(length, line):
    from profile import ball_phrase
    return _cap(ball_phrase(length, line))


def _rate_line(d):
    """'28 wickets in 739 balls · 3.8 per 100' from a danger dict."""
    if not d or not d.get("balls"):
        return ""
    return f"{d['wickets']} wickets in {d['balls']:,} balls · {d['wickets'] / d['balls'] * 100:.1f} per 100"


# ── a bowler's page ───────────────────────────────────────────────────────────────────────────
SCOPES = (("all", "All", "All batters", "all batters"), ("rhb", "RHB", "Right-handers", "right-handers"),
          ("lhb", "LHB", "Left-handers", "left-handers"))
_FIELD_NAME = {"Bouncer plan": "Bouncer"}


def _zone_cards(P):
    out = []
    w, r = P.get("wkt_zone"), P.get("run_zone")
    if w:
        out.append(("w", "Most wickets", _zone(w["length"], w["line"]),
                    f"{int(w['value'])} of {int(w['total'])} ({w['share'] * 100:.0f}%)"))
    if r:
        out.append(("", "Most runs", _zone(r["length"], r["line"]),
                    f"{int(r['value']):,} of {int(r['total']):,} ({r['share'] * 100:.0f}%)"))
    if P.get("danger_cell"):
        d = P["danger_cell"]
        out.append(("w", "Most wickets per ball", _zone(d["length"], d["line"]), _rate_line(d)))
    if P.get("danger_line"):
        d = P["danger_line"]
        from profile import _LINE_PHRASE
        out.append(("w", "Danger pitching line", _cap(_LINE_PHRASE.get(d["line"], d["line"])), _rate_line(d)))
    if P.get("danger_length"):
        d = P["danger_length"]
        out.append(("w", "Danger length", _cap(_len_word(d["length"])), _rate_line(d)))
    return "<div class='zc two-up'>" + "".join(
        f"<div class='z {c}'><div class='k'>{E(k)}</div><div class='v'>{E(v)}</div><div class='s'>{E(s)}</div></div>"
        for c, k, v, s in out) + "</div>" if out else ""


def _how_out(P):
    rows = []
    for d in P.get("dismissal_index") or []:
        if d["count"] < 2:
            continue
        idx = d.get("index")
        rows.append([E(d["type"]), f"{d['count']}", f"{d['share']:.0f}%",
                     f"{d['base_share']:.0f}%" if d.get("base_share") is not None else "–",
                     (f"<b>{idx:.2f}×</b>" if idx and idx >= 1.15 else f"{idx:.2f}×") if idx is not None else "–"])
    if not rows:
        return ""
    return table(["How out", "Wickets", "Share", "Type", "Index"], rows, cls="narrow")


def _catches(P):
    c = P.get("catch_pos_counts")
    if not c:
        return ""
    top = [(k, v) for k, v in c.most_common(6) if v >= 3][:5]
    if not top:
        return ""
    word = lambda k: {"Keeper": "the keeper"}.get(k, k.replace("Slip: ", "").replace(": regulation", "").lower()
                                                     + (" slip" if k.startswith("Slip") else ""))
    return "<p class='note'>Catches: " + ", ".join(f"{E(word(k))} {v}" for k, v in top) + ".</p>"


def _form_table(P, all_note=""):
    rf = P.get("recent_form")
    if not rf:
        return ""
    def row(lab, s):
        return [E(lab), _n(s["balls"]), _n(s["wkts"]), _n(s["avg"], 1), _n(s["econ"], 2), _n(s["sr"], 1),
                _n(s["false_pct"], 0, "%"), _n(s["speed"]), _n(s["length"], 2, " m")]
    r, c = rf["recent"], rf["career"]
    note = ""
    if r.get("sr") and c.get("sr"):
        note = (f"A wicket every {r['sr']:.0f} balls in the last {rf['n_matches']} Tests, every {c['sr']:.0f} across the career")
        if r.get("false_pct") is not None and c.get("false_pct") is not None:
            note += f". False shots {r['false_pct']:.0f}% against {c['false_pct']:.0f}%"
        note += "."
    return (label(f"Current form{all_note} · last {rf['n_matches']} Tests, {_day(rf['date_from'])} to {_day(rf['date_to'])}")
            + table(["", "Balls", "Wkts", "Avg", "Econ", "Bowl SR", "False shots", "km/h", "Length"],
                    [row(f"Last {rf['n_matches']} Tests", r), row("Career", c)], hi=0)
            + (f"<p class='note'>{E(note)}</p>" if note else ""))


def _summary_facts(P, Ps, key):
    """The facts block: the profile's own factual lines, then angle and stumps."""
    from cricket_core import stumps
    out = []
    bt = (P.get("ball_types") or {}).get("stock")
    if bt:
        out.append(("Stock ball", f"<b>{E(bt['phrase'])}</b> · {bt['pct']:.0f}% of balls"
                    + (f", economy {bt['econ']:.2f}" if bt.get("econ") is not None else "")
                    + f", {bt['wkts']} wickets"))
    for f in (P.get("how_to_play") or {}).get("facts") or []:
        out.append((f["label"], f["text"]))            # already factual HTML from the profile
    if key == "all":
        a, b = P.get("round_lhb"), P.get("round_rhb")
        if a is not None or b is not None:
            out.append(("Angle", f"round the wicket to left-handers {_n(a, 0, '%')}, to right-handers {_n(b, 0, '%')}"))
    elif P.get("round_pct") is not None:
        out.append(("Angle", f"round the wicket on {P['round_pct']:.0f}% of balls"))
    s = stumps.bowler_vs_type(P["df"], fmt="Test")
    if s:
        out.append(("Hit the stumps", f"{s['rate']:.1f}% of tracked balls on course for the stumps · "
                    f"an average {E(s['label'])} bowler {s['expected']:.1f}%"))
    return out


def _over_construction(P):
    sq = P.get("sequencing")
    if not sq or not sq.get("over_shape"):
        return ""
    shape = sq["over_shape"]
    best = max(range(len(shape)), key=lambda i: shape[i]["wkt_rate"])
    rows = [[f"{o['pos']}", _n(o["med_len"], 1, " m"), f"{o['short_pct']:.0f}%", f"{o['econ']:.2f}", f"{o['wkt_rate']:.1f}%"]
            for o in shape]
    fx = []
    if sq.get("length_sd") is not None:
        fx.append(("Length spread", f"±{sq['length_sd']:.1f} m"))
    sp = P.get("seq_patterns") or {}
    ws = P.get("wicket_setup")
    if ws and ws.get("n", 0) >= 12:
        dl = ws["wk_len"] - ws["prev_len"]
        bits = [f"{abs(dl) * 100:.0f} cm {'fuller' if dl < 0 else 'shorter'}" if abs(dl) >= 0.25 else "the same length"]
        if ws.get("wk_spd") and ws.get("prev_spd"):
            dv = ws["wk_spd"] - ws["prev_spd"]
            bits.append(f"{abs(dv):.0f} km/h {'quicker' if dv > 0 else 'slower'}" if abs(dv) >= 2 else "the same pace")
        fx.append(("Wicket ball", f"against the ball before it: {' and '.join(bits)} ({ws['n']} dismissals)"))
    if sp.get("after_short_fuller_pct") is not None and (sp.get("after_short_n") or 0) >= 30:
        fx.append(("After a short ball", f"pitches up {sp['after_short_fuller_pct']:.0f}% of the time "
                   f"({sp['after_short_n']:,} short balls)"))
    if sp.get("after_bdry_shorter_pct") is not None and (sp.get("after_bdry_n") or 0) >= 30:
        fx.append(("After a boundary", f"goes shorter {sp['after_bdry_shorter_pct']:.0f}% of the time "
                   f"({sp['after_bdry_n']:,} boundaries)"))
    return (label("Over construction")
            + "<div class='two'><div>" + table(["Ball", "Median length", "Short", "Econ", "Wicket %"], rows, hi=best, cls="narrow")
            + "</div><div>" + facts(fx, "Through the over") + "</div></div>")


def _crease(P):
    c = P.get("crease")
    if not c:
        return ""
    fx = []
    ref = P.get("crease_ref") or {}
    fp = {f["label"]: f for f in P.get("fingerprint") or []}
    if c.get("height_cm"):
        h = fp.get("Release height")
        fx.append(("Release height", f"{c['height_cm'] / 100:.2f} m"
                   + (f" · P{h['pctl']:.0f} against {E(h['peer'])} ({band_word(h['pctl'])})" if h and h.get("pctl") is not None else "")))
    dom = c.get(c.get("dominant") or "over") or {}
    if dom:
        w = fp.get("Crease variation")
        fx.append(("Crease", f"about {dom['width_cm']:.0f} cm from middle stump {'over' if c.get('dominant') == 'over' else 'round'} the wicket · "
                   f"moves ±{dom['sd_cm']:.0f} cm on it"
                   + (f" · P{w['pctl']:.0f} for variation ({band_word(w['pctl'])})" if w and w.get("pctl") is not None else "")))
    del ref
    use = []
    for nm, k, share in (("Over the wicket", "over", c.get("over_share")), ("Round the wicket", "round", c.get("round_share"))):
        m = c.get(k)
        if m and m["n"] >= 50:
            use.append([nm, _n(share, 0, "%"), f"{m['tight_pct']:.0f}%", f"{m['std_pct']:.0f}%", f"{m['wide_pct']:.0f}%"])
    bands = []
    lab = {"tight": "Tight (under 45 cm)", "standard": "Standard (45-75 cm)", "wide": "Wide (over 75 cm)"}
    for b in ("tight", "standard", "wide"):
        m = (c.get("bands") or {}).get(b)
        if m:
            bands.append([lab[b], f"{m['balls']:,} ({m['share']:.0f}%)", f"{m['econ']:.2f}", str(m["wkts"]),
                          _n(m["avg"], 1), _n(m["sr"], 0)])
    return (facts(fx, "At the crease")
            + (table(["Angle", "Balls", "Tight", "Standard", "Wide"], use, cls="narrow") if use else "")
            + (table(["Crease position", "Balls", "Econ", "Wkts", "Avg", "Bowl SR"], bands) if bands else ""))


def _movement(P):
    m = P.get("movement")
    if not m:
        return ""
    spin = P.get("is_spin")
    def d(x):
        return f"{x['out_pct']:.0f}% away · {x['in_pct']:.0f}% in" if x else ""
    rows = []
    for lab, avg, pc, dr, dp in (("Drift" if spin else "Swing", m.get("avg_swing"), m.get("swing_pctl"), m.get("swing_dir"), 2),
                                 ("Turn" if spin else "Seam", m.get("avg_seam"), m.get("seam_pctl"), m.get("seam_dir"), 2),
                                 ("Bounce", m.get("avg_bounce"), m.get("bounce_pctl"), None, 1)):
        if pc is None:
            continue
        rows.append([lab, _n(avg, dp, "°"), f"P{pc:.0f} · {band_word(pc)}", d(dr)])
    peer = "spinner" if spin else "pace bowler"
    return table(["", "Average", f"Against the average {peer}", "Direction"], rows) if rows else ""


def _fields_block(bid, plan, hand, title):
    opts = [{"slot": f.get("slot", ""), "name": _FIELD_NAME.get(f["label"], f["label"]),
             "fielders": [{"angle": p["angle"], "radius": p["radius"]} for p in f["fielders"]],
             "spare": f.get("spare")}
            for f in ((plan or {}).get("hands", {}).get(hand) or {}).get("fields") or [] if f.get("fielders")]
    import json as _j
    data = _j.dumps(opts, ensure_ascii=False, separators=(",", ":"))
    return (f"<div class='fb' data-fb='{E(str(bid))}' data-kind='bowler' data-hand='{hand}' "
            f"data-pack='vs_{hand.lower()}' data-opts='{E(data)}'>{label(title)}<div class='fbody'></div></div>")


def _vision(clips):
    """The reels in the A4 report's clip list, as the packs' reel rows."""
    if not clips:
        return "<p class='thin'>No available footage.</p>"
    def title(t):
        t = str(t or "")
        return t.capitalize() if t.istitle() and " " in t else t        # "Danger Cell" -> "Danger cell"
    rows = [(k, title(v.get("title") or k), len(v.get("items") or [])) for k, v in clips.items() if v.get("items")]
    if not rows:
        return "<p class='thin'>No available footage.</p>"
    return "<div class='reels'>" + "".join(
        f"<a class='vlink rl' data-pl='{E(k)}' data-n='{n}' href='#'>{E(t)}</a>" for k, t, n in rows) + "</div>"


def _bowler_scope(key, P, Ps, ctx):
    """One scope pane: every section for all batters, or for one hand."""
    sid = lambda s: f"{key}-{s}"
    hands = [h for h in ("RHB", "LHB") if Ps.get(h) and Ps[h].get("n_balls")] if key == "all" else [key.upper()]
    hword = {"RHB": "Right-handers", "LHB": "Left-handers"}
    who = "all batters" if key == "all" else hword[key.upper()].lower()
    s = []

    # ── summary ──
    notes = "<div class='notes2'>" + "".join(
        f"<div class='cn' data-notes='{E(P['bowler_id'])}' data-pack='vs_{h.lower()}' "
        f"data-title=\"Coaches' notes{' · to ' + hword[h].lower() if key == 'all' else ''}\" hidden></div>" for h in hands) + "</div>"
    top = f"{P['max_spd_99']:.0f}" if P.get("max_spd_99") else None
    fg = [(f"{P['n_balls']:,}", "Balls"), (f"{P['n_wkts']}", "Wickets"), (_n(P.get("bowl_avg"), 1), "Average"),
          (_n(P.get("strike_rate"), 1), "Bowl SR"), (_n(P.get("economy"), 2), "Economy")]
    if P.get("avg_spd"):
        fg.append((f"{P['avg_spd']:.0f}" + (f"<small> /{top}</small>" if top else ""), "km/h · top"))
    fp = pct_rows(P.get("fingerprint"))
    peer = next((f.get("peer") for f in P.get("fingerprint") or [] if f.get("peer")), "bowlers of the type")
    s.append(sec(sid("sum"), "Summary", who,
                 notes + figs(fg) + facts(_summary_facts(P, Ps, key)) + _form_table(P, "" if key == "all" else " · all batters")
                 + ((label(f"Against other {type_word(P.get('primary_type')).lower()} bowlers, career and last 3 years" + ("" if key == "all" else ", all batters")) + fp
                     + "<p class='note'>The solid mark is the career, the dotted gold mark the last three years. Bands: 80 and above "
                       "among the highest, 60-80 above average, 40-60 around average, 20-40 below average, under 20 among the lowest. "
                       "Repeatability is the spread of length, so a higher percentile is a tighter spread.</p>") if fp else "")))
    del peer

    # ── threat ──
    pics = []
    for h in hands:
        html_, n = ctx["wicket_pics"][h]
        pics.append((f"{hword[h]} · {n}", html_))
    left = (panes([p[0] for p in pics], [p[1] for p in pics], "Wicket balls") if pics else "")
    tracked = P.get("n_tracked") or 0
    from cricket_core import stumps
    st_ = stumps.bowler_vs_type(P["df"], fmt="Test")
    tfig = [(_n(P.get("beaten_pct"), 1, "%"), "Beaten"), (_n(P.get("false_pct"), 1, "%"), "False shots")]
    if st_:
        tfig.append((f"{st_['rate']:.1f}%<small class='ln'>type {st_['expected']:.1f}</small>", "Hit the stumps"))
    s.append(sec(sid("thr"), "Threat", who,
                 "<div class='two wide-l'><div>" + left
                 + "<p class='note'>Where the wicket balls pitched and where they passed the stumps, from behind the bowler: "
                   "a right-hander's off side on the left.</p></div><div class='col'>"
                 + _zone_cards(P) + figs(tfig)
                 + f"<p class='note'>Beaten and false shots on {tracked:,} balls with a recorded shot.</p>"
                 + _how_out(P) + _catches(P) + "</div></div>"))

    # ── ball types ──
    bt = P.get("ball_types") or {}
    import report as R
    btr = R._ball_type_rows(P)
    stock = ""
    if bt.get("stock"):
        sv = None if P["is_spin"] else R._swing_verdict(P.get("movement"))
        desc = R._ball_type_desc(bt["stock"], P["is_spin"], R._swing_cell_word(sv) if sv else None, hand=P["filters"]["hand"])
        stock = (f"<p class='lead'><b>Stock ball:</b> {E(desc)}, {bt['stock']['pct']:.0f}% of balls"
                 + (f" at {bt['stock']['econ']:.2f} an over" if bt['stock'].get("econ") is not None else "") + ".</p>")
    tb = table(["Pitch length and line", "Movement", "Balls", "Economy", "Wkts", "Beaten"],
               [[E(_cap(r["phrase"])), f"<span class='wrap'>{E(r['move'])}</span>", r["pct"], r["econ"], r["wkts"], r["beat"]] for r in btr],
               hi=0) if btr else ""
    ba = R._ball_age_data(P) or {}
    age = []
    raw_age = P.get("ball_age") or {}
    for k in ("new", "old"):
        b, rb = ba.get(k), raw_age.get(k) or {}
        dc = rb.get("danger_cell")
        if b and dc:
            lab = (f"New ball · overs 1-{raw_age['split_over']}" if k == "new"
                   else f"Old ball · overs {raw_age['split_over'] + 1} on")
            age.append(f"<div class='z w'><div class='k'>{E(lab)}</div><div class='v'>Most wickets per ball: "
                       f"{E(_zone(dc['length'], dc['line']).lower())}</div>"
                       f"<div class='s'>{E(_rate_line(dc))} · all {b['wkts']} wickets in {b['n']} balls · "
                       f"economy {b['econ']}</div></div>")
    s.append(sec(sid("bt"), "Ball types", who, stock + tb + (f"<div class='zc two-up'>{''.join(age)}</div>" if age else "")))

    # ── match-ups ──
    mt = R._matchup_split_tables(P)
    heads = ["", "Balls", "Wkts", "Avg", "Econ", "Bowl SR", "False", "Length"]
    mu = "<div class='two'>"
    if mt.get("ball"):
        mu += "<div>" + label("New ball and old ball") + table(heads, [[E(c) for c in r] for r in mt["ball"]]) + "</div>"
    if mt.get("position"):
        mu += "<div>" + label("By batting position") + table(heads, [[E(c) for c in r] for r in mt["position"]]) + "</div>"
    mu += "</div>"
    vs = ctx.get("vs_squad")
    if vs and key == "all":
        bits = []
        if vs.get("threats"):
            bits.append("<p>Lowest expected averages against this bowler: " + ", ".join(
                f"<b>{E(n)}</b> {a:.1f}" for n, _h, a, _d in vs["threats"]) + ".</p>")
        if vs.get("targets"):
            bits.append("<p>Highest expected averages against this bowler: " + ", ".join(
                f"<b>{E(n)}</b> {a:.1f}" for n, _h, a in vs["targets"]) + ".</p>")
        if bits:
            mu += ("<div class='cn'><div class='t'><b>Against our squad</b><span class='sim'>Match simulation</span></div>"
                   + "".join(bits) + "<p class='note'>From the match simulation, which plays each pairing thousands of times "
                   "from full Test records. Only batters well clear of the rest are named.</p></div>")
    s.append(sec(sid("mu"), "Match-ups", who, mu))

    # ── scoring ──
    sc = P.get("scoring")
    if sc:
        zones = {}
        from cricket_core import charts
        for r in P["df"]:
            runs = r.get("bat_score_n") or 0
            if runs and r.get("is_legal"):
                k = charts.wagon_sector(r, bool(r.get("is_lhb")))
                if k:
                    zones[k] = zones.get(k, 0) + runs
        from build_hub_packs import _zones_svg
        wheel = _zones_svg(zones, False) if zones else ""
        d = sc.get("dir_pct") or {}
        sfig = [(f"{sc['bdry_pct']:.0f}%", "Runs in boundaries"), (f"{sc['milked_pct']:.0f}%", "Rotated"),
                (_n(sc.get("balls_per_bdry"), 0), "Balls per boundary")]
        if d:
            sfig.append((f"{d['off']:.0f}%", "Runs off side"))
        fam = [[E(f["name"].replace("/", " / ").lower().capitalize()), f"{f['balls']:,}", f"{f['runs']:,.0f}", f"{f['runs_pct']:.0f}%",
                str(f["bdry"]), f"{f['rpb']:.2f}"] for f in sc.get("families") or []]
        s.append(sec(sid("sc"), "Scoring", who,
                     "<div class='two'><div class='wheelbox'>" + wheel
                     + f"<p class='note' style='text-align:center'>{int(sum(zones.values())):,} runs · off side on the left"
                     + (", left-handers mirrored" if key == "all" else "") + "</p></div><div class='col'>"
                     + figs(sfig) + (table(["Shot", "Balls", "Runs", "% runs", "4s and 6s", "Per ball"], fam) if fam else "")
                     + "</div></div>"))

    # ── pace ──
    chart, groups = speed_chart(P["df"])
    if chart:
        g = dict(groups)
        lead = ""
        sp = g.get("By spell")
        if sp and len(sp) >= 2:
            lead = f"Median {sp[0][1]:.1f} km/h in the first spell, {sp[-1][1]:.1f} in {sp[-1][0].lower()}"
            dy = g.get("By day")
            if dy and len(dy) >= 2:
                lead += f" — {dy[0][1]:.1f} on {dy[0][0].lower()}, {dy[-1][1]:.1f} on {dy[-1][0].lower()}"
            lead += "."
        s.append(sec(sid("pace"), "Pace", who, (f"<p class='lead'>{E(lead)}</p>" if lead else "")
                     + f"<div class='speed'>{chart}</div><p class='note'>Median speed in km/h, legal balls with a recorded speed. "
                       f"Top speed (99th percentile of every recorded ball) {_n(P.get('max_spd_99'), 1)} km/h.</p>"))

    # ── angle and release ──
    orr = P.get("over_round")
    ang = ""
    if orr:
        rows = []
        for nm, share, n, m in (("Over the wicket", orr["over_share"], orr["over_n"], orr["over"]),
                                ("Round the wicket", orr["round_share"], orr["round_n"], orr["round"])):
            if m:
                rows.append([nm, f"{n:,} ({share:.0f}%)", E(_cap(m.get("modal_zone") or "–")), _n(m.get("med_len"), 1, " m"),
                             _n(m.get("short_pct"), 0, "%"), _n(m.get("econ"), 2), str(m["wkts"])])
            else:
                rows.append([nm, f"{n:,} ({share:.0f}%)", "–", "–", "–", "–", "0"])
        ang += table(["", "Balls", "Pitching line", "Median length", "Short", "Econ", "Wkts"], rows)
    maps = []
    for h in hands:
        maps.append((hword[h], ctx["angle_maps"][h]))
    if maps:
        ang += panes([m[0] for m in maps], [m[1] for m in maps], "Where they pitch it, by angle")
        ang += ("<p class='note'>Every ball, from behind the bowler. The Dots view colours each ball by what came of it "
                "(red a wicket, blue a four, purple a six). Density shades where most balls land.</p>")
    rel, nrel = ctx["release"]
    ang += ("<div class='two'><div>" + (label("Release point · from behind the bowler, all batters") + rel
            + f"<p class='note'>{min(nrel, 1400):,} of {nrel:,} tracked balls. Green over the wicket, gold round. Dashed white: "
              "45 cm and 75 cm from middle stump. Solid white: the return creases.</p>" if rel else "")
            + "</div><div class='col'>" + _crease(P) + "</div></div>")
    ang += _over_construction(P)
    s.append(sec(sid("ang"), "Angle and release", who, ang))

    # ── movement ──
    grids = [(hword[h], beaten_grid(Ps[h].get("beaten_df") or [], spin=bool(P.get("is_spin")))) for h in hands]
    s.append(sec(sid("mv"), "Movement", who + ", against the average " + ("spinner" if P["is_spin"] else "pace bowler"),
                 _movement(P) + panes([g[0] for g in grids], [g[1] for g in grids], "Where they beat the bat")))

    # ── field and vision ──
    fb = "".join(f"<div>{_fields_block(P['bowler_id'], ctx['plan'], h, 'To ' + hword[h].lower())}</div>" for h in hands)
    s.append(sec(sid("fld"), "Their field", "", f"<div class='two'>{fb}</div>"
                 "<p class='note'>The planner's fields for this bowler. A field the coaches set replaces the estimate and carries a "
                 "gold dot.</p>"))
    s.append(sec(sid("vis"), "Vision", "", _vision(ctx.get("clips"))))
    return "".join(s)


_JUMP = (("sum", "Summary"), ("thr", "Threat"), ("bt", "Ball types"), ("mu", "Match-ups"), ("sc", "Scoring"),
         ("pace", "Pace"), ("ang", "Angle and release"), ("mv", "Movement"), ("fld", "Their field"), ("vis", "Vision"))


def bowler_page(bid, Ps, ctx):
    """The whole page: header with the scope switch, the jump strip, a pane per scope."""
    P = Ps["All"]
    name = person(P["name"])
    have = [(k, lab) for k, H, lab, _w in SCOPES if Ps.get(H) and Ps[H].get("n_balls")]
    seg = ("<div class='seg' role='tablist' aria-label='Batters'>" + "".join(
        f"<button type='button' data-scope='{k}' class='{'on' if i == 0 else ''}'>{E(lab)}</button>"
        for i, (k, lab) in enumerate(have)) + "</div>")
    last = max((r.get("match_date") or "" for r in P["raw"]), default="")
    img = ctx.get("img") or ""
    av = (f"<img class='av lg' src='{E(img)}' alt=''>" if img else
          f"<span class='av lg ini'>{E(''.join(w[0] for w in name.split()[:2]))}</span>")
    head = (f"<header class='ph'><div class='in'><a class='back' href='{E(ctx.get('back_href', 'index.html'))}'>‹ "
            f"{E(ctx.get('back_label', 'Reports'))}</a>"
            f"<div class='who'>{av}<div><h1>{E(name)}</h1><div class='sb'>{E(type_word(P.get('primary_type')))} · "
            f"{E(team_word(P.get('team')))} · Tests, career</div></div></div>"
            f"<div class='ctl'><span class='k'>Batters</span>{seg}<span class='stamp'>Built {E(ctx['built'])} · "
            f"Tests to {_day(last)}</span></div></div></header>")
    nav = ("<nav class='jump'><div class='in'>" + "".join(
        f"<a href='#all-{a}' data-to='{a}'>{E(t)}</a>" for a, t in _JUMP) + "</div></nav>")
    body = "".join(f"<div class='scope' data-scope='{k}'{'' if i == 0 else ' hidden'}>"
                   f"{_bowler_scope(k, Ps[H], Ps, ctx)}</div>"
                   for i, (k, H, _l, _w) in enumerate(s for s in SCOPES if Ps.get(s[1]) and Ps[s[1]].get("n_balls")))
    hp = {"series": ctx.get("planner") or "", "pid": str(bid), "kind": "bowler"}
    return head + nav + f"<main class='hpw'>{body}</main>" + ctx["defs"].html(), hp, f"{name} · bowling"


# ── the pictures a bowler's page needs, made once per hand ────────────────────────────────────
def _angle_block(Ph, hand, pics_dir, bid, defs):
    """Over and round the wicket side by side, with a Dots / Density switch."""
    import os
    legal = [r for r in Ph["df"] if r.get("is_legal")]
    lhb, spin = hand == "LHB", bool(Ph.get("is_spin"))
    dots, dens = [], []
    for ang, flag, word in (("over", False, "Over the wicket"), ("round", True, "Round the wicket")):
        rows = [r for r in legal if r.get("is_round") is flag]
        cap = f"<figcaption>{word} · {len(rows):,}</figcaption>"
        if len(rows) < 150:
            none = f"<figure>{cap}<div class='none'>{len(rows)} balls, too few to draw</div></figure>"
            dots.append(none)
            dens.append(none)
            continue
        f = angle_map_png(rows, os.path.join(pics_dir, f"bowl_{bid}_{hand.lower()}_{ang}.webp"), lhb, spin)
        dots.append(f"<figure>{cap}<img src='pics/{f}' loading='lazy' alt='{word}, every ball'></figure>")
        from cricket_core import cricviz as cv
        dsvg = density_svg(rows, lhb=lhb, bands=cv.SPIN_BANDS if spin else None)
        dens.append(f"<figure>{cap}{defs.use(f'dens-{hand.lower()}-{ang}', dsvg)}</figure>")
    return panes(["Dots", "Density"], [f"<div class='angle'>{''.join(dots)}</div>", f"<div class='angle'>{''.join(dens)}</div>"],
                 "")


def bowler_ctx(bid, Ps, pics_dir, *, plan=None, clips=None, img="", planner="", built="", back=("index.html", "Reports"),
               opp=""):
    import os
    os.makedirs(pics_dir, exist_ok=True)
    P = Ps["All"]
    ctx = {"plan": plan or {}, "clips": clips or {}, "img": img, "planner": planner, "built": built,
           "back_href": back[0], "back_label": back[1], "wicket_pics": {}, "angle_maps": {}, "defs": Defs()}
    d = ctx["defs"]
    for h in ("RHB", "LHB"):
        if Ps.get(h) and Ps[h].get("n_balls"):
            ctx["wicket_pics"][h] = wicket_pics(Ps[h], h == "LHB", d, f"wk-{h.lower()}")
            ctx["angle_maps"][h] = _angle_block(Ps[h], h, pics_dir, bid, d)
    rel, n = release_svg(P["raw"], left_arm=str(P.get("primary_type") or "").lower().startswith("left"))
    ctx["release"] = (d.use("rel", rel, "chart") if rel else "", n)
    ctx["vs_squad"] = _vs_squad(bid, _store(opp))
    return ctx


# ── the page ──────────────────────────────────────────────────────────────────────────────────
def page(title, body, hp, *, fields_v="0", snippet=""):
    import json, os
    from cricket_core import webcharts as wc
    from cricket_core.video import click_guard
    here = os.path.dirname(os.path.abspath(__file__))
    css = wc.CSS + "".join(open(os.path.join(here, f), encoding="utf-8").read() for f in ("hub_pack.css", "report_web.css"))
    js = open(os.path.join(here, "report_web.js"), encoding="utf-8").read()
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{E(title)}</title>{wc.head_links()}<style>{css}</style>{click_guard() if snippet else ''}</head>"
            f"<body class='hp'><!--hub-bar-->{body}"
            f"<script>window.HP={json.dumps(hp, ensure_ascii=False)};</script>"
            f"<script src='/static/fields.js?v={fields_v}'></script><script>{js}</script>{snippet}</body></html>")


def bowler_profiles(bid, raw=None, fmt="Test", level="international"):
    """All batters, then each hand, from one load of the rows."""
    import profile as PR
    import report as R
    from data_loaders import load_bowler_deliveries
    raw = PR.process_rows(raw if raw is not None else load_bowler_deliveries(bid, fmt=fmt, level=level))
    Ps = {}
    for H, hand in (("All", "All"), ("RHB", "vs RHB"), ("LHB", "vs LHB")):
        P = PR.build_profile(bid, hand=hand, raw=raw, fmt=fmt, level=level)
        if P.get("n_balls"):
            Ps[H] = P
    return Ps


# ── a batter's page ───────────────────────────────────────────────────────────────────────────
# The scopes: all bowling, then each type our attack carries. Our side's types, not every type the
# batter has faced: the page is for planning against them.
BAT_GROUPS = (("right_pace", "Right-arm pace"), ("left_pace", "Left-arm pace"), ("off_spin", "Off spin"),
              ("left_orthodox", "Left-arm orthodox"))
_TYPE_GROUP = {"Right Fast": "right_pace", "Right Medium": "right_pace", "Left Fast": "left_pace",
               "Left Medium": "left_pace", "Off Spin": "off_spin", "Left Orthodox": "left_orthodox",
               "Leg Break": "leg_spin", "Left Unorthodox": "left_unorthodox"}
_TYPE_WORD = {"Right Fast": "Right-arm fast", "Right Medium": "Right-arm medium", "Left Fast": "Left-arm fast",
              "Left Medium": "Left-arm medium", "Off Spin": "Off spin", "Left Orthodox": "Left-arm orthodox",
              "Leg Break": "Leg spin", "Left Unorthodox": "Left-arm wrist spin"}


def _bpd(d):
    """Balls per dismissal, or None with no dismissal."""
    return d["balls"] / d["outs"] if d.get("outs") else None


def _bat_row(label_html, d):
    return [label_html, _n(d.get("avg"), 1), _n(d.get("sr"), 0), _n(d.get("false_pct"), 0, "%"), _n(_bpd(d), 0),
            f"{d['balls']:,}"]


_BAT_HEADS = ["Average", "Strike rate", "False shots", "BPD", "Balls"]


def _dim_table(dim, key, title, is_spin=False):
    """A dimension of the record as a table, the lowest average (on 40 balls or more) shaded."""
    import batting_report as BR
    if not dim:
        return ""
    scored = [i for i, d in enumerate(dim) if d.get("avg") is not None and d["balls"] >= 40]
    hi = min(scored, key=lambda i: dim[i]["avg"]) if scored else None
    rows = [_bat_row(E(_cap(BR._blabel(d["bucket"], key, is_spin))), d) for d in dim]
    return table([title] + _BAT_HEADS, rows, hi=hi)


def _bat_facts(P, key):
    """The facts block for a batter, each a computed number and what it is of."""
    import batting_report as BR
    out = []
    isg = bool(P.get("is_spin_group"))
    # all bowling: the length and line splits are v pace (or spin); a type's scope is that type
    against = ("v spin" if isg else "v pace") if key == "all" else "v " + dict(BAT_GROUPS)[key].lower()
    dims = P.get("dims") or {}
    avg = P.get("average")
    for k, word in (("length", "length"), ("line", "pitching line")):
        w = BR._worst(dims.get(k) or [])
        if w and avg and w["avg"] < avg * 0.9:
            out.append((f"Lowest by {word}", f"<b>{E(BR._pitch_line(w['bucket']) if k == 'line' else str(w['bucket']).lower())}</b> "
                        f"· average {w['avg']:.1f} over {w['balls']:,} balls ({against}, "
                        f"{avg:.1f} {'overall' if key == 'all' else 'against the type in all'})"))
    mv = [d for d in dims.get("seam") or [] if d["balls"] >= 40 and d.get("avg") is not None]
    if mv:
        out.append(("Movement", " · ".join(f"{E(BR._blabel(d['bucket'], 'seam_dir', isg))} {d['avg']:.1f}" for d in mv)))
    g = P.get("grid_danger")
    if g and g.get("outs"):
        out.append(("Out most often to", f"<b>{E(g['length_band'].lower())} {E(g['line_region'])}</b> · "
                    f"BPD {_bpd(g):.0f}, average {_n(g.get('avg'), 0)}, {g['balls']} balls"))
    dis = P.get("dismissals")
    if dis:
        n = sum(dis.values())
        out.append(("How out", " · ".join(f"{E(k.lower())} {v / n * 100:.0f}%" for k, v in dis.most_common(3))))
    ph = P.get("phase") or {}
    if ph.get("early") and ph.get("set"):
        out.append(("First 30 balls", f"average {_n(ph['early']['avg'], 1)}, BPD {_n(_bpd(ph['early']), 0)} · "
                    f"once set {_n(ph['set']['avg'], 1)}, BPD {_n(_bpd(ph['set']), 0)}"))
    off, leg = _sides(P)
    if off is not None:
        out.append(("Runs by side", f"off side <b>{off:.0f}%</b> · leg side <b>{leg:.0f}%</b>"))
    if key == "all":
        vd = [(t, v) for t, v in (P.get("vs_detail") or {}).items() if v["balls"] >= 300 and v.get("avg")]
        if len(vd) >= 2:
            lo, hi_ = min(vd, key=lambda tv: tv[1]["avg"]), max(vd, key=lambda tv: tv[1]["avg"])
            out.append(("By bowler type", f"lowest {E(_TYPE_WORD.get(lo[0], lo[0]).lower())} {lo[1]['avg']:.1f} · "
                        f"highest {E(_TYPE_WORD.get(hi_[0], hi_[0]).lower())} {hi_[1]['avg']:.1f} (300 balls or more)"))
    return out


def _bat_pct(fp):
    """Batting fingerprint strips. A false-shot row is better low, which the note says."""
    rows = [dict(f, label=f["label"].replace("False-shot %", "False shots").replace("False % vs", "False shots v"))
            for f in fp or []]
    return pct_rows(rows)


def _bat_wicket_pics(P, defs, key):
    from cricket_core import cricviz as cv
    outs = [dict(r, striker_dismissed="1") for r in P["raw"] if r.get("is_legal") and (r.get("is_out") or r.get("is_wicket"))]
    if len(outs) < 5:
        return "<p class='note'>Too few dismissals to draw.</p>", len(outs)
    lhb = bool(P.get("is_lhb"))
    bands = {"bands": cv.SPIN_BANDS} if P.get("is_spin_group") else {}
    pm = cv.pitch_map(outs, lhb=lhb, metrics=False, **bands)
    bh = cv.beehive(outs, lhb=lhb)
    return f"<div class='pics2'>{defs.use(key + '-opm', pm, 'pm')}{defs.use(key + '-obh', bh, 'bh')}</div>", len(outs)


def _bat_wheel(P, defs, key):
    """Runs by fielding area (the packs' zones wheel) with the CricViz spider beside it on a toggle."""
    from cricket_core import charts, cricviz as cv
    from build_hub_packs import _zones_svg
    lhb = bool(P.get("is_lhb"))
    rows = [r for r in P["raw"] if r.get("is_legal")]
    zones = {}
    for r in rows:
        runs = r.get("bat_score_n") or 0
        if runs:
            k = charts.wagon_sector(r, lhb)
            if k:
                zones[k] = zones.get(k, 0) + runs
    if not zones:
        return ""
    spider = cv.wagon_wheel([r for r in rows if (r.get("bat_score_n") or 0) > 0], lhb=lhb)
    side = "left" if not lhb else "right"
    return (panes(["Zones", "Every scoring shot"],
                  [f"<div class='wheelbox'>{_zones_svg(zones, lhb)}</div>",
                   f"<div class='wheelbox'>{defs.use(key + '-spider', spider)}</div>"], "Runs")
            + f"<p class='note' style='text-align:center'>{int(sum(zones.values())):,} runs · off side on the {side}</p>")


def _attacked(pid, name):
    try:
        from attack_cards import card_for
        card = card_for(pid, name)
        return card if card and card.get("series") else None
    except Exception:
        return None


def _store(opp):
    """The series' match-up store, chosen by name. Not the first store that mentions the player:
    a South Africa batter is in both the ODI store (matchup_store_south_africa) and the Test one,
    and the ODI one sorts first (12-10-2026)."""
    import json as _j
    import os
    if not opp:
        return None
    try:
        from cricket_core.config import project_path
        p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{opp}.json")
        return _j.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    except Exception:
        return None


def _sim_options(pid, store):
    """Our bowlers against this batter, best first."""
    cells = [c for c in (store or {}).get("they_bat", []) if c["batter_id"] == str(pid) and c["sim_avg"] is not None]
    return sorted(cells, key=lambda c: c["sim_avg"])


def _vs_squad(bid, store):
    """Our frontline batters against this bowler, exceptions only, gated as the A4 report gates
    them (report._vs_squad_ctx): medium or high confidence and well clear of the median."""
    import json as _j
    import os
    roles_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "players.json")
    roles = ({k: r.get("role") for k, r in _j.load(open(roles_p, encoding="utf-8")).items()}
             if os.path.exists(roles_p) else {})
    cells = [c for c in (store or {}).get("we_bat", []) if c["bowler_id"] == str(bid) and c["sim_avg"] is not None
             and roles.get(c["batter_id"]) != "Bowler"]
    if not cells:
        return None
    solid = [c for c in cells if c["confidence"] in ("Med", "High")]
    med = sorted(c["sim_avg"] for c in cells)[len(cells) // 2]
    threats = sorted([c for c in solid if c["sim_avg"] <= 0.75 * med], key=lambda c: c["sim_avg"])[:3]
    targets = sorted([c for c in solid if c["sim_avg"] >= 1.3 * med], key=lambda c: -c["sim_avg"])[:3]
    if not (threats or targets):
        return None
    return {"threats": [(c["batter"], c["bat_hand"], c["sim_avg"], c.get("top_dismissal", "")) for c in threats],
            "targets": [(c["batter"], c["bat_hand"], c["sim_avg"]) for c in targets]}


def _bat_fields(pid, rows_by_group, group, title, hand):
    import json as _j
    row = rows_by_group.get(group) or {}
    opts = [{"slot": "", "name": _FIELD_NAME.get(f["label"], f["label"]),
             "fielders": [{"angle": p["angle"], "radius": p["radius"]} for p in f["fielders"]], "spare": f.get("spare")}
            for f in row.get("fields") or [] if f.get("fielders") and "alternative" not in f["label"]]
    data = _j.dumps(opts, ensure_ascii=False, separators=(",", ":"))
    return (f"<div class='fb' data-fb='{E(str(pid))}' data-kind='batter' data-hand='{hand}' "
            f"data-pack='{E(group)}' data-opts='{E(data)}'>{label(title)}<div class='fbody'></div></div>")


# ── a batter: Tom's 16-10-2026 read of the England pages ─────────────────────────────────────────
# Facts as tiles across the page, not a list down its left; each reel beside the numbers it shows
# rather than a Vision section at the end; the scoring split by side only (no shot types — "off the
# hook" against spin made no sense); and three questions answered from the record: is hitting the
# stumps worth more, which length and line, and how they go against the slower ball.
_OFF_SECTORS = {"Third Man", "Cover Point", "Cover", "Mid-Off"}


def fact_tiles(rows, title="The facts"):
    rows = [(k, v) for k, v in rows if v]
    if not rows:
        return ""
    return (f"<div class='fx'><div class='lbl'>{E(title)}</div><div class='ftiles'>"
            + "".join(f"<div class='ft'><div class='k'>{E(k)}</div><div class='v'>{v}</div></div>" for k, v in rows)
            + "</div></div>")


def _reels(clips, keys, used=None):
    """Reel buttons for these clip keys, in a row under the numbers they show."""
    out = []
    for k in keys:
        v = (clips or {}).get(k) or {}
        if v.get("items"):
            t = str(v.get("title") or k)
            t = t.capitalize() if t.istitle() and " " in t else t
            out.append(f"<a class='vlink rl' data-pl='{E(k)}' data-n='{len(v['items'])}' href='#'>{E(t)}</a>")
            if used is not None:
                used.add(k)
    return f"<div class='reels inline'>{''.join(out)}</div>" if out else ""


def _sides(P):
    """Runs to the off side and the leg side, from the same eight areas the wheel draws."""
    from cricket_core import charts
    lhb = bool(P.get("is_lhb"))
    off = leg = 0.0
    for r in P["raw"]:
        runs = r.get("bat_score_n") or 0
        if r.get("is_legal") and runs:
            k = charts.wagon_sector(r, lhb)
            if k:
                if k in _OFF_SECTORS:
                    off += runs
                else:
                    leg += runs
    tot = off + leg
    return (off / tot * 100, leg / tot * 100) if tot else (None, None)


def _hits_stumps(r):
    """Would this ball have hit the stumps: through the stumps' width (plus the ball) and under the
    bails, from the tracked line and height at the stumps. None when the ball was not tracked."""
    line, height = r.get("at_stumps_line_m"), r.get("at_stumps_height_m")
    if line is None or height is None or height <= 0 or height > 2.5 or abs(line) > 3:
        return None
    return abs(line) <= 0.15 and height <= 0.75


_SPEED_REF = {}
_SPEED_WORD = {"Test": "first-class", "ODI": "one-day", "T20": "T20", "T20I": "T20"}


def _off_pace(fmt):
    """{bowler_id: the speed below which a ball is well off their stock pace}, for this format."""
    if fmt in _SPEED_REF:
        return _SPEED_REF[fmt]
    import csv
    import os
    from cricket_core.config import project_path
    want = {"Test": "multi-day", "ODI": "one-day", "T20": "T20", "T20I": "T20"}.get(fmt, "multi-day")
    p = os.path.join(project_path("referencebuilder"), "data", "bowler_speed_profile_by_format.csv")
    out = {}
    if os.path.exists(p):
        for row in csv.DictReader(open(p, encoding="utf-8")):
            if row.get("format") == want and row.get("off_pace_kph"):
                try:
                    out[str(row["bowler_id"])] = float(row["off_pace_kph"])
                except ValueError:
                    pass
    _SPEED_REF[fmt] = out
    return out


def _line_length(key, P, ctx, isg, against):
    """Is hitting the stumps worth more, which length and line, and the slower ball — each from the
    record against this scope's bowling (pace for the all-bowling page, spin for a spin type)."""
    from batter_profile import _split_stats
    legal = [r for r in P["raw"] if r.get("is_legal")]
    rows = [r for r in legal if bool(r.get("vs_pace")) != isg] if key == "all" else legal
    blocks, grid = [], ""
    # the stumps: on the all-bowling page pace and spin both, since a batter bowled or LBW to one
    # and never the other is the point (Duckett's six in ODIs all came from spin)
    sets = ([("pace", [r for r in legal if r.get("vs_pace")]), ("spin", [r for r in legal if not r.get("vs_pace")])]
            if key == "all" else [(against, rows)])
    trs, his, notes = [], [], []
    for word, rs in sets:
        hit = [r for r in rs if _hits_stumps(r) is True]
        miss = [r for r in rs if _hits_stumps(r) is False]
        tracked = len(hit) + len(miss)
        if tracked < 120 or len(hit) < 30:
            continue
        a, b = _split_stats(hit), _split_stats(miss)
        bm = sum(1 for r in hit if r.get("is_out") and r.get("how_out") in ("Bowled", "LBW"))
        pre = f"{_cap(word)} · " if key == "all" else ""
        if (_bpd(a) or 1e9) < (_bpd(b) or 1e9):
            his.append(len(trs))
        elif _bpd(b):
            his.append(len(trs) + 1)
        trs += [_bat_row(f"{pre}hitting", a), _bat_row(f"{pre}missing", b)]
        outs = (f"{bm} of the {a['outs']} dismissals off them bowled or LBW" if a["outs"]
                else "no dismissals off them")
        notes.append(f"v {word}, {len(hit) / tracked * 100:.0f}% of {tracked:,} tracked balls were hitting the stumps, {outs}")
    if trs:
        import report_visuals as RV
        tab = (table(["Stumps"] + _BAT_HEADS, trs, hi=his)
               + f"<p class='note'>{'. '.join(_cap(n) for n in notes)}. Hitting = through the stumps' width and under the bails "
                 "at the stumps, from ball tracking. The shaded row in each pair has the lower BPD.</p>")
        pic = RV.stumps_view([(f"v {w}", rs) for w, rs in sets], bool(P.get("is_lhb")))
        blocks.append(panes(["Chart", "Table"], [pic, tab], "Hitting the stumps") if pic
                      else label("Hitting the stumps") + tab)
    # length x pitching line
    lengths = [d["bucket"] for d in (P.get("dims") or {}).get("length") or []]
    lines = [d["bucket"] for d in (P.get("dims") or {}).get("line") or []]
    if key != "all":
        lengths = lengths or sorted({r.get("length_band") for r in rows if r.get("length_band")})
    cells = {}
    for r in rows:
        lb, lr = r.get("length_band"), r.get("line_region")
        if lb in lengths and lr in lines:
            cells.setdefault((lb, lr), []).append(r)
    stats = {k: _split_stats(v) for k, v in cells.items()}
    good = {k: s for k, s in stats.items() if s["balls"] >= 20}
    if len(good) >= 4:
        import batting_report as BR
        low = min((k for k, s in good.items() if s["outs"] >= 2), key=lambda k: _bpd(good[k]), default=None)
        head = "<tr><th></th>" + "".join(f"<th>{E(_cap(str(BR._blabel(l, 'line_region', isg))))}</th>" for l in lines) + "</tr>"
        body = ""
        for lb in lengths:
            tds = ""
            for lr in lines:
                s = good.get((lb, lr))
                if not s:
                    tds += "<td class='thin'>–</td>"
                    continue
                cls = " class='hi'" if (lb, lr) == low else ""
                sub = f"avg {_n(s.get('avg'), 0)} · {s['balls']} balls" if s["outs"] else f"{s['balls']} balls"
                tds += f"<td{cls}><b>{f'BPD {_bpd(s):.0f}' if s['outs'] else 'no outs'}</b><small>{sub}</small></td>"
            body += f"<tr><th>{E(_cap(str(BR._blabel(lb, 'length_band', isg)).lower()))}</th>{tds}</tr>"
        import report_visuals as RV
        tab = (f"<div class='tw'><table class='t grid'><thead>{head}</thead><tbody>{body}</tbody></table></div>"
               + "<p class='note'>BPD (balls per dismissal), then the average and the balls, on 20 balls or more. "
                 "The shaded cell has the lowest BPD on two dismissals or more.</p>")
        pic = RV.danger_map(rows, bool(P.get("is_lhb")), isg)
        title = f"By length and pitching line · v {against}"
        grid = panes(["Chart", "Table"], [pic, tab], title) if pic else label(title) + tab
    # the slower ball (pace)
    if not isg:
        ref = _off_pace(ctx.get("fmt", "Test"))
        known = [r for r in rows if r.get("ball_speed_n") and ref.get(str(r.get("bowler_id")))]
        slow = [r for r in known if r["ball_speed_n"] < ref[str(r["bowler_id"])]]
        stock = [r for r in known if r["ball_speed_n"] >= ref[str(r["bowler_id"])]]
        if len(slow) >= 25 and stock:
            a, b = _split_stats(slow), _split_stats(stock)
            lo = 0 if (_bpd(a) or 1e9) < (_bpd(b) or 1e9) else 1
            blocks.append(label("Slower balls · v pace") + table(
                [""] + _BAT_HEADS, [_bat_row("Slower balls", a), _bat_row("Stock pace", b)], hi=lo)
                + f"<p class='note'>A slower ball is one well off that bowler's own stock pace, set from their tracked "
                  f"speeds in {_SPEED_WORD.get(ctx.get('fmt', 'Test'), 'first-class')} cricket — {len(slow) / len(known) * 100:.0f}% of the "
                  f"{len(known):,} tracked balls from pace. The shaded row has the lower BPD.</p>")
    # the stumps and the slower ball down the left, the length-by-line grid on the right
    if not (blocks or grid):
        return ""
    if not (blocks and grid):
        return "".join(blocks) + grid
    return f"<div class='two'><div class='col'>{''.join(blocks)}</div><div class='col'>{grid}</div></div>"


def _batter_scope(key, P, Pb, ctx):
    import batting_report as BR
    sid = lambda s: f"{key}-{s}"
    pid = str(P["batter_id"])
    groups = [g for g, _l in BAT_GROUPS if Pb.get(g)] if key == "all" else [key]
    gword = dict(BAT_GROUPS)
    who = "all bowling" if key == "all" else gword[key].lower()
    isg = bool(P.get("is_spin_group"))
    s = []

    # ── summary ──
    optional = " data-optional='1'" if key == "all" else ""
    notes = "<div class='notes2'>" + "".join(
        f"<div class='cn' data-notes='{E(pid)}' data-pack='{E(g)}'{optional} "
        f"data-title=\"Coaches' notes{' · v ' + gword[g].lower() if key == 'all' else ''}\" hidden></div>" for g in groups) + "</div>"
    fg = [(f"{P['runs']:,.0f}", "Runs"), (_n(P.get("average"), 1), "Average"), (_n(P.get("strike_rate"), 1), "Strike rate"),
          (f"{P.get('n_out') or 0}", "Dismissals")]
    nb = sum(1 for r in P["raw"] if r.get("is_legal"))
    if P.get("n_out"):
        fg.append((f"{nb / P['n_out']:.0f}", "BPD"))
    sh = P.get("share") or {}
    if key == "all" and sh.get("team_share_median") is not None:
        fg.append((f"{sh['team_share_median']:.1f}%", "Typical share of team runs"))
    fp = _bat_pct(ctx["fp"]) if key == "all" else ""
    s.append(sec(sid("sum"), "Summary", who,
                 notes + figs(fg) + fact_tiles(_bat_facts(P, key))
                 + ((label(f"Against {ctx.get('one', 'Test')} batters, career and last 3 years" if ctx.get("fmt", "Test") == "Test"
                          else f"Against {'T20I' if ctx.get('fmt') == 'T20' else ctx.get('one')} batters: internationals between "
                               "full members since 2015") + fp
                    + (f"<p class='note'>On {ctx['fp'][0]['n_balls']:,} balls, below the cohort's floor: ranked against the "
                       "cohort, a small sample.</p>" if ctx["fp"] and ctx["fp"][0].get("small") else "")
                     + "<p class='note'>For the false-shot rows a low percentile is good: fewer false shots than most. The solid mark "
                       "is the career, the dotted gold mark the last three years. Bands: 80 and above among the highest, 60-80 above "
                       "average, 40-60 around average, 20-40 below average, under 20 among the lowest.</p>") if fp else "")))

    # ── by bowler type (all bowling only) ──
    if key == "all":
        rows = []
        for lab, k in (("Pace", "pace"), ("Spin", "spin")):
            v = (P.get("vs") or {}).get(k)
            if v:
                rows.append(_bat_row(f"<b>{lab}</b>", v))
        det = sorted((P.get("vs_detail") or {}).items(), key=lambda kv: -kv[1]["balls"])
        for t, v in det:
            rows.append(_bat_row(E(_TYPE_WORD.get(t, t)), v))
        scored = [i for i, (t, v) in enumerate(det, start=len(rows) - len(det)) if v.get("avg") is not None and v["balls"] >= 300]
        lo = min(scored, key=lambda i: det[i - (len(rows) - len(det))][1]["avg"]) if scored else None
        import report_visuals as RV
        tab = (table(["Bowler type"] + _BAT_HEADS, rows, hi=lo)
               + "<p class='note'>The shaded row is the lowest average on 300 balls or more. The switch at the top narrows the "
                 "whole page to one type.</p>")
        vs = P.get("vs") or {}
        bars = RV.type_bars([(f"<b>{lab}</b>", vs[k]) for lab, k in (("Pace", "pace"), ("Spin", "spin")) if vs.get(k)]
                            + [(E(_TYPE_WORD.get(t, t)), v) for t, v in det], P.get("average"))
        s.append(sec(sid("type"), "By bowler type", who, panes(["Chart", "Table"], [bars, tab], "Average") if bars else tab))

    # ── where they get out ──
    pics, n_out = ctx["out_pics"][key]
    dims = P.get("dims") or {}
    g = P.get("grid_danger")
    danger = (f"<div class='z w' style='margin-top:10px'><div class='k'>Out most often to"
              f"{' (v ' + ('spin' if isg else 'pace') + ')' if key == 'all' else ''}</div><div class='v'>"
              f"{E(_cap(g['length_band'].lower()))} {E(g['line_region'])}</div><div class='s'>BPD {_bpd(g):.0f} · average "
              f"{_n(g.get('avg'), 0)} · {g['balls']} balls · false shots {_n(g.get('false_pct'), 0, '%')}</div></div>"
              if g and g.get("outs") else "")
    against = "spin" if isg else "pace"
    dtabs = (_dim_table(dims.get("length"), "length_band", "Length") + _dim_table(dims.get("line"), "line_region", "Pitching line")
             + _dim_table(dims.get("seam"), "seam_dir", "Turn" if isg else "Seam movement", isg))
    dis = P.get("dismissals")
    how = ""
    if dis:
        import report_visuals as RV
        n = sum(dis.values())
        how = table(["How out", "Count", "Share"], [[E(k), str(v), f"{v / n * 100:.0f}%"] for k, v in dis.most_common()], cls="narrow")
        ground = RV.catch_map(P["raw"], bool(P.get("is_lhb")))
        how = panes(["Ground", "Table"], [ground, how], "How out") if ground else how
    extra = []
    for k, word in (("speed", "speed"), ("over_round", "angle")):
        w = BR._worst(dims.get(k) or [])
        if w:
            extra.append(f"Lowest average by {word}{' v ' + against if key == 'all' else ''}: "
                         f"{E(str(BR._blabel(w['bucket'], k)).lower())} {w['avg']:.1f} over {w['balls']:,} balls.")
    # the reels sit with the numbers they show (the same reels on every scope, as the Vision section was)
    clips = ctx.get("clips") or {}
    used = set()
    s.append(sec(sid("vul"), "Where they get out", who,
                 _reels(clips, ("dismissals", "danger"), used)
                 + "<div class='two wide-l'><div class='col'>" + label(f"Dismissals · {n_out}") + pics + danger + how + "</div>"
                 f"<div class='col'>{label('By ball, v ' + against) if key == 'all' else ''}{dtabs}</div></div>"
                 f"<p class='note'>{' '.join(extra)} The shaded row in each table is the lowest average on 40 balls or more. "
                 "BPD is balls per dismissal.</p>"))

    # ── how they score ──
    off, leg = _sides(P)
    sfig = [(f"{off:.0f}%", "Runs off side"), (f"{leg:.0f}%", "Runs leg side")] if off is not None else []
    st = dims.get("stroke") or []
    shot = lambda b: "Pull" if isg and b == "Pull/Hook" else b.replace("/", " / ")
    worst_false = max(range(len(st)), key=lambda i: st[i].get("false_pct") or 0) if st else None
    stab = (label("Shots v " + against) if key == "all" and st else "") + table(["Shot"] + _BAT_HEADS, [_bat_row(E(shot(d["bucket"])), d) for d in st], hi=worst_false) if st else ""
    rest = [k for k in (clips or {}) if k not in used and k not in ("risky_stroke", "false_shots")]
    s.append(sec(sid("score"), "How they score", who,
                 _reels(clips, ("risky_stroke", "false_shots", *rest), used)
                 + f"<div class='two'><div>{ctx['wheels'][key]}</div><div class='col'>{figs(sfig)}{stab}"
                 + ("<p class='note'>The shaded shot has the most false shots.</p>" if st else "") + "</div></div>"))

    # ── line, length and pace ──
    llp = _line_length(key, P, ctx, isg, against if key == "all" else gword[key].lower())
    if llp:
        s.append(sec(sid("llp"), "Line, length and pace", who, llp))

    # ── how attacks bowled, and our options (all bowling only) ──
    if key == "all" and ctx.get("attacked") and ctx.get("fmt", "Test") == "Test":
        a = ctx["attacked"]
        rows = []
        for r in a.get("series") or []:
            rows.append([f"v {E(str(r.get('opp') or ''))}<small style='display:block;color:var(--muted)'>{_day(r.get('d0'))}</small>",
                         str(r.get("tests") or ""), _n(r.get("balls")), _n(r.get("runs")), _n(r.get("avg"), 1),
                         f"<span class='wrap'>{E(str(r.get('summary') or ''))}</span>"])
        if rows:
            s.append(sec(sid("att"), "How attacks bowled to them", "last 3 series",
                         table(["Series", "Tests", "Balls", "Runs", "Average", "What they bowled"], rows)))
    opts = ctx.get("sim") or []
    if key != "all":
        opts = [c for c in opts if c.get("bowler_type_key") == key]
    if opts:
        rows = [[E(c["bowler"]), E(c.get("bowler_type") or ""), f"{c['sim_avg']:.1f}",
                 _n(c.get("fail_to_set_pct"), 1, "%"), E(c.get("top_dismissal") or "")] for c in opts[:6]]
        s.append(sec(sid("opt"), "Our options", "", "<p class='note'>From the match simulation, which plays each pairing "
                     f"thousands of times from full {ctx.get('one', 'Test')} records. A lower expected average favours our bowler.</p>"
                     + table(["Bowler", "Type", "Expected avg", "Out in first 30", "Top dismissal"], rows, hi=0),
                     extra="<span class='sim'>Match simulation</span>"))

    # ── field and vision ──
    fb = [(gword[g], _bat_fields(pid, ctx["field_rows"], g, "v " + gword[g].lower(), "LHB" if P.get("is_lhb") else "RHB"))
          for g in groups if any(f.get("fielders") for f in (ctx["field_rows"].get(g) or {}).get("fields") or [])]
    if fb:
        body = (panes([f[0] for f in fb], [f[1] for f in fb], "Bowler type") if len(fb) > 1 else fb[0][1])
        s.append(sec(sid("fld"), "Your field", "", f"<div class='two'><div>{body}</div><div><p class='note'>The planner's fields "
                     "for this batter, one per situation. A field the coaches set replaces the estimate and carries a gold dot.</p>"
                     "</div></div>"))
    return "".join(s)


_BAT_JUMP = (("sum", "Summary"), ("type", "By bowler type"), ("vul", "Where they get out"), ("score", "How they score"),
             ("llp", "Line, length and pace"), ("att", "How attacks bowled"), ("opt", "Our options"), ("fld", "Your field"))


def batter_profiles(pid, raw=None, fmt="Test", level="international", source="warehouse"):
    """All bowling, each of our attack's types, and the last three years for the fingerprint."""
    import datetime as dt
    from batting_loaders import load_batter_deliveries
    from batter_profile import build_batter_profile, process_batting_rows
    raw = process_batting_rows(raw if raw is not None else load_batter_deliveries(pid, fmt=fmt, level=level, source=source))
    Pb = {"All": build_batter_profile(pid, raw=raw, fmt=fmt, level=level, source=source), "_source": source}
    for g, _l in BAT_GROUPS:
        P = build_batter_profile(pid, raw=raw, group=g, fmt=fmt, level=level, source=source)
        if sum(1 for r in P["raw"] if r.get("is_legal")) >= 300:
            Pb[g] = P
    cut = (dt.date.today() - dt.timedelta(days=int(365.25 * 3))).isoformat()
    rec = [r for r in raw if (r.get("match_date") or "") >= cut]
    Pb["_recent"] = (build_batter_profile(pid, raw=rec, fmt=fmt, level=level, source=source)
                     if sum(1 for r in rec if r.get("is_legal")) >= 300 else None)
    return Pb


def batter_ctx(pid, Pb, pics_dir, *, clips=None, img="", planner="", built="", back=("index.html", "Reports"),
               field_rows=None, opp="", fmt="Test"):
    import batting_report as BR
    P = Pb["All"]
    d = Defs()
    one, many = {"Test": ("Test", "Tests"), "ODI": ("ODI", "ODIs"), "T20": ("T20I", "T20Is")}.get(fmt, ("Test", "Tests"))
    ctx = {"clips": clips or {}, "img": img, "planner": planner, "built": built, "back_href": back[0], "back_label": back[1],
           "defs": d, "out_pics": {}, "wheels": {}, "field_rows": field_rows or {}, "fmt": fmt, "one": one, "many": many}
    for k, Pk in [("all", P)] + [(g, Pb[g]) for g, _l in BAT_GROUPS if Pb.get(g)]:
        ctx["out_pics"][k] = _bat_wicket_pics(Pk, d, f"bo-{k}")
        ctx["wheels"][k] = _bat_wheel(Pk, d, f"bw-{k}")
    fp_recent = {}
    Pr = Pb.get("_recent")
    if Pr and (Pr.get("n_out") or 0) >= 6:
        vp, vs = (Pr.get("vs") or {}).get("pace") or {}, (Pr.get("vs") or {}).get("spin") or {}
        fp_recent = {k: v for k, v in (("Average", Pr.get("average")), ("Strike rate", Pr.get("strike_rate")),
                                       ("False % vs pace", vp.get("false_pct")), ("False % vs spin", vs.get("false_pct")))
                     if v is not None}
    # Each format ranks against its own reference (batter_vulnerability_profile[_odi|_t20i].csv). The
    # white-ball ones count internationals between full members from 2015, so the last-three-years
    # mark (from this page's own rows: every ODI, or every T20 league for T20) is left off there.
    ctx["fp"] = BR._fingerprint_cards(P, recent_vals=fp_recent if fmt == "Test" else {})
    ctx["attacked"] = _attacked(pid, P.get("name")) if fmt == "Test" else None    # attack cards read Tests
    ctx["sim"] = _sim_options(pid, _store(opp))
    return ctx


def batter_page(pid, Pb, ctx):
    P = Pb["All"]
    rec_note = ""
    if Pb.get("_source", "warehouse") != "warehouse":
        import batting_report as BR
        rec_note = BR._record_label(P.get("raw") or [], ctx.get("fmt", "Test"), "international")
    name = person(P["name"])
    scopes = [("all", "All")] + [(g, lab) for g, lab in BAT_GROUPS if Pb.get(g)]
    seg = ("<div class='seg' role='tablist' aria-label='Bowling'>" + "".join(
        f"<button type='button' data-scope='{k}' class='{'on' if i == 0 else ''}'>{E(lab)}</button>"
        for i, (k, lab) in enumerate(scopes)) + "</div>")
    last = max((r.get("match_date") or "" for r in P["raw_all"] if isinstance(r, dict)), default="") if P.get("raw_all") else \
        max((r.get("match_date") or "" for r in P["raw"]), default="")
    img = ctx.get("img") or ""
    av = (f"<img class='av lg' src='{E(img)}' alt=''>" if img else
          f"<span class='av lg ini'>{E(''.join(w[0] for w in name.split()[:2]))}</span>")
    head = (f"<header class='ph'><div class='in'><a class='back' href='{E(ctx.get('back_href', 'index.html'))}'>‹ "
            f"{E(ctx.get('back_label', 'Reports'))}</a>"
            f"<div class='who'>{av}<div><h1>{E(name)}</h1><div class='sb'>{'Left-hander' if P.get('is_lhb') else 'Right-hander'} · "
            f"{E(team_word(P.get('team')) or 'first-class')}{'' if rec_note else ' · ' + ctx.get('many', 'Tests') + ', career'}</div>"
            f"{('<div class=\'sb\'>' + E(rec_note) + '</div>') if rec_note else ''}</div></div>"
            f"<div class='ctl'><span class='k'>Bowling</span>{seg}<span class='stamp'>Built {E(ctx['built'])} · "
            f"{ctx.get('many', 'Tests')} to {_day(last)}</span></div></div></header>")
    nav = ("<nav class='jump'><div class='in'>" + "".join(
        f"<a href='#all-{a}' data-to='{a}'>{E(t)}</a>" for a, t in _BAT_JUMP) + "</div></nav>")
    body = "".join(f"<div class='scope' data-scope='{k}'{'' if i == 0 else ' hidden'}>"
                   f"{_batter_scope(k, P if k == 'all' else Pb[k], Pb, ctx)}</div>" for i, (k, _l) in enumerate(scopes))
    hp = {"series": ctx.get("planner") or "", "pid": str(pid), "kind": "batter"}
    return head + nav + f"<main class='hpw'>{body}</main>" + ctx["defs"].html(), hp, f"{name} · batting"


# ── a series ──────────────────────────────────────────────────────────────────────────────────
_FMT_WORD = {"test": "Test", "odi": "ODI", "t20": "T20I"}


def _snippet(clips, src):
    if not clips:
        return ""
    from cricket_core.video import inline_player_snippet
    return inline_player_snippet({k: v.get("items") or [] for k, v in clips.items()},
                                 {k: v.get("title") or "" for k, v in clips.items()}, src=src)


def _index(title, sub, groups, back):
    """web/index.html: everyone with a new-look report, bowlers then batters."""
    tiles = []
    for head, rows in groups:
        if not rows:
            continue
        t = "".join(f"<a class='tile' href='{E(href)}'>"
                    + (f"<img class='av sm' src='{E(img)}' alt=''>" if img else
                       f"<span class='av sm ini'>{E(''.join(w[0] for w in name.split()[:2]))}</span>")
                    + f"<span><b>{E(name)}</b><span>{E(what)}</span></span></a>" for name, what, href, img in rows)
        tiles.append(f"<h2 class='sec'>{E(head)}</h2><div class='tiles'>{t}</div>")
    return (f"<header class='ph'><div class='in'><a class='back' href='{E(back[0])}'>‹ {E(back[1])}</a>"
            f"<div class='who'><div><h1>{E(title)}</h1><div class='sb'>{E(sub)}</div></div></div></div></header>"
            f"<main class='hpw'>{''.join(tiles)}</main>")


def build(slug, out_root=None, only=None, kinds=("bowling", "batting")):
    """Write coach/<slug>/web/ into the coach build: a page per player and an index. The pictures
    go in web/pics/. Reads the same series entry, roster and clip lists as build_coach_site."""
    import datetime
    import json
    import os
    import time
    from build_coach_site import _series, _fmt_level, _about, _bowler_plans, _pick, _opp_key
    from publish_site import _sidecar_map
    here = os.path.dirname(os.path.abspath(__file__))
    out_root = out_root or os.path.join(here, "coach_build")
    try:
        entry = _series(slug)
        fk, level = _fmt_level(entry)
    except SystemExit:
        # an archived series has left series.json; squads.json still carries its name and format
        sq = json.load(open(os.path.join(here, "squads.json"), encoding="utf-8")).get(slug)
        if not sq:
            raise
        entry = {"name": sq.get("name") or slug, "format": sq.get("format"), "level": sq.get("level")}
        fk = {"test": "test", "odi": "odi"}.get(str(sq.get("format") or "Test").lower(), "t20")
        level = "a-team" if str(sq.get("level") or "").lower().startswith("a") else "international"
    fmt = {"test": "Test", "odi": "ODI", "t20": "T20"}[fk]
    bowlers, batters = _about(slug)
    smap = _sidecar_map()
    planner = entry.get("planner_series") or ""
    plans = (_bowler_plans(slug) or {}).get("bowlers") or {}
    opp = _opp_key(slug)
    overview = {}
    for g, _l in BAT_GROUPS:
        p = os.path.join(here, "data", f"overview_{g}_{opp}.json")
        if os.path.exists(p):
            overview[g] = {str(r.get("bid")): r for r in json.load(open(p, encoding="utf-8")).get("rows") or []}
    root = os.path.join(out_root, "coach", slug)
    web = os.path.join(root, "web")
    os.makedirs(os.path.join(web, "pics"), exist_ok=True)
    built = datetime.date.today().strftime("%d-%m-%Y")
    fields_v = "0"
    fj = os.path.join(here, "..", "playerpacks", "static", "fields.js")
    if os.path.exists(fj):
        import hashlib
        fields_v = hashlib.sha1(open(fj, "rb").read()).hexdigest()[:10]

    def img(pid):
        for ext in (".png", ".jpg"):
            if os.path.exists(os.path.join(root, "img", f"{pid}{ext}")):
                return f"../img/{pid}{ext}"
        return ""

    def clips_of(pid, kind, name=""):
        hit = _pick(smap, pid, kind, fk, level)
        base = hit[1] if hit else None
        if not base and name:
            # no render sidecars here (a machine that only holds the coach build): find the coach
            # build's clip list by the report's file name, firstname_surname_<kind>_..._test_<hand>
            import glob as _g
            import re as _re
            stem = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            got = sorted(f for f in _g.glob(os.path.join(root, "reports", f"{stem}_{kind}_*{fk}*.clips.json"))
                         if "_vs_" not in f)
            base = os.path.basename(got[0])[:-len(".clips.json")] if got else None
        if not base:
            return {}, ""
        p = os.path.join(root, "reports", f"{base}.clips.json")
        return (json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}), f"../reports/{base}.clips.json"

    order = lambda people: sorted(people.items(), key=lambda kv: (int(kv[1].get("order") or 99), kv[1].get("name") or ""))
    # Scouting links these pages in place of the A4 reports (Tom, 13-10-2026), so the way back is
    # into Scouting: a bowler from Their bowlers, a batter from the Bowling plans their card sits in
    back_bowl = ("../batting/index.html", "Their bowlers")
    back_bat = ("../index.html", "Bowling plans")
    if not os.path.exists(os.path.join(root, "batting", "index.html")):
        # an older series' coach view has no Their bowlers page: back to the series
        back_bowl = back_bat = ("../index.html", entry.get("name") or "Scouting")

    def one_bowler(pid):
        if fmt != "Test":
            import report_web_wb as WB
            P = WB.wb_profile(pid, fmt=fmt, level=level)
            if P.get("empty"):
                return f"no {fmt} bowling"
            clips, src = clips_of(pid, "bowling", bowlers.get(pid, {}).get("name", ""))
            ctx = {"clips": clips, "img": img(pid), "planner": planner, "built": built,
                   "back_href": back_bowl[0], "back_label": back_bowl[1]}
            body, hp, title = WB.wb_bowler_page(pid, P, ctx, fmt)
            open(os.path.join(web, f"bowling_{pid}.html"), "w", encoding="utf-8").write(
                page(title, body, hp, fields_v=fields_v, snippet=_snippet(clips, src)))
            return "bowling"
        Ps = bowler_profiles(pid, fmt=fmt, level=level)
        if not Ps.get("All"):
            return f"no {fmt} bowling"
        clips, src = clips_of(pid, "bowling", bowlers.get(pid, {}).get("name", ""))
        ctx = bowler_ctx(pid, Ps, os.path.join(web, "pics"), plan=plans.get(pid), clips=clips, img=img(pid),
                         planner=planner, built=built, back=back_bowl, opp=opp)
        body, hp, title = bowler_page(pid, Ps, ctx)
        open(os.path.join(web, f"bowling_{pid}.html"), "w", encoding="utf-8").write(
            page(title, body, hp, fields_v=fields_v, snippet=_snippet(clips, src)))
        return "bowling"

    def one_batter(pid):
        # as the packs decide it (build_pack_extras): a batter whose clips are scoped to Cricket-21
        # has no record at this level, and is profiled from Cricket-21 as well
        meta = batters.get(pid) or {}
        source = "both" if any(str(v).startswith("C21:") for k, v in meta.items() if k.startswith("clip_scope_")) else "warehouse"
        Pb = batter_profiles(pid, fmt=fmt, level=level, source=source)
        if not Pb.get("All"):
            return f"no {fmt} batting"
        clips, src = clips_of(pid, "batting", batters.get(pid, {}).get("name", ""))
        ctx = batter_ctx(pid, Pb, os.path.join(web, "pics"), clips=clips, img=img(pid), planner=planner,
                         built=built, back=back_bat, opp=opp, fmt=fmt,
                         field_rows={g: rows[pid] for g, rows in overview.items() if pid in rows})
        body, hp, title = batter_page(pid, Pb, ctx)
        open(os.path.join(web, f"batting_{pid}.html"), "w", encoding="utf-8").write(
            page(title, body, hp, fields_v=fields_v, snippet=_snippet(clips, src)))
        return "batting"

    # A warehouse timeout part-way through a squad (seen 12-10-2026, after six bowlers) costs that
    # player one retry, then is reported at the end; it does not stop the rest of the squad.
    failed = []
    for kind, people, fn in (("bowling", bowlers, one_bowler), ("batting", batters, one_batter)):
        if kind not in kinds:
            continue
        for pid, meta in order(people):
            pid = str(pid)
            if only and pid not in only:
                continue
            t0 = time.time()
            for attempt in (1, 2):
                try:
                    what = fn(pid)
                    print(f"  {meta.get('name')}: {what}, {time.time() - t0:.0f} s", flush=True)
                    break
                except Exception as exc:
                    print(f"  {meta.get('name')}: {kind} failed ({type(exc).__name__}: {str(exc)[:120]})"
                          + (", trying once more" if attempt == 1 else ""), flush=True)
                    if attempt == 2:
                        failed.append(f"{meta.get('name')} ({kind})")
                    else:
                        time.sleep(20)
    if failed:
        print("NOT BUILT: " + ", ".join(failed), flush=True)
    if not only:
        # every page on disk, not just this run's: a batting-only rebuild keeps the bowlers listed
        def listed(people, kind, what):
            return [(meta.get("name") or pid, what(meta), f"{kind}_{pid}.html", img(str(pid))) for pid, meta in order(people)
                    if os.path.exists(os.path.join(web, f"{kind}_{pid}.html"))]
        rows_b = listed(bowlers, "bowling", lambda m: str(m.get("type") or "Bowler"))
        rows_t = listed(batters, "batting", lambda m: "Left-hander" if str(m.get("hand") or "").upper().startswith("L")
                        else "Right-hander")
        body = _index("Reports, new look", f"{entry.get('name') or slug} · {fmt} reports",
                      [("Their bowlers", rows_b), ("Their batters", rows_t)],
                      ("../index.html", entry.get("name") or "Scouting"))
        open(os.path.join(web, "index.html"), "w", encoding="utf-8").write(page("Reports, new look", body, {}))
    return web


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Write the web reports for a series into the coach build.")
    ap.add_argument("slug")
    ap.add_argument("--only", nargs="*", help="player ids (skips the index)")
    ap.add_argument("--kinds", nargs="*", default=["bowling", "batting"])
    ap.add_argument("--reuse-pics", action="store_true", help="keep over/round pictures already drawn")
    a = ap.parse_args()
    REUSE_PICS = a.reuse_pics
    print(build(a.slug, only=set(a.only) if a.only else None, kinds=tuple(a.kinds)))
