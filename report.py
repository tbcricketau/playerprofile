"""
report.py — render a one-bowler scouting PDF from build_profile().

`render_report(bowler_id, hand, out_dir)` computes the profile, exports the
Plotly charts to embedded PNGs, fills an Opta-themed HTML template and prints it
to PDF with headless Chromium (Playwright).  Batch driver: build_reports.py.
"""
import base64
import datetime
import glob
import os
import re
import shutil
import subprocess
import tempfile

import math
import statistics
from collections import Counter

from jinja2 import Template

from version import REPORT_VERSION
from profile import build_profile, fmt as _fmt
from photos import get_photo_data_uri
from report_style import REPORT_CSS, headline_cards
from cricket_core.charts import (
    pitch_scatter_map, pitch_heatmap, beehive, wagon_wheel_zones, release_map,
    fingerprint_strip, speed_violin, innings_violin, day_violin, zone_concentration,
    LENGTH_ZONES_1M, LENGTH_ZONES_05M,
)
from cricket_core.video import first_example as _first_example, get_fairplay_sas as _get_fairplay_sas

# ── Opta light theme (mirrors theme.py / CLAUDE.md) ─────────────────────────────
BG_PAGE, BG_PANEL = "#F5F7FA", "#FFFFFF"
TEXT_PRI, TEXT_SEC = "#1a1a2e", "#6b7280"
ACCENT, DANGER = "#003087", "#b91c1c"
BORDER = "rgba(0,0,0,0.10)"

_HAND_LABEL = {"All": "All batters", "vs LHB": "vs left-handers", "vs RHB": "vs right-handers"}
_BATTER_DESC = {"vs LHB": "left-hand batters", "vs RHB": "right-hand batters", "All": "the batter"}

# Natural cricket phrasing for a (length-zone, line-zone) pair — replaces the
# terse "Full / Stumps" slash notation with commentary-style language.
_LEN_PHRASE = {
    "Yorker/Full": "full", "Full": "full", "Good Length": "a good length",
    "Back of Length": "back of a length", "Short": "short",
}
_LINE_PHRASE = {
    "Wide of 6th": "wide outside off", "6th stump": "on the 6th stump",
    "5th stump": "on the 5th stump", "4th stump": "in the 4th-stump channel",
    "Stumps": "on the stumps", "Down leg": "down the leg side",
}


def _ball_phrase(length: str | None, line: str | None) -> str:
    """e.g. ('Good Length', '4th stump') -> 'a good length in the 4th-stump channel'."""
    lp = _LEN_PHRASE.get(length, (length or "").lower()) if length else ""
    lnp = _LINE_PHRASE.get(line, (f"on a {line.lower()} line" if line else "")) if line else ""
    return f"{lp} {lnp}".strip()


def _cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s

# Country codes for a clean text badge (Windows Chromium has no colour flag glyphs).
_COUNTRY_CODE = {
    "australia": "AUS", "england": "ENG", "india": "IND", "new zealand": "NZL",
    "south africa": "RSA", "pakistan": "PAK", "sri lanka": "SL", "west indies": "WI",
    "bangladesh": "BAN", "zimbabwe": "ZIM", "afghanistan": "AFG", "ireland": "IRE",
    "scotland": "SCO", "netherlands": "NED", "namibia": "NAM", "nepal": "NEP",
    "oman": "OMA", "papua new guinea": "PNG", "kenya": "KEN", "canada": "CAN", "usa": "USA",
}


def _country_code(team: str) -> str:
    key = re.sub(r"\s+(m|w|men|women)$", "", team or "", flags=re.IGNORECASE).strip().lower()
    return _COUNTRY_CODE.get(key, "")


def _fig_uri(fig, w=680, h=430) -> str:
    """Plotly figure -> base64 PNG data URI (via kaleido)."""
    png = fig.to_image(format="png", width=w, height=h, scale=2)
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _pct(v, dp=0):
    return _fmt(v, f".{dp}f", "%")


def _zone_angle(P: dict, line_label: str | None = None, length_label: str | None = None) -> str:
    """Over/round the wicket split for the wicket balls in a given pitching zone.
    Returns a short phrase like 'round the wicket' / 'mostly over the wicket (65%)'
    or '' when the sample is too thin to state."""
    lz, ez = P["line_zones"], P["length_zones"]

    def _in(r):
        if line_label is not None:
            x = r.get("pitch_line_m")
            if x is None or next((lbl for a, b, lbl in lz if a <= x < b), None) != line_label:
                return False
        if length_label is not None:
            y = r.get("pitch_length_m")
            if y is None or next((lbl for a, b, lbl in ez if a <= y < b), None) != length_label:
                return False
        return True

    sub = [r for r in P["df"] if r.get("is_wicket") and _in(r)]
    over = sum(1 for r in sub if r.get("is_round") is False)
    rnd = sum(1 for r in sub if r.get("is_round") is True)
    tot = over + rnd
    if tot < 8:
        return ""
    if over / tot >= 0.85:
        return "over the wicket"
    if rnd / tot >= 0.85:
        return "round the wicket"
    dom = "over" if over >= rnd else "round"
    return f"mostly {dom} the wicket ({max(over, rnd) / tot * 100:.0f}%)"


def _narrative(P: dict) -> dict:
    """Auto-generated prose answering the three scouting questions."""
    is_spin = P["is_spin"]
    themes, threats, expose = [], [], []

    # Common themes
    spd = f"{_fmt(P['avg_spd'])} kph (up to {_fmt(P['max_spd_99'])})" if P["avg_spd"] else "pace not tracked"
    themes.append(f"{P['primary_type']}, averaging {spd}.")
    nb = P.get("new_ball_share")                       # % of innings they open the bowling (Tests)
    if not is_spin and nb is not None and nb >= 25:
        themes.append(f"{'Usually' if nb >= 45 else 'Often'} takes the new ball "
                      f"(opens in {_pct(nb)} of innings).")
    if P["common_len_band"]:
        themes.append(f"Typical length is <b>{P['common_len_band']}</b> (their good length); "
                      f"median {_fmt(P['avg_len_m'], '.1f')} m.")
    if P.get("ball_types") and P["ball_types"]["stock"]:
        s = P["ball_types"]["stock"]
        themes.append(f"Stock ball is <b>{_ball_type_desc(s, is_spin, hand=P['filters']['hand'])}</b> "
                      f"({_pct(s['pct'])} of deliveries).")
    elif P["stock"]:
        themes.append(f"Stock ball is <b>{_ball_phrase(P['stock']['length'], P['stock']['line'])}</b> "
                      f"({_pct(P['stock']['share'] * 100)} of deliveries).")
    if P["round_pct"] is not None:
        hw = _hand_word(P)
        rl, rr = P.get("round_lhb"), P.get("round_rhb")
        if hw:   # per-hand report — name the hand this view is for
            themes.append(f"Goes round the wicket {_pct(P['round_pct'])} of the time against {hw}.")
        elif rl is not None and rr is not None:   # combined — give the per-hand split (it's what matters)
            themes.append(f"Round the wicket to LHB {_pct(rl)} · over the wicket to RHB "
                          f"(round {_pct(rr)}).")
        else:
            themes.append(f"Goes round the wicket {_pct(P['round_pct'])} of the time.")
    orr = P.get("over_round")
    if orr and orr["show"]:
        o, r = orr["over"], orr["round"]
        seg = []
        if o["modal_zone"] and r["modal_zone"] and o["modal_zone"] != r["modal_zone"]:
            seg.append(f"shifts his pitching line from {o['modal_zone'].lower()} to {r['modal_zone'].lower()}")
        ld = orr["len_delta"]
        if ld is not None and abs(ld) >= 0.3 and r["med_len"] is not None:
            seg.append(f"brings his length back to {r['med_len']:.1f} m" if ld > 0
                       else f"pitches fuller, up to {r['med_len']:.1f} m")
        if seg:
            themes.append(f"<b>Round the wicket</b> he {' and '.join(seg)}.")
    if is_spin and P["avg_turn"] is not None:
        themes.append(f"Turns it {_fmt(P['avg_turn'])}° on average; {_pct(P['big_turn_pct'])} of balls turn ≥5°.")
    # sequencing — a condensed line (full detail in the Sequencing section)
    sq = P.get("sequencing")
    if sq and sq.get("length_sd") is not None:
        sd = sq["length_sd"]
        if is_spin:
            rep = ("repeats his length ball after ball" if sd < 1.05
                   else "mixes his flight and length" if sd > 1.45 else "holds a fairly consistent length")
        else:
            rep = ("hammers a repeatable length" if sd < 1.85
                   else "varies his length a lot" if sd > 2.25 else "holds a fairly consistent length")
        os_ = [o for o in sq["over_shape"] if o["med_len"] is not None]
        early, late = [o for o in os_ if o["pos"] <= 2], [o for o in os_ if o["pos"] >= 5]
        trend = ""
        if early and late:
            es = statistics.mean(o["short_pct"] for o in early)
            ls = statistics.mean(o["short_pct"] for o in late)
            if ls - es >= 3:
                trend = ", banging it in more as the over goes on"
            elif es - ls >= 3:
                trend = ", starting shorter then pitching up through the over"
        themes.append(f"Across an over he <b>{rep}</b>{trend}.")

    # Biggest threats
    if P["danger_length"]:
        d = P["danger_length"]
        threats.append(f"Most dangerous length is <b>{d['length']}</b> "
                       f"({d['wickets']} wkts, {_fmt(d['adj_rate'])}% adjusted strike).")
    if P["danger_line"]:
        dl = P["danger_line"]
        ang = _zone_angle(P, line_label=dl["line"])
        atag = f" ({ang})" if ang else ""
        threats.append(f"Danger pitching line: <b>{dl['line']}</b>{atag}.")
    if P["wkt_zone"]:
        w = P["wkt_zone"]
        ang = _zone_angle(P, line_label=w["line"], length_label=w["length"])
        atag = f", {ang}" if ang else ""
        threats.append(f"Takes {_pct(w['share'] * 100)} of wickets pitching "
                       f"<b>{_ball_phrase(w['length'], w['line'])}</b>{atag}.")
    if P["beaten_pct"] is not None:
        threats.append(f"Beats the bat {_pct(P['beaten_pct'], 1)} of tracked balls "
                       f"(false-shot {_pct(P['false_pct'], 1)}).")
    td = P.get("threat_dismissal")
    if td:
        # lead with the SIGNATURE (over-indexed) type, not the caught-for-everyone raw mode; when
        # there's no standout, state the dominant type REFINED (caught behind / in the field, not "caught")
        if td.get("signature"):
            threats.append(f"Gets you <b>{td['label']}</b> more than most — {_pct(td['share'])} of "
                           f"his wickets ({td['index']:.1f}× the typical rate for this type).")
        else:
            threats.append(f"Wickets come mostly <b>{td['label']}</b> ({_pct(td['share'])}).")
    if P["n_caught"]:
        cb = P["caught_behind"] / P["n_caught"] * 100
        tops = ", ".join(k.lower() for k, _ in P["catch_pos_counts"].most_common(3))
        line = f"{_pct(cb)} of catches are behind the wicket (keeper / slips / gully)"
        threats.append(line + (f"; most often to {tops}." if tops else "."))

    # Areas to exploit
    if P["run_zone"]:
        r = P["run_zone"]
        expose.append(f"Concedes most runs pitching <b>{_ball_phrase(r['length'], r['line'])}</b> "
                      f"({_pct(r['share'] * 100)} of runs).")
    if P["is_pace"] and P["sb_n"]:
        expose.append(f"Short ball: {_pct(P['short_pct'])} of deliveries, "
                      f"economy {_fmt(P['sb_econ'])} — {P['sb_wkts']} wkts from {P['sb_n']} short balls.")
    if P["danger_length"]:
        expose.append(f"Away from {P['danger_length']['length'].lower()}, the wicket threat drops off — "
                      f"look to score in the less-productive lengths.")

    # Fold the counter-strategy ("How to Play Him") into the three boxes: what to score off →
    # Areas to Exploit; his set-ups/traps → Biggest Threats. (Respect items duplicate the danger
    # threats already listed, so they're not repeated.)
    htp = P.get("how_to_play") or {}
    for line in htp.get("attack", []):
        if "short ball" in line.lower() and any("short ball" in e.lower() for e in expose):
            continue
        expose.append(line)
    for line in htp.get("watch", []):
        threats.append(line)
    return {"themes": themes, "threats": threats, "expose": expose}


