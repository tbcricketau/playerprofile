"""The white-ball bowling reports as web pages (13-10-2026, Tom: "ODI and T20 in the same pattern").

The Test page (report_web.py) scopes a bowler by the batter's hand. The white-ball profiles
(odi_profile, t20_profile) are built around the phase of the innings instead, and do not split by
hand, so here the scope switch is the phase: all overs, then powerplay, middle and death (a phase
needs 60 balls). The hand is a toggle inside the sections that need one (the pictures).

Numbers come from build_odi_profile / build_t20_profile and their helpers, so the page and the A4
report agree. Pictures are drawn in the page: the CricViz wicket pitch map and beehive, and for
where they bowl the Density view, with the dot view beside it when a slice has few enough balls
to draw as SVG (the build machine has no browser to make a picture file).
"""
from __future__ import annotations

import report_web as RW
from report_web import E, sec, table, figs, facts, label, panes, band_word, pct_rows, _n, _day

FMT_WORD = {"ODI": ("ODI", "ODIs"), "T20": ("T20I", "T20Is")}
MIN_PHASE_BALLS = 60
MAX_DOTS = 700          # a slice with more balls than this shows Density only (SVG size)


def wb_profile(bid, fmt="ODI", level="international", source="warehouse"):
    if fmt == "T20":
        from t20_profile import build_t20_profile
        return build_t20_profile(str(bid), level=level, source=source)
    from odi_profile import build_odi_profile
    return build_odi_profile(str(bid), level=level, source=source)


def _stats(rows):
    from odi_profile import _phase_stats
    return _phase_stats(rows)


def _var_type(r, off):
    from odi_profile import _var_type as vt
    return vt(r, off)


def _hand_rows(rows):
    """Balls, round %, economy, wickets, average, Bowl SR and boundary % to each hand."""
    out = []
    for lab, lhb in (("Right-handers", False), ("Left-handers", True)):
        hr = [r for r in rows if bool(r.get("is_lhb")) == lhb]
        s = _stats(hr)
        if not s:
            continue
        kr = [r for r in hr if r.get("is_legal") and r.get("is_round") is not None]
        rp = sum(1 for r in kr if r["is_round"]) / len(kr) * 100 if kr else None
        out.append([lab, f"{s['balls']:,}", _n(rp, 0, "%"), _n(s["economy"], 2), str(s["wickets"]), _n(s["average"], 1),
                    _n(s["strike_rate"], 1), _n(s["boundary_pct"], 0, "%")])
    return out


def _variation_mix(rows, off):
    from collections import Counter
    legal = [r for r in rows if r.get("is_legal")]
    mix = Counter(v for v in (_var_type(r, off) for r in legal) if v)
    n = len(legal) or 1
    return [(t, c, c / n * 100) for t, c in mix.most_common()]


def _where_block(rows, hand, P, defs, key):
    """Where the balls pitched for one hand: on pace and off pace (pace bowlers), over and round."""
    from cricket_core import cricviz as cv
    lhb = hand == "LHB"
    spin = bool(P.get("is_spin"))
    bands = cv.SPIN_BANDS if spin else None
    off = P.get("off_pace_kph")
    legal = [r for r in rows if r.get("is_legal") and bool(r.get("is_lhb")) == lhb]
    slices = [("all", "", legal)] if spin else [
        ("on", "On pace", [r for r in legal if _var_type(r, off) is None]),
        ("off", "Off pace (slower balls)", [r for r in legal if _var_type(r, off) is not None])]
    blocks = []
    for sk, slabel, srows in slices:
        dens_figs, dot_figs, all_dots = [], [], True
        for ang, flag, word in (("over", False, "Over the wicket"), ("round", True, "Round the wicket")):
            ar = [dict(r, striker_dismissed="1" if r.get("is_wicket") else "0") for r in srows if r.get("is_round") is flag]
            cap = f"<figcaption>{word} · {len(ar):,}</figcaption>"
            if len(ar) < 40:
                none = f"<figure>{cap}<div class='none'>{len(ar)} balls, too few to draw</div></figure>"
                dens_figs.append(none)
                dot_figs.append(none)
                continue
            dens_figs.append(f"<figure>{cap}{defs.use(f'{key}-{sk}-{ang}-d', RW.density_svg(ar, lhb=lhb, bands=bands))}</figure>")
            if len(ar) <= MAX_DOTS:
                pm = cv.pitch_map(ar, lhb=lhb, metrics=False, **({"bands": bands} if bands else {}))
                dot_figs.append(f"<figure>{cap}{defs.use(f'{key}-{sk}-{ang}-p', pm)}</figure>")
            else:
                all_dots = False
        dens_html = "<div class='angle'>" + "".join(dens_figs) + "</div>"
        if all_dots and len(dot_figs) == len(dens_figs):
            # few enough balls everywhere to draw every one: Density and Dots, as on the Test page
            dots_html = "<div class='angle'>" + "".join(dot_figs) + "</div>"
            blocks.append(RW.panes(["Dots", "Density"], [dots_html, dens_html], slabel))
        else:
            blocks.append((label(slabel) if slabel else "") + dens_html)
    return "".join(blocks)


