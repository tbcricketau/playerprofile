"""
batting_report.py — render a one-batter scouting PDF (Test / red-ball).

First pass: headline + the novel share-of-runs "match impact" metric, how they
score (shot groups, areas, wagon), how they fare vs each bowler type + weaknesses,
and how they get out.  Reuses report.py's Chromium PDF machinery and the Opta theme.

    from batting_report import render_batting_report
    render_batting_report("940135")           # Steve Smith
"""
import datetime
import os
import re

from jinja2 import Template

from version import REPORT_VERSION
from batter_profile import build_batter_profile, BOWLER_GROUPS
import field_engine as fe
from photos import get_photo_data_uri
from ludis_cricket.charts import wagon_wheel_zones, fingerprint_strip
from ludis_cricket.video import first_example, get_fairplay_sas
from report import (
    _fig_uri, _html_to_pdf, _country_code,
    BG_PAGE, BG_PANEL, TEXT_PRI, TEXT_SEC, ACCENT, DANGER, BORDER,
)


def _fmt(v, spec=".0f", suffix=""):
    if v is None:
        return "—"
    try:
        return f"{float(v):{spec}}{suffix}"
    except (TypeError, ValueError):
        return "—"


def _cards(P: dict) -> list:
    s = P.get("share") or {}
    return [
        ("Runs", _fmt(P["runs"]), f"{P['n_out']} dismissals"),
        ("Average", _fmt(P["average"], ".1f"), f"SR {_fmt(P['strike_rate'], '.1f')}"),
        ("Innings", _fmt(s.get("innings")), "batted"),
        ("Share of team runs", _fmt(s.get("team_share_career"), ".1f", "%"), "career, off the bat"),
        ("Carries the innings", _fmt(s.get("carried_rate"), ".0f", "%"), "innings with ≥25% of team"),
    ]


def _impact_read(P: dict) -> str:
    s = P.get("share")
    if not s:
        return ""
    tc, tm = s["team_share_career"], s["team_share_median"]
    lead = (f"Makes <b>{tc:.1f}%</b> of his team's runs over a career (typical innings "
            f"{tm:.1f}%), and <b>{_fmt(s['match_share_career'], '.1f', '%')}</b> of all runs in his matches")
    carry = (f"; carries the innings (≥25% of the team's runs) {s['carried_rate']:.0f}% of the time"
             + (f", and dominates (≥40%) {s['big_rate']:.0f}%" if s["big_rate"] >= 3 else ""))
    return lead + carry + "."


def _vs_rows(P: dict) -> list:
    out = []
    for label, key in (("Pace", "pace"), ("Spin", "spin")):
        v = P["vs"].get(key)
        if not v:
            continue
        out.append((label, _fmt(v["avg"], ".1f"), _fmt(v["sr"], ".1f"),
                    _fmt(v["false_pct"], ".1f", "%"), _fmt(v["dismissal_per100"], ".2f"),
                    f"{v['balls']:,}"))
    # detailed types under each
    for t, v in sorted(P["vs_detail"].items(), key=lambda kv: -kv[1]["balls"]):
        out.append(("  " + t, _fmt(v["avg"], ".1f"), _fmt(v["sr"], ".1f"),
                    _fmt(v["false_pct"], ".1f", "%"), _fmt(v["dismissal_per100"], ".2f"),
                    f"{v['balls']:,}"))
    return out


def _vs_read(P: dict) -> str:
    vs = P["vs"]
    if "pace" not in vs or "spin" not in vs:
        return ""
    p, s = vs["pace"], vs["spin"]
    if not (p["avg"] and s["avg"]):
        return ""
    if P["weakness"] == "spin":
        return (f"Noticeably weaker against spin (averages {s['avg']:.0f} vs {p['avg']:.0f} against pace; "
                f"falser shot {s['false_pct']:.0f}% vs {p['false_pct']:.0f}%) — attack him with spin.")
    if P["weakness"] == "pace":
        return (f"Stronger against spin ({s['avg']:.0f}) than pace ({p['avg']:.0f}); "
                f"pace — especially the quicks — is the more productive line of attack.")
    return f"Handles both similarly (pace {p['avg']:.0f}, spin {s['avg']:.0f})."


def _shot_rows(P: dict) -> list:
    return [(g["name"], f"{g['runs']:.0f}", f"{g['runs_pct']:.0f}%", str(g["balls"]), str(g["outs"]))
            for g in P["shot_groups"]]


def _dir_read(P: dict) -> str:
    d = P.get("dir_pct")
    if not d:
        return ""
    top = max(d, key=d.get)
    side = {"off": "the off side", "leg": "the leg side", "straight": "straight down the ground"}[top]
    return f"Scores most of his runs through {side} ({d[top]:.0f}%; off {d['off']:.0f}% · leg {d['leg']:.0f}% · straight {d['straight']:.0f}%)."


def _phase_rows(P: dict) -> list:
    """Start of innings (first 30 balls) vs set — (label, avg, sr, false%, outs/100,
    bdry%, balls, weakflag). Weak = the phase with the higher dismissal rate."""
    ph = P.get("phase")
    if not ph:
        return []
    weak_key = max(ph, key=lambda k: ph[k]["dismissal_per100"] or 0)
    rows = []
    for key, label in (("early", "First 30 balls"), ("set", "Once set (31+)")):
        s = ph[key]
        rows.append((label, _fmt(s["avg"], ".1f"), _fmt(s["sr"], ".0f"),
                     _fmt(s["false_pct"], ".0f", "%"), _fmt(s["dismissal_per100"], ".2f"),
                     _fmt(s["bdry_pct"], ".0f", "%"), f"{s['balls']:,}", key == weak_key))
    return rows