def _figures(P: dict) -> dict:
    df, bdf = P["df"], P["beaten_df"]
    lz = P["line_zones"]
    # Pitch maps use finer length bands than the broad named zones — metre bands
    # for pace, half-metre for spin — so the map actually reads like a pitch.
    fine_ez = LENGTH_ZONES_05M if P["is_spin"] else LENGTH_ZONES_1M
    is_lhb = P["filters"]["hand"] == "vs LHB"
    p05, p95 = P["speed_p05"], P["speed_p95"]
    # Portrait, but a touch wider now the line splits into 6 stump columns —
    # otherwise the 4th/5th/6th channels are unreadable.
    pw, ph = 440, (660 if P["is_spin"] else 540)

    figs = {
        "pitch_count": _fig_uri(pitch_heatmap(df, value="count", title="", flip_x=is_lhb), w=pw, h=ph),
        "pitch_wkts":  _fig_uri(pitch_heatmap(df, value="wickets", title="", flip_x=is_lhb), w=pw, h=ph),
        "beehive":     _fig_uri(beehive(df, metric="wickets", title="", line_zones=lz, flip_x=is_lhb), w=380, h=400),
        "wagon":       _fig_uri(wagon_wheel_zones(df, metric="runs", title="", n_sectors=8, is_lhb=is_lhb), w=500, h=430),
        "violin_spell": _fig_uri(speed_violin(df, speed_min=p05, speed_max=p95, title=""), w=560, h=400),
        "violin_inns":  _fig_uri(innings_violin(df, speed_min=p05, speed_max=p95, title=""), w=560, h=400),
        "violin_day":   _fig_uri(day_violin(df, speed_min=p05, speed_max=p95, title=""), w=560, h=400),
    }
    if bdf:
        # Shared length scale so the grid and heatmap align (a horizontal line at 6m matches on
        # both). Cap just past his deepest beaten balls (p98) to drop the empty long-length rows.
        _bl = sorted(r["pitch_length_m"] for r in bdf
                     if r.get("pitch_length_m") is not None and -1.0 <= r["pitch_length_m"] <= 15.0)
        _bmax = max(9.0, min(13.5, _bl[int(len(_bl) * 0.98)] + 1.0)) if _bl else 12.0
        beaten_yrange = (_bmax, -0.6)
        # pass the raster size: the figure sizes its text from the pixels it will occupy
        figs["beaten"] = _fig_uri(pitch_scatter_map(bdf, lz, fine_ez, value="count", title="",
                                  min_balls=1, flip_x=is_lhb, y_range=beaten_yrange,
                                  width=pw, height=ph), w=pw, h=ph)
        figs["beaten_heat"] = _fig_uri(pitch_heatmap(bdf, value="count", title="",
                                       flip_x=is_lhb, y_range=beaten_yrange), w=pw, h=ph)
    orr = P.get("over_round")
    if orr:
        # Always render both maps (even a near-empty one) so the two-column layout stays
        # consistent — the sparse/empty side just shows the pitch backdrop.
        over_df = [r for r in df if r.get("is_round") is False]
        rnd_df  = [r for r in df if r.get("is_round") is True]
        figs["over_map"]  = _fig_uri(pitch_heatmap(over_df, value="count", title="", flip_x=is_lhb), w=pw, h=ph)
        figs["round_map"] = _fig_uri(pitch_heatmap(rnd_df,  value="count", title="", flip_x=is_lhb), w=pw, h=ph)
    # release-point cloud (behind the bowler) — career, all deliveries with release data
    if P.get("crease"):
        legal_raw = [r for r in P["raw"] if r.get("is_legal")]
        try:
            hp = float((P.get("crease_ref") or {}).get("height_pctl"))
        except (TypeError, ValueError):
            hp = None
        figs["release_map"] = _fig_uri(release_map(legal_raw, title="", height_pctl=hp), w=520, h=470)
    return figs


def _recent_card_vals(P: dict) -> dict:
    """Last-3-year values for the headline cards, from a recency-filtered re-profile (same 300-ball
    floor as the fingerprint overlay — a thin window isn't a real change). {card-label: value str}."""
    import datetime as _dt
    cut = (_dt.date.today() - _dt.timedelta(days=int(365.25 * 3))).isoformat()
    rec = [r for r in P.get("raw", []) if (r.get("match_date") or "") >= cut]
    if sum(1 for r in rec if r.get("is_legal")) < 300:
        return {}
    Pr = build_profile(P["bowler_id"], hand=P["filters"]["hand"], raw=rec)
    out = {}
    if Pr.get("economy") is not None:
        out["Economy"] = _fmt(Pr["economy"])
    # avg / SR always shown when the window qualifies — "—" when there are no recent wickets, so the
    # 3-yr line is present and honest rather than blank (a blank reads as a bug).
    nw_rec = Pr.get("n_wkts") or 0
    out["Bowling Avg"] = _fmt(Pr.get("bowl_avg")) if nw_rec else "— (no wkts)"
    out["Bowl strike rate"] = _fmt(Pr.get("strike_rate")) if nw_rec else "— (no wkts)"
    if Pr.get("avg_spd") is not None:
        out["Avg speed"] = f"{_fmt(Pr['avg_spd'])} kph"
    if Pr.get("avg_len_m") is not None:
        out["Avg length"] = f"{_fmt(Pr['avg_len_m'], '.2f')} m"
    if Pr.get("round_pct") is not None:
        out["Round the wkt"] = _pct(Pr["round_pct"])
    return out


def _cards(P: dict) -> list:
    """Headline metric cards (career value + last-3-yr under each). Canonical builder lives in
    report_style so the Test / ODI / T20 reports share one identical top-card row."""
    return headline_cards(P, P.get("_recent_cards") or {})


def _threat_cards(P: dict) -> list:
    cards = [
        ("Beaten %", _pct(P["beaten_pct"], 1), f"n={P['n_tracked']:,}"),
        ("False-shot %", _pct(P["false_pct"], 1), "beaten + edges"),
    ]
    if P["is_spin"]:
        cards.append(("Avg turn", _fmt(P["avg_turn"], ".1f", "°"), f"{_pct(P['big_turn_pct'])} ≥5°"))
        cards.append(("Avg drift", _fmt(P["avg_drift"], ".1f", "°"), "in-air"))
    else:
        m = P.get("movement") or {}
        if m.get("avg_seam") is not None:
            cards.append(("Avg seam", _fmt(m["avg_seam"], ".2f", "°"),
                          _pctl_word(m.get("seam_pctl")) or "off pitch"))
        if m.get("avg_swing") is not None:
            cards.append(("Avg swing", _fmt(m["avg_swing"], ".2f", "°"), "in-air"))
    return cards


def _dismissal_rows(P: dict) -> list:
    """Normalised dismissal mix: (type, his %, base %, index text, colour). Caught
    dominates for everyone, so we index each type against the peer base rate and
    highlight where he over-indexes (his genuine wicket-taking signature)."""
    di = P.get("dismissal_index") or []
    rows = []
    for d in di:
        if d["count"] < 2:          # drop one-off freak modes (e.g. a single hit-wicket)
            continue
        idx = d["index"]
        if idx is None:
            idx_txt, colour = "—", TEXT_SEC
        else:
            idx_txt = f"{idx:.2f}×"
            colour = (DANGER if idx >= 1.15 else "#9aa3b2" if idx <= 0.85 else TEXT_PRI)
        rows.append((
            d["type"], f"{d['share']:.0f}%",
            f"{d['base_share']:.0f}%" if d["base_share"] is not None else "—",
            idx_txt, colour,
        ))
    return rows


def _dismissal_peer_label(P: dict) -> str:
    kind = "pace" if P.get("is_pace") else ("spin" if P.get("is_spin") else "")
    hand = {"vs LHB": " to LHB", "vs RHB": " to RHB"}.get(P["filters"]["hand"], "")
    return f"vs the average {kind} bowler{hand}".strip()


def _danger_cards(P: dict) -> list:
    """(header, big, sub, is_danger) tuples for the danger grid."""
    out = []
    if P["wkt_zone"]:
        w = P["wkt_zone"]
        out.append(("Wickets — where most come from", _cap(_ball_phrase(w['length'], w['line'])),
                    f"{_pct(w['share'] * 100)} of mapped wickets ({int(w['value'])} of {int(w['total'])})", True))
    if P["run_zone"]:
        r = P["run_zone"]
        out.append(("Runs — where most conceded", _cap(_ball_phrase(r['length'], r['line'])),
                    f"{_pct(r['share'] * 100)} of runs ({int(r['value'])} of {int(r['total'])})", False))

    def _rate(d):
        tag = " · low sample" if d.get("low_conf") else ""
        return f"{d['wickets']} wkts / {d['balls']:,} balls · {_fmt(d['adj_rate'])}% adj ({_fmt(d['rate'])}% raw){tag}"

    if P["danger_line"]:
        out.append(("Danger line", P["danger_line"]["line"], _rate(P["danger_line"]), True))
    if P["danger_length"]:
        out.append(("Danger length", P["danger_length"]["length"], _rate(P["danger_length"]), True))
    if P["danger_cell"]:
        d = P["danger_cell"]
        out.append(("Most lethal zone (by rate)", f"{d['length']} / {d['line']}", _rate(d), True))
    return out


def _ord(n) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _pctl_word(p) -> str:
    if p is None:
        return ""
    if p >= 80: return "well above avg"
    if p >= 60: return "above avg"
    if p >= 40: return "about average"
    if p >= 20: return "below avg"
    return "well below avg"


def _movement_rows(P: dict) -> list:
    """(label, avg, percentile-text, direction-text) rows for the Movement table."""
    m = P.get("movement")
    if not m:
        return []
    is_spin = P["is_spin"]

    def _dir(d):
        return f"{d['out_pct']:.0f}% away / {d['in_pct']:.0f}% in" if d else "—"

    rows = []
    if m["swing_pctl"] is not None:
        rows.append(("Drift" if is_spin else "Swing", _fmt(m["avg_swing"], ".2f", "°"),
                     f"{_ord(m['swing_pctl'])} pct ({_pctl_word(m['swing_pctl'])})", _dir(m["swing_dir"])))
    if m["seam_pctl"] is not None:
        rows.append(("Turn" if is_spin else "Seam", _fmt(m["avg_seam"], ".2f", "°"),
                     f"{_ord(m['seam_pctl'])} pct ({_pctl_word(m['seam_pctl'])})", _dir(m["seam_dir"])))
    if m["bounce_pctl"] is not None:
        rows.append(("Bounce", _fmt(m["avg_bounce"], ".1f", "°"),
                     f"{_ord(m['bounce_pctl'])} pct ({_pctl_word(m['bounce_pctl'])})", "—"))
    return rows


def _modal_zone(rows, zones, col):
    c = Counter()
    for r in rows:
        x = r.get(col)
        if x is None:
            continue
        z = next((lbl for a, b, lbl in zones if a <= x < b), None)
        if z:
            c[z] += 1
    return c.most_common(1)[0][0] if c else None


def _off_leg_runs(rows):
    off = leg = 0.0
    for r in rows:
        runs = r.get("bat_score_n") or 0
        if not runs:
            continue
        hx = r.get("hit_x_n")
        if hx is None:   # same fallback the wagon uses: polar hit_len × angle
            hl, ha = r.get("hit_len_n"), r.get("hit_ang_n")
            hx = hl * math.sin(math.radians(ha)) if (hl is not None and ha is not None) else None
        if hx is None:
            continue
        if (hx > 0) != r["is_lhb"]:   # batter-relative off side (hit_x is absolute)
            off += runs
        else:
            leg += runs
    tot = off + leg
    return (off / tot * 100, leg / tot * 100) if tot else (None, None)


def _chart_reads(P: dict) -> dict:
    """One interpretive sentence per visual (what the data *says*, not what it is)."""
    lz, df = P["line_zones"], P["df"]
    wk = [r for r in df if r["is_wicket"]]
    st, wz, rz, dl = P["stock"], P["wkt_zone"], P["run_zone"], P["danger_line"]
    I = {}
    if st:
        sh = P["short_pct"]
        tail = "drops short often" if sh >= 28 else ("mixes in the short ball" if sh >= 15 else "rarely drops short")
        I["pitch_count"] = f"Pitches it {_ball_phrase(st['length'], st['line'])} most often ({int(st['share'] * 100)}%); {tail} ({int(sh)}%)."
    if wz:
        extra = f", but strikes most often pitching {_LINE_PHRASE.get(dl['line'], dl['line'].lower())}" if dl else ""
        I["pitch_wkts"] = f"Wickets come mostly from balls pitched {_ball_phrase(wz['length'], wz['line'])}{extra}."
    asz, pz = _modal_zone(wk, lz, "at_stumps_line_m"), _modal_zone(wk, lz, "pitch_line_m")
    if asz:
        nb = f" — pitches around {pz.lower()} and moves it back" if (pz and pz != asz) else ""
        I["beehive"] = f"Wicket balls pass the stumps mostly at {asz.lower()}{nb}."
    off, leg = _off_leg_runs(df)
    if off is not None:
        I["wagon"] = f"Runs come mostly on the {'off' if off >= leg else 'leg'} side ({int(max(off, leg))}%)."
    return I


def _danger_read(P: dict) -> str:
    dl, dlen, wz, rz = P["danger_line"], P["danger_length"], P["wkt_zone"], P["run_zone"]
    out = []
    if dlen and dl:
        out.append(f"Most threatening pitching {_ball_phrase(dlen['length'], dl['line'])} "
                   f"({dlen['wickets']} wkts, {dlen['adj_rate']:.1f}% strike).")
    if wz and rz:
        out.append(f"Most wickets come from {_ball_phrase(wz['length'], wz['line'])}, "
                   f"while he leaks the most runs {_ball_phrase(rz['length'], rz['line'])}.")
    return " ".join(out)


def _speed_read(P: dict) -> str:
    """Pace trend across all three axes the charts show — spell, innings and match day."""
    unit = "km/h"
    s1, s3, i1, i2 = P["spd_spell1"], P["spd_spell3p"], P["spd_inn1"], P["spd_inn2"]
    out = []
    # spell
    if s1 and s3:
        d = s1 - s3
        out.append("holds his pace across spells" if abs(d) < 1.5
                   else (f"drops ~{abs(d):.1f} {unit} from his opening spell to later spells" if d > 0
                         else f"is ~{abs(d):.1f} {unit} quicker in later spells"))
    # innings
    if i1 and i2:
        di = i1 - i2
        out.append("is a touch slower in the 2nd innings" if di > 0.7
                   else ("is quicker in the 2nd innings" if di < -0.7 else "keeps his pace into the 2nd innings"))
    # match day — day 1 vs the later days (fatigue across a Test)
    def _mean(vs):
        return sum(vs) / len(vs) if vs else None
    day_speeds = {}
    for r in P.get("df", []):
        d = r.get("match_day_n")
        if r.get("is_legal") and r.get("ball_speed_n") is not None and d:
            day_speeds.setdefault(min(int(d), 5), []).append(r["ball_speed_n"])
    d1 = _mean(day_speeds.get(1))
    late = [v for k in (4, 5) for v in day_speeds.get(k, [])]
    dl = _mean(late)
    if d1 and dl and len(late) >= 30:
        dd = d1 - dl
        out.append("and is as quick on the final day as day one" if abs(dd) < 1.5
                   else (f"and loses ~{abs(dd):.1f} {unit} by the later days" if dd > 0
                         else f"and is ~{abs(dd):.1f} {unit} quicker later in the match"))
    if not out:
        return ""
    sentence = "He " + ", ".join(out)
    return sentence + "."


