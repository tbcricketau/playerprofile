"""
field_engine.py — justified field settings for a batter × bowler group × innings phase,
built from what the batter DOES (no fielder-placement data needed). See FIELD_PLAN.md.

Three evidence layers, each carrying the stat that justifies every fielder:
  1. Run flow      — 10 batter-relative sectors from hit_to_angle (~100% of scoring balls):
                     runs/100 balls + boundary share → where to save runs / post deep riders.
  2. Expected catch — his false-shot mix by stroke × the cohort's stroke→catch-position
                     distribution (referencebuilder/data/catch_position_norms.csv) → where his
                     mishits carry → the catchers. His OWN observed catches
                     (batter_field_profile.csv) are kept for the backtest.
  3. Phase weight  — first 30 balls: wicket-biased (more catchers); once set: run-biased.

Output: an ordered field (keeper + 9) where each fielder has a role (catch/save) and a
one-line justification, plus a backtest ("under N of his M caught dismissals vs this group").

Batter-relative angle convention (matches ludis_cricket.lookups.field_coords):
  br_angle = hit_to_angle if RHB else -hit_to_angle ;  +ve = OFF side, 0 = straight.
"""
import csv
import os
from collections import defaultdict

from ludis_cricket.lookups import FIELD_POS, field_coords

_REF = r"c:\Ludis\referencebuilder\data"
_COHORT_CSV = os.path.join(_REF, "catch_position_norms.csv")
_PROFILE_CSV = os.path.join(_REF, "batter_field_profile.csv")

# Batter-relative sectors (+off). Behind square handled by the wide fine buckets.
_SECTORS = [
    ("third man",  115, 165), ("point",       70, 115), ("cover",   35, 70),
    ("mid-off",     10,  35), ("straight",   -10,  10), ("mid-on",  -35, -10),
    ("midwicket",  -70, -35), ("square leg",-115, -70), ("fine leg",-165,-115),
]
# sector -> (ring position name, deep position name) from FIELD_POS
_SECTOR_POS = {
    "third man":  ("Third man", "Deep third man"),
    "point":      ("Point", "Deep point"),
    "cover":      ("Cover", "Deep cover"),
    "mid-off":    ("Mid-off", "Long-off"),
    "straight":   ("Mid-on", "Long-on"),
    "mid-on":     ("Mid-on", "Long-on"),
    "midwicket":  ("Midwicket", "Deep midwicket"),
    "square leg": ("Square leg", "Deep square leg"),
    "fine leg":   ("Fine leg", "Deep fine leg"),
}
_FMT = "test"
_CACHE = {}


def _load_csv(path):
    if path not in _CACHE:
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        _CACHE[path] = rows
    return _CACHE[path]


def _cohort_catch_dist(group):
    """{stroke_family: {position: share%}} for this bowler group (Tests)."""
    out = defaultdict(dict)
    for r in _load_csv(_COHORT_CSV):
        if r["format"] == _FMT and r["bowler_group"] == group:
            out[r["stroke_family"]][r["position"]] = float(r["share"])
    return out


def _batter_field(batter_id, group):
    """His observed positions vs this group: {position: {balls, runs, saved, catches}}."""
    out = {}
    for r in _load_csv(_PROFILE_CSV):
        if r["format"] == _FMT and r["batter_id"] == str(batter_id) and r["bowler_group"] == group:
            out[r["position"]] = {"balls": int(r["balls_fielded"]), "runs": int(r["runs_conceded"]),
                                  "saved": int(r["runs_saved"]), "catches": int(r["catches"])}
    return out


def _br_angle(r, is_lhb):
    a = r.get("hit_ang_n")
    if a is None:
        return None
    return a if not is_lhb else -a


def _sector_of(angle):
    if angle is None:
        return None
    for name, lo, hi in _SECTORS:
        if lo <= angle < hi:
            return name
    return "fine leg" if angle < 0 else "third man"     # very fine edges fold into the ends