def _phase_read(P: dict) -> str:
    ph = P.get("phase")
    if not ph:
        return ""
    e, s = ph["early"], ph["set"]
    if not (e["dismissal_per100"] and s["dismissal_per100"]):
        return ""
    ratio = e["dismissal_per100"] / s["dismissal_per100"] if s["dismissal_per100"] else None
    if ratio and ratio >= 1.4:
        txt = (f"<b>Get him early</b> — he's {ratio:.1f}× more likely to fall in his first 30 balls "
               f"({e['dismissal_per100']:.1f} vs {s['dismissal_per100']:.1f} dismissals/100 once set")
        if e["false_pct"] and s["false_pct"]:
            txt += f"; false shot {e['false_pct']:.0f}% vs {s['false_pct']:.0f}%"
        txt += ")."
    elif ratio and ratio <= 1.1:
        txt = (f"Starts securely — his dismissal rate barely drops once set "
               f"({e['dismissal_per100']:.1f} early vs {s['dismissal_per100']:.1f}/100); "
               f"early pressure alone won't buy his wicket.")
    else:
        txt = (f"Somewhat more vulnerable early ({e['dismissal_per100']:.1f} vs "
               f"{s['dismissal_per100']:.1f} dismissals/100 once set).")
    if e.get("top_shots"):
        fam, pct = e["top_shots"][0]
        txt += f" Early runs come mainly off the {fam.lower()} ({pct:.0f}%)."
    return txt


def _dismissal_read(P: dict) -> str:
    dis, n = P["dismissals"], P["n_dismissals"]
    if not n:
        return ""
    top = dis.most_common(1)[0]
    bt = P["dismissal_bowler_type"].most_common(1)
    btxt = f"; most often to {bt[0][0].lower()} ({bt[0][1]})" if bt else ""
    return f"Most often out <b>{top[0].lower()}</b> ({top[1] / n * 100:.0f}% of dismissals){btxt}."


def _narrative(P: dict) -> dict:
    themes, strengths, weak = [], [], []
    hand = "left-hand bat" if P["is_lhb"] else "right-hand bat"
    themes.append(f"{hand}, averaging {_fmt(P['average'], '.1f')} at a strike rate of {_fmt(P['strike_rate'], '.1f')}.")
    s = P.get("share")
    if s:
        themes.append(f"Carries a big share of the batting — {s['team_share_career']:.1f}% of team runs.")
    if P.get("dir_pct"):
        d = P["dir_pct"]
        top = max(d, key=d.get)
        themes.append(f"Scores mainly through {'the off side' if top=='off' else 'the leg side' if top=='leg' else 'the V'} ({d[top]:.0f}%).")
    if P["shot_groups"]:
        g = P["shot_groups"][0]
        strengths.append(f"Main scoring shot is the {g['name'].lower()} ({g['runs_pct']:.0f}% of runs).")
    nr = _stroke_norm_read(P)
    if nr:
        strengths.append(nr)
    vsr = _vs_read(P)
    if vsr:
        (weak if P["weakness"] == "spin" else strengths).append(vsr)
    pr = _phase_read(P)
    if pr:
        (strengths if pr.startswith("Starts securely") else weak).append(pr)
    if P["dismissals"]:
        weak.append(_dismissal_read(P))
    # dimension-driven weaknesses (seam/swing/length/line/stroke)
    for line in _dim_weakness_reads(P):
        weak.append(line)
    return {"themes": themes, "strengths": strengths, "weak": weak}


# ── Vulnerability dimensions ─────────────────────────────────────────────────────
import csv as _csv
import os as _os

_BAT_REF_CSV = r"c:\Ludis\referencebuilder\data\batter_vulnerability_profile.csv"
_BAT_REF = None


def _bat_ref():
    global _BAT_REF
    if _BAT_REF is None:
        _BAT_REF = {}
        if _os.path.exists(_BAT_REF_CSV):
            with open(_BAT_REF_CSV, encoding="utf-8", newline="") as f:
                _BAT_REF = {row["batter_id"]: row for row in _csv.DictReader(f)}
    return _BAT_REF


# ── Stroke norms (how he scores vs the typical Test batter) ─────────────────────
# Built by referencebuilder/scripts/build_batter_stroke_norms.py, keyed by format ×
# bowler group (all / pace / spin / right_pace / … — the report's group vocabulary).
# Shares are within stroke-coded balls only.
_STROKE_NORMS_CSV = r"c:\Ludis\referencebuilder\data\batter_stroke_norms.csv"
_STROKE_COHORT_CSV = r"c:\Ludis\referencebuilder\data\stroke_norms_cohort.csv"
_STROKE_NORMS = None
_NORM_FAMS = ("Drive", "Cut", "Pull/Hook", "Sweep", "Work/Nudge", "Slog", "Ramp/Scoop")
_NORM_FORMAT = "test"
_MIN_COHORT = 40          # fine-grain cohort must be at least this big, else fall back


def _stroke_norms_ref():
    global _STROKE_NORMS
    if _STROKE_NORMS is None:
        per, cohort = {}, {}
        if _os.path.exists(_STROKE_NORMS_CSV):
            with open(_STROKE_NORMS_CSV, encoding="utf-8", newline="") as f:
                for row in _csv.DictReader(f):
                    per[(row["batter_id"], row.get("format", "test"),
                         row.get("bowler_group", "all"), row["family"])] = row
        if _os.path.exists(_STROKE_COHORT_CSV):
            with open(_STROKE_COHORT_CSV, encoding="utf-8", newline="") as f:
                for row in _csv.DictReader(f):
                    cohort[(row.get("format", "test"), row.get("bowler_group", "all"),
                            row["family"])] = row
        _STROKE_NORMS = (per, cohort)
    return _STROKE_NORMS


def _nf(row, key):
    try:
        return float(row.get(key))
    except (TypeError, ValueError):
        return None


