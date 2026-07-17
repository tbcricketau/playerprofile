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
import json

from jinja2 import Template

from version import REPORT_VERSION
from batter_profile import (build_batter_profile, BOWLER_GROUPS,
                            process_batting_rows, load_batter_deliveries)
import field_engine as fe
from photos import get_photo_data_uri
from cricket_core.charts import wagon_wheel_zones, fingerprint_strip
from cricket_core.video import first_example, get_fairplay_sas
from report import (
    _fig_uri, _html_to_pdf, _country_code,
    BG_PAGE, BG_PANEL, TEXT_PRI, TEXT_SEC, ACCENT, DANGER, BORDER,
)
from report_style import REPORT_CSS, card


def _fmt(v, spec=".0f", suffix=""):
    if v is None:
        return "—"
    try:
        return f"{float(v):{spec}}{suffix}"
    except (TypeError, ValueError):
        return "—"


def _cards(P: dict, recent: dict = None) -> list:
    """Headline cards — one metric each, career value with the last-3-yr value under it. `recent`
    = {label: last-3-yr value str}. 'Median % of runs' = the typical innings' share of the team
    total (median, not the career aggregate, which a couple of big scores skew)."""
    s = P.get("share") or {}
    rec = recent or {}
    return [
        card("Runs", _fmt(P["runs"]), f"{P['n_out']} dismissals · {_fmt(s.get('innings'))} inns"),
        card("Average", _fmt(P["average"], ".1f"), recent=rec.get("Average", "")),
        card("Strike rate", _fmt(P["strike_rate"], ".1f"), recent=rec.get("Strike rate", "")),
        card("Median % of runs", _fmt(s.get("team_share_median"), ".1f", "%"), "of team, per innings",
             recent=rec.get("Median % of runs", "")),
        card("Carries the innings", _fmt(s.get("carried_rate"), ".0f", "%"), "innings with ≥25% of team",
             recent=rec.get("Carries the innings", "")),
    ]


def _impact_read(P: dict) -> str:
    s = P.get("share")
    if not s:
        return ""
    tc, tm = s["team_share_career"], s["team_share_median"]
    lead = (f"Makes <b>{tc:.1f}%</b> of their team's runs over a career (typical innings "
            f"{tm:.1f}%), and <b>{_fmt(s['match_share_career'], '.1f', '%')}</b> of all runs in their matches")
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
                f"falser shot {s['false_pct']:.0f}% vs {p['false_pct']:.0f}%) — attack them with spin.")
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
    return f"Scores most of their runs through {side} ({d[top]:.0f}%; off {d['off']:.0f}% · leg {d['leg']:.0f}% · straight {d['straight']:.0f}%)."


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
        txt = (f"<b>Get them early</b> — they're {ratio:.1f}× more likely to fall in their first 30 balls "
               f"({e['dismissal_per100']:.1f} vs {s['dismissal_per100']:.1f} dismissals/100 once set")
        if e["false_pct"] and s["false_pct"]:
            txt += f"; false shot {e['false_pct']:.0f}% vs {s['false_pct']:.0f}%"
        txt += ")."
    elif ratio and ratio <= 1.1:
        txt = (f"Starts securely — their dismissal rate barely drops once set "
               f"({e['dismissal_per100']:.1f} early vs {s['dismissal_per100']:.1f}/100); "
               f"early pressure alone won't buy their wicket.")
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