def run_flow(rows, is_lhb):
    """Per sector: balls, runs, boundary runs, runs/100, boundary share. Scoring balls only
    place; every legal ball counts toward the denominator."""
    agg = defaultdict(lambda: {"balls": 0, "runs": 0.0, "bdry": 0.0})
    legal = 0
    for r in rows:
        if not r["is_legal"]:
            continue
        legal += 1
        if r["runs"] <= 0:
            continue
        s = _sector_of(_br_angle(r, is_lhb))
        if not s:
            continue
        agg[s]["balls"] += 1
        agg[s]["runs"] += r["runs"]
        if r["runs"] in (4.0, 6.0):
            agg[s]["bdry"] += r["runs"]
    out = {}
    for s, v in agg.items():
        out[s] = {**v, "runs_per100": v["runs"] / legal * 100 if legal else 0,
                  "bdry_share": v["bdry"] / v["runs"] * 100 if v["runs"] else 0,
                  "runs_share": v["runs"]}
    tot = sum(v["runs"] for v in out.values()) or 1
    for v in out.values():
        v["runs_share"] = v["runs"] / tot * 100
    return out, legal


def expected_catches(rows, group):
    """His false-shot count by stroke × cohort stroke→position distribution → expected
    relative catches per position, plus the dominant stroke feeding each position."""
    cohort = _cohort_catch_dist(group)
    false_by_stroke = defaultdict(int)
    for r in rows:
        if r.get("has_shot_q") and r.get("is_false_shot") and r.get("stroke_family"):
            false_by_stroke[r["stroke_family"]] += 1
    exp = defaultdict(float)
    feed = defaultdict(lambda: defaultdict(float))
    for stroke, nfalse in false_by_stroke.items():
        for pos, share in cohort.get(stroke, {}).items():
            exp[pos] += nfalse * share / 100.0
            feed[pos][stroke] += nfalse * share / 100.0
    dom = {p: (max(feed[p], key=feed[p].get) if feed[p] else None) for p in exp}
    return exp, dom, false_by_stroke


def _n_catchers(phase, is_spin, false_rate):
    """Non-keeper dedicated catchers. More early and when he plays falser; realistic caps."""
    base = 3 if phase == "early" else 2
    if is_spin:
        base = 3 if phase == "early" else 1     # bat-pad + slip early, one catcher set
    if false_rate is not None and false_rate >= 20 and phase == "early":
        base += 1
    return max(1, min(4, base))