def _wicket_pics(rows, hand, P, defs, key):
    from cricket_core import cricviz as cv
    lhb = hand == "LHB"
    wk = [dict(r, striker_dismissed="1") for r in rows if r.get("is_legal") and r.get("is_wicket")
          and bool(r.get("is_lhb")) == lhb]
    if len(wk) < 5:
        return f"<p class='note'>{len(wk)} wickets, too few to draw.</p>", len(wk)
    bands = {"bands": cv.SPIN_BANDS} if P.get("is_spin") else {}
    pm = cv.pitch_map(wk, lhb=lhb, metrics=False, **bands)
    bh = cv.beehive(wk, lhb=lhb)
    return f"<div class='pics2'>{defs.use(key + '-pm', pm, 'pm')}{defs.use(key + '-bh', bh, 'bh')}</div>", len(wk)


def _scope(key, phase, P, ctx, fmt):
    sid = lambda s: f"{key}-{s}"
    defs = ctx["defs"]
    one, many = FMT_WORD[fmt]
    rows = P["raw"] if phase is None else [r for r in P["raw"] if r.get("phase") == phase]
    who = "all overs" if phase is None else phase.lower()
    s = _stats(rows)
    ph = next((p for p in P.get("phases") or [] if p["phase"] == phase), None) if phase else None
    out = []

    # ── summary ──
    fg = [(f"{s['balls']:,}", "Balls"), (str(s["wickets"]), "Wickets"), (_n(s["economy"], 2), "Economy"),
          (_n(s["average"], 1), "Average"), (_n(s["strike_rate"], 1), "Bowl SR"), (_n(s["dot_pct"], 0, "%"), "Dot balls")]
    if P.get("is_pace") and s.get("avg_speed"):
        top = P.get("top_speed") if phase is None else None
        fg.append((f"{s['avg_speed']:.0f}" + (f"<small> /{top:.0f}</small>" if top else ""), "km/h" + (" · top" if top else "")))
    fx = []
    if phase is None:
        tops = sorted(P.get("phases") or [], key=lambda p: -p["pct_balls"])
        if tops:
            fx.append(("Overs by phase", " · ".join(f"{p['phase'].lower()} {p['pct_balls']:.0f}%" for p in tops) + " of their overs"))
    else:
        if ph:
            fx.append(("Share of overs", f"{ph['pct_balls']:.0f}% of their overs are in the {phase.lower()}"))
            bits = []
            if ph.get("econ_pctl") is not None:
                bits.append(f"economy P{ph['econ_pctl']} ({band_word(ph['econ_pctl'])}, higher is harder to score off)")
            if ph.get("wkt_pctl") is not None:
                bits.append(f"wickets per ball P{ph['wkt_pctl']} ({band_word(ph['wkt_pctl'])})")
            if bits:
                fx.append(("Against the type", " · ".join(bits) + f" in the {phase.lower()}"))
    rl, rr = P.get("round_lhb"), P.get("round_rhb")
    if phase is None and (rl is not None or rr is not None):
        fx.append(("Angle", f"round the wicket to left-handers {_n(rl, 0, '%')}, to right-handers {_n(rr, 0, '%')}"))
    if P.get("is_pace"):
        mix = _variation_mix(rows, P.get("off_pace_kph"))
        tot = sum(p for _t, _c, p in mix)
        if mix:
            fx.append(("Slower balls", f"{tot:.0f}% of balls · most often the {E(mix[0][0].lower())} ({mix[0][2]:.0f}%)"))
    fx.append(("Boundaries", f"{s['boundary_pct']:.0f}% of balls go for four or six"))
    if phase is None:
        from cricket_core import stumps
        st = stumps.bowler_vs_type(P["raw"], fmt="ODI" if fmt == "ODI" else "T20I")
        if st:
            fx.append(("Hit the stumps", f"{st['rate']:.1f}% of tracked balls on course for the stumps · an average "
                       f"{E(st['label'])} bowler {st['expected']:.1f}%"))
    fp = pct_rows(P.get("fingerprint")) if phase is None else ""
    out.append(sec(sid("sum"), "Summary", who,
                   figs(fg) + facts(fx)
                   + ((label(f"Against other {RW.type_word(P.get('primary_type')).lower()} bowlers in {many}, career and last 3 years")
                       + fp + "<p class='note'>The solid mark is the career, the dotted gold mark the last three years. Bands: 80 "
                       "and above among the highest, 60-80 above average, 40-60 around average, 20-40 below average, under 20 "
                       "among the lowest.</p>") if fp else "")))

    # ── phases (all overs) ──
    if phase is None and P.get("phases"):
        rows_ = []
        for p in P["phases"]:
            ep = f"P{p['econ_pctl']}" if p.get("econ_pctl") is not None else "–"
            wp = f"P{p['wkt_pctl']}" if p.get("wkt_pctl") is not None else "–"
            rows_.append([p["phase"], f"{p['pct_balls']:.0f}%", _n(p["economy"], 2), ep, str(p["wickets"]), wp,
                          _n(p["average"], 1), _n(p["strike_rate"], 1), _n(p["boundary_pct"], 0, "%"), _n(p["dot_pct"], 0, "%")]
                         + ([_n(p.get("avg_speed"), 0)] if P.get("is_pace") else []))
        heads = ["Phase", "Overs", "Economy", "Economy v type", "Wkts", "Wickets v type", "Avg", "Bowl SR", "Boundary %", "Dot %"] \
            + (["km/h"] if P.get("is_pace") else [])
        # the percentile columns only where the phase norms were there to compute them
        have_p = any(p.get("econ_pctl") is not None or p.get("wkt_pctl") is not None for p in P["phases"])
        if not have_p:
            keep = [i for i, h in enumerate(heads) if not h.endswith("v type")]
            heads = [heads[i] for i in keep]
            rows_ = [[r[i] for i in keep] for r in rows_]
        out.append(sec(sid("ph"), "Phases", "", table(heads, rows_)
                       + (f"<p class='note'>Percentiles against {'pace' if P.get('is_pace') else 'spin'} bowlers in {many} in "
                          "the same phase, two-new-balls era: a higher economy percentile is harder to score off, a higher "
                          "wickets percentile takes wickets more often.</p>" if have_p else "")))

    # ── length and variations (pace) ──
    dd = P.get("deepdive")
    if P.get("is_pace") and dd and dd.get("overall"):
        o = dd["overall"]
        rows_ = []
        for p in dd.get("phases") or []:
            if phase and p["phase"] != phase:
                continue
            rows_.append([p["phase"], f"{p['yorker_pct']:.0f}%", f"{p['bouncer_pct']:.0f}%", f"{p['slower_pct']:.0f}%",
                          f"{p['slower_yorker']['pct']:.1f}%", f"{p['slower_bouncer']['pct']:.1f}%", f"{p['economy']:.2f}"])
        if phase is None:
            rows_.append(["<b>All overs</b>", f"{o['yorker_pct']:.0f}%", f"{o['bouncer_pct']:.0f}%", f"{o['slower_pct']:.0f}%",
                          f"{o['slower_yorker']['pct']:.1f}%", f"{o['slower_bouncer']['pct']:.1f}%", f"{o['economy']:.2f}"])
        inner = table(["", "Yorker / full", "Bouncer / short", "Slower ball", "Slower yorker", "Slower bouncer", "Economy"], rows_)
        lines = []
        if phase is None:
            for lab, k in (("Yorker pitching line", "yorker_line"), ("Bouncer line at the stumps", "bouncer_line")):
                b = o.get(k) or {}
                if b.get("bands"):
                    lines.append((lab, " · ".join(f"{E(x['band'].lower())} {x['pct']:.0f}%" for x in b["bands"]) + f" ({b['n']} balls)"))
        mix = _variation_mix(rows, P.get("off_pace_kph"))
        mt = table(["Slower ball type", "Balls", "Share of balls"], [[E(t), str(c), f"{p:.1f}%"] for t, c, p in mix if c >= 4],
                   cls="narrow") if mix else ""
        out.append(sec(sid("var"), "Length and variations", who, inner
                       + "<div class='two'><div>" + facts(lines, "Lines") + "</div><div>" + mt + "</div></div>"
                       + "<p class='note'>Shares of that phase's legal balls. A slower ball is one coded as a variation, or "
                         "one well off their stock pace that carries no other code.</p>"))

    # ── match-ups ──
    hr = _hand_rows(rows)
    if hr:
        out.append(sec(sid("mu"), "Match-ups", who, table(["", "Balls", "Round the wicket", "Economy", "Wkts", "Avg", "Bowl SR",
                                                           "Boundary %"], hr)))

    # ── wicket balls and where they bowl ──
    hands = [h for h in ("RHB", "LHB") if any(bool(r.get("is_lhb")) == (h == "LHB") for r in rows if r.get("is_legal"))]
    word = {"RHB": "Right-handers", "LHB": "Left-handers"}
    wpics = []
    for h in hands:
        html_, n = _wicket_pics(rows, h, P, defs, f"{key}-wk-{h.lower()}")
        wpics.append((f"{word[h]} · {n}", html_))
    where = [(word[h], _where_block(rows, h, P, defs, f"{key}-wh-{h.lower()}")) for h in hands]
    out.append(sec(sid("thr"), "Where they bowl", who,
                   "<div class='two wide-l'><div>" + (panes([w[0] for w in wpics], [w[1] for w in wpics], "Wicket balls") if wpics else "")
                   + "<p class='note'>Where the wicket balls pitched and passed the stumps, from behind the bowler.</p></div>"
                   + "<div>" + (panes([w[0] for w in where], [w[1] for w in where], "Every ball") if where else "") + "</div></div>"
                   + "<p class='note'>Density shades where most balls land; Dots draws each ball by what came of it (red a "
                     "wicket, blue a four, purple a six) where a slice has few enough balls to draw.</p>"))

    out.append(sec(sid("vis"), "Vision", "", RW._vision(ctx.get("clips"))))
    return "".join(out)