def _movement_read(P: dict) -> str:
    m = P.get("movement")
    if not m:
        return ""
    is_spin = P["is_spin"]
    gens = []
    if m["seam_pctl"] is not None:
        gens.append(f"{_pctl_word(m['seam_pctl'])} {'turn' if is_spin else 'seam'}")
    if m["swing_pctl"] is not None:
        gens.append(f"{_pctl_word(m['swing_pctl'])} {'drift' if is_spin else 'swing'}")
    if not gens:
        return ""
    read = f"Generates {' and '.join(gens)} for a {m['pace_spin']} bowler"
    sd = m["seam_dir"]
    if sd:
        who = _BATTER_DESC.get(P["filters"]["hand"], "the batter")
        read += f"; {'turns' if is_spin else 'seams'} it {'away' if sd['out_pct'] >= sd['in_pct'] else 'in'} more to {who} ({int(max(sd['out_pct'], sd['in_pct']))}%)"
    return read + "."


def _swing_verdict(m: dict) -> dict | None:
    """Is this bowler's swing phase-dependent? From movement['swing_age'] (new vs old
    ball). Returns a dict only when the dominant swing DIRECTION flips between the new and
    old ball (each phase >=55% one way, and they differ) — the exact case that a flat
    'both ways' label hides (e.g. new-ball out-swing that reverses in). Else None."""
    sa = (m or {}).get("swing_age") or {}
    def dom(x):
        if not x or x["n"] < 20:
            return None, None
        if x["out_pct"] >= 55:
            return "away", x["out_pct"]
        if x["in_pct"] >= 55:
            return "in", x["in_pct"]
        return None, None
    nd, npc = dom(sa.get("new"))
    od, opc = dom(sa.get("old"))
    if nd and od and nd != od:
        return {"new": nd, "old": od, "new_pct": npc, "old_pct": opc,
                "new_n": sa["new"]["n"], "old_n": sa["old"]["n"]}
    return None


def _swing_shape_phrase(v: dict) -> str:
    """Sentence phrase for a phase-dependent swinger (archetype read)."""
    if v["new"] == "away" and v["old"] == "in":
        return (f"swings it away with the new ball ({v['new_pct']:.0f}%) and reverses it "
                f"back in when it's old ({v['old_pct']:.0f}%)")
    if v["new"] == "in" and v["old"] == "away":
        return (f"swings it in with the new ball ({v['new_pct']:.0f}%) and away once it's "
                f"old ({v['old_pct']:.0f}%)")
    return f"swings it {v['new']} with the new ball and {v['old']} when it's old"


def _swing_cell_word(v: dict) -> str:
    """Compact swing-direction word for a ball-type table cell (phase-dependent case)."""
    if v["new"] == "away" and v["old"] == "in":
        return "away, reverses in"
    if v["new"] == "in" and v["old"] == "away":
        return "in, reverses away"
    return f"{v['new']} new / {v['old']} old"


def _swing_age_read(P: dict) -> str:
    """One-line swing-by-ball-age readout (shown when both phases have a usable sample)."""
    m = P.get("movement") or {}
    if P.get("is_spin") or not (m.get("avg_swing") and m["avg_swing"] >= 0.4):
        return ""   # only for bowlers who actually swing it (else a seamer gets a noisy line)
    sa = m.get("swing_age") or {}
    new, old = sa.get("new"), sa.get("old")
    if not (new and old and new["n"] >= 20 and old["n"] >= 20):
        return ""
    who = _BATTER_DESC.get(P["filters"]["hand"], "the batter")
    def part(d):
        return f"{d['out_pct']:.0f}% away / {d['in_pct']:.0f}% in"
    read = (f"Swing by ball age to {who}: new ball (≤25 ov, n={new['n']}) {part(new)}; "
            f"old ball (≥40 ov, n={old['n']}) {part(old)}")
    if _swing_verdict(m):
        read += " — the swing direction reverses with the old ball"
    return read + "."


def _pace_style(m: dict) -> str:
    """Archetype read for a seam/pace bowler: hit-the-deck seamer vs swing bowler,
    two-way movement vs one-directional."""
    seam_p, swing_p, bounce_p = m["seam_pctl"], m["swing_pctl"], m["bounce_pctl"]
    sd, wd = m["seam_dir"], m["swing_dir"]

    def hi(p, t=60): return p is not None and p >= t
    def lo(p): return p is not None and p <= 30

    def _dir_phrase(d, verb_out, verb_in):
        """(kind, phrase) — 'both' two-way, 'one' one-directional, 'mostly' skewed."""
        if not d:
            return None, None
        out, inn = d["out_pct"], d["in_pct"]
        dom, dom_pct = (verb_out, out) if out >= inn else (verb_in, inn)
        if min(out, inn) >= 35:
            return "both", f"moves it both ways ({out:.0f}% away / {inn:.0f}% in)"
        if dom_pct >= 80:
            return "one", f"almost exclusively {dom} ({dom_pct:.0f}%)"
        return "mostly", f"predominantly {dom} ({dom_pct:.0f}%)"

    # Hit-the-deck is defined by BOUNCE off a hard length (not necessarily big seam) —
    # unless swing is their standout weapon, in which case that leads.
    deck = bounce_p is not None and bounce_p >= 65 and not hi(swing_p)

    parts = []
    if deck:
        base = "a hit-the-deck bowler who bangs it into a hard length for steep bounce"
        if hi(seam_p, 55):
            base += " and seams it around"
        parts.append(base)
    elif hi(swing_p) and swing_p >= (seam_p or 0):
        v = _swing_verdict(m)
        if v:                                    # direction flips new ball -> old ball
            parts.append(f"a swing bowler who {_swing_shape_phrase(v)}")
        else:
            _, ph = _dir_phrase(wd, "outswing", "inswing")
            parts.append(f"a swing bowler who {ph}" if ph else "a genuine swing bowler")
    elif hi(seam_p):
        _, ph = _dir_phrase(sd, "leaves the bat off the seam", "nips it back off the seam")
        parts.append(f"a seam bowler who {ph}" if ph else "a seam bowler")
    elif lo(swing_p) and lo(seam_p):
        parts.append("built on pace and accuracy more than lateral movement")
    else:
        parts.append("a moderate mover of the ball")

    if not deck:
        if hi(bounce_p):
            parts.append("gets extra bounce")
        elif lo(bounce_p):
            parts.append("skids through at a lower trajectory")
    return "; ".join(parts)


def _spin_style(m: dict) -> str:
    """Archetype read for a spinner: big turner vs flight/accuracy, two-way threat, bounce."""
    turn_p, drift_p, bounce_p = m["seam_pctl"], m["swing_pctl"], m["bounce_pctl"]
    td = m["seam_dir"]

    def hi(p): return p is not None and p >= 60
    def lo(p): return p is not None and p <= 30

    tp = m.get("turn_physical")
    parts = []
    if hi(turn_p):
        parts.append("a big turner of the ball")
    elif lo(turn_p):
        parts.append("not a big spinner — relies on flight, drift and accuracy")
    else:
        parts.append("a moderate spinner of the ball")
    # 'two-way threat' only if he genuinely turns it both PHYSICAL ways (a real wrong'un/doosra)
    # — not the batter-relative artefact where a stock off-break reads in-to-RHB / away-from-LHB.
    if tp and min(tp["off_pct"], tp["leg_pct"]) >= 25:
        parts.append(f"turns it both ways ({tp['off_pct']:.0f}% off break / {tp['leg_pct']:.0f}% "
                     "leg break) — a genuine two-way threat")
    if hi(bounce_p):
        parts.append("extracts steep bounce")
    elif lo(bounce_p):
        parts.append("skids it on with lower bounce")
    if hi(drift_p):
        parts.append("gets sharp drift in the air")
    return "; ".join(parts)


def _bowler_style(P: dict) -> str:
    """One-sentence 'what sort of bowler is this' summary for the Movement box."""
    m = P.get("movement")
    if not m:
        return ""
    s = _spin_style(m) if P["is_spin"] else _pace_style(m)
    if not s:
        return ""
    return s[0].upper() + s[1:] + "."


def _scoring_stats(P: dict) -> list:
    """(label, value, sub) stat pills for the Scoring Profile header."""
    s = P.get("scoring")
    if not s:
        return []
    d = s["dir_pct"] or {}
    out = [
        ("Boundary %", f"{s['bdry_pct']:.0f}%", "runs in 4s/6s"),
        ("Rotated %", f"{s['milked_pct']:.0f}%", "runs in 1s & 2s"),
        ("Balls / boundary", (f"{s['balls_per_bdry']:.0f}" if s["balls_per_bdry"] else "—"), ""),
    ]
    if d:
        out += [
            ("Off side %", f"{d['off']:.0f}%", "of runs"),
            ("Leg side %", f"{d['leg']:.0f}%", "of runs"),
            ("Straight %", f"{d['straight']:.0f}%", "down the ground"),
        ]
    return out


def _scoring_rows(P: dict) -> list:
    """(family, balls, runs, %runs, 4s+6s, runs/ball) rows for the shot-type table."""
    s = P.get("scoring")
    if not s:
        return []
    return [
        (f["name"], f["balls"], f"{f['runs']:.0f}", f"{f['runs_pct']:.0f}%",
         str(f["bdry"]), f"{f['rpb']:.2f}")
        for f in s["families"]
    ]


def _scoring_read(P: dict) -> str:
    """Interpretive read: put away vs milked, where the runs go, which shot hurts most."""
    s = P.get("scoring")
    if not s:
        return ""
    b, bpb = s["bdry_pct"], s["balls_per_bdry"]
    d, fam = s["dir_pct"], s["families"]

    bpb_txt = f" — a boundary every {bpb:.0f} balls" if bpb else ""
    if b >= 45:
        lead = f"{b:.0f}% of his runs come in boundaries{bpb_txt}"
    elif b <= 30:
        lead = (f"Hard to get away — only {b:.0f}% of runs are boundaries{bpb_txt}; "
                "the strike is rotated in ones and twos")
    else:
        lead = f"{b:.0f}% of his runs come in boundaries{bpb_txt}"

    bits = [lead]
    if d:
        top = max(d, key=d.get)
        side = {"off": "the off side", "leg": "the leg side",
                "straight": "straight down the ground"}[top]
        bits.append(f"most runs go to {side} ({d[top]:.0f}%)")

    if fam:
        bthreat = max(fam, key=lambda f: f["bdry"])
        worked = next((f for f in fam if f["name"] == "Work/Nudge"), None)
        if bthreat["bdry"] >= 8 and bthreat["name"] != "Work/Nudge":
            bits.append(f"the {bthreat['name'].lower()} hurts most "
                        f"({bthreat['bdry']} fours/sixes at {bthreat['rpb']:.1f} runs/ball)")
        elif worked and worked["runs_pct"] >= 30:
            bits.append(f"runs come mostly by working him around ({worked['runs_pct']:.0f}% of runs)")

    read = "; ".join(bits) + "."
    return read[0].upper() + read[1:]


def _over_round_rows(P: dict) -> list:
    """(Angle, Balls, Line, Length, Short%, Econ, Wkts, Bdry%) rows — always both angles
    when the section exists, so the table is present even for a lopsided split. An angle
    with no balls shows dashes; the read caveats a small/absent sample."""
    orr = P.get("over_round")
    if not orr:
        return []
    rows = []
    for name, share, n, m in [("Over", orr["over_share"], orr["over_n"], orr["over"]),
                              ("Round", orr["round_share"], orr["round_n"], orr["round"])]:
        if m:
            rows.append((
                name, f"{n} ({share:.0f}%)",
                m["modal_zone"] or "—",
                f"{m['med_len']:.1f} m" if m["med_len"] is not None else "—",
                f"{m['short_pct']:.0f}%" if m["short_pct"] is not None else "—",
                f"{m['econ']:.2f}" if m["econ"] is not None else "—",
                str(m["wkts"]),
                f"{m['bdry_pct']:.0f}%" if m["bdry_pct"] is not None else "—",
            ))
        else:
            rows.append((name, f"{n} ({share:.0f}%)", "—", "—", "—", "—", "0", "—"))
    return rows


def _hand_word(P: dict, plural: bool = True) -> str | None:
    """The batter-hand this view is filtered to, as a noun — or None for 'All batters'."""
    h = (P.get("filters") or {}).get("hand")
    if h == "vs LHB":
        return "left-handers" if plural else "the left-hander"
    if h == "vs RHB":
        return "right-handers" if plural else "the right-hander"
    return None


def _round_by_hand_read(P: dict) -> str:
    """Over/round tendency stated per hand (for the All-batters view, where a single
    aggregate hides that a bowler's angle is usually hand-specific)."""
    def phrase(h, rpct):
        if rpct is None:
            return None
        if rpct >= 70:
            return f"round the wicket to {h} ({rpct:.0f}%)"
        if rpct <= 30:
            return f"over the wicket to {h} ({100 - rpct:.0f}% over)"
        return f"a mix to {h} ({rpct:.0f}% round)"
    parts = [p for p in (phrase("RHB", P.get("round_rhb")), phrase("LHB", P.get("round_lhb"))) if p]
    return "Bowls " + "; ".join(parts) + "." if parts else ""


