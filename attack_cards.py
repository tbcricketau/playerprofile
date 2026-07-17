"""
attack_cards.py — "how you've been attacked" cards for OUR squad batters (ATTACK_PLANS.md §5+§8,
P2). For each squad player: derive their last 3 Test series (consecutive matches vs one opposition),
and for each series compute the opposition's pace plan against them — length/line diet cells with a
z-gate against the in-series control (same bowlers, same matches, other same-hand top-7 teammates),
plus every dismissal with its delivery id (video linkage comes in P3).

Calibrated on the two verified cases: Weatherald/Ashes (`ATTACK_PLANS_WEATHERALD.md`) and
Labuschagne (`ATTACK_PLANS_MARNUS.md`). Pace cells only in v1 — spin diet cells need the spin
group lookups (2821/2824) and their own control; spin dismissals ARE included.

Usage:
    .\\venv\\Scripts\\python.exe attack_cards.py                    # all squad players, all squads.json series
    .\\venv\\Scripts\\python.exe attack_cards.py --ids 2580027      # one player (testing)
Output: data/attack_cards.json  {player_id: {name, hand, series: [card, ...]}}
"""
import argparse
import json
import math
import os
from collections import Counter

from config import DATA_SCHEMA
from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.config import international_series_sql
from cricket_core.video import clip_stem

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "attack_cards.json")

SERIES_GAP_DAYS = 75          # consecutive Tests vs the same opposition within this gap = one series
N_SERIES = 3
# Flag = magnitude-first (consistent pace vs spin): a cell reads more/less only when the raw gap vs
# the control is at least MIN_PP percentage points AND not pure noise (|z| >= Z_SOFT). A pure z-gate
# flagged tiny pace gaps (huge n) but never a real spin gap (small n) — see ATTACK_CARDS_REDESIGN.md.
MIN_PP = 8.0                  # min percentage-point gap (you vs others) to flag a cell
Z_SOFT = 1.3                  # light reliability guard so a big gap on thin data doesn't over-claim
MIN_CELL = 5                  # min balls (player side) for a cell to be quotable

# Length collapsed to 3 reader bands (from lookup 2819): pitched up / good length / short.
LEN_UP = {"<1 m", "1-2 m", "2-5 m"}
LEN_GOOD = {"5-6 m", "6-8 m", "8-9 m"}
LEN_SHORT = {"9-10 m", "10+ m"}
# over_the_wicket: "1"/"True" = over, "0"/"False" = round the wicket (mirrors profile.is_round).
_ROUND_VALS = {"0", "False", "false"}

_TEST = (f"M.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
         f"WHERE name IN {international_series_sql('Test')})")

# Length bands (lookup 2819, fine) -> commentary names, and the band sets the composites use.
LEN_NAME = {"<1 m": "yorker length", "1-2 m": "very full", "2-5 m": "full", "5-6 m": "fullish",
            "6-8 m": "a good length", "8-9 m": "back of a length", "9-10 m": "short of a length",
            "10+ m": "short"}
LINE_NAME = {"Channel": "the channel", "Wide Outside Off": "wide of off",
             "In Line": "at the stumps", "Outside Leg": "at the pads"}
# Spin bands (lookup 2821 length / 2824 line)
SLEN_NAME = {"<4 m": "tossed up", "4-5 m": "on a good length", "5+ m": "dragged short"}
SLIN_NAME = {"Outside Off": "outside off", "Mid and Off": "middle and off",
             "Leg and Mid": "middle and leg", "Outside Leg": "outside leg"}
SHORTISH = {"8-9 m", "9-10 m", "10+ m"}
FULLISH = {"<1 m", "1-2 m", "2-5 m", "5-6 m", "6-8 m"}
HOW = {"4": "Bowled", "5": "Caught", "6": "LBW", "7": "Hit Wicket", "8": "Stumped", "9": "Run Out"}