_JUMP = (("sum", "Summary"), ("ph", "Phases"), ("var", "Length and variations"), ("mu", "Match-ups"),
         ("thr", "Where they bowl"), ("vis", "Vision"))


def wb_bowler_page(bid, P, ctx, fmt="ODI"):
    one, many = FMT_WORD[fmt]
    name = RW.person(P["name"])
    ctx.setdefault("defs", RW.Defs())
    counts = {p["phase"]: p["balls"] for p in P.get("phases") or []}
    scopes = [("all", None, "All overs")] + [(ph.lower(), ph, ph) for ph in ("Powerplay", "Middle", "Death")
                                             if counts.get(ph, 0) >= MIN_PHASE_BALLS]
    seg = ("<div class='seg' role='tablist' aria-label='Phase'>" + "".join(
        f"<button type='button' data-scope='{k}' class='{'on' if i == 0 else ''}'>{E(lab)}</button>"
        for i, (k, _p, lab) in enumerate(scopes)) + "</div>")
    last = max((r.get("match_date") or "" for r in P["raw"]), default="")
    img = ctx.get("img") or ""
    av = (f"<img class='av lg' src='{E(img)}' alt=''>" if img else
          f"<span class='av lg ini'>{E(''.join(w[0] for w in name.split()[:2]))}</span>")
    head = (f"<header class='ph'><div class='in'><a class='back' href='{E(ctx.get('back_href', 'index.html'))}'>‹ "
            f"{E(ctx.get('back_label', 'Reports'))}</a>"
            f"<div class='who'>{av}<div><h1>{E(name)}</h1><div class='sb'>{E(RW.type_word(P.get('primary_type')))} · "
            f"{E(RW.team_word(P.get('team')))} · {many}, career · {P.get('matches') or 0} matches</div></div></div>"
            f"<div class='ctl'><span class='k'>Phase</span>{seg}<span class='stamp'>Built {E(ctx['built'])} · "
            f"{many} to {_day(last)}</span></div></div></header>")
    nav = ("<nav class='jump'><div class='in'>" + "".join(
        f"<a href='#all-{a}' data-to='{a}'>{E(t)}</a>" for a, t in _JUMP) + "</div></nav>")
    body = "".join(f"<div class='scope' data-scope='{k}'{'' if i == 0 else ' hidden'}>{_scope(k, ph, P, ctx, fmt)}</div>"
                   for i, (k, ph, _l) in enumerate(scopes))
    hp = {"series": ctx.get("planner") or "", "pid": str(bid), "kind": "bowler"}
    return head + nav + f"<main class='hpw'>{body}</main>" + ctx["defs"].html(), hp, f"{name} · {one} bowling"