def _over_round_read(P: dict) -> str:
    """Interpretive read of how line/length/threat shift between over and round. Full
    comparative narrative only when the split is a genuine two-way tactic; otherwise a
    usage note that caveats a small or absent minority sample."""
    orr = P.get("over_round")
    if not orr:
        return ""
    if not orr["show"]:
        # All-batters view: over/round is hand-specific, so describe it per hand.
        hw = _hand_word(P)
        if hw is None:
            byhand = _round_by_hand_read(P)
            if byhand:
                return byhand
        target = f"to {hw}" if hw else "in this view"
        o_n, r_n = orr["over_n"], orr["round_n"]
        o_s, r_s = orr["over_share"], orr["round_share"]
        if o_n >= r_n:
            dom, ds, dn = "over the wicket", o_s, o_n
            minor, ms, mn, enough = "round the wicket", r_s, r_n, orr["round_enough"]
        else:
            dom, ds, dn = "round the wicket", r_s, r_n
            minor, ms, mn, enough = "over the wicket", o_s, o_n, orr["over_enough"]
        if mn == 0:
            return f"Bowls exclusively {dom} {target} ({dn:,} balls) — never goes {minor} in this data."
        tail = (f"{minor} is a rare change-up ({ms:.0f}%, {mn} balls)" if enough
                else f"the {minor} sample ({mn} balls) is too small to read into")
        return f"Almost exclusively {dom} {target} ({ds:.0f}%, {dn:,} balls); {tail}."
    o, r = orr["over"], orr["round"]
    bits = []
    if o["modal_zone"] and r["modal_zone"] and o["modal_zone"] != r["modal_zone"]:
        bits.append(f"round the wicket his pitching line moves from {o['modal_zone'].lower()} "
                    f"to {r['modal_zone'].lower()}")
    elif orr["line_delta"] is not None and abs(orr["line_delta"]) >= 0.08:
        ld = orr["line_delta"]
        bits.append(f"round the wicket his pitching line moves {abs(ld) * 100:.0f} cm "
                    f"{'wider of off' if ld < 0 else 'straighter, into the pads'}")
    else:
        bits.append("his pitching line stays similar over and round the wicket")
    if orr["len_delta"] is not None and abs(orr["len_delta"]) >= 0.3:
        bits.append(f"and pitches {abs(orr['len_delta']) * 100:.0f} cm "
                    f"{'fuller' if orr['len_delta'] < 0 else 'shorter'}")
    thr = []
    if o["econ"] is not None and r["econ"] is not None:
        thr.append(f"economy {o['econ']:.2f}→{r['econ']:.2f}")
    if o["sr"] and r["sr"]:
        thr.append(f"a wicket every {o['sr']:.0f}→{r['sr']:.0f} balls")
    read = "; ".join(bits)
    if thr:
        read += " — " + ", ".join(thr) + " (over→round)"
    return read[0].upper() + read[1:] + "."


def _repeatability_peer(P: dict) -> str:
    """Peer-benchmarked length repeatability, e.g. ' — more repeatable than 62% of pace
    bowlers'.  Empty string when the reference profile is missing/thin."""
    rp = P.get("repeatability")
    if not rp:
        return ""
    try:
        pctl = float(rp.get("length_sd_pctl"))
    except (TypeError, ValueError):
        return ""
    kind = rp.get("pace_spin") or ("spin" if P["is_spin"] else "pace")
    # length_sd_pctl = % of same-type bowlers with SD <= his (low = tighter),
    # so 'more repeatable than' = 100 - pctl.
    return f"; more repeatable than {100 - pctl:.0f}% of {kind} bowlers"


def _sequencing_read(P: dict) -> str:
    """B1 repeatability (style-relative) + B2 how the length changes across an over."""
    sq = P.get("sequencing")
    if not sq:
        return ""
    is_spin = P["is_spin"]
    sd = sq["length_sd"]
    parts = []
    if sd is not None:
        if is_spin:
            rep = ("Relentlessly consistent — repeats his length ball after ball" if sd < 1.05
                   else "Varies his flight and length rather than hammering one spot" if sd > 1.45
                   else "Consistent with his length")
        else:
            rep = ("Metronomic — hammers the same length repeatedly, little to feast on" if sd < 1.85
                   else "Variable with his length" if sd > 2.25
                   else "Moderately consistent with his length")
        peer = _repeatability_peer(P)
        parts.append(f"{rep} (length spread ±{sd:.1f} m{peer})")

    os_ = [o for o in sq["over_shape"] if o["med_len"] is not None]
    early = [o for o in os_ if o["pos"] <= 2]
    late = [o for o in os_ if o["pos"] >= 5]
    if early and late:
        es = statistics.mean(o["short_pct"] for o in early)
        ls = statistics.mean(o["short_pct"] for o in late)
        el = statistics.median([o["med_len"] for o in early])
        ll = statistics.median([o["med_len"] for o in late])
        if ls - es >= 3:
            parts.append(f"tends to bang it in later in the over (short {es:.0f}%→{ls:.0f}% by the 5th–6th ball)")
        elif es - ls >= 3:
            parts.append("drops shorter early, then pitches up later in the over")
        elif ll - el <= -0.4:
            parts.append("pitches fuller as the over goes on")
        elif sd is not None and ((is_spin and sd > 1.45) or (not is_spin and sd > 2.25)):
            # high overall spread → 'no trend' rather than a contradictory 'steady length'
            parts.append("with no consistent trend to his length across the over")
        else:
            parts.append("holds a steady length right through the over")

    # crease mix across the over (does he change his release position ball to ball?)
    cc = [o for o in sq["over_shape"] if o.get("crease_cm") is not None]
    ce = [o["crease_cm"] for o in cc if o["pos"] <= 2]
    cl = [o["crease_cm"] for o in cc if o["pos"] >= 5]
    if ce and cl:
        d = statistics.mean(cl) - statistics.mean(ce)
        if d >= 6:
            parts.append(f"and moves wider on the crease as the over goes on "
                         f"({statistics.mean(ce):.0f}→{statistics.mean(cl):.0f} cm from the stumps)")
        elif d <= -6:
            parts.append(f"and tightens his crease position later in the over "
                         f"({statistics.mean(ce):.0f}→{statistics.mean(cl):.0f} cm)")
        else:
            parts.append("and holds the same crease position through the over")

    if not parts:
        return ""
    read = "; ".join(parts)
    return read[0].upper() + read[1:] + "."


def _seq_pattern_read(P: dict) -> str:
    """B3 ball-to-ball setups + B4 how he sets up his wickets."""
    s = P.get("seq_patterns")
    if not s or s["wk_with_prev"] < 40:
        return ""
    is_spin = P["is_spin"]
    bits = []
    if not is_spin and s["after_short_n"] >= 60 and s["after_short_fuller_pct"] is not None:
        f = s["after_short_fuller_pct"]
        if f <= 40:
            bits.append(f"doubles up on the short ball — pitches up only {f:.0f}% of the time after banging one in")
        elif f >= 52:
            bits.append(f"uses the short ball as a one-off — follows it with a fuller length {f:.0f}% of the time")

    wf, wsh = s["wk_fuller_pct"], s["wk_shorter_pct"]
    if wf is not None and wsh is not None:
        if wf - wsh >= 12:
            bits.append(f"sets batters up then pitches fuller for the wicket "
                        f"({wf:.0f}% of dismissals come off a ball fuller than the one before)")
        elif wsh - wf >= 12:
            bits.append(f"often strikes with a shorter ball than the previous one ({wsh:.0f}% of dismissals)")

    wst, ww = s["wk_straighter_pct"], s["wk_wider_pct"]
    if wst is not None and ww is not None and wst - ww >= 8:
        bits.append(f"and tends to strike with a straighter ball after working across the batter "
                    f"({wst:.0f}% straighter than the ball before)")

    if not bits:
        return "Takes his wickets with the stock ball rather than obvious set-ups."
    read = "; ".join(bits)
    return read[0].upper() + read[1:] + "."


_PEER_LABEL = {"Right pace": "right-arm pace", "Left pace": "left-arm pace",
               "Right spin": "right-arm spin", "Left spin": "left-arm spin"}


def _crease_read(P: dict) -> str:
    """Release point & crease use: release height (tall/low), how wide of the stumps he
    releases, and how much he varies it — all benchmarked vs the same hand × pace/spin peers.
    Release data is modern-era (2017+); percentiles vs bowlers of the same type + hand."""
    c = P.get("crease")
    if not c:
        return ""
    dom = c.get(c["dominant"])
    if not dom:
        return ""
    ref = P.get("crease_ref") or {}
    peer = _PEER_LABEL.get(ref.get("peer_group"), "spin" if P["is_spin"] else "pace")
    w, sd = dom["width_cm"], dom["sd_cm"]

    def _pctl(key):
        try:
            return float(ref.get(key))
        except (TypeError, ValueError):
            return None

    parts = []
    hp, h = _pctl("height_pctl"), c.get("height_cm")
    if hp is not None:
        if hp >= 70:
            parts.append(f"a high release point (taller than {hp:.0f}% of {peer})")
        elif hp <= 30:
            parts.append(f"a low, skiddy release point (lower than {100 - hp:.0f}% of {peer})")
        else:
            parts.append("a mid-height release point")
    elif h is not None:
        parts.append(f"releases from about {h / 100:.2f} m")

    wp = _pctl("width_pctl")
    if wp is not None and wp >= 70:
        parts.append(f"releases wide of the stumps ({w:.0f} cm out, wider than {wp:.0f}% of {peer})")
    elif wp is not None and wp <= 30:
        parts.append(f"releases tight to the stumps ({w:.0f} cm out, tighter than {100 - wp:.0f}% of {peer})")
    else:
        parts.append(f"releases about {w:.0f} cm from the middle stump")

    vp = _pctl("var_pctl")
    if vp is not None and vp >= 70:
        parts.append(f"varies his spot on the crease a lot (more than {vp:.0f}% of {peer})")
    elif vp is not None and vp <= 30:
        parts.append(f"releases from the same spot almost every ball (steadier than {100 - vp:.0f}% of {peer})")
    elif vp is None:
        if sd >= 18:
            parts.append("moves around on the crease")
        elif sd <= 10:
            parts.append("releases from a consistent spot")

    read = "; ".join(parts)
    o, r = c["over"], c["round"]
    if o and r and min(o["n"], r["n"]) >= 100 and abs(o["width_cm"] - r["width_cm"]) >= 15:
        wider = "round" if r["width_cm"] > o["width_cm"] else "over"
        read += (f". Comes wider {wider} the wicket "
                 f"({o['width_cm']:.0f} cm over vs {r['width_cm']:.0f} cm round)")
    return read[0].upper() + read[1:] + "."


def _fingerprint_cards(P: dict) -> list:
    """(label, pct, pct_txt, colour, disp, peer, img) cards for the fingerprint panel —
    each a mini peer distribution with this bowler marked (career line + last-3yr overlay)."""
    out = []
    for m in P.get("fingerprint", []):
        p = m.get("pctl")
        colour = (ACCENT if (p is not None and p >= 60)
                  else "#9aa3b2" if (p is not None and p <= 33) else TEXT_SEC)
        rp = m.get("pctl_recent")
        out.append({
            "label": m["label"],
            "pct_txt": f"P{p:.0f}" if p is not None else "—",
            "recent_txt": (f"P{rp:.0f}" if (m.get("recent") is not None and rp is not None) else None),
            "colour": colour,
            "disp": m["disp"],
            "peer": f"vs {m['peer']}",
            "img": _fig_uri(fingerprint_strip(m["values"], m["value"], invert=m["invert"],
                                              recent_value=m.get("recent")), w=250, h=84),
        })
    return out


def _fingerprint_headline(P: dict) -> str | None:
    """One line naming the fingerprint traits that have shifted in the last 3 years — the
    'how they're changing' read. Noise-gated on the percentile move (the recent window is already
    ball-floored where the value is computed); leads with declines."""
    pace_txt, others = None, []
    for m in P.get("fingerprint", []):
        cv, rv, cp, rp = m.get("value"), m.get("recent"), m.get("pctl"), m.get("pctl_recent")
        if None in (cv, rv, cp, rp) or abs(rp - cp) < 12:
            continue
        if m["label"] == "Pace":                         # the headline metric for a quick — lead with it
            pace_txt = f"pace {'down' if rv < cv else 'up'} ~{abs(rv - cv):.0f} km/h (now {rv:.0f})"
        else:
            others.append((abs(rp - cp), f"{m['label'].lower()} {'up' if rp > cp else 'down'}"))
    others.sort(reverse=True)                             # biggest shifts first
    parts = ([pace_txt] if pace_txt else []) + [t for _s, t in others]
    parts = parts[:3]
    return ("Changing (last 3 years vs career): " + "; ".join(parts) + ".") if parts else None


def _crease_band_rows(P: dict) -> list:
    """(band, %balls, balls, econ, wkts, avg, SR) — how he goes when tight/standard/wide."""
    c = P.get("crease")
    if not c or not c.get("bands"):
        return []
    lab = {"tight": "Tight (<45cm)", "standard": "Standard (45–75)", "wide": "Wide (>75cm)"}
    rows = []
    for b in ("tight", "standard", "wide"):
        m = c["bands"].get(b)
        if not m:
            continue
        rows.append((lab[b], f"{m['share']:.0f}%", f"{m['balls']:,}",
                     f"{m['econ']:.2f}", str(m["wkts"]),
                     f"{m['avg']:.1f}" if m["avg"] else "—",
                     f"{m['sr']:.0f}" if m["sr"] else "—"))
    return rows


def _crease_usage_rows(P: dict) -> list:
    """(angle, balls%, tight%, standard%, wide%) — how he mixes his crease position,
    split by over vs round the wicket."""
    c = P.get("crease")
    if not c:
        return []
    rows = []
    for nm, key, share in (("Over the wicket", "over", c.get("over_share")),
                           ("Round the wicket", "round", c.get("round_share"))):
        m = c.get(key)
        if not m or m["n"] < 50:
            continue
        rows.append((nm, f"{share:.0f}%" if share is not None else "—",
                     f"{m['tight_pct']:.0f}%", f"{m['std_pct']:.0f}%", f"{m['wide_pct']:.0f}%"))
    return rows