def build_field(P, group, phase):
    """Return an ordered field for a phase ('early'|'set'). Each entry:
    {position, angle, radius, role, kind: 'catch'|'save', why}."""
    is_lhb = P["is_lhb"]
    is_spin = group in ("off_spin", "leg_spin", "left_orthodox", "left_unorthodox", "spin")
    rows = [r for r in P["raw"] if (r["is_early"] if phase == "early" else not r["is_early"])]
    if sum(1 for r in rows if r["is_legal"]) < 80:
        return None

    flow, legal = run_flow(rows, is_lhb)
    exp, dom, false_by_stroke = expected_catches(rows, group)
    observed = _batter_field(P["batter_id"], group)
    shotq = sum(1 for r in rows if r.get("has_shot_q"))
    false_rate = (sum(1 for r in rows if r.get("is_false_shot")) / shotq * 100) if shotq else None

    field, used_pos, used_sector = [], set(), set()

    def add(name, kind, why):
        c = FIELD_POS.get(name) or field_coords(name)
        if name in used_pos:
            return
        used_pos.add(name)
        field.append({"position": name, "angle": c["angle"], "radius": c["radius"],
                      "role": c["role"], "kind": kind, "why": why})

    # keeper always
    add("Keeper", "catch", "Standing to the stumps.")

    # LAYER 2 — catchers, ranked by expected catches
    n_catch = _n_catchers(phase, is_spin, false_rate)
    ranked = sorted(exp.items(), key=lambda kv: -kv[1])
    placed = 0
    for pos, score in ranked:
        if placed >= n_catch or pos in ("Keeper", "Bowler"):
            continue
        c = field_coords(pos)
        if c["role"] != "catch":
            continue     # only cordon/bat-pad positions act as dedicated catchers here
        stroke = dom.get(pos)
        obs = observed.get(pos, {}).get("catches", 0)
        share = _cohort_catch_dist(group).get(stroke, {}).get(pos)
        why = (f"His false {stroke.lower()}s carry here "
               f"({share:.0f}% of {stroke.lower()} catches vs {_group_label(group)} across Tests)"
               if stroke and share else "Catches his mishits in the cordon")
        if obs:
            why += f"; {obs} of his caught dismissals here already"
        add(pos, "catch", why + ".")
        placed += 1

    # LAYER 1 — savers/riders on his biggest run sectors, one per sector
    slots = 9 - (len(field) - 1)          # 9 outfielders; keeper doesn't count
    sectors_ranked = sorted(flow.items(), key=lambda kv: -kv[1]["runs_share"])
    for s, v in sectors_ranked:
        if slots <= 0:
            break
        if s in used_sector or s not in _SECTOR_POS or v["balls"] < 5:
            continue
        ring_name, deep_name = _SECTOR_POS[s]
        deep = v["bdry_share"] >= 33 and phase == "set"
        name = deep_name if deep else ring_name
        if name in used_pos:
            name = (ring_name if deep else deep_name)
            if name in used_pos:
                continue
        kind = "save"
        why = (f"{v['runs_share']:.0f}% of his runs vs {_group_label(group)} go {_sector_phrase(s)}"
               f" ({v['bdry_share']:.0f}% in boundaries, n={v['balls']} scoring balls)"
               + (" — held back on the rope." if deep else " — cuts off the single/two."))
        add(name, kind, why)
        used_sector.add(s)
        slots -= 1

    backtest = _backtest(field, observed, flow, exp)
    return {"phase": phase, "group": group, "group_label": _group_label(group),
            "n_catchers": placed + 1, "false_rate": false_rate, "legal": legal,
            "field": field, "backtest": backtest}


def _backtest(field, observed, flow, exp):
    """Validation. Primary is cohort-based (always available): of where his mishits are
    EXPECTED to carry, how much sits at the recommended catch positions. Observed catches
    (thin — position coding is sparse) are a secondary note. Boundary coverage from run-flow."""
    catch_pos = {f["position"] for f in field if f["kind"] == "catch"}
    tot_exp = sum(exp.values()) or 1
    exp_covered = sum(v for p, v in exp.items() if p in catch_pos) / tot_exp * 100
    total_catches = sum(v["catches"] for v in observed.values())
    covered_catches = sum(v["catches"] for p, v in observed.items() if p in catch_pos)
    deep_sectors = {s for f in field if f["role"] == "deep"
                    for s, (rn, dn) in _SECTOR_POS.items() if f["position"] in (rn, dn)}
    tot_bdry = sum(v["bdry"] for v in flow.values()) or 1
    covered_bdry = sum(v["bdry"] for s, v in flow.items() if s in deep_sectors)
    return {"exp_catch_covered_pct": exp_covered,
            "catches_covered": covered_catches, "catches_total": total_catches,
            "bdry_covered_pct": covered_bdry / tot_bdry * 100}


_GROUP_LABELS = {
    "right_pace": "right-arm pace", "left_pace": "left-arm pace", "pace": "pace",
    "off_spin": "off spin", "leg_spin": "leg spin", "left_orthodox": "left-arm orthodox",
    "left_unorthodox": "left-arm wrist spin", "spin": "spin", "all": "all bowling",
}


def _group_label(g):
    return _GROUP_LABELS.get(g, g)