def _norms_grain(P: dict):
    """Finest norms grain available for this report: the report's bowler group, then its
    pace/spin parent, then 'all'. Returns (group_key, label, cohort_n) or None."""
    per, cohort = _stroke_norms_ref()
    chain = []
    if P.get("group"):
        chain.append((P["group"], P.get("group_label") or P["group"]))
        chain.append(("spin", "spin") if P.get("is_spin_group") else ("pace", "pace"))
    chain.append(("all", None))
    for grp, label in chain:
        n = max((int(_nf(cohort.get((_NORM_FORMAT, grp, f), {}), "n_batters") or 0)
                 for f in _NORM_FAMS), default=0)
        has_batter = any((P["batter_id"], _NORM_FORMAT, grp, f) in per for f in _NORM_FAMS)
        if n >= _MIN_COHORT and has_batter:
            return grp, label, n
    return None


def _stroke_norm_rows(P: dict) -> list:
    """(family, his runs%, norm runs%, index, pctl, over/under flag) at the chosen grain."""
    grain = _norms_grain(P)
    if not grain:
        return []
    grp, _, _ = grain
    per, cohort = _stroke_norms_ref()
    rows = []
    for fam in _NORM_FAMS:
        r = per.get((P["batter_id"], _NORM_FORMAT, grp, fam))
        ch = cohort.get((_NORM_FORMAT, grp, fam), {})
        if r is None:
            continue
        his, norm = _nf(r, "runs_pct"), _nf(ch, "runs_pct_median")
        if his is None or norm is None:
            continue
        idx = his / norm if norm else None
        flag = ""     # highlight genuinely distinctive scoring shots
        if idx is not None and (his >= 3 or norm >= 3):
            flag = "over" if idx >= 1.35 else ("under" if idx <= 0.6 else "")
        rows.append((fam, f"{his:.0f}%", f"{norm:.0f}%",
                     f"{idx:.1f}×" if idx is not None else "—",
                     f"P{_nf(r, 'runs_pct_pctl'):.0f}" if _nf(r, "runs_pct_pctl") is not None else "—",
                     flag, his))
    rows.sort(key=lambda t: -t[6])
    return [t[:6] for t in rows]


def _stroke_norm_caption(P: dict) -> str:
    grain = _norms_grain(P)
    if not grain:
        return ""
    grp, label, n = grain
    scope = f"vs {label}" if label else "all bowling"
    return (f"Share of stroke-coded runs {scope}; index = his share ÷ cohort median "
            f"({n} Test batters). Highlight = signature shot; ▼ = scores unusually little there.")


def _stroke_norm_read(P: dict) -> str:
    """One line naming his most over- and under-indexed scoring shots vs the norm."""
    grain = _norms_grain(P)
    if not grain:
        return ""
    grp, label, _ = grain
    per, cohort = _stroke_norms_ref()
    over, under = [], []
    for fam in _NORM_FAMS:
        r = per.get((P["batter_id"], _NORM_FORMAT, grp, fam))
        ch = cohort.get((_NORM_FORMAT, grp, fam), {})
        if r is None:
            continue
        his, norm = _nf(r, "runs_pct"), _nf(ch, "runs_pct_median")
        if his is None or not norm:
            continue
        idx = his / norm
        if idx >= 1.35 and his >= 4:
            over.append((idx, fam, his))
        elif idx <= 0.6 and norm >= 6:
            under.append((idx, fam, his, norm))
    scope = f" vs {label}" if label else ""
    parts = []
    if over:
        idx, fam, his = max(over)
        parts.append(f"The <b>{fam.lower()}</b> brings him {his:.0f}% of his runs{scope} — "
                     f"{idx:.1f}× the typical Test batter's share.")
    if under:
        idx, fam, his, norm = min(under)
        parts.append(f"Scores unusually little off the <b>{fam.lower()}</b>{scope} "
                     f"({his:.0f}% of runs vs {norm:.0f}% typically).")
    return " ".join(parts)


def _blabel(bucket, key, is_spin=False):
    if bucket is True or bucket is False:
        return "Round the wicket" if bucket is True else "Over the wicket"
    if key == "seam_dir":
        mv = "turn" if is_spin else "seam"
        return {"in": f"{mv}s in", "straight": f"no {mv}", "away": f"{mv}s away"}.get(bucket, bucket)
    if key == "swing_dir":
        mv = "drift" if is_spin else "swing"
        return {"in": f"{mv}s in", "straight": f"no {mv}", "out": f"{mv}s away"}.get(bucket, bucket)
    return str(bucket)


def _dim_rows(dim: list, key: str, is_spin: bool = False) -> list:
    """(label, avg, SR, false%, dis/100, bdry%, balls, weak) — weak flags the lowest-average
    bucket with a real sample (the batter's soft spot in that dimension)."""
    if not dim:
        return []
    scored = [d for d in dim if d["avg"] is not None and d["balls"] >= 40]
    weak_bucket = min(scored, key=lambda d: d["avg"])["bucket"] if scored else None
    rows = []
    for d in dim:
        rows.append((
            _blabel(d["bucket"], key, is_spin),
            _fmt(d["avg"], ".1f"), _fmt(d["sr"], ".0f"),
            _fmt(d["false_pct"], ".0f", "%"), _fmt(d["dismissal_per100"], ".2f"),
            _fmt(d["bdry_pct"], ".0f", "%"), f"{d['balls']:,}",
            d["bucket"] == weak_bucket,
        ))
    return rows


def _worst(dim: list, by="avg"):
    """Most vulnerable bucket in a dimension (lowest avg / highest dis-rate), min 40 balls."""
    cand = [d for d in dim if d["balls"] >= 40 and d.get("avg") is not None]
    if not cand:
        return None
    return min(cand, key=lambda d: d["avg"]) if by == "avg" else max(cand, key=lambda d: d["dismissal_per100"] or 0)