def _sequencing_rows(P: dict) -> list:
    """(ball-in-over, median length, short%, econ, wkt%) rows for the over-shape table."""
    sq = P.get("sequencing")
    if not sq:
        return []
    return [
        (f"Ball {o['pos']}",
         f"{o['med_len']:.1f} m" if o["med_len"] is not None else "—",
         f"{o['short_pct']:.0f}%",
         f"{o['econ']:.2f}",
         f"{o['wkt_rate']:.1f}%")
        for o in sq["over_shape"]
    ]


def _at_stumps_phrase(ats: dict | None) -> str | None:
    """Natural phrase for where a ball type ends up at the stumps."""
    if not ats:
        return None
    line, ht = ats["line"], ats["height"]
    if line == "outside off":
        return "passing outside off"
    if line == "leg":
        return "sliding down leg"
    if ht == "over":
        return "climbing over off" if line == "off stump" else "climbing over the stumps"
    return "hitting the top of off" if line == "off stump" else "hitting the stumps"


def _dir_word(p, verb) -> str:
    """in / away / both ways from an in-swing %. 'seaming in' reads as 'seaming back'."""
    if p >= 65:
        return "back" if verb == "seaming" else "in"
    if p <= 35:
        return "away"
    return "both ways"


def _move_phrase(t: dict, is_spin: bool, swing_override: str | None = None,
                 hand: str = "All") -> str | None:
    """What the ball does through the air and off the pitch for a ball type. Reports
    BOTH swing (in-air) and seam/turn (off-pitch) when each is material, dominant
    first — so a swing bowler reads 'swinging away', not just 'seaming'.
    For SPIN in a combined (All) view, turn is described by PHYSICAL break (off/leg break) —
    off-spin turns 'in' to a RHB but 'away' from a LHB, so the batter-relative label reads a
    false 'both ways' across hands. A hand-filtered view keeps the batter-relative 'in/away'.
    `swing_override` replaces a per-ball-type 'both ways' swing word with a bowler-level
    phase phrase (e.g. 'away, reverses in') when the swing is really ball-age driven."""
    _MAT = 0.4    # mean |movement| (deg) below this is negligible for this ball type
    comps = []    # (magnitude, phrase)
    # swing / drift — in-air
    swm, swp, swn = t.get("swing_mag"), t.get("sw_in_pct"), t.get("sw_n") or 0
    if swm is not None and swm >= _MAT:
        verb = "drifting" if is_spin else "swinging"
        word = _dir_word(swp, verb) if (swp is not None and swn >= 15) else ""
        if swing_override and word == "both ways":   # a flat 'both ways' hides a ball-age flip
            word = swing_override
        comps.append((swm, f"{verb} {word}".strip()))
    # seam / turn — off the pitch
    smm, smp, smn = t.get("seam_mag"), t.get("mv_in_pct"), t.get("mv_n") or 0
    if smm is not None and smm >= _MAT:
        if is_spin and hand == "All":
            ob = t.get("mv_offbreak_pct")
            if ob is not None and smn >= 15:
                phrase = ("turning in to the RHB / away from the LHB" if ob >= 60
                          else "turning away from the RHB / in to the LHB" if ob <= 40
                          else "turning both ways")
            else:
                phrase = "turning"
            comps.append((smm, phrase))
        else:
            verb = "turning" if is_spin else "seaming"
            word = _dir_word(smp, verb) if (smp is not None and smn >= 15) else ""
            comps.append((smm, f"{verb} {word}".strip()))
    if not comps:
        return None
    comps.sort(key=lambda c: -c[0])   # dominant movement first
    return ", ".join(c[1] for c in comps)


def _ball_type_desc(t: dict, is_spin: bool, swing_override: str | None = None,
                    hand: str = "All") -> str:
    """Full 'what it does' description: length/line + movement + at-stumps."""
    parts = [t["phrase"]]
    mv = _move_phrase(t, is_spin, swing_override, hand=hand)
    if mv:
        parts.append(mv)
    ats = _at_stumps_phrase(t["at_stumps"])
    if ats:
        parts.append(ats)
    return ", ".join(parts)


def _stock_read(P: dict) -> str:
    """Enriched stock-ball sentence + main variations."""
    bt = P.get("ball_types")
    if not bt or not bt["stock"]:
        return ""
    s = bt["stock"]
    _sv = None if P["is_spin"] else _swing_verdict(P.get("movement"))
    _sov = _swing_cell_word(_sv) if _sv else None
    read = f"Stock ball — <b>{_ball_type_desc(s, P['is_spin'], _sov, hand=P['filters']['hand'])}</b> ({s['pct']:.0f}% of deliveries"
    if s["econ"] is not None:
        read += f", economy {s['econ']:.2f}"
    read += ")"
    varz = [t for t in bt["types"][1:3] if t["pct"] >= 8]
    if varz:
        vtxt = " and ".join(f"{t['phrase']} ({t['pct']:.0f}%)" for t in varz)
        read += f". Minor variations: {vtxt}"
    return read + "."


def _ball_type_rows(P: dict) -> list:
    """(type, movement, %, econ, wkts, beaten%) rows for the ball-type table.
    Movement is a summary of the same rows (not a further split), shown where enough
    balls are tracked, so the sample doesn't shrink."""
    bt = P.get("ball_types")
    if not bt:
        return []
    is_spin = P["is_spin"]
    _hand = P["filters"]["hand"]
    _sv = None if is_spin else _swing_verdict(P.get("movement"))
    _sov = _swing_cell_word(_sv) if _sv else None
    return [
        {"phrase": t["phrase"],
         "move": _move_phrase(t, is_spin, _sov, hand=_hand) or "—",
         "pct": f"{t['pct']:.0f}%",
         "econ": f"{t['econ']:.2f}" if t["econ"] is not None else "—",
         "wkts": str(t["wkts"]),
         "beat": f"{t['beaten_pct']:.0f}%" if t["beaten_pct"] is not None else "—",
         "key": f"bt_{i}"}
        for i, t in enumerate(bt["types"][:6])
    ]


def _fmt_stat(v, dp=1, suffix=""):
    return "—" if v is None else f"{v:.{dp}f}{suffix}"


def _ball_age_data(P: dict) -> dict | None:
    """New-ball vs old-ball view: top ball types + headline threat + danger cell for each phase."""
    ba = P.get("ball_age")
    if not ba:
        return None

    def block(b, label):
        if not b:
            return None
        rows = [(t["phrase"], f"{t['pct']:.0f}%",
                 f"{t['econ']:.2f}" if t["econ"] is not None else "—", str(t["wkts"]))
                for t in b["types"]]
        dc = b.get("danger_cell")
        dl = b.get("danger_length")
        return {
            "label": label, "n": f"{b['n_balls']:,}", "wkts": b["wkts"],
            "econ": f"{b['econ']:.2f}" if b["econ"] is not None else "—", "rows": rows,
            "danger": f"{dc['length'].lower()} {dc['line']}" if dc else None,
            "danger_rate": f"{dc['adj_rate']:.1f}" if dc and dc.get("adj_rate") else None,
            "danger_len": dl["length"] if dl else None,
            "danger_len_rate": f"{dl['adj_rate']:.1f}" if dl and dl.get("adj_rate") else None,
        }
    new = block(ba["new"], f"New ball (≤{ba['split_over']} ov)")
    old = block(ba["old"], f"Old ball ({ba['split_over'] + 1}+ ov)")
    if not (new or old):
        return None
    return {"new": new, "old": old}


def _recent_form_rows(P: dict) -> dict | None:
    """Two comparable rows — recent window vs career — for the Current Form table."""
    rf = P.get("recent_form")
    if not rf:
        return None

    def row(s):
        return {"balls": f"{s['balls']:,}", "wkts": str(s["wkts"]),
                "avg": _fmt_stat(s["avg"], 1), "econ": _fmt_stat(s["econ"], 2),
                "sr": _fmt_stat(s["sr"], 1), "false": _fmt_stat(s["false_pct"], 0, "%"),
                "speed": _fmt_stat(s["speed"], 0), "length": _fmt_stat(s["length"], 2, " m")}
    return {"recent": row(rf["recent"]), "career": row(rf["career"]),
            "n_matches": rf["n_matches"], "date_from": rf["date_from"], "date_to": rf["date_to"],
            "read": _recent_form_read(P)}


def _recent_form_read(P: dict) -> str:
    rf = P.get("recent_form")
    if not rf:
        return ""
    r, c = rf["recent"], rf["career"]
    if not (r["avg"] and c["avg"]):
        return f"Last {rf['n_matches']} Tests: {r['wkts']} wickets."
    if r["avg"] <= c["avg"] * 0.8:
        trend = f"striking more often right now (avg {r['avg']:.0f} in his last {rf['n_matches']} Tests vs {c['avg']:.0f} career)"
    elif r["avg"] >= c["avg"] * 1.2:
        trend = f"less penetrative of late (avg {r['avg']:.0f} in his last {rf['n_matches']} Tests vs {c['avg']:.0f} career)"
    else:
        trend = f"around his career level lately (avg {r['avg']:.0f} last {rf['n_matches']} vs {c['avg']:.0f} career)"
    return f"He's {trend}."


def _matchup_split_tables(P: dict) -> dict:
    """Match-up tables (ball age / batting phase) within the report's hand. Each row:
    (label, balls, wkts, avg, econ, sr, false%, med-length). Includes length so it subsumes the
    old length-by-match-up section. Empty groups already dropped in the profile."""
    mu = P.get("matchups") or {}

    def rows(group):
        out = []
        for label, s in group.items():
            out.append((label, f"{s['balls']:,}", str(s["wkts"]),
                        _fmt_stat(s["avg"], 1), _fmt_stat(s["econ"], 2),
                        _fmt_stat(s["sr"], 1), _fmt_stat(s["false_pct"], 0, "%"),
                        _fmt_stat(s["length"], 2, " m")))
        return out
    return {"ball": rows(mu.get("ball", {})), "position": rows(mu.get("position", {}))}


def _wicket_setup_read(P: dict) -> str:
    """Concrete 'ball before the wicket' line for the sequencing section."""
    ws = P.get("wicket_setup")
    if not ws or ws.get("n", 0) < 12:
        return ""
    parts = []
    dl = ws["wk_len"] - ws["prev_len"]
    if abs(dl) >= 0.25:
        parts.append(f"the wicket ball lands about {abs(dl) * 100:.0f} cm "
                     f"{'fuller' if dl < 0 else 'shorter'} than the ball before it")
    if ws.get("wk_spd") and ws.get("prev_spd"):
        dv = ws["wk_spd"] - ws["prev_spd"]
        if abs(dv) >= 2:
            parts.append(f"about {abs(dv):.0f} km/h {'quicker' if dv > 0 else 'slower'}")
    if not parts:
        return (f"Across {ws['n']} dismissals, his wicket ball is close in length and pace to the "
                f"delivery before it — he builds pressure with repetition, not a big change-up.")
    return f"Across {ws['n']} dismissals, {' and '.join(parts)} — that's the change that brings the wicket."


def _angle_variation(P: dict) -> str:
    """Over/round-the-wicket tactic + variation usage (key in white-ball)."""
    parts = []
    rl, rr = P.get("round_lhb"), P.get("round_rhb")
    if rl is not None and rr is not None:
        if rl >= 25 and rr < 15:
            parts.append(f"Round the wicket to LHB ({int(rl)}%), stays over to RHB")
        elif rr >= 25 and rl < 15:
            parts.append(f"Round the wicket to RHB ({int(rr)}%), stays over to LHB")
        elif rl >= 25 and rr >= 25:
            parts.append(f"Uses round the wicket to both (LHB {int(rl)}% · RHB {int(rr)}%)")
        else:
            parts.append(f"Mostly over the wicket (round LHB {int(rl)}% · RHB {int(rr)}%)")
    sb, sk = P.get("slower_ball_pct"), P.get("slower_ball_kph")
    if sb is not None:
        detail = f" (~{_fmt(sk, '.0f')} kph)" if sk else ""
        parts.append(f"slower balls {sb:.1f}%{detail}")
    return " · ".join(parts)


def _matchup_insight(P: dict) -> str:
    """One-line read of the length match-up tables (ball age + tail treatment)."""
    bits = []
    nb, ob = P["new_ball"], P["old_ball"]
    if nb and ob and abs(ob["short_pct"] - nb["short_pct"]) >= 4:
        up = ob["short_pct"] > nb["short_pct"]
        bits.append(f"{'bangs it in more' if up else 'pitches fuller'} with the old ball "
                    f"({_pct(nb['short_pct'])}→{_pct(ob['short_pct'])} short)")
    t3, tail = P["pos_groups"].get("Top 3"), P["pos_groups"].get("Tail")
    if t3 and tail:
        if tail["short_pct"] - t3["short_pct"] >= 5:
            bits.append(f"more short balls at the tail ({_pct(tail['short_pct'])} vs {_pct(t3['short_pct'])} to the top 3)")
        if tail["full_pct"] - t3["full_pct"] >= 5:
            bits.append(f"more yorkers/full at the tail ({_pct(tail['full_pct'])})")
    if not bits:
        return ""
    return "; ".join(bits)[0].upper() + "; ".join(bits)[1:] + "."


def _examples(P: dict) -> dict:
    """One playable example clip per key insight (stock ball, a wicket) for 'watch' PDF links.
    Best-effort; empty if video is unavailable."""
    try:
        _get_fairplay_sas(ttl_hours=72)   # long-lived SAS so baked PDF links last a few days
    except Exception:
        return {}
    df = P.get("df") or []

    def _first(rows):
        rows = [r for r in rows if r.get("clip_stem")]
        rows.sort(key=lambda r: r.get("match_date") or "", reverse=True)   # recent first (coverage)
        return _first_example(rows)

    ex = {}
    st = (P.get("ball_types") or {}).get("stock")
    if st:
        stock = [r for r in df if r.get("ball_type") == (st["band"], st["region"])]
        stock.sort(key=lambda r: (not r.get("is_wicket"), not r.get("is_false_shot")))  # illustrative first
        ex["stock"] = _first(stock)
    ex["wicket"] = _first([r for r in df if r.get("is_wicket")])
    return ex