_BAT_REF_CSV = r"c:\Projects\referencebuilder\data\batter_vulnerability_profile.csv"
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
_STROKE_NORMS_CSV = r"c:\Projects\referencebuilder\data\batter_stroke_norms.csv"
_STROKE_COHORT_CSV = r"c:\Projects\referencebuilder\data\stroke_norms_cohort.csv"
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
    return (f"Share of stroke-coded runs {scope}; index = their share ÷ cohort median "
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
        parts.append(f"The <b>{fam.lower()}</b> brings them {his:.0f}% of their runs{scope} — "
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
        mv = [d for d in dims.get(dk, []) if d["bucket"] in ("in", "away", "out")
              and d["balls"] >= 60 and d["avg"] is not None]
        straight = next((d for d in dims.get(dk, []) if d["bucket"] == "straight"), None)
        if mv and straight and straight["avg"]:
            worst = min(mv, key=lambda d: d["avg"])
            if worst["avg"] < straight["avg"] * 0.75:
                dirw = _blabel(worst["bucket"], dk + "_dir", is_spin)
                out.append(f"The ball that {dirw} hurts them (avg {worst['avg']:.0f} vs {straight['avg']:.0f} when it holds its line).")
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

# a type-scoped player report only shows the traits that matter to the bowler viewing it —
# a pace bowler doesn't need the batter's vs-spin trait, and vice versa.
_FP_FOCUS = {
    "pace": {"avg", "sr", "false_pct", "pace_false", "seam_false", "swing_false", "short_false", "bdry_pct"},
    "spin": {"avg", "sr", "false_pct", "spin_false", "bdry_pct"},
}


def _bpctl_of(v, peers):
    """Percentile of value v within peers (% at or below)."""
    if v is None or not peers:
        return None
    return 100.0 * sum(1 for x in peers if x <= v) / len(peers)


def _fingerprint_cards(P: dict, recent_vals: dict = None, focus: str = None) -> list:
    ref = _bat_ref()
    me = ref.get(P["batter_id"])
    if not me:
        return []
    recent_vals = recent_vals or {}
    keep = _FP_FOCUS.get(focus)                         # type-scoped report → only relevant traits
    cards = []
    for key, label, vuln in _FP:
        if keep is not None and key not in keep:
            continue
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
        card = {"label": label, "pctl": pctl, "value": val, "values": peers,
                "vuln": vuln, "colour": colour, "disp": disp}
        rv = recent_vals.get(label)
        if rv is not None:
            card["recent"] = rv
            card["pctl_recent"] = _bpctl_of(rv, peers)
        cards.append(card)
    return cards


def _fingerprint_headline(cards: list) -> str | None:
    """How the batter's fingerprint has shifted in the last 3 years — leads with the biggest
    percentile move (noise-gated at 12 points). Vulnerability metrics are phrased as more/less
    vulnerable, scoring metrics as up/down."""
    moves = []
    for m in cards:
        cp, rp = m.get("pctl"), m.get("pctl_recent")
        if cp is None or rp is None or abs(rp - cp) < 12:
            continue
        lab = m["label"].lower()
        if m.get("vuln"):
            txt = f"{lab} {'up' if rp > cp else 'down'}"
        else:
            txt = f"{lab} {'up' if rp > cp else 'down'}"
        moves.append((abs(rp - cp), txt))
    if not moves:
        return None
    moves.sort(reverse=True)
    return "Changing (last 3 years vs career): " + "; ".join(t for _s, t in moves[:3]) + "."


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
        mv = [d for d in dims.get(dk, []) if d["bucket"] in ("in", "away", "out")
              and d["balls"] >= 60 and d["avg"] is not None]
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
        plan += f"; they're most often out <b>{top[0].lower()}</b> to this attack"
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
        return (f"<b>Pure {base}.</b> Nothing in their game clears the deviation bar (cohort P75) "
                f"against {fs['group_label']}, so the orthodox field stands — that <i>is</i> the read.")
    n = len(chg)
    gains = []
    if bt["bdry_gain"] >= 1:
        gains.append(f"+{bt['bdry_gain']:.0f}% of their boundary runs")
    if bt["exp_catch_gain"] >= 1:
        gains.append(f"+{bt['exp_catch_gain']:.0f}% of their expected edges")
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
        short_ball = None

        def _jrows(field):
            return [(f["position"], "Change" if f["tag"] == "change" else "Stock",
                     f["why"], f["tag"]) for f in field]

        def _diagram(field):
            try:
                return _fig_uri(fe.field_diagram(field, P["is_lhb"], title=""), w=300, h=300)
            except Exception:
                return ""

        for phase, title in (("early", "Early — first 30 balls"), ("set", "Once set")):
            fs = fe.build_field(subP, group, phase)
            if not fs:
                continue
            short_ball = short_ball or fs.get("short_ball")
            cols.append({"title": title, "fig": _diagram(fs["field"]), "rows": _jrows(fs["field"]),
                         "backtest": _field_backtest_line(fs, phase), "legal": fs["legal"]})
        # heavy puller → the named short-ball / bumper plan as an extra alternative field
        if short_ball:
            cols.append({"title": "Short-ball plan", "fig": _diagram(short_ball["field"]),
                         "rows": _jrows(short_ball["field"]), "backtest": short_ball["note"], "legal": None})
        if cols:
            blocks.append({"label": fe._group_label(group), "cols": cols})
    return blocks


def _build_player(P: dict, pdf_path: str) -> dict:
    """Build batting playlists, write a self-contained modal video player next to the PDF, and
    return {player, keys, stroke_name} for the report's ▶ links. Best-effort."""
    try:
        get_fairplay_sas(ttl_hours=72)
        from playlists import build_batting_playlists
        from cricket_core.video import build_player_html, write_playlists
        pls = build_batting_playlists(P, cap=8)
        if not pls:
            return {}
        player_path = pdf_path[:-4] + ".player.html"
        sub = f"{P['name']} — batting scout" + (f" vs {P['group_label']}" if P.get("group") else "")
        build_player_html(pls, player_path, title=P["name"], subtitle=sub)
        write_playlists(pdf_path[:-4] + ".playlists.json", pls,
                        meta={"batter_id": str(P["batter_id"]), "batter": P["name"]})
        strokes = [d for d in (P.get("dims", {}).get("stroke") or []) if d["balls"] >= 30 and d.get("false_pct") is not None]
        stroke_name = max(strokes, key=lambda d: d["false_pct"])["bucket"] if strokes else None
        return {"player": _file_url(player_path), "lists": {k: True for k in pls},
                "stroke_name": stroke_name, "playlists": pls}
    except Exception:
        return {}


def render_batting_report(batter_id: str, out_dir: str = "reports", group: str | None = None,
                          render_pdf: bool = True) -> str:
    """Combined overview (group=None) or a focused per-bowler-type exploit report (e.g.
    group='right_pace'). Same engine; the focused one filters to that bowler group + adds a plan.
    `render_pdf=False` writes the .html + .pmode.html only (fast web iteration, skips the slow print)."""
    raw_all = process_batting_rows(load_batter_deliveries(batter_id))
    P = build_batter_profile(batter_id, raw=raw_all, group=group)

    # a type-scoped player report (group set) keeps the fingerprint/impact but shows only the
    # traits + numbers for that bowling type. focus = pace/spin picks which fingerprint cards stay.
    focus = ("spin" if P.get("is_spin_group") else "pace") if group else None

    # recency: last-3yr values. The fingerprint is vs ALL Test batters, so its recency is the
    # OVERALL 3yr (Pr); the top cards' avg/SR are vs-this-type, so their recency is the type 3yr (Pg).
    fp_recent = {}
    card_recent = {}
    import datetime as _dt
    _cut = (_dt.date.today() - _dt.timedelta(days=int(365.25 * 3))).isoformat()
    _rec = [r for r in raw_all if (r.get("match_date") or "") >= _cut]
    if sum(1 for r in _rec if r.get("is_legal")) >= 300:    # floor — a thin window isn't a real change
        Pr = build_batter_profile(batter_id, raw=_rec)
        Pg = build_batter_profile(batter_id, raw=_rec, group=group) if group else Pr
        vp, vs = (Pr.get("vs") or {}).get("pace") or {}, (Pr.get("vs") or {}).get("spin") or {}
        _sr = Pr.get("share") or {}                    # share is innings-based → overall, not type
        if (Pr.get("n_out") or 0) >= 6:
            fp_recent["Average"] = Pr.get("average")
            fp_recent["Strike rate"] = Pr.get("strike_rate")
            card_recent["Carries the innings"] = _fmt(_sr.get("carried_rate"), ".0f", "%")
        if (Pg.get("n_out") or 0) >= 6 and Pg.get("average") is not None:
            card_recent["Average"] = _fmt(Pg["average"], ".1f")
        if Pg.get("strike_rate") is not None:
            card_recent["Strike rate"] = _fmt(Pg["strike_rate"], ".1f")
        card_recent["Median % of runs"] = _fmt(_sr.get("team_share_median"), ".1f", "%")
        fp_recent["False % vs pace"] = vp.get("false_pct")
        fp_recent["False % vs spin"] = vs.get("false_pct")
        fp_recent = {k: v for k, v in fp_recent.items() if v is not None}
        card_recent = {k: v for k, v in card_recent.items() if v not in (None, "—")}

    figs = {}
    try:
        figs["wagon"] = _fig_uri(
            wagon_wheel_zones(P["raw"], metric="runs", title="", n_sectors=8, is_lhb=P["is_lhb"]),
            w=500, h=430)
    except Exception:
        figs["wagon"] = ""

    fp_cards = []                              # fingerprint from the vs-all reference; focus trims traits
    for c in _fingerprint_cards(P, recent_vals=fp_recent, focus=focus):
        try:
            img = _fig_uri(fingerprint_strip(c["values"], c["value"], invert=False,
                                             recent_value=c.get("recent")), w=250, h=84)
        except Exception:
            img = ""
        rp = c.get("pctl_recent")
        fp_cards.append({**c, "img": img, "pct_txt": f"P{c['pctl']:.0f}",
                         "recent_txt": (f"P{rp:.0f}" if (c.get("recent") is not None and rp is not None) else None)})
    fp_headline = _fingerprint_headline(fp_cards)

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

    def _attacked_ctx():
        """'How attacks bowl to them — last 3 series' (attack_cards machinery, any batter)."""
        try:
            from attack_cards import card_for
            card = card_for(batter_id, P.get("name"))
            return card if card and card.get("series") else None
        except Exception:
            return None

    def _sim_options_ctx():
        """Our best simulated options vs this batter, from the series matchup store."""
        try:
            import glob as _g
            from cricket_core.config import project_path
            for p in _g.glob(os.path.join(project_path("matchupmodel"), "data",
                                          "matchup_store_*.json")):
                store = json.load(open(p, encoding="utf-8"))
                cells = [c for c in store.get("they_bat", [])
                         if c["batter_id"] == str(batter_id) and c["sim_avg"] is not None]
                if not cells:
                    continue
                ranked = sorted(cells, key=lambda c: c["sim_avg"])
                struct = [c for c in cells if c.get("structural_threat")]
                sline = ""
                if struct:
                    b = struct[0]
                    sline = (f"Structurally, {b['bowler_type'].lower()} turning the ball away from "
                             f"the {b['bat_hand']} is the matchup class that persists — favour that "
                             f"angle when the individual reads are thin.")
                return {"rows": [(c["bowler"], c["bowler_type"], c["sim_avg"], c["sim_sr"],
                                  c.get("fail_to_set_pct"), c["danger"], c["top_dismissal"],
                                  c["confidence"]) for c in ranked[:5]],
                        "structural": sline, "built": store.get("built")}
        except Exception:
            pass
        return None

    ctx = {
        "P": P, "code": _country_code(P["team"]),
        "photo_uri": get_photo_data_uri(P["batter_id"], fmt="test", name=P.get("name")),
        "attacked": _attacked_ctx(), "sim_options": _sim_options_ctx(),
        "hand_label": "LHB" if P["is_lhb"] else "RHB",
        "cards": _cards(P, card_recent), "impact_read": _impact_read(P),
        "vs_rows": _vs_rows(P), "vs_read": _vs_read(P),
        "shot_rows": _shot_rows(P), "dir_read": _dir_read(P),
        "norm_rows": _stroke_norm_rows(P), "norm_read": _stroke_norm_read(P),
        "norm_caption": _stroke_norm_caption(P),
        "norm_scope": (lambda g: (f"vs {g[1]}" if g and g[1] else "all bowling"))(_norms_grain(P)),
        "phase_rows": _phase_rows(P), "phase_read": _phase_read(P),
        "dismissal_read": _dismissal_read(P),
        "dismissals": P["dismissals"].most_common(6),
        "narrative": _narrative(P), "figs": figs,
        "fp_cards": fp_cards, "fp_headline": fp_headline, "dim": dim_tables, "plan_read": _plan_read(P),
        "field_blocks": _field_blocks(P),
        "mv_label": ("Turn" if isg else "Seam"), "sw_label": ("Drift" if isg else "Swing"),
        "version": REPORT_VERSION, "build_date": datetime.date.today().strftime("%d %b %Y"),
        "css": REPORT_CSS,                     # base stylesheet ({{ css }} was rendering empty)
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

    def _render(player_mode):
        """Full coach report, or the reduced player-facing cut (the coach-only 'Our Best Options'
        simulated-matchup table — how OUR bowlers match up to this batter — stripped). A type-scoped
        player report (group set) keeps the fingerprint + impact; the coach exploit cut stays lean."""
        c2 = dict(ctx, player_mode=player_mode)
        # fingerprint + impact show on the combined report and on any PLAYER-mode report (incl. the
        # type-scoped one); the coach exploit cut (group set, not player-mode) stays lean.
        c2["show_fp"] = (group is None) or player_mode
        if player_mode:
            c2["sim_options"] = None
        h = Template(_TEMPLATE).render(**c2)
        if ctx["video"].get("playlists"):
            # Interactive HTML report: ▶ opens the playlist as a modal OVER the report in the same
            # tab (iOS Safari/Chrome friendly); the PDF keeps the standalone-player href fallback.
            from cricket_core.video import inline_player_snippet
            snippet = ("<!--PLAYER_SNIPPET_START-->"
                       + inline_player_snippet(ctx["video"]["playlists"]) + "<!--PLAYER_SNIPPET_END-->")
            h = h.replace("</body>", snippet + "</body>")
        return h

    html = _render(False)
    with open(out_path[:-4] + ".html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(out_path[:-4] + ".pmode.html", "w", encoding="utf-8") as f:
        f.write(_render(True))
    if render_pdf:
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
    {% for cd in cards %}
      <div class="card"><div class="lab">{{cd.lab}}</div><div class="val">{{cd.val}}</div>
      {% if cd.sub %}<div class="csub">{{cd.sub}}</div>{% endif %}
      {% if cd.recent %}<div class="crec"><span class="rl">3-yr</span> {{cd.recent}}</div>{% endif %}</div>
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

  {% if fp_cards and show_fp %}
  <h2>Batting Fingerprint <span class="sub" style="font-weight:400">(percentile vs Test batters{% if P.group %} · {{P.group_label}} traits{% endif %})</span></h2>
  {% if fp_headline %}<div class="read" style="margin-bottom:6px">{{fp_headline}}</div>{% endif %}
  <div class="fpgrid">
    {% for f in fp_cards %}
    <div class="fpcard">
      <div class="lab">{{f.label}}</div>
      <div class="pct" style="color:{{f.colour}}">{{f.pct_txt}}{% if f.recent_txt %} <span style="color:#d9822b;font-size:12px">&rarr; {{f.recent_txt}}</span>{% endif %}</div>
      <img src="{{f.img}}">
      <div class="sub">{{f.disp}}{% if f.vuln %} · higher = weaker{% else %} · higher = better{% endif %}</div>
    </div>
    {% endfor %}
  </div>
  <div class="cap" style="text-align:left"><b style="color:{{c.ACCENT}}">Solid line = career</b>, <b style="color:#d9822b">dotted = last 3 years</b> (avg / SR / false% vs pace &amp; spin). Percentile among Test batters (&ge;1500 balls). Red = a target (high vulnerability); green = a strength.</div>
  {% endif %}

  {% if impact_read and show_fp %}
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

  {% if attacked %}
  <h2 class="pbreak">How Attacks Bowl To Them <span class="sub" style="font-weight:400">(last {{attacked.series|length}} series)</span></h2>
  {% for s in attacked.series %}
  <div style="margin-bottom:10px">
    <div style="font-weight:700;font-size:11.5px">v {{s.opp}} <span class="sub" style="font-weight:400">· {{s.tests}} Test{{'s' if s.tests != 1 else ''}} · {{s.balls}} balls · {{s.runs}} runs{% if s.avg is not none %} · avg {{s.avg}}{% endif %}</span></div>
    {% if s.cells %}<div class="read" style="margin:3px 0 5px">{{s.summary}}</div>
    <table class="mtab" style="width:auto">
      <tr><th>Ball</th><th>Them</th><th>Teammates</th><th></th></tr>
      {% for c in s.cells if c.flag in ('more','less') %}
      <tr><td class="lab">{{c.label|capitalize}}</td><td>{{'%.0f'|format(c.pct)}}%</td><td>{{'%.0f'|format(c.ctrl_pct)}}%</td><td style="font-weight:700;color:{{'#991b1b' if c.flag=='more' else '#075985'}}">{{'▲ more' if c.flag=='more' else '▼ less'}}</td></tr>
      {% endfor %}
    </table>
    {% else %}<div class="cap" style="text-align:left">Too few balls in this series to compare a plan.</div>{% endif %}
  </div>
  {% endfor %}
  <div class="cap" style="text-align:left">Only the balls of each attack's pace plan that differed from what the same bowlers gave that side's other {{hand_label}} top-order batters. The full dismissal detail sits in the vision playlists.</div>
  {% endif %}

  {% if sim_options %}
  <h2 class="pbreak">Our Best Options <span class="sub" style="font-weight:400">(simulated matchups)</span></h2>
  <div class="cap" style="text-align:left;margin-bottom:5px">From the match simulation — a tool that plays each batter-v-bowler pairing out thousands of times from their full Test profiles. Low expected average = the bowler wins the matchup. "Cohort" confidence = they have not faced enough of that type for a personal read.</div>
  <table class="mtab">
    <tr><th>Bowler</th><th>Type</th><th>Exp avg</th><th>Exp SR</th><th>Out in first 30 %</th><th>Stock wicket ball</th><th>Top dismissal</th><th>Confidence</th></tr>
    {% for bow, btype, avg, sr, fts, danger, dis, conf in sim_options.rows %}
    <tr><td class="lab">{{bow}}</td><td>{{btype}}</td><td>{{avg}}</td><td>{{sr}}</td><td>{{fts if fts is not none else '—'}}</td><td>{{danger}}</td><td>{{dis}}</td><td>{{'Cohort' if conf=='None' else conf}}</td></tr>
    {% endfor %}
  </table>
  {% if sim_options.structural %}<div class="read" style="margin-top:4px">{{sim_options.structural}}</div>{% endif %}
  {% endif %}

  <h2 class="pbreak">Where They're Vulnerable <span class="sub" style="font-weight:400">({% if P.group %}{{P.group_label}}{% else %}vs pace{% endif %})</span></h2>
  <div class="cap" style="text-align:left;margin-bottom:6px">Per bucket: batting average, strike rate, false-shot %, dismissals per 100 balls, boundary %. Pink row = their lowest-average (softest) bucket in that dimension.</div>
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
    <div class="dh">Danger ball — where they're most likely out {% if video.lists.danger %}<a class="vlink" data-pl="danger" href="{{video.player}}#danger">▶ watch danger balls</a>{% endif %}</div>
    <div class="db">{{P.grid_danger.length_band}} / {{P.grid_danger.line_region}}</div>
    <div class="ds">{{ '%.1f'|format(P.grid_danger.dismissal_per100) }} dismissals per 100 · averages {{ '%.0f'|format(P.grid_danger.avg) }} here · {{P.grid_danger.balls}} balls · false shot {{ '%.0f'|format(P.grid_danger.false_pct) }}%</div>
  </div>
  {% endif %}

  <h2 class="pbreak">How They Score &amp; Get Out</h2>
  <div class="grid2">
    <div>
      {% if dir_read %}<div class="read">{{dir_read|safe}}</div>{% endif %}
      <div style="font-weight:700;font-size:10.5px;margin:2px 0 3px">Shot types (risk)
        {% if video.lists.risky_stroke %}<a class="vlink" data-pl="risky_stroke" href="{{video.player}}#risky_stroke">▶ their {{video.stroke_name|lower}}</a>{% endif %}</div>
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
        <tr><th>Shot</th><th>% of their runs</th><th>Typical</th><th>Index</th><th>Pctl</th></tr>
        {% for fam, his, norm, idx, pctl, flag in norm_rows %}
        <tr class="{{ 'sig' if flag == 'over' else '' }}"><td class="lab">{{fam}}</td><td>{{his}}</td><td>{{norm}}</td><td>{{idx}}{% if flag == 'under' %} ▼{% endif %}</td><td>{{pctl}}</td></tr>
        {% endfor %}
      </table>
      <div class="cap">{{norm_caption}}</div>
      {% endif %}
    </div>
    <div>
      {% if figs.wagon %}<img class="wag" src="{{figs.wagon}}"><div class="cap">Where they score — runs by area{% if P.group %} vs {{P.group_label}}{% endif %} (mirrored for a left-hander).</div>{% endif %}
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
  <h2 class="pbreak">Suggested Fields <span class="sub" style="font-weight:400">(the stock field &plusmn; their evidenced deviations)</span></h2>
  <div class="cap" style="text-align:left;margin-bottom:6px">Each field starts from the <b>stock template</b> for that bowler type &amp; phase (orthodox because it works), then makes at most <b>three</b> changes — each one earned by a trigger in <b>their</b> game clearing the cohort P75 bar (do they lap, cut, pull, score square, edge early?). <b>Change</b> rows are highlighted with their stat; <b>Stock</b> rows carry the orthodoxy line. The read line backtests the changes against the pure stock field. Early = first 30 balls; Set = once in. Drawn from behind the bowler (bowler bottom, striker top); off side is on the {% if P.is_lhb %}right{% else %}left{% endif %}.</div>
  {% for blk in field_blocks %}
    <div style="font-weight:700;font-size:11.5px;margin:10px 0 4px;color:{{c.ACCENT}}">Field vs {{blk.label}}</div>
    {% for col in blk.cols %}
    <div style="font-weight:700;font-size:10px;margin:4px 0 2px">{{col.title}}{% if col.legal %} <span style="font-weight:400;color:{{c.TEXT_SEC}}">· {{col.legal}} balls</span>{% endif %}</div>
    <div class="fgrid">
      <div>
        {% if col.fig %}<img class="fieldmap" src="{{col.fig}}">{% endif %}
        <div class="read" style="margin-top:4px">{{col.backtest|safe}}</div>
      </div>
      <table class="mtab">
        <tr><th>Fielder</th><th>Stock/Change</th><th style="text-align:left">Why they're there</th></tr>
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