def _dim_weakness_reads(P: dict) -> list:
    """Short 'how to get him' lines drawn from the dimension splits + danger cell."""
    dims, out = P.get("dims") or {}, []
    is_spin = P.get("is_spin_group")
    base_avg = P.get("average") or 0
    # length
    w = _worst(dims.get("length", []))
    if w and base_avg and w["avg"] < base_avg * 0.8:
        out.append(f"Vulnerable to the <b>{w['bucket'].lower()}</b> (averages {w['avg']:.0f} there vs {base_avg:.0f} overall; "
                   f"{w['dismissal_per100']:.1f} dismissals/100).")
    # line
    w = _worst(dims.get("line", []))
    if w and base_avg and w["avg"] < base_avg * 0.8:
        out.append(f"Struggles <b>{w['bucket']}</b> ({w['avg']:.0f} avg, {w['dismissal_per100']:.1f} outs/100).")
    # seam / swing (movement each way)
    for dk, word in (("seam", "turn" if is_spin else "seam"), ("swing", "drift" if is_spin else "swing")):
        mv = [d for d in dims.get(dk, []) if d["bucket"] in ("in", "away", "out") and d["balls"] >= 60]
        straight = next((d for d in dims.get(dk, []) if d["bucket"] == "straight"), None)
        if mv and straight and straight["avg"]:
            worst = min(mv, key=lambda d: d["avg"])
            if worst["avg"] < straight["avg"] * 0.75:
                dirw = _blabel(worst["bucket"], dk + "_dir", is_spin)
                out.append(f"The ball that {dirw} hurts him (avg {worst['avg']:.0f} vs {straight['avg']:.0f} when it holds its line).")
    # danger cell
    g = P.get("grid_danger")
    if g:
        out.append(f"Most dangerous ball: <b>{g['length_band'].lower()} {g['line_region']}</b> "
                   f"({g['dismissal_per100']:.1f} dismissals/100, avg {g['avg']:.0f}).")
    # risky stroke
    strokes = [d for d in dims.get("stroke", []) if d["balls"] >= 30 and d.get("false_pct") is not None]
    if strokes:
        risky = max(strokes, key=lambda d: d["false_pct"])
        if risky["false_pct"] >= 25:
            out.append(f"His <b>{risky['bucket'].lower()}</b> is high-risk (false shot {risky['false_pct']:.0f}%, "
                       f"{risky['dismissal_per100']:.1f} outs/100).")
    return out[:6]


# fingerprint metrics: (ref key, label, higher_is_vulnerability)
_FP = [
    ("avg", "Average", False), ("sr", "Strike rate", False),
    ("false_pct", "False-shot %", True), ("pace_false", "False % vs pace", True),
    ("spin_false", "False % vs spin", True), ("seam_false", "False % vs seam", True),
    ("swing_false", "False % vs swing", True), ("short_false", "False % vs short", True),
    ("bdry_pct", "Boundary %", False),
]


def _fingerprint_cards(P: dict) -> list:
    ref = _bat_ref()
    me = ref.get(P["batter_id"])
    if not me:
        return []
    cards = []
    for key, label, vuln in _FP:
        try:
            pctl = float(me.get(key + "_pctl"))
            val = float(me.get(key))
        except (TypeError, ValueError):
            continue
        peers = []
        for row in ref.values():
            try:
                peers.append(float(row[key]))
            except (TypeError, ValueError):
                pass
        if len(peers) < 20:
            continue
        # colour: for vulnerability metrics a high pctl is a target (danger); for good metrics
        # a high pctl is a strength (accent). Muted in the middle.
        hi = pctl >= 65
        if vuln:
            colour = DANGER if hi else ("#15803d" if pctl <= 35 else TEXT_SEC)
        else:
            colour = "#15803d" if hi else (DANGER if pctl <= 20 else TEXT_SEC)
        disp = f"{val:.1f}" + ("%" if key not in ("avg", "sr") else "")
        cards.append({"label": label, "pctl": pctl, "value": val, "values": peers,
                      "vuln": vuln, "colour": colour, "disp": disp})
    return cards


def _plan_read(P: dict) -> str:
    """Focused report: a concise 'how to bowl to him' plan for the bowler group."""
    if not P.get("group"):
        return ""
    dims, is_spin, gl = P["dims"], P["is_spin_group"], P["group_label"]
    bits = []
    wl, ln = _worst(dims.get("length", [])), _worst(dims.get("line", []))
    if wl and ln:
        bits.append(f"hunt the <b>{wl['bucket'].lower()} {ln['bucket']}</b>")
    for dk in ("seam", "swing"):
        mv = [d for d in dims.get(dk, []) if d["bucket"] in ("in", "away", "out") and d["balls"] >= 60]
        straight = next((d for d in dims.get(dk, []) if d["bucket"] == "straight"), None)
        if mv and straight and straight["avg"]:
            worst = min(mv, key=lambda d: d["avg"])
            if worst["avg"] < straight["avg"] * 0.8:
                bits.append(f"get it to {_blabel(worst['bucket'], dk + '_dir', is_spin)}")
    plan = f"Plan for {gl}: " + ("; ".join(bits) if bits else "few clear structural weaknesses")
    g = P.get("grid_danger")
    if g:
        plan += f". Danger ball: the <b>{g['length_band'].lower()} {g['line_region']}</b> ({g['dismissal_per100']:.1f} outs/100, avg {g['avg']:.0f})"
    if P["dismissals"]:
        top = P["dismissals"].most_common(1)[0]
        plan += f"; he's most often out <b>{top[0].lower()}</b> to this attack"
    return plan + "."


def _file_url(path: str) -> str:
    return "file:///" + os.path.abspath(path).replace("\\", "/").replace(" ", "%20")