def _vs_squad_ctx(bowler_id):
    """The 'vs our squad' strip (SCOUTING_REBUILD.md): exceptions only, from the series matchup
    store. Threats/targets need confidence Med/High AND a column-rank extreme; the structural
    spin line covers whole hand-classes; real head-to-head is a note, never an average."""
    try:
        import glob as _g
        import json as _json
        from cricket_core.config import project_path
        mm = project_path("matchupmodel")
        # frontline only — "he wins the matchup vs our No.10" is trivially true, not intel
        roles_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "players.json")
        roles = ({pid: r.get("role") for pid, r in
                  _json.load(open(roles_p, encoding="utf-8")).items()}
                 if os.path.exists(roles_p) else {})
        for p in _g.glob(os.path.join(mm, "data", "matchup_store_*.json")):
            store = _json.load(open(p, encoding="utf-8"))
            cells = [c for c in store.get("we_bat", [])
                     if c["bowler_id"] == str(bowler_id) and c["sim_avg"] is not None
                     and roles.get(c["batter_id"]) != "Bowler"]
            if not cells:
                continue
            solid = [c for c in cells if c["confidence"] in ("Med", "High")]
            med = sorted(c["sim_avg"] for c in cells)[len(cells) // 2] if cells else 0
            # material deviation vs his norm against OUR frontline, not just rank order
            threats = sorted([c for c in solid if c["sim_avg"] <= 0.75 * med],
                             key=lambda c: c["sim_avg"])[:3]
            targets = sorted([c for c in solid if c["sim_avg"] >= 1.3 * med],
                             key=lambda c: -c["sim_avg"])[:3]
            struct = [c for c in cells if c.get("structural_threat")]
            sline = ""
            if struct:
                names = sorted({c["batter"].split()[-1] for c in struct})
                hand = struct[0]["bat_hand"]
                sline = (f"Structurally he takes the ball away from the {hand} — harder work for "
                         f"{', '.join(names)} regardless of individual reads; a left/right pairing "
                         f"at the crease blunts it.")
            h2h_note = ""
            opp = store["opp"].lower().replace(" ", "_")
            hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"h2h_{opp}.json")
            if os.path.exists(hp):
                h2h = _json.load(open(hp, encoding="utf-8"))
                mine = [r for r in h2h.get("our_batting", []) if r["bowler_id"] == str(bowler_id)]
                if mine:
                    balls = sum(r["balls"] for r in mine)
                    wkts = sum(r["wickets"] for r in mine)
                    h2h_note = (f"Real meetings with this squad: {balls} balls across "
                                f"{len(mine)} batters ({wkts} wicket{'s' if wkts != 1 else ''}) — "
                                "too few to average; the footage is in each player's pack and on "
                                "the Match-ups page.")
            if not (threats or targets or sline):
                return None                    # nothing clears the gate — the strip stays silent
            return {"threats": [(c["batter"], c["bat_hand"], c["sim_avg"],
                                 c.get("top_dismissal", "")) for c in threats],
                    "targets": [(c["batter"], c["bat_hand"], c["sim_avg"]) for c in targets],
                    "structural": sline, "h2h_note": h2h_note}
    except Exception:
        pass
    return None


def build_html(P: dict, video: dict = None, player_mode: bool = False) -> str:
    """`player_mode=True` produces the reduced player-facing cut: identical bowling detail
    (fingerprint, pitch maps, danger zones, sequencing) but with the coach-only 'Vs Our Squad'
    matchup verdicts stripped — a player never sees how they personally match up to an opponent."""
    hand = P["filters"]["hand"]
    photo_uri = get_photo_data_uri(P["bowler_id"], fmt="test", name=P.get("name"))

    miss_zone = None
    if P["beaten_df"]:
        miss_zone = zone_concentration(P["beaten_df"], P["line_zones"], P["length_zones"], "count")

    ctx = {
        "video": video or {},
        "P": P, "hand_label": _HAND_LABEL.get(hand, hand), "code": _country_code(P["team"]),
        "photo_uri": photo_uri, "figs": _figures(P), "cards": _cards(P),
        "vs_squad": None if player_mode else _vs_squad_ctx(P["bowler_id"]),
        "player_mode": player_mode,
        "threat_cards": _threat_cards(P), "danger_cards": _danger_cards(P),
        "dismissal_rows": _dismissal_rows(P), "dismissal_peer": _dismissal_peer_label(P),
        "unmapped_wkts": (P["n_wkts"] - int(P["wkt_zone"]["total"])) if P.get("wkt_zone") else 0,
        "narrative": _narrative(P), "miss_zone": miss_zone,
        "dismissals": sorted(P["dismissal_counts"].items(), key=lambda kv: -kv[1]),
        "catch_positions": P["catch_pos_counts"].most_common(6),
        "pos_groups": list(P["pos_groups"].items()),
        "matchup_insight": _matchup_insight(P),
        "movement_rows": _movement_rows(P),
        "reads": _chart_reads(P),
        "angle_variation": _angle_variation(P),
        "danger_read": _danger_read(P),
        "speed_read": _speed_read(P),
        "movement_read": _movement_read(P),
        "swing_age_read": _swing_age_read(P),
        "bowler_style": _bowler_style(P),
        "scoring_stats": _scoring_stats(P),
        "scoring_rows": _scoring_rows(P),
        "scoring_read": _scoring_read(P),
        "over_round_rows": _over_round_rows(P),
        "over_round_read": _over_round_read(P),
        "ball_type_rows": _ball_type_rows(P),
        "ball_age": _ball_age_data(P),
        "stock_read": _stock_read(P),
        "how_to_play": P.get("how_to_play"),
        "hand_noun": _hand_word(P) or "batters of this hand",
        "recent_form": _recent_form_rows(P),
        "matchup_tables": _matchup_split_tables(P),
        "wicket_setup_read": _wicket_setup_read(P),
        "sequencing_read": _sequencing_read(P),
        "seq_pattern_read": _seq_pattern_read(P),
        "crease_read": _crease_read(P),
        "crease_usage_rows": _crease_usage_rows(P),
        "crease_band_rows": _crease_band_rows(P),
        "fingerprint_cards": _fingerprint_cards(P),
        "fingerprint_headline": _fingerprint_headline(P),
        "sequencing_rows": _sequencing_rows(P),
        "version": REPORT_VERSION,
        "build_date": datetime.date.today().strftime("%d %b %Y"),
        "pct": _pct, "fmt": _fmt, "css": REPORT_CSS,
        "c": dict(BG_PAGE=BG_PAGE, BG_PANEL=BG_PANEL, TEXT_PRI=TEXT_PRI,
                  TEXT_SEC=TEXT_SEC, ACCENT=ACCENT, DANGER=DANGER, BORDER=BORDER),
    }
    return Template(_TEMPLATE).render(**ctx)


def _find_chromium() -> str:
    """Locate a Chromium/Edge/Chrome binary for headless PDF printing.

    We drive the browser directly via subprocess (not Playwright's Python API)
    because Playwright's sync wrapper needs greenlet, whose native DLL is blocked
    by the machine's Application Control policy.
    """
    base = os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "ms-playwright")
    hits = sorted(glob.glob(os.path.join(base, "chromium-*", "chrome-win", "chrome.exe")), reverse=True)
    if hits:
        return hits[0]
    # Chrome-for-Testing fetched by kaleido/choreographer (plotly_get_chrome). Preferred over a
    # system Edge: it uses an isolated profile so `--print-to-pdf` never hands off to a running
    # Edge and return early (which prints an ERR_FILE_NOT_FOUND page once the temp html is cleaned).
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local")
    choreo = sorted(glob.glob(os.path.join(local, "plotly", "choreographer", "deps", "chrome-*", "chrome.exe")), reverse=True)
    if choreo:
        return choreo[0]
    for p in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if os.path.exists(p):
            return p
    raise RuntimeError("No Chromium/Edge/Chrome found for PDF export.")