def _f(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _is_out(r):
    return r.get("striker_dismissed") in ("1", "True", "true")


def _z(p1, n1, p2, n2):
    if not n1 or not n2:
        return 0.0
    p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or 1e-9
    return (p1 - p2) / se


def _lookup(conn, cur, type_id):
    return {r["id"]: r["description"] for r in run_query(
        f"SELECT id, description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id={type_id}", conn, cur)}


def _player_balls(conn, cur, pid):
    """All the player's Test deliveries, ball order, with opposition + the fields the card needs
    (pace AND spin pitch groups, plus clip fields for the 'more'-cell video examples)."""
    return run_query(f"""
        SELECT D.delivery_id, D.match_id, CONVERT(varchar(10), M.match_date, 120) d,
            T.team_name opp, D.legal_ball, D.bat_score, D.striker_dismissed, D.how_out_id,
            D.stroke_id, D.shot_quality_id,
            D.pitch_line_group_pace_id lin, D.pitch_length_group_pace_1_id len,
            D.pitch_line_group_spin_id slin, D.pitch_length_group_spin_1_id slen,
            D.over_the_wicket ow,
            D.bowler_pace_spin_id ps, P.surname bowler, LH.description hand,
            D.video_file_name, M.match_length_id, S.name season, SR.gender_id
        FROM [{DATA_SCHEMA}].[Deliveries] D
        JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id = M.match_id
        JOIN [{DATA_SCHEMA}].[Teams] T ON D.team_bowling_id = T.team_id
        LEFT JOIN [{DATA_SCHEMA}].[Seasons] S ON M.season_id = S.season_id
        LEFT JOIN [{DATA_SCHEMA}].[Series] SR ON M.series_id = SR.series_id
        LEFT JOIN [{DATA_SCHEMA}].[Players] P ON D.bowler_id = P.player_id
        LEFT JOIN [{DATA_SCHEMA}].[Lookups] LH ON LH.lookup_type_id = 10 AND LH.id = D.striker_hand_id
        WHERE D.striker_id = '{pid}' AND {_TEST} AND D.legal_ball = '1'
        ORDER BY M.match_date, D.match_innings, TRY_CONVERT(int, D.[over]), TRY_CONVERT(int, D.ball_in_over)
    """, conn, cur)


def _control_balls(conn, cur, pid, match_ids, hand_like):
    """Same matches, opposition (pace AND spin) to other same-hand top-7 batters — the control
    cohort. Split by `ps` (pace/spin) in build_card."""
    midlist = ",".join(f"'{m}'" for m in match_ids)
    return run_query(f"""
        SELECT D.match_id, D.bowler_pace_spin_id ps,
               D.pitch_line_group_pace_id lin, D.pitch_length_group_pace_1_id len,
               D.pitch_line_group_spin_id slin, D.pitch_length_group_spin_1_id slen,
               D.over_the_wicket ow,
               T.team_name opp
        FROM [{DATA_SCHEMA}].[Deliveries] D
        JOIN [{DATA_SCHEMA}].[Teams] T ON D.team_bowling_id = T.team_id
        LEFT JOIN [{DATA_SCHEMA}].[Lookups] LH ON LH.lookup_type_id = 10 AND LH.id = D.striker_hand_id
        WHERE D.match_id IN ({midlist}) AND D.striker_id <> '{pid}' AND D.legal_ball = '1'
          AND LH.description LIKE '{hand_like}' AND TRY_CONVERT(int, D.striker_batting_position) <= 7
    """, conn, cur)


def _clip(r):
    return clip_stem(r.get("season"), r.get("gender_id"), r.get("match_length_id"),
                     r.get("match_id"), r.get("video_file_name"))


def _derive_series(balls):
    """Group the player's matches into cricket series: consecutive matches, one opposition,
    gap < SERIES_GAP_DAYS. Returns newest-first [{opp, match_ids, d0, d1}]."""
    import datetime
    matches = []           # ordered (match_id, date, opp)
    seen = set()
    for r in balls:
        if r["match_id"] not in seen:
            seen.add(r["match_id"])
            matches.append((r["match_id"], r["d"], r["opp"]))
    series = []
    for mid, d, opp in matches:
        dt = datetime.date.fromisoformat(d)
        if series and series[-1]["opp"] == opp and (dt - series[-1]["_last"]).days < SERIES_GAP_DAYS:
            series[-1]["match_ids"].append(mid)
            series[-1]["d1"], series[-1]["_last"] = d, dt
        else:
            series.append({"opp": opp, "match_ids": [mid], "d0": d, "d1": d, "_last": dt})
    for s in series:
        s.pop("_last")
    return list(reversed(series))


def _pace_defs(LEN, LIN):
    """Pace plan cells across three orthogonal axes — angle (over/round the wicket), length (3
    reader bands) and pitching line (disambiguated from the stump line) — plus two composite danger
    balls. Redesigned per ATTACK_CARDS_REDESIGN.md so the card answers 'how did they bowl to you'."""
    defs = [
        # angle
        ("round the wicket", lambda r: str(r.get("ow")) in _ROUND_VALS),
        # length — 3 bands
        ("pitched up", lambda r: LEN.get(r["len"]) in LEN_UP),
        ("a good length", lambda r: LEN.get(r["len"]) in LEN_GOOD),
        ("short", lambda r: LEN.get(r["len"]) in LEN_SHORT),
        # pitching line (where it bounced — NOT the stump line)
        ("pitched in the channel", lambda r: LIN.get(r["lin"]) == "Channel"),
        ("pitched at the stumps", lambda r: LIN.get(r["lin"]) == "In Line"),
        ("pitched wide of off", lambda r: LIN.get(r["lin"]) == "Wide Outside Off"),
        ("pitched at your pads", lambda r: LIN.get(r["lin"]) == "Outside Leg"),
    ]
    # composite danger balls (kept — Tom likes the specificity)
    defs.append(("cut ball (short, wide off)",
                 lambda r: LEN.get(r["len"]) in LEN_SHORT
                 and LIN.get(r["lin"]) in ("Channel", "Wide Outside Off")))
    defs.append(("full at the stumps",
                 lambda r: LEN.get(r["len"]) in (LEN_UP | {"5-6 m", "6-8 m"}) and LIN.get(r["lin"]) == "In Line"))
    return defs


def _spin_defs(SLEN, SLIN):
    defs = []
    for band in ("<4 m", "4-5 m", "5+ m"):
        defs.append((SLEN_NAME.get(band, band), lambda r, b=band: SLEN.get(r["slen"]) == b))
    for grp in ("Outside Off", "Mid and Off", "Leg and Mid", "Outside Leg"):
        defs.append((SLIN_NAME.get(grp, grp), lambda r, g=grp: SLIN.get(r["slin"]) == g))
    defs.append(("tossed up outside off",
                 lambda r: SLEN.get(r["slen"]) == "<4 m" and SLIN.get(r["slin"]) in ("Outside Off", "Mid and Off")))
    defs.append(("into the pads",
                 lambda r: SLIN.get(r["slin"]) in ("Leg and Mid", "Outside Leg") and SLEN.get(r["slen"]) in ("<4 m", "4-5 m")))
    return defs


def _diet_cells(w_balls, c_balls, defs, floor_w=60, floor_c=120):
    """Plan table for one bowler family: pct vs the in-series control per cell, with a flag
    (more/less/even/thin). For 'more' cells it bakes a few example clip stems (recent, with video)
    so the reader can watch where they went at them. Returns [] if the sample is too thin."""
    out = []
    nw, nc = len(w_balls), len(c_balls)
    if nw < floor_w or nc < floor_c:
        return out
    for label, pred in defs:
        matched = [r for r in w_balls if pred(r)]
        cw, cc = len(matched), sum(1 for r in c_balls if pred(r))
        p1, p2 = cw / nw, cc / nc
        z = _z(p1, nw, p2, nc)
        expected = cc * nw / nc
        diff_pp = abs(p1 - p2) * 100                  # magnitude-first: the raw gap, in points
        if cw < 3 and expected < 3:
            flag = "thin"
        elif diff_pp >= MIN_PP and abs(z) >= Z_SOFT and max(cw, expected) >= MIN_CELL:
            flag = "more" if p1 > p2 else "less"
        else:
            flag = "even"
        cell = {"label": label, "pct": round(100 * p1, 1), "ctrl_pct": round(100 * p2, 1),
                "z": round(z, 1), "flag": flag}
        if flag == "more":                       # video examples of the cell they went at
            ex = [{"delivery_id": r["delivery_id"], "clip_stem": _clip(r)}
                  for r in reversed(matched) if _clip(r)]
            if ex:
                cell["examples"] = ex[:6]
        out.append(cell)
    return out


# Cell label -> how it reads inside "bowled you more/less …". Numbers live in the table, not here.
_PROSE = {
    "yorker length": "at yorker length", "very full": "very full", "full": "full",
    "fullish": "fullish", "a good length": "on a good length",
    "back of a length": "back of a length", "short of a length": "short of a length",
    "short": "short", "the channel": "in the channel", "wide of off": "wide of off",
    "at the stumps": "at the stumps", "on leg": "at {poss} pads",
    "cut ball (short, wide off)": "with the width to cut",
    "full at the stumps": "full and straight",
}


def _join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


SPIN_PROSE = {"tossed up": "tossed up", "on a good length": "on a good length",
              "dragged short": "dragged short", "outside off": "outside off",
              "middle and off": "at middle and off", "middle and leg": "at middle and leg",
              "outside leg": "outside leg", "tossed up outside off": "tossed up outside off",
              "into the pads": "into {poss} pads"}


# person-relative pronouns: OUR squad packs read "you/your", opposition reports read "them/their"
_PRON = {"you": ("you", "your", "your teammates"),
         "them": ("them", "their", "the other top-order batters")}


def _diet_sentence(cells, prose, person="you"):
    """One sentence: the more/less cells that cleared the gate. The table carries the numbers.
    `person` = "you" (our squad packs) or "them" (opposition reports)."""
    subj, poss, peers = _PRON.get(person, _PRON["you"])
    ranked = sorted([c for c in cells if c["flag"] in ("more", "less")], key=lambda c: -abs(c["z"]))
    pos = [prose.get(c["label"], c["label"]).format(poss=poss) for c in ranked if c["flag"] == "more"][:3]
    neg = [prose.get(c["label"], c["label"]).format(poss=poss) for c in ranked if c["flag"] == "less"][:3]
    if pos and neg:
        return f"They bowled {subj} more {_join(pos)}, and less {_join(neg)}."
    if pos:
        return f"They bowled {subj} more {_join(pos)} than {peers}."
    if neg:
        return f"They bowled {subj} less {_join(neg)} than {peers}."
    return f"They bowled to {subj} as they bowled to {peers}."


def _spin_summary(spin_cells, person="you"):
    return _diet_sentence(spin_cells, SPIN_PROSE, person) if spin_cells else None


# length band -> verb when it's the dominant band vs when they went there MORE than the cohort
_LEN_DOM = {"pitched up": "pitched it up", "a good length": "stuck to a good length", "short": "went short"}
_LEN_MORE = {"pitched up": "pitched it up", "a good length": "hit a good length", "short": "banged it in short"}
# pitching-line label -> the natural "target" phrase (the {poss} is person-swapped)
_LINE_PHRASE = {"pitched at the stumps": "at {poss} stumps", "pitched in the channel": "in the channel",
                "pitched wide of off": "wide of off", "pitched at your pads": "at {poss} pads"}


def _pace_read(cells, person="you"):
    """The 'how did they bowl to you' sentence — angle → length → target. Leads with the axes the
    opposition leaned on against this batter (a flagged 'more'), else describes the dominant pattern.
    Returns None if there's nothing to say (no length data)."""
    _s, poss, _p = _PRON.get(person, _PRON["you"])
    by = {c["label"]: c for c in cells}
    pct = lambda l: by.get(l, {}).get("pct", 0)
    flag = lambda l: by.get(l, {}).get("flag", "even")

    # angle — only mention it when it's a feature (leaned on, or clearly the stock angle)
    round_pct = pct("round the wicket")
    if flag("round the wicket") == "more" or round_pct >= 45:
        angle = "came round the wicket and "
    elif round_pct and round_pct <= 8:
        angle = "stayed over the wicket, "
    else:
        angle = ""

    # length — a flagged 'more' band wins, else the modal band
    len_labels = ["pitched up", "a good length", "short"]
    if not any(pct(l) for l in len_labels):
        return None
    more_len = [l for l in len_labels if flag(l) == "more"]
    if more_len:
        length = _LEN_MORE[more_len[0]]
    else:
        modal = max(len_labels, key=pct)
        length = _LEN_DOM[modal]

    # line target — a flagged 'more' line wins, else the modal line
    line_labels = ["pitched at the stumps", "pitched in the channel", "pitched wide of off", "pitched at your pads"]
    more_line = [l for l in line_labels if flag(l) == "more"]
    tgt = (more_line[0] if more_line else max(line_labels, key=pct))
    line = _LINE_PHRASE[tgt].format(poss=poss)
    return f"They {angle}{length} {line}."


def _summary(cells, outs_detail, person="you"):
    """The pace read ('how did they bowl to you'), then the dismissals. The table carries the numbers."""
    s1 = _pace_read(cells, person) if cells else ""     # thin pace → no read, just the dismissals
    if not outs_detail:
        return (s1 + " Not dismissed in the series.").strip()
    modes = Counter(o["how"] for o in outs_detail)
    mode_str = _join([f"{n} {m if m == 'LBW' else m.lower()}" for m, n in modes.most_common()])
    n = len(outs_detail)
    s2 = f"{n} dismissal{'s' if n != 1 else ''} — {mode_str}"
    locs = Counter((o["length"], o["line"]) for o in outs_detail if o["length"] and o["line"])
    if locs:
        (ln, li), c = locs.most_common(1)[0]
        if c >= 2 and c / n >= 0.4:
            s2 += f", the wicket ball most often {ln}, {li}"
    strokes = Counter(o["stroke"] for o in outs_detail if o.get("stroke") and o["stroke"] not in ("None", "No Shot"))
    if strokes:
        stk, c = strokes.most_common(1)[0]
        if c >= 2 and c / n >= 0.4:
            s2 += f", playing the {stk.lower()}"
    return (s1 + " " + s2).strip() + "."


def build_card(conn, cur, pid, name, LEN, LIN, STK, SLEN, SLIN, person="you"):
    balls = _player_balls(conn, cur, pid)
    if not balls:
        return None
    hand = Counter(str(r["hand"]) for r in balls).most_common(1)[0][0]
    hand_like = "%eft%" if "eft" in hand.lower() else "%ight%"
    pdefs, sdefs = _pace_defs(LEN, LIN), _spin_defs(SLEN, SLIN)
    cards = []
    for s in _derive_series(balls)[:N_SERIES]:
        sb = [r for r in balls if r["match_id"] in s["match_ids"]]
        pace = [r for r in sb if r["ps"] == "1"]
        spin = [r for r in sb if r["ps"] == "2"]
        runs = sum(int(_f(r["bat_score"], 0)) for r in sb)
        outs = [r for r in sb if _is_out(r)]
        ctrl = [r for r in _control_balls(conn, cur, pid, s["match_ids"], hand_like)
                if r["opp"] == s["opp"]]
        ctrl_pace = [r for r in ctrl if r["ps"] == "1"]
        ctrl_spin = [r for r in ctrl if r["ps"] == "2"]
        outs_detail = [{
            "how": HOW.get(r["how_out_id"], "?"), "bowler": r["bowler"],
            "stroke": STK.get(r["stroke_id"], None),
            "length": LEN_NAME.get(LEN.get(r["len"], ""), None),
            "line": LINE_NAME.get(LIN.get(r["lin"], ""), None),
            "pace_spin": "pace" if r["ps"] == "1" else ("spin" if r["ps"] == "2" else None),
            "date": r["d"], "delivery_id": r["delivery_id"],
            "clip_stem": _clip(r)} for r in outs]
        cells = _diet_cells(pace, ctrl_pace, pdefs)
        spin_cells = _diet_cells(spin, ctrl_spin, sdefs, floor_w=40, floor_c=80)
        cards.append({
            "opp": s["opp"].replace(" M", ""), "d0": s["d0"], "d1": s["d1"],
            "tests": len(s["match_ids"]), "balls": len(sb),
            "pace_balls": len(pace), "spin_balls": len(spin),
            "runs": runs, "outs": len(outs),
            "avg": round(runs / len(outs), 1) if outs else None,
            "spin_share": round(100 * len(spin) / len(sb)) if sb else 0,
            "ctrl_balls": len(ctrl), "cells": cells, "spin_cells": spin_cells,
            "dismissals": outs_detail,
            "summary": _summary(cells, outs_detail, person),
            "spin_summary": _spin_summary(spin_cells, person),
        })
    return {"name": name, "hand": hand, "series": cards}


_LOOKUP_CACHE = None


def card_for(pid, name=None, person="them"):
    """One-call attack card for ANY batter (ours or opposition) — used by batting_report to
    render 'how attacks bowl to them, last 3 series'. Opens its own connection.
    `person` defaults to "them": these are opposition batters in a scouting/player-mode report."""
    global _LOOKUP_CACHE
    conn, cur = set_conn_cursor()
    if _LOOKUP_CACHE is None:
        _LOOKUP_CACHE = (_lookup(conn, cur, 2819), _lookup(conn, cur, 2823), _lookup(conn, cur, 24),
                         _lookup(conn, cur, 2821), _lookup(conn, cur, 2824))
    if not name:
        r = run_query(f"SELECT TOP 1 name, surname FROM [{DATA_SCHEMA}].[Players] "
                      f"WHERE player_id='{pid}'", conn, cur)
        name = f"{r[0]['name']} {r[0]['surname']}" if r else str(pid)
    card = build_card(conn, cur, str(pid), name, *_LOOKUP_CACHE, person=person)
    conn.close()
    return card


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="*", help="restrict to these player ids (testing)")
    args = ap.parse_args()
    players = json.load(open(os.path.join(HERE, "players.json"), encoding="utf-8"))
    ids = args.ids or list(players)
    conn, cur = set_conn_cursor()
    LEN = _lookup(conn, cur, 2819)
    LIN = _lookup(conn, cur, 2823)
    STK = _lookup(conn, cur, 24)
    SLEN = _lookup(conn, cur, 2821)
    SLIN = _lookup(conn, cur, 2824)
    out = {}
    for pid in ids:
        name = players.get(pid, {}).get("name", pid)
        card = build_card(conn, cur, pid, name, LEN, LIN, STK, SLEN, SLIN)
        if card:
            out[pid] = card
            n = len(card["series"])
            print(f"  {name:<22} {n} series: " + " | ".join(
                f"v {c['opp']} ({c['tests']}T, pace {len(c['cells'])}c/spin {len(c['spin_cells'])}c)" for c in card["series"]))
        else:
            print(f"  {name:<22} no Test deliveries — no card")
    conn.close()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"\nwrote {OUT} ({len(out)} players)")


if __name__ == "__main__":
    main()