# ── Suggested fields (field_engine) ────────────────────────────────────────────────
_TYPE_TO_GROUP = {t: g for g, (types, _) in BOWLER_GROUPS.items() for t in types}
_ROLE_LABEL = {"catch": "Catch", "save": "Save"}
_PACE_GROUPS = ("right_pace", "left_pace")
_SPIN_GROUPS = ("off_spin", "leg_spin", "left_orthodox", "left_unorthodox")
_FIELD_MIN_BALLS = 120           # a group needs this many career balls to earn a field


def _field_targets(P: dict) -> list:
    """[(group, rows)] to draw a field for. Focused report → the report's group; combined →
    the batter's most-faced pace group + most-faced spin group (each on its own filtered rows)."""
    if P.get("group"):
        return [(P["group"], P["raw"])]
    from collections import Counter
    cnt = Counter()
    for r in P["raw_all"]:
        if r["is_legal"]:
            g = _TYPE_TO_GROUP.get(r.get("bowler_type_simple"))
            if g:
                cnt[g] += 1
    out = []
    for pool in (_PACE_GROUPS, _SPIN_GROUPS):
        avail = [g for g in pool if cnt.get(g, 0) >= _FIELD_MIN_BALLS]
        if not avail:
            continue
        g = max(avail, key=lambda x: cnt[x])
        types = BOWLER_GROUPS[g][0]
        out.append((g, [r for r in P["raw_all"] if r.get("bowler_type_simple") in types]))
    return out


def _field_backtest_line(fs: dict, phase: str) -> str:
    """Deviations-only read: the stock base + how many changes it earns, and what those changes
    buy vs the untouched stock field (FIELD_PLAN §6)."""
    bt, chg, base = fs["backtest"], fs["changes"], fs["base_note"]
    if not chg:
        return (f"<b>Pure {base}.</b> Nothing in his game clears the deviation bar (cohort P75) "
                f"against {fs['group_label']}, so the orthodox field stands — that <i>is</i> the read.")
    n = len(chg)
    gains = []
    if bt["bdry_gain"] >= 1:
        gains.append(f"+{bt['bdry_gain']:.0f}% of his boundary runs")
    if bt["exp_catch_gain"] >= 1:
        gains.append(f"+{bt['exp_catch_gain']:.0f}% of his expected edges")
    tail = (" — covering " + " and ".join(gains) + " vs the pure stock field") if gains else ""
    return (f"<b>{base.capitalize()} + {n} change{'s' if n != 1 else ''}</b> "
            f"(highlighted){tail}.")


def _field_blocks(P: dict) -> list:
    """Render-ready field blocks: one per bowler group, each with an early + set column
    (field diagram data-URI, justification rows, backtest line)."""
    blocks = []
    for group, rows in _field_targets(P):
        subP = {"is_lhb": P["is_lhb"], "batter_id": P["batter_id"], "raw": rows}
        cols = []
        for phase, title in (("early", "Early — first 30 balls"), ("set", "Once set")):
            fs = fe.build_field(subP, group, phase)
            if not fs:
                continue
            try:
                uri = _fig_uri(fe.field_diagram(fs["field"], P["is_lhb"], title=""), w=300, h=300)
            except Exception:
                uri = ""
            jrows = [(f["position"], "Change" if f["tag"] == "change" else "Stock",
                      f["why"], f["tag"]) for f in fs["field"]]
            cols.append({"title": title, "fig": uri, "rows": jrows,
                         "backtest": _field_backtest_line(fs, phase), "legal": fs["legal"]})
        if cols:
            blocks.append({"label": fe._group_label(group), "cols": cols})
    return blocks


def _build_player(P: dict, pdf_path: str) -> dict:
    """Build batting playlists, write a self-contained modal video player next to the PDF, and
    return {player, keys, stroke_name} for the report's ▶ links. Best-effort."""
    try:
        get_fairplay_sas(ttl_hours=72)
        from playlists import build_batting_playlists
        from ludis_cricket.video import build_player_html, write_playlists
        pls = build_batting_playlists(P, cap=8)
        if not pls:
            return {}
        player_path = pdf_path[:-4] + ".player.html"
        sub = f"{P['name']} — batting scout" + (f" vs {P['group_label']}" if P.get("group") else "")
        build_player_html(pls, player_path, title=P["name"], subtitle=sub)
        write_playlists(pdf_path[:-4] + ".playlists.json", pls)
        strokes = [d for d in (P.get("dims", {}).get("stroke") or []) if d["balls"] >= 30 and d.get("false_pct") is not None]
        stroke_name = max(strokes, key=lambda d: d["false_pct"])["bucket"] if strokes else None
        return {"player": _file_url(player_path), "lists": {k: True for k in pls},
                "stroke_name": stroke_name, "playlists": pls}
    except Exception:
        return {}