def _html_to_pdf(html: str, out_path: str) -> None:
    exe = _find_chromium()
    tmp_html = out_path + ".src.html"
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(html)
    user_dir = tempfile.mkdtemp(prefix="pp_chrome_")
    url = "file:///" + os.path.abspath(tmp_html).replace("\\", "/")
    # NOTE: use Popen + DEVNULL, NOT subprocess.run(capture_output=True). With --headless=new
    # Chrome spawns child renderer/gpu processes; on Windows a run(timeout, capture_output)
    # call can't drain the stdout/stderr pipes those orphaned children still hold, so it hangs
    # indefinitely instead of timing out (wedged a whole batch once — see git history).
    # DEVNULL removes the pipe; on timeout we kill the entire Chrome process tree.
    p = subprocess.Popen(
        [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--user-data-dir={user_dir}", "--no-pdf-header-footer",
         "--run-all-compositor-stages-before-draw", "--virtual-time-budget=10000",
         f"--print-to-pdf={out_path}", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        p.wait(timeout=180)
        if p.returncode not in (0, None):
            raise RuntimeError(f"Chrome exit {p.returncode} rendering {os.path.basename(out_path)}")
    except subprocess.TimeoutExpired:
        try:                                    # bound taskkill too — it must not hang the batch
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except Exception:
            pass
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        raise RuntimeError(f"Chrome PDF render timed out (180s) for {os.path.basename(out_path)}")
    finally:
        try:
            os.remove(tmp_html)
        except OSError:
            pass
        # Delete the throwaway Chrome profile — otherwise these pile up in %TEMP% (hundreds
        # over a batch) and eventually Chrome hangs on startup. This was the real batch-wedge.
        shutil.rmtree(user_dir, ignore_errors=True)


def _file_url(path: str) -> str:
    return "file:///" + os.path.abspath(path).replace("\\", "/").replace(" ", "%20")


def _build_player(P: dict, pdf_path: str, subtitle: str, target_country: str | None = None) -> dict:
    """Build per-insight playlists, write a self-contained modal video player next to the PDF,
    and return {player: file-url, keys: {...}} for the report's ▶ links. Best-effort.
    `target_country` orders clips by like-for-like conditions (see build_playlists)."""
    try:
        _get_fairplay_sas(ttl_hours=72)          # long-lived SAS baked into the player
        from playlists import build_playlists
        from cricket_core.video import build_player_html, write_playlists
        built = build_playlists(P, cap=8, target_country=target_country)
        pls, pl_meta = built["playlists"], built.get("meta")
        # Always write the sidecar (with meta: bowler_id + name) — even with no clips — so
        # publish_site can map + serve the report; no-clip bowlers otherwise vanish from the site.
        write_playlists(pdf_path[:-4] + ".playlists.json", pls, meta=pl_meta)
        if not pls:
            return {"lists": {}}          # no clips: keep `lists` so the template guards work
        _titles = (pl_meta or {}).get("titles")   # per-bowler ball-type names for bt_0.. playlists
        player_path = pdf_path[:-4] + ".player.html"
        build_player_html(pls, player_path, title=P["name"], subtitle=subtitle, titles=_titles)
        return {"player": _file_url(player_path), "lists": {k: True for k in pls},
                "playlists": pls, "titles": _titles}
    except Exception:
        return {"lists": {}}


def render_report(bowler_id: str, hand: str = "All", out_dir: str = "reports",
                  position: str = "All positions", spell: str = "All",
                  length_mode: str = "Zones", with_playlists: bool = True,
                  target_country: str | None = "Australia", render_pdf: bool = True) -> str:
    """Build the profile, render HTML, print to PDF. Returns the PDF path. When
    `with_playlists`, also builds video playlists + a `<pdf>.player.html` modal player and links
    the report's ▶ buttons to it (best-effort — never breaks the report if video is unavailable).

    `target_country` = where the next series is played; video examples are ordered like-for-like
    (that country's conditions first, then similar, then the rest). Defaults to Australia (home
    series). Pass None for pure recency."""
    P = build_profile(bowler_id, hand=hand, position=position, spell=spell, length_mode=length_mode)
    P["_recent_cards"] = _recent_card_vals(P)          # last-3-yr values for the top cards (once)

    os.makedirs(out_dir, exist_ok=True)
    # firstname_surname_bowling_{pace|spin}_{format}_{hand}.pdf
    nm = P["name"]
    if "," in nm:
        surname, first = (x.strip() for x in nm.split(",", 1))
    else:
        _p = nm.split()
        first, surname = (" ".join(_p[:-1]), _p[-1]) if len(_p) > 1 else ("", nm)

    def _slug(s):
        return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")

    who = "_".join(p for p in (_slug(first), _slug(surname)) if p) or f"bowler_{bowler_id}"
    btype = "pace" if P["is_pace"] else ("spin" if P["is_spin"] else "bowling")
    fmt = "test"   # Test-match data for now; will branch when white-ball is added
    hand_tag = {"All": "all", "vs LHB": "lhb", "vs RHB": "rhb"}.get(hand, "all")
    out_path = os.path.abspath(os.path.join(out_dir, f"{who}_bowling_{btype}_{fmt}_{hand_tag}.pdf"))

    video = (_build_player(P, out_path, subtitle=f"{P['name']} — bowling scout",
                           target_country=target_country) if with_playlists else {})
    html = build_html(P, video=video)
    # reduced player-facing cut: same bowling detail, coach-only 'Vs Our Squad' verdicts stripped
    pm_html = build_html(P, video=video, player_mode=True)
    snippet = ""
    if video.get("playlists"):
        # Interactive HTML report: same page + an in-page lightbox. ▶ opens the playlist as a
        # modal OVER the report (same tab — the iOS/Safari use case); the PDF keeps the href
        # fallback to the standalone player.html (the snippet is display:none in print).
        from cricket_core.video import inline_player_snippet
        # Markers let the web app swap this baked-SAS player for a mint-on-demand one (webapp.py).
        snippet = ("<!--PLAYER_SNIPPET_START-->"
                   + inline_player_snippet(video["playlists"], titles=video.get("titles"))
                   + "<!--PLAYER_SNIPPET_END-->")
        html = html.replace("</body>", snippet + "</body>")
        pm_html = pm_html.replace("</body>", snippet + "</body>")
    # Always write the interactive .html (with the player snippet when there are clips) so the
    # site serves every bowler, including no-clip ones.
    with open(out_path[:-4] + ".html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(out_path[:-4] + ".pmode.html", "w", encoding="utf-8") as f:
        f.write(pm_html)
    if render_pdf:
        _html_to_pdf(html, out_path)
    return out_path


_TEMPLATE = r"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  @page { size: A4; margin: 0 0 9mm 0;
    @bottom-right { content: counter(page) " / " counter(pages);
      font-family: Inter, sans-serif; font-size: 8px; color: {{c.TEXT_SEC}};
      margin-right: 10mm; }
    @bottom-left { content: "{{P.name}} · bowling scout"; font-family: Inter, sans-serif;
      font-size: 8px; color: {{c.TEXT_SEC}}; margin-left: 10mm; } }
  {{ css }}
</style></head>
<body><div class="page">

  <div class="header">
    {% if photo_uri %}<img src="{{photo_uri}}">{% else %}<div class="ph">🏏</div>{% endif %}
    <div>
      <h1>{{P.name}} {% if code %}<span class="flag">{{code}}</span>{% endif %}</h1>
      <div class="sub">{{P.team}} · {{P.primary_type}} · <b>{{hand_label}}</b></div>
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

  <h2>Scouting Summary</h2>
  <div class="summary">
    <div class="sbox"><h3 style="color:{{c.ACCENT}}">Common themes</h3><ul>
      {% for t in narrative.themes %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
    <div class="sbox"><h3 style="color:{{c.DANGER}}">Biggest threats</h3><ul>
      {% for t in narrative.threats %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
    <div class="sbox"><h3 style="color:#15803d">Areas to exploit</h3><ul>
      {% for t in narrative.expose %}<li>{{t|safe}}</li>{% endfor %}</ul></div>
  </div>

  {% if fingerprint_cards %}
  <h2>Bowling Fingerprint</h2>
  {% if fingerprint_headline %}<div class="read" style="margin-bottom:6px">{{fingerprint_headline}}</div>{% endif %}
  <div class="fpgrid">
    {% for f in fingerprint_cards %}
    <div class="fpcard">
      <div class="lab">{{f.label}}</div>
      <div class="pct" style="color:{{f.colour}}">{{f.pct_txt}}{% if f.recent_txt %} <span style="color:#d9822b;font-size:12px">→ {{f.recent_txt}}</span>{% endif %}</div>
      <img src="{{f.img}}">
      <div class="sub">{{f.disp}} · {{f.peer}}</div>
    </div>
    {% endfor %}
  </div>
  <div class="cap" style="text-align:left"><b style="color:{{c.ACCENT}}">Solid line = career</b>, <b style="color:#d9822b">dotted = last 3 years</b> (where enough recent balls). Percentile within same-type peers (grey = the peer distribution, line = this bowler). Release/crease vs hand × pace/spin; movement/speed/repeatability vs pace/spin. Release &amp; speed are modern-era (2017+ / partial). <b>Crease variation</b> = how much he moves his release point sideways across the crease from ball to ball (within his main angle): a high percentile = he varies where he lets the ball go a lot, a low percentile = he releases from the same spot every ball. <b>Repeatability</b> = length consistency over his stock-length band (2–11&nbsp;m, so deliberate yorkers and bouncers don't count as poor control): a high percentile = tighter, more metronomic lengths than peers; a low percentile = he varies his length more. A marker at the very edge = he sits beyond the typical peer range on that trait.</div>
  {% endif %}

  {% if recent_form %}
  <h2 class="pbreak">Current Form <span class="sub" style="font-weight:400">(last {{recent_form.n_matches}} Tests · {{recent_form.date_from}} → {{recent_form.date_to}})</span></h2>
  {% if recent_form.read %}<div class="read">{{recent_form.read|safe}}</div>{% endif %}
  <table class="mtab" style="max-width:760px">
    <tr><th>Window</th><th>Balls</th><th>Wkts</th><th>Avg</th><th>Econ</th><th>SR</th><th>False%</th><th>Avg speed</th><th>Avg length</th></tr>
    <tr class="weakrow"><td class="lab">Last {{recent_form.n_matches}} Tests</td><td>{{recent_form.recent.balls}}</td><td>{{recent_form.recent.wkts}}</td><td>{{recent_form.recent.avg}}</td><td>{{recent_form.recent.econ}}</td><td>{{recent_form.recent.sr}}</td><td>{{recent_form.recent.false}}</td><td>{{recent_form.recent.speed}}</td><td>{{recent_form.recent.length}}</td></tr>
    <tr><td class="lab">Career</td><td>{{recent_form.career.balls}}</td><td>{{recent_form.career.wkts}}</td><td>{{recent_form.career.avg}}</td><td>{{recent_form.career.econ}}</td><td>{{recent_form.career.sr}}</td><td>{{recent_form.career.false}}</td><td>{{recent_form.career.speed}}</td><td>{{recent_form.career.length}}</td></tr>
  </table>
  {% endif %}

  <h2>Threat Profile{% if video.lists.wickets %}<a class="vlink" data-pl="wickets" href="{{video.player}}#wickets">▶ watch wickets</a>{% endif %}{% if video.lists.new_ball_outswing %}<a class="vlink" data-pl="new_ball_outswing" href="{{video.player}}#new_ball_outswing">▶ new-ball swing</a>{% endif %}</h2>
  <div class="cards">
    {% for lab, val, csub in threat_cards %}
      <div class="card"><div class="lab">{{lab}}</div><div class="val">{{val}}</div>
      <div class="csub">{{csub}}</div></div>
    {% endfor %}
  </div>
  {% if dismissal_rows %}
  <div class="grid2 avoid" style="margin-top:8px;align-items:start">
    <div>
      <table class="mtab">
        <tr><th>How he gets you out</th><th>His&nbsp;%</th><th>Base</th><th>Index</th></tr>
        {% for typ, share, base, idx_txt, colour in dismissal_rows %}
        <tr><td class="lab">{{typ}}</td><td>{{share}}</td><td>{{base}}</td><td style="color:{{colour}};font-weight:700">{{idx_txt}}</td></tr>
        {% endfor %}
      </table>
      <div class="cap" style="text-align:left">Share of his {{P.n_dismissals}} wickets by type, indexed against the base rate {{dismissal_peer}} (men's Tests). <b>Index&nbsp;&gt;1</b> = he does it more than most, <b>&lt;1</b> = less. Caught is high for everyone — the signal is the over-indexed row.</div>
    </div>
    <div class="pills">
      {% if catch_positions %}<b>Catches to:</b>
        {% for k, v in catch_positions %}<span>{{k}} {{v}}</span>{% endfor %}{% endif %}
      {% if angle_variation %}<br><b>Angle &amp; variations:</b> {{angle_variation}}{% endif %}
    </div>
  </div>
  {% else %}
  <div style="margin-top:8px" class="pills">
    {% if catch_positions %}<b>Catches to:</b>
      {% for k, v in catch_positions %}<span>{{k}} {{v}}</span>{% endfor %}{% endif %}
    {% if angle_variation %}<br><b>Angle &amp; variations:</b> {{angle_variation}}{% endif %}
  </div>
  {% endif %}

  {% if ball_type_rows %}
  <h2>Stock Ball &amp; Ball Types <span class="sub" style="font-weight:400">({{hand_label}})</span>
    {% if video.lists.stock_ball %}<a class="vlink" data-pl="stock_ball" href="{{video.player}}#stock_ball">▶ watch stock balls</a>{% endif %}</h2>
  {% if stock_read %}<div class="read" style="font-weight:700;color:{{c.TEXT_PRI}};border-left:3px solid {{c.ACCENT}};padding-left:8px;margin-bottom:6px">{{stock_read|safe}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Ball type (pitch length × pitching line)</th><th>Movement</th><th>%</th><th>Econ</th><th>Wkts</th><th>Beaten %</th></tr>
    {% for row in ball_type_rows %}
    <tr><td class="lab">{{row.phrase}}{% if video.lists[row.key] %} <a class="vlink tiny" data-pl="{{row.key}}" href="{{video.player}}#{{row.key}}" title="Watch {{row.phrase}}">▶</a>{% endif %}</td><td>{{row.move}}</td><td>{{row.pct}}</td><td>{{row.econ}}</td><td>{{row.wkts}}</td><td>{{row.beat}}</td></tr>
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left;margin:4px 0 0">
    Ball type = pitch-length band × pitching-line region. <b>Movement</b> = swing in the air + seam/turn off
    the pitch, whichever is material, dominant first (ball-tracking, tracked balls only; blank if too few).
    <b>Beaten %</b> = false-shot rate on tracked balls. The stock-ball line above also notes where it passes the stumps.
  </div>
  {% if ball_age and (ball_age.new or ball_age.old) %}
  {% macro agecol(b) %}
    {% if b %}
    <div>
      <div style="font-weight:700;font-size:10.5px;margin:0 0 3px">{{b.label}} <span style="font-weight:400;color:{{c.TEXT_SEC}}">· {{b.n}} balls · {{b.wkts}} wkts · econ {{b.econ}}</span></div>
      <table class="mtab">
        <tr><th>Top ball type</th><th>%</th><th>Econ</th><th>Wkts</th></tr>
        {% for phrase, pct_, econ, wkts in b.rows %}
        <tr><td class="lab">{{phrase}}</td><td>{{pct_}}</td><td>{{econ}}</td><td>{{wkts}}</td></tr>
        {% endfor %}
      </table>
      {% if b.danger %}<div class="cap" style="text-align:left;margin-top:2px">Most lethal: <b>{{b.danger}}</b>{% if b.danger_rate %} ({{b.danger_rate}} wkts/100){% endif %}.</div>{% endif %}
    </div>
    {% endif %}
  {% endmacro %}
  <div style="font-weight:700;font-size:11px;margin:10px 0 4px;color:{{c.ACCENT}}">New ball vs old ball</div>
  <div class="grid2 avoid" style="align-items:start">
    {{ agecol(ball_age.new) }}
    {{ agecol(ball_age.old) }}
  </div>
  <div class="cap" style="text-align:left">How his ball types and threat shift with ball age (split at {{P.ball_age.split_over}} overs). Empty side = too few balls in that phase.</div>
  {% endif %}
  {% endif %}

  <h2>Danger Zones <span class="sub" style="font-weight:400">({{hand_label}})</span>{% if video.lists.danger_cell %}<a class="vlink" data-pl="danger_cell" href="{{video.player}}#danger_cell">▶ watch danger balls</a>{% endif %}</h2>
  <div class="grid2 avoid">
    {% for h, b, s, warn in danger_cards[:2] %}
      <div class="dcard {{'warn' if warn else 'plain'}}"><div class="dh">{{h}}</div>
      <div class="db">{{b}}</div><div class="ds">{{s}}</div></div>
    {% endfor %}
  </div>
  <div class="grid3 avoid" style="margin-top:8px">
    {% for h, b, s, warn in danger_cards[2:] %}
      <div class="dcard warn"><div class="dh">{{h}}</div>
      <div class="db">{{b}}</div><div class="ds">{{s}}</div></div>
    {% endfor %}
  </div>
  {% if danger_read %}<div class="read" style="margin-top:7px">{{danger_read}}</div>{% endif %}
  {% if unmapped_wkts > 0 %}<div class="cap" style="text-align:left;margin-top:4px">Zone shares are over his <b>mapped</b> wickets — {{unmapped_wkts}} wicket{{'s' if unmapped_wkts != 1 else ''}} pitched too full to place on the map (tracked length at/behind the crease), so they sit outside the grid.</div>{% endif %}
  {% if ball_age and ((ball_age.new and ball_age.new.danger) or (ball_age.old and ball_age.old.danger)) %}
  {% macro agedanger(b) %}
    {% if b %}
      <div class="dcard plain"><div class="dh">{{b.label}}</div>
        <div class="db">{% if b.danger %}{{b.danger}}{% else %}—{% endif %}</div>
        <div class="ds">{% if b.danger_rate %}most lethal cell · {{b.danger_rate}} wkts/100{% endif %}{% if b.danger_len %} · danger length {{b.danger_len.lower()}}{% endif %} · {{b.wkts}} wkts off {{b.n}} balls</div></div>
    {% endif %}
  {% endmacro %}
  <div style="font-weight:700;font-size:11px;margin:10px 0 4px;color:{{c.ACCENT}}">Danger by ball age</div>
  <div class="grid2 avoid">
    {{ agedanger(ball_age.new) }}
    {{ agedanger(ball_age.old) }}
  </div>
  {% endif %}

  {% if matchup_tables.ball or matchup_tables.position %}
  {% macro mutable(title, rows) %}
    {% if rows %}
    <div>
      <div style="font-weight:700;font-size:10.5px;margin:0 0 3px">{{title}}</div>
      <table class="mtab">
        <tr><th>Split</th><th>Balls</th><th>Wkts</th><th>Avg</th><th>Econ</th><th>SR</th><th>False%</th><th>Med length</th></tr>
        {% for lab, balls, wkts, avg, econ, sr, fs, ln in rows %}
        <tr><td class="lab">{{lab}}</td><td>{{balls}}</td><td>{{wkts}}</td><td>{{avg}}</td><td>{{econ}}</td><td>{{sr}}</td><td>{{fs}}</td><td>{{ln}}</td></tr>
        {% endfor %}
      </table>
    </div>
    {% endif %}
  {% endmacro %}
  <h2 class="pbreak">Match-ups <span class="sub" style="font-weight:400">({{hand_label}})</span></h2>
  <div class="grid2 avoid" style="align-items:start">
    {{ mutable('New ball vs old ball', matchup_tables.ball) }}
    {{ mutable('By batting position', matchup_tables.position) }}
  </div>
  {% if matchup_insight %}<div class="read" style="margin-top:6px">{{matchup_insight}}</div>{% endif %}
  <div class="cap" style="text-align:left">Lower average / higher false-shot = the match-up that suits him; higher average = where batters have got on top. Med length = his median pitch length in that split.</div>
  {% endif %}

  {% if vs_squad %}
  <h2>Vs Our Squad <span class="sub" style="font-weight:400">(simulated matchups)</span></h2>
  <div class="cap" style="text-align:left;margin-bottom:5px">From the match simulation — each pairing played out thousands of times from full Test profiles. Only the matchups that sit clearly away from this bowler's norm are listed; everyone unlisted profiles as roughly average against him. The full grid for every pairing is on the series Match-ups page.</div>
  {% if vs_squad.threats %}
  <div class="read"><b>Best matchups for him:</b>
    {% for nm, hand, avg, dis in vs_squad.threats %} {{nm}} ({{hand}}, exp avg {{avg}}{% if dis %}, {{dis}}{% endif %}){{ "," if not loop.last }}{% endfor %}.</div>
  {% endif %}
  {% if vs_squad.targets %}
  <div class="read"><b>Batters who profile on top:</b>
    {% for nm, hand, avg in vs_squad.targets %} {{nm}} ({{hand}}, exp avg {{avg}}){{ "," if not loop.last }}{% endfor %}.</div>
  {% endif %}
  {% if vs_squad.structural %}<div class="read">{{vs_squad.structural}}</div>{% endif %}
  {% if vs_squad.h2h_note %}<div class="cap" style="text-align:left;margin-top:3px">{{vs_squad.h2h_note}}</div>{% endif %}
  {% endif %}

  {% if scoring_stats %}
  <h2>Scoring Profile <span class="sub" style="font-weight:400">({{hand_label}})</span></h2>
  {% if scoring_read %}<div class="read" style="font-weight:700;color:{{c.TEXT_PRI}};border-left:3px solid {{c.ACCENT}};padding-left:8px;margin-bottom:6px">{{scoring_read}}</div>{% endif %}
  <div class="cards" style="grid-template-columns:repeat(3,1fr)">
    {% for lab, val, csub in scoring_stats %}
      <div class="card"><div class="lab">{{lab}}</div><div class="val">{{val}}</div>
      {% if csub %}<div class="csub">{{csub}}</div>{% endif %}</div>
    {% endfor %}
  </div>
  {% if scoring_rows %}
  <table class="mtab" style="margin-top:9px">
    <tr><th>Shot type</th><th>Balls</th><th>Runs</th><th>% runs</th><th>4s/6s</th><th>Runs/ball</th></tr>
    {% for fam, balls, runs, rpct, bdry, rpb in scoring_rows %}
    <tr><td class="lab">{{fam}}</td><td>{{balls}}</td><td>{{runs}}</td><td>{{rpct}}</td><td>{{bdry}}</td><td>{{rpb}}</td></tr>
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left;margin:4px 0 0">
    Direction from ball-tracking (all scoring shots); shot type recorded on {{pct(P.scoring.stroke_cov)}} of scoring balls
    ({{P.scoring.n_stroke}}/{{P.scoring.n_scoring}}) — groups with &lt;5 balls omitted.
  </div>
  {% endif %}
  {% endif %}

  <h2>Pitch Maps &amp; Scoring</h2>
  <div class="grid2 avoid">
    <div class="fig"><div class="ct">At the Stumps (wickets)</div><img class="chart bee" style="width:58%" src="{{figs.beehive}}">
      <div class="cap">{{reads.beehive or "Ball position as it passes the stumps for wicket balls."}}</div></div>
    <div class="fig"><div class="ct">Where They're Scored Off</div><img class="chart wag" style="width:66%" src="{{figs.wagon}}">
      <div class="cap">{{reads.wagon or "Where runs are scored, by fielding area."}}</div></div>
  </div>
  <div class="grid2 avoid" style="margin-top:6px">
    <div class="fig"><div class="ct">Where They Pitch It</div><img class="chart pmap" style="width:66%" src="{{figs.pitch_count}}">
      <div class="cap">{{reads.pitch_count or "Density of pitch locations — length down, line across."}}</div></div>
    <div class="fig"><div class="ct">Where Wickets Come From</div><img class="chart pmap" style="width:66%" src="{{figs.pitch_wkts}}">
      <div class="cap">{{reads.pitch_wkts or "Pitch location of wicket-taking balls."}}</div></div>
  </div>

  <h2>Speed &amp; Spells</h2>
  {% if speed_read %}<div class="read">{{speed_read}}</div>{% endif %}
  <div class="grid3 avoid">
    <div class="fig"><div class="ct">Speed by Spell</div><img class="chart" src="{{figs.violin_spell}}"><div class="cap">By spell — opening burst vs later spells.</div></div>
    <div class="fig"><div class="ct">Speed by Innings</div><img class="chart" src="{{figs.violin_inns}}"><div class="cap">1st vs 2nd innings of the match.</div></div>
    <div class="fig"><div class="ct">Speed by Day</div><img class="chart" src="{{figs.violin_day}}"><div class="cap">By match day — fatigue across the game.</div></div>
  </div>

  {% if over_round_rows %}
  <h2 class="pbreak">Over vs Round the Wicket <span class="sub" style="font-weight:400">({{hand_label}})</span></h2>
  {% if over_round_read %}<div class="read" style="font-weight:700;color:{{c.TEXT_PRI}};border-left:3px solid {{c.ACCENT}};padding-left:8px;margin-bottom:6px">{{over_round_read}}</div>{% endif %}
  <table class="mtab">
    <tr><th>Angle</th><th>Balls</th><th>Pitch line</th><th>Length</th><th>Short %</th><th>Econ</th><th>Wkts</th><th>Bdry %</th></tr>
    {% for ang, balls, line, length, short, econ, wkts, bdry in over_round_rows %}
    <tr><td class="lab">{{ang}}</td><td>{{balls}}</td><td>{{line}}</td><td>{{length}}</td><td>{{short}}</td><td>{{econ}}</td><td>{{wkts}}</td><td>{{bdry}}</td></tr>
    {% endfor %}
  </table>
  <div class="grid2 avoid" style="margin-top:6px">
    <div class="fig"><div class="ct">Over the Wicket</div><img class="chart pmap" style="width:66%" src="{{figs.over_map}}">
      <div class="cap">{% if P.over_round.over_enough %}Where he pitches it from over the wicket ({{P.over_round.over_n}} balls).{% else %}Over the wicket — only {{P.over_round.over_n}} balls to {{hand_noun}}, too few to read into.{% endif %}</div></div>
    <div class="fig"><div class="ct">Round the Wicket</div><img class="chart pmap" style="width:66%" src="{{figs.round_map}}">
      <div class="cap">{% if P.over_round.round_enough %}Where he pitches it from round the wicket ({{P.over_round.round_n}} balls).{% else %}Round the wicket — only {{P.over_round.round_n}} balls to {{hand_noun}}, too few to read into.{% endif %}</div></div>
  </div>
  {% endif %}

  {% if sequencing_read or seq_pattern_read or crease_read or wicket_setup_read %}
  <h2>Sequencing &amp; Over Construction</h2>
  {% if sequencing_read %}<div class="read" style="font-weight:700;color:{{c.TEXT_PRI}};border-left:3px solid {{c.ACCENT}};padding-left:8px;margin-bottom:6px">{{sequencing_read}}</div>{% endif %}
  {% if seq_pattern_read %}<div class="read" style="font-weight:700;color:{{c.TEXT_PRI}};border-left:3px solid {{c.DANGER}};padding-left:8px;margin-bottom:6px">{{seq_pattern_read}}</div>{% endif %}
  {% if wicket_setup_read %}<div class="read">{{wicket_setup_read}}</div>{% endif %}
  {% if sequencing_rows %}
  <table class="mtab">
    <tr><th>Ball in over</th><th>Median length</th><th>Short %</th><th>Econ</th><th>Wkt %</th></tr>
    {% for pos, length, short, econ, wkt in sequencing_rows %}
    <tr><td class="lab">{{pos}}</td><td>{{length}}</td><td>{{short}}</td><td>{{econ}}</td><td>{{wkt}}</td></tr>
    {% endfor %}
  </table>
  <div class="cap" style="text-align:left;margin:4px 0 0">
    Length spread = std-dev of pitch length (smaller = more repeatable). The table shows how his length,
    scoring and wicket rate shift across the six balls of an over. Set-up lines compare each ball with the
    previous delivery in the same over (career, all batters).
  </div>
  {% endif %}
  {% endif %}

  {% if crease_read %}
  <h2 class="pbreak">Release Point &amp; Crease Use</h2>
  <div class="read" style="font-weight:700;color:{{c.TEXT_PRI}};border-left:3px solid #15803d;padding-left:8px;margin-bottom:6px">{{crease_read}}</div>
  <div class="grid2 avoid" style="align-items:start">
    <div>
      {% if crease_band_rows %}
      <table class="mtab">
        <tr><th>Crease position</th><th>% balls</th><th>Balls</th><th>Econ</th><th>Wkts</th><th>Avg</th><th>SR</th></tr>
        {% for band, share, balls, econ, wkts, avg, sr in crease_band_rows %}
        <tr><td class="lab">{{band}}</td><td>{{share}}</td><td>{{balls}}</td><td>{{econ}}</td><td>{{wkts}}</td><td>{{avg}}</td><td>{{sr}}</td></tr>
        {% endfor %}
      </table>
      <div class="cap" style="text-align:left">How he goes when he releases tight / standard / wide of the middle stump (all release-tracked balls).</div>
      {% endif %}
      {% if crease_usage_rows %}
      <table class="mtab" style="margin-top:8px">
        <tr><th>Angle</th><th>Balls</th><th>Tight</th><th>Standard</th><th>Wide</th></tr>
        {% for angle, balls, tight, std, wide in crease_usage_rows %}
        <tr><td class="lab">{{angle}}</td><td>{{balls}}</td><td>{{tight}}</td><td>{{std}}</td><td>{{wide}}</td></tr>
        {% endfor %}
      </table>
      <div class="cap" style="text-align:left">His crease-position mix, split by over vs round. Release data is modern-era (2017+); percentiles vs same hand + type.</div>
      {% endif %}
    </div>
    {% if figs.release_map %}
    <div class="fig"><div class="ct">Release Point (behind the bowler)</div><img class="chart rel" src="{{figs.release_map}}">
      <div class="cap">Where he lets the ball go — lateral position × height (purple density). Over and round labelled; dotted lines mark tight/standard/wide and the return creases.</div></div>
    {% endif %}
  </div>
  {% endif %}

  {% if movement_rows %}
  <h2>Movement <span class="sub" style="font-weight:400">(vs the average {{P.movement.pace_spin}} bowler · {{hand_label}})</span></h2>
  {% if bowler_style %}<div class="read" style="font-weight:700;color:{{c.TEXT_PRI}};border-left:3px solid {{c.ACCENT}};padding-left:8px;margin-bottom:5px">{{bowler_style}}</div>{% endif %}
  {% if movement_read %}<div class="read">{{movement_read}}</div>{% endif %}
  {% if swing_age_read %}<div class="read">{{swing_age_read}}</div>{% endif %}
  <div class="cap" style="text-align:left;margin:0 0 6px">
    Percentile vs all Test {{P.movement.pace_spin}} bowlers; direction is which way it moves to this batter. Bounce = extra bounce vs expected.
  </div>
  <table class="mtab">
    <tr><th>Movement</th><th>Avg</th><th>vs average</th><th>Direction ({{hand_label}})</th></tr>
    {% for lbl, val, pctl, dir in movement_rows %}
    <tr><td class="lab">{{lbl}}</td><td>{{val}}</td><td>{{pctl}}</td><td>{{dir}}</td></tr>
    {% endfor %}
  </table>
  {% endif %}

  {% if figs.beaten %}
  <h2>Beaten Zones (play-and-miss)</h2>
  <div class="grid2 avoid">
    <div class="fig"><div class="ct">Beaten — Grid</div><img class="chart pmap" src="{{figs.beaten}}">
      <div class="cap">Length × line where he beats the bat — exact counts per cell.</div></div>
    <div class="fig"><div class="ct">Beaten — Heatmap</div><img class="chart pmap" src="{{figs.beaten_heat}}">
      <div class="cap">The same play-and-miss density, smoothed, with pitch markings.</div></div>
  </div>
  <div class="read" style="margin-top:6px">
    {% if miss_zone %}Beats the bat most at <b>{{miss_zone.length}} / {{miss_zone.line}}</b> ({{pct(miss_zone.share*100)}} of play-and-misses). {% endif %}
    Overall he beats the bat {{pct(P.beaten_pct,1)}} of tracked balls (false-shot {{pct(P.false_pct,1)}}, n={{'{:,}'.format(P.n_tracked)}}).
  </div>
  {% endif %}

  <div class="foot">
    Test-match career data. Beaten/false-shot use ~38% shot-quality tracking; turn/drift ~30% ball-tracking.
    Catches split by fielding position (DeliveryFielders view); some catches have no recorded position.
    Danger zones use empirical-Bayes shrinkage (≥3 wkts to qualify).
  </div>

</div></body></html>
"""