def _sector_phrase(s):
    return {"third man": "to third man", "point": "square on the off",
            "cover": "through cover", "mid-off": "down the ground on the off",
            "straight": "straight down the ground", "mid-on": "down the ground on the leg",
            "midwicket": "through midwicket", "square leg": "square on the leg",
            "fine leg": "fine on the leg"}.get(s, f"to {s}")


# ── Field diagram ────────────────────────────────────────────────────────────────
def field_diagram(fieldset, is_lhb, title=""):
    """Circular field map — striker at centre, bowler at top, off side on the left for a
    RHB (mirrored for LHB). Catchers filled accent, run-savers hollow. Returns a go.Figure."""
    import math
    import plotly.graph_objects as go
    from ludis_cricket.theme import (BG_PANEL, BG_PITCH, ACCENT, DANGER, TEXT_PRI, TEXT_SEC)

    R = 1.0
    fig = go.Figure()
    # boundary + 30-yard ring
    th = [i / 120 * 2 * math.pi for i in range(121)]
    fig.add_trace(go.Scatter(x=[R * math.cos(t) for t in th], y=[R * math.sin(t) for t in th],
                             mode="lines", line=dict(color="#2e7d32", width=2), fill="toself",
                             fillcolor=BG_PITCH, hoverinfo="skip", showlegend=False))
    ring = 0.62
    fig.add_trace(go.Scatter(x=[ring * math.cos(t) for t in th], y=[ring * math.sin(t) for t in th],
                             mode="lines", line=dict(color="#2e7d32", width=1, dash="dot"),
                             hoverinfo="skip", showlegend=False))
    # pitch (striker at centre, bowler toward top)
    fig.add_shape(type="rect", x0=-0.05, x1=0.05, y0=-0.08, y1=0.34,
                  fillcolor="#c8a25a", line=dict(color="#a07d3a", width=1), opacity=0.55)

    mirror = -1 if not is_lhb else 1     # RHB off side to the left
    for f in fieldset:
        ang = math.radians(f["angle"])
        x = mirror * f["radius"] * math.sin(ang)
        y = f["radius"] * math.cos(ang)
        is_catch = f["kind"] == "catch"
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers",
            marker=dict(size=15 if is_catch else 13,
                        color=(DANGER if is_catch else BG_PANEL),
                        line=dict(color=(DANGER if is_catch else ACCENT), width=2),
                        symbol="circle"),
            hovertext=f"{f['position']} — {f['why']}", hoverinfo="text", showlegend=False))
        # label just outside the marker, pushed toward the boundary
        lx = mirror * min(f["radius"] + 0.12, 1.05) * math.sin(ang)
        ly = min(f["radius"] + 0.12, 1.05) * math.cos(ang)
        fig.add_annotation(x=lx, y=ly, text=f["position"], showarrow=False,
                           font=dict(size=8.5, color=TEXT_PRI),
                           bgcolor="rgba(255,255,255,0.6)", borderpad=1)
    # batter/bowler cues
    fig.add_annotation(x=0, y=-0.14, text="▲ striker", showarrow=False,
                       font=dict(size=8, color=TEXT_SEC))
    fig.add_annotation(x=0, y=0.40, text="bowler", showarrow=False,
                       font=dict(size=8, color=TEXT_SEC))
    hand = "LHB — off side right" if is_lhb else "RHB — off side left"
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color=TEXT_PRI), x=0.5, xanchor="center"),
        paper_bgcolor=BG_PANEL, plot_bgcolor=BG_PANEL,
        margin=dict(l=6, r=6, t=28 if title else 6, b=16), showlegend=False,
        xaxis=dict(visible=False, range=[-1.15, 1.15], scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, range=[-1.15, 1.15]),
        annotations=list(fig.layout.annotations) + [dict(
            x=0, y=-1.12, text=hand, showarrow=False, font=dict(size=8, color=TEXT_SEC))])
    return fig