def render_batting_report(batter_id: str, out_dir: str = "reports", group: str | None = None) -> str:
    """Combined overview (group=None) or a focused per-bowler-type exploit report (e.g.
    group='right_pace'). Same engine; the focused one filters to that bowler group + adds a plan."""
    P = build_batter_profile(batter_id, group=group)
    figs = {}
    try:
        figs["wagon"] = _fig_uri(
            wagon_wheel_zones(P["raw"], metric="runs", title="", n_sectors=8, is_lhb=P["is_lhb"]),
            w=500, h=430)
    except Exception:
        figs["wagon"] = ""

    fp_cards = []
    if group is None:                         # fingerprint is vs all batters — combined report only
        for c in _fingerprint_cards(P):
            try:
                img = _fig_uri(fingerprint_strip(c["values"], c["value"], invert=False), w=250, h=84)
            except Exception:
                img = ""
            fp_cards.append({**c, "img": img, "pct_txt": f"P{c['pctl']:.0f}"})

    dims = P["dims"]
    isg = P["is_spin_group"]
    dim_tables = {
        "seam": _dim_rows(dims["seam"], "seam_dir", isg),
        "swing": _dim_rows(dims["swing"], "swing_dir", isg),
        "speed": _dim_rows(dims["speed"], "speed_band"),
        "length": _dim_rows(dims["length"], "length_band"),
        "line": _dim_rows(dims["line"], "line_region"),
        "over_round": _dim_rows(dims["over_round"], "is_round"),
        "stroke": _dim_rows(dims["stroke"], "stroke_family"),
    }

    ctx = {
        "P": P, "code": _country_code(P["team"]),
        "photo_uri": get_photo_data_uri(P["batter_id"]),
        "hand_label": "LHB" if P["is_lhb"] else "RHB",
        "cards": _cards(P), "impact_read": _impact_read(P),
        "vs_rows": _vs_rows(P), "vs_read": _vs_read(P),
        "shot_rows": _shot_rows(P), "dir_read": _dir_read(P),
        "norm_rows": _stroke_norm_rows(P), "norm_read": _stroke_norm_read(P),
        "norm_caption": _stroke_norm_caption(P),
        "norm_scope": (lambda g: (f"vs {g[1]}" if g and g[1] else "all bowling"))(_norms_grain(P)),
        "phase_rows": _phase_rows(P), "phase_read": _phase_read(P),
        "dismissal_read": _dismissal_read(P),
        "dismissals": P["dismissals"].most_common(6),
        "narrative": _narrative(P), "figs": figs,
        "fp_cards": fp_cards, "dim": dim_tables, "plan_read": _plan_read(P),
        "field_blocks": _field_blocks(P),
        "mv_label": ("Turn" if isg else "Seam"), "sw_label": ("Drift" if isg else "Swing"),
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "c": dict(BG_PAGE=BG_PAGE, BG_PANEL=BG_PANEL, TEXT_PRI=TEXT_PRI, TEXT_SEC=TEXT_SEC,
                  ACCENT=ACCENT, DANGER=DANGER, BORDER=BORDER),
    }

    def _slug(s):
        return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    nm = P["name"]
    if "," in nm:
        surname, first = (x.strip() for x in nm.split(",", 1))
    else:
        parts = nm.split()
        first, surname = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", nm)
    who = "_".join(x for x in (_slug(first), _slug(surname)) if x) or f"batter_{batter_id}"
    hand_tag = "lhb" if P["is_lhb"] else "rhb"
    gtag = f"_vs_{group}" if group else ""
    out_path = os.path.abspath(os.path.join(out_dir, f"{who}_batting_test_{hand_tag}{gtag}.pdf"))
    os.makedirs(out_dir, exist_ok=True)

    ctx["video"] = _build_player(P, out_path)
    html = Template(_TEMPLATE).render(**ctx)
    if ctx["video"].get("playlists"):
        # Interactive HTML report: ▶ opens the playlist as a modal OVER the report in the same
        # tab (iOS Safari/Chrome friendly); the PDF keeps the standalone-player href fallback.
        from ludis_cricket.video import inline_player_snippet
        html = html.replace("</body>", inline_player_snippet(ctx["video"]["playlists"]) + "</body>")
        with open(out_path[:-4] + ".html", "w", encoding="utf-8") as f:
            f.write(html)
    _html_to_pdf(html, out_path)
    return out_path




_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  @page { size: A4; margin: 0 0 9mm 0;
    @bottom-right { content: counter(page) " / " counter(pages); font-family: Inter, sans-serif; font-size: 8px; color: {{c.TEXT_SEC}}; margin-right: 10mm; }
    @bottom-left { content: "{{P.name}} · batting scout"; font-family: Inter, sans-serif; font-size: 8px; color: {{c.TEXT_SEC}}; margin-left: 10mm; } }
  {{ css }}
  /* ── batting-report specifics (extend / override the shared core) ── */
  .page { padding: 6px 4px; }
  h1 { font-size: 23px; }
  h2 { margin: 18px 0 8px; }
  .cards { grid-template-columns: repeat(5, 1fr); }
  .tag { font-size: 11px; font-weight: 700; color: #fff; background: {{c.DANGER}}; padding: 2px 8px; border-radius: 6px; }
  .read { font-size: 10.5px; line-height: 1.4; }
  .impact { font-weight: 700; border-left: 3px solid {{c.ACCENT}}; padding: 6px 10px; background: {{c.BG_PANEL}}; border-radius: 0 8px 8px 0; }
  .plan { font-weight: 700; border-left: 3px solid {{c.DANGER}}; padding: 7px 11px; background: #fdf1f1; border-radius: 0 8px 8px 0; font-size: 11.5px; }
  .grid2 { grid-template-columns: 1.2fr 1fr; }
  .grid2b { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
  .mtab tr.weak td { background: #fdf1f1; } .mtab tr.weak td.lab { color: {{c.DANGER}}; }
  .mtab tr.sig td { background: #eef3fb; } .mtab tr.sig td.lab { color: {{c.ACCENT}}; font-weight: 700; }
  .fpgrid { grid-template-columns: repeat(3, 1fr); }
  .fpcard .pct { font-size: 20px; }
  .dcard { border: 1px solid #f2c9c9; background: #fdf1f1; margin-top: 6px; padding: 9px 12px; }
  .dcard .db { font-size: 15px; font-weight: 800; }
  img.wag { width: 96%; display: block; margin: 0 auto; border: 1px solid {{c.BORDER}}; border-radius: 8px; background:#fff; }
  img.fieldmap { width: 100%; max-width: 250px; display: block; margin: 0 auto; }
  .fgrid { display: grid; grid-template-columns: 250px 1fr; gap: 12px; align-items: start; margin-bottom: 8px; }
</style></head>
<body><div class="page">

  <div class="header">
    {% if photo_uri %}<img src="{{photo_uri}}">{% else %}<div class="ph">🏏</div>{% endif %}
    <div>
      <h1>{{P.name}} {% if code %}<span class="flag">{{code}}</span>{% endif %}
        {% if P.group %}<span class="tag">vs {{P.group_label}}</span>{% endif %}</h1>
      <div class="sub">{{P.team}} · {{hand_label}} · {% if P.group %}How to exploit — {{P.group_label}} plan{% else %}Batting profile (Test){% endif %}</div>
    </div>
    <div class="ver">v{{version}}<br>{{build_date}}</div>
  </div>

  <div class="cards">
    {% for lab, val, sub in cards %}
      <div class="card"><div class="lab">{{lab}}</div><div class="val">{{val}}</div>
      {% if sub %}<div class="csub">{{sub}}</div>{% endif %}</div>
    {% endfor %}
  </div>

  {% if plan_read %}<div class="plan" style="margin-top:10px">{{plan_read|safe}}</div>{% endif %}

  <div class="summary">
    <div class="sbox"><h3 style="color:{{c.ACCENT}}">Common themes</h3><ul>
      {% for t in narrative.themes %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
    <div class="sbox"><h3 style="color:#15803d">Strengths</h3><ul>
      {% for t in narrative.strengths %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
    <div class="sbox"><h3 style="color:{{c.DANGER}}">Weaknesses / how to get him</h3><ul>
      {% for t in narrative.weak %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
  </div>

  {% if fp_cards %}
  <h2>Batting Fingerprint <span class="sub" style="font-weight:400">(percentile vs Test batters)</span></h2>
  <div class="fpgrid">
    {% for f in fp_cards %}
    <div class="fpcard">
      <div class="lab">{{f.label}}</div>
      <div class="pct" style="color:{{f.colour}}">{{f.pct_txt}}</div>
      <img src="{{f.img}}">
      <div class="sub">{{f.disp}}{% if f.vuln %} · higher = weaker{% else %} · higher = better{% endif %}</div>
    </div>
    {% endfor %}
  </div>
  <div class="cap" style="text-align:left">Percentile among Test batters (&ge;1500 balls). Red = a target (high vulnerability); green = a strength. Grey line = this batter in the peer spread.</div>
  {% endif %}

  {% if impact_read and not P.group %}
  <h2>Match Impact <span class="sub" style="font-weight:400">(share of runs)</span></h2>
  <div class="read impact">{{impact_read|safe}}</div>
  {% endif %}

  {% if not P.group %}
  <h2>Against Each Bowler Type</h2>
  {% if vs_read %}<div class="read impact">{{vs_read|safe}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Bowler type</th><th>Average</th><th>Strike rate</th><th>False-shot %</th><th>Dismissals / 100</th><th>Balls</th></tr>
    {% for lab, avg, sr, fs, dis, balls in vs_rows %}
    <tr><td class="lab">{{lab}}</td><td>{{avg}}</td><td>{{sr}}</td><td>{{fs}}</td><td>{{dis}}</td><td>{{balls}}</td></tr>
    {% endfor %}
  </table>
  {% endif %}

  {% if phase_rows %}
  <h2>Start of Innings vs Set</h2>
  {% if phase_read %}<div class="read impact">{{phase_read|safe}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Phase</th><th>Average</th><th>Strike rate</th><th>False-shot %</th><th>Dismissals / 100</th><th>Boundary %</th><th>Balls</th></tr>
    {% for lab, avg, sr, fs, dis, bd, balls, weak in phase_rows %}
    <tr class="{{ 'weak' if weak else '' }}"><td class="lab">{{lab}}</td><td>{{avg}}</td><td>{{sr}}</td><td>{{fs}}</td><td>{{dis}}</td><td>{{bd}}</td><td>{{balls}}</td></tr>
    {% endfor %}
  </table>
  {% endif %}

  <h2 class="pbreak">Where He's Vulnerable <span class="sub" style="font-weight:400">({% if P.group %}{{P.group_label}}{% else %}vs pace{% endif %})</span></h2>
  <div class="cap" style="text-align:left;margin-bottom:6px">Per bucket: batting average, strike rate, false-shot %, dismissals per 100 balls, boundary %. Pink row = his lowest-average (softest) bucket in that dimension.</div>
  {% macro dimtable(title, rows) %}
    {% if rows %}
    <div>
      <div style="font-weight:700;font-size:10.5px;margin:2px 0 3px">{{title}}</div>
      <table class="mtab">
        <tr><th>{{title}}</th><th>Avg</th><th>SR</th><th>False%</th><th>Outs/100</th><th>Bdry%</th><th>Balls</th></tr>
        {% for lab, avg, sr, fs, dis, bd, balls, weak in rows %}
        <tr class="{{ 'weak' if weak else '' }}"><td class="lab">{{lab}}</td><td>{{avg}}</td><td>{{sr}}</td><td>{{fs}}</td><td>{{dis}}</td><td>{{bd}}</td><td>{{balls}}</td></tr>
        {% endfor %}
      </table>
    </div>
    {% endif %}
  {% endmacro %}

  <div class="grid2b">
    {{ dimtable(mv_label ~ ' movement', dim.seam) }}
    {{ dimtable(sw_label, dim.swing) }}
  </div>
  <div class="grid2b" style="margin-top:10px">
    {{ dimtable('Length', dim.length) }}
    {{ dimtable('Pitching line', dim.line) }}
  </div>
  <div class="grid2b" style="margin-top:10px">
    {{ dimtable('Speed', dim.speed) }}
    {{ dimtable('Over vs round', dim.over_round) }}
  </div>

  {% if P.grid_danger %}
  <div class="dcard">
    <div class="dh">Danger ball — where he's most likely out {% if video.lists.danger %}<a class="vlink" data-pl="danger" href="{{video.player}}#danger">▶ watch danger balls</a>{% endif %}</div>
    <div class="db">{{P.grid_danger.length_band}} / {{P.grid_danger.line_region}}</div>
    <div class="ds">{{ '%.1f'|format(P.grid_danger.dismissal_per100) }} dismissals per 100 · averages {{ '%.0f'|format(P.grid_danger.avg) }} here · {{P.grid_danger.balls}} balls · false shot {{ '%.0f'|format(P.grid_danger.false_pct) }}%</div>
  </div>
  {% endif %}

  <h2 class="pbreak">How He Scores &amp; Gets Out</h2>
  <div class="grid2">
    <div>
      {% if dir_read %}<div class="read">{{dir_read|safe}}</div>{% endif %}
      <div style="font-weight:700;font-size:10.5px;margin:2px 0 3px">Shot types (risk)
        {% if video.lists.risky_stroke %}<a class="vlink" data-pl="risky_stroke" href="{{video.player}}#risky_stroke">▶ his {{video.stroke_name|lower}}</a>{% endif %}</div>
      <table class="mtab">
        <tr><th>Shot</th><th>Avg</th><th>SR</th><th>False%</th><th>Outs/100</th><th>Bdry%</th><th>Balls</th></tr>
        {% for lab, avg, sr, fs, dis, bd, balls, weak in dim.stroke %}
        <tr class="{{ 'weak' if weak else '' }}"><td class="lab">{{lab}}</td><td>{{avg}}</td><td>{{sr}}</td><td>{{fs}}</td><td>{{dis}}</td><td>{{bd}}</td><td>{{balls}}</td></tr>
        {% endfor %}
      </table>
      {% if norm_rows %}
      <div style="font-weight:700;font-size:10.5px;margin:8px 0 3px">Scoring mix vs the typical Test batter <span style="font-weight:400;color:{{c.TEXT_SEC}}">({{norm_scope}})</span></div>
      {% if norm_read %}<div class="read">{{norm_read|safe}}</div>{% endif %}
      <table class="mtab">
        <tr><th>Shot</th><th>% of his runs</th><th>Typical</th><th>Index</th><th>Pctl</th></tr>
        {% for fam, his, norm, idx, pctl, flag in norm_rows %}
        <tr class="{{ 'sig' if flag == 'over' else '' }}"><td class="lab">{{fam}}</td><td>{{his}}</td><td>{{norm}}</td><td>{{idx}}{% if flag == 'under' %} ▼{% endif %}</td><td>{{pctl}}</td></tr>
        {% endfor %}
      </table>
      <div class="cap">{{norm_caption}}</div>
      {% endif %}
    </div>
    <div>
      {% if figs.wagon %}<img class="wag" src="{{figs.wagon}}"><div class="cap">Where he scores — runs by area{% if P.group %} vs {{P.group_label}}{% endif %} (mirrored for a left-hander).</div>{% endif %}
    </div>
  </div>

  {% if dismissal_read %}<div class="read" style="margin-top:6px">{{dismissal_read|safe}}
    {% if video.lists.dismissals %}<a class="vlink" data-pl="dismissals" href="{{video.player}}#dismissals">▶ watch dismissals</a>{% endif %}</div>{% endif %}
  <table class="mtab" style="max-width:420px">
    <tr><th>Dismissal mode</th><th>Count</th><th>%</th></tr>
    {% for mode, cnt in dismissals %}
    <tr><td class="lab">{{mode}}</td><td>{{cnt}}</td><td>{{ (cnt / P.n_dismissals * 100) | round | int }}%</td></tr>
    {% endfor %}
  </table>

  {% if field_blocks %}
  <h2 class="pbreak">Suggested Fields <span class="sub" style="font-weight:400">(the stock field &plusmn; his evidenced deviations)</span></h2>
  <div class="cap" style="text-align:left;margin-bottom:6px">Each field starts from the <b>stock template</b> for that bowler type &amp; phase (orthodox because it works), then makes at most <b>three</b> changes — each one earned by a trigger in <b>his</b> game clearing the cohort P75 bar (does he lap, cut, pull, score square, edge early?). <b>Change</b> rows are highlighted with his stat; <b>Stock</b> rows carry the orthodoxy line. The read line backtests the changes against the pure stock field. Early = first 30 balls; Set = once in. Drawn from behind the bowler (bowler bottom, striker top); off side is on the {% if P.is_lhb %}right{% else %}left{% endif %}.</div>
  {% for blk in field_blocks %}
    <div style="font-weight:700;font-size:11.5px;margin:10px 0 4px;color:{{c.ACCENT}}">Field vs {{blk.label}}</div>
    {% for col in blk.cols %}
    <div style="font-weight:700;font-size:10px;margin:4px 0 2px">{{col.title}} <span style="font-weight:400;color:{{c.TEXT_SEC}}">· {{col.legal}} balls</span></div>
    <div class="fgrid">
      <div>
        {% if col.fig %}<img class="fieldmap" src="{{col.fig}}">{% endif %}
        <div class="read" style="margin-top:4px">{{col.backtest|safe}}</div>
      </div>
      <table class="mtab">
        <tr><th>Fielder</th><th>Stock/Change</th><th style="text-align:left">Why he's there</th></tr>
        {% for pos, role, why, tag in col.rows %}
        <tr class="{{ 'sig' if tag=='change' else '' }}"><td class="lab">{{pos}}</td><td>{{role}}</td><td style="text-align:left">{{why}}</td></tr>
        {% endfor %}
      </table>
    </div>
    {% endfor %}
  {% endfor %}
  {% endif %}

</div></body></html>
"""
