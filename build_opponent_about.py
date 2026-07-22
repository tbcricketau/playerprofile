"""
build_opponent_about.py — distil each opposition player's SCOUTING profile into a few plain
facts for the player packs. Players want "what is this bowler/batter about?", not a simulation
(Tom, 2026-07-16) — the full scouting reports have it but are too detailed, so we condense.

For each opposition bowler: type + pace, stock ball, where the wickets come, movement.
For each opposition batter: how they score, pace vs spin, how they get out, early vs set.

Source = the same profile builders the scouting reports use (report.build_profile /
batter_profile.build_batter_profile). Cached to data/opponent_about_{opp}.json; read by
build_player_site. Opponents come from the series matchup store's rosters.

Run:  .\\venv\\Scripts\\python.exe build_opponent_about.py --opp bangladesh
"""
import argparse
import json
import os
import warnings
from collections import Counter

warnings.filterwarnings("ignore")

from cricket_core.config import project_path, international_series_sql
from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.video import clip_stem
from config import DATA_SCHEMA
from report import build_profile
from batter_profile import build_batter_profile
from batting_report import card_summary
from profile import _LEN_ADJ, _LINE_REGION, _LEN_BAND, _zone_lbl, LENGTH_ZONES_PACE

HERE = os.path.dirname(os.path.abspath(__file__))
_AREA = {"off": "through the off side", "leg": "through the leg side", "straight": "down the ground"}

# Below this many Test balls in the relevant role, fall back to the player's ALL-FORMAT record for
# the format-ROBUST facts only (CROSSFORMAT_TRANSLATION.md: pace/line/length/shot translate; average,
# strike rate, economy, wicket-rate do NOT — so the fallback never quotes those).
TEST_FLOOR = 300
_TEST = (f"M.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
         f"WHERE name IN {international_series_sql('Test')})")
# false-shot ids (lookup 2811), matching the batting profile's convention
_FALSE_SQ = {"2", "3", "4", "6", "10", "14", "17", "21", "25", "26", "28"}


def distil_bowler(P, type_label):
    facts = []
    if P.get("avg_spd"):
        if P.get("is_pace"):
            facts.append(f"{type_label} — averages {P['avg_spd']:.0f} km/h, tops {P['max_spd_99']:.0f}.")
        else:                                            # spin: average + the pace range they work in
            p05, p95 = P.get("speed_p05"), P.get("speed_p95")
            rng = f", ranges {p05:.0f}–{p95:.0f}" if (p05 and p95) else ""
            facts.append(f"{type_label} — averages {P['avg_spd']:.0f} km/h{rng}.")
    else:
        facts.append(f"{type_label}.")
    bt = P.get("ball_types") or {}
    st = bt.get("stock")
    if st and st.get("phrase"):
        facts.append(f"Stock ball: {st['phrase']} ({st['pct']:.0f}% of what they bowl).")
    # over vs round-the-wicket stock, for pace — noted only when they bowl round enough to matter
    orr = P.get("over_round")
    if P.get("is_pace") and orr:
        over_p = _angle_phrase(orr.get("over")) if orr.get("over_enough") else None
        round_p = (_angle_phrase(orr.get("round"))
                   if orr.get("round_enough") and (orr.get("round_share") or 0) >= 12 else None)
        if over_p and round_p and over_p != round_p:   # only note it when the angles differ
            facts.append(f"By angle — over the wicket, {over_p}; round the wicket, {round_p}.")
        elif round_p and round_p != (st.get("phrase") if st else None):
            facts.append(f"Round the wicket, their stock ball is {round_p}.")
    dlen, dline = P.get("danger_length"), P.get("danger_line")
    if dlen and dlen.get("length"):
        where = f", around {dline['line'].lower()}" if dline and dline.get("line") else ""
        facts.append(f"Takes most of their wickets {dlen['length'].lower()}{where}.")
    if P.get("is_pace") and st and (st.get("swing_mag") or 0) >= 0.6:
        facts.append("Gets the ball to swing — watch the ball in the air.")
    return {"type": type_label, "is_pace": bool(P.get("is_pace")),
            "facts": facts, "order": int(P.get("n_balls") or 0)}


def distil_batter(P, hand):
    facts = []
    sg = P.get("shot_groups") or []
    dp = P.get("dir_pct") or {}
    if sg:
        top = sg[0]["name"].lower()
        if dp:
            area = _AREA[max(dp, key=dp.get)]
            facts.append(f"Scores mainly {area}; go-to shot is the {top}.")
        else:
            facts.append(f"Main scoring shot is the {top}.")
    w = P.get("weakness")
    if w == "spin":
        facts.append("Weaker against spin than pace.")
    elif w == "pace":
        facts.append("Handles spin well — pace is the more likely way through.")
    dis = P.get("dismissals")
    n = P.get("n_dismissals") or 0
    if dis and n:
        mode, c = dis.most_common(1)[0]
        facts.append(f"Most often out {mode.lower()} ({c / n * 100:.0f}% of dismissals).")
    ph = P.get("phase") or {}
    e, s = ph.get("early"), ph.get("set")
    if e and s and e.get("dismissal_per100") and s.get("dismissal_per100"):
        if e["dismissal_per100"] >= 1.4 * s["dismissal_per100"]:
            facts.append("Vulnerable early — worth attacking in their first 30 balls.")

    # type-scoped facts (a pace bowler's pack shows only pace; a spinner's only spin)
    vs = P.get("vs") or {}

    def type_facts(t):
        v = vs.get(t)
        if not v or not v.get("avg"):
            return []
        line = f"Vs {t}: averages {v['avg']:.0f} at a strike rate of {v['sr']:.0f}"
        if v.get("false_pct"):
            line += f", false-shot {v['false_pct']:.0f}%"
        out = [line + "."]
        sg = P.get("shot_groups") or []
        if sg:
            out.append(f"Main scoring shot is the {sg[0]['name'].lower()}.")
        return out

    return {"hand": hand, "facts": facts, "order": int(P.get("runs") or 0),
            "facts_pace": type_facts("pace"), "facts_spin": type_facts("spin")}


def _q(conn, cur, sql):
    return run_query(sql, conn, cur)


_CLIP_COLS = ("D.delivery_id, D.video_file_name, D.match_id, M.match_length_id, "
              "S.name season, SR.gender_id")
_CLIP_JOINS = (f"JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id "
               f"LEFT JOIN [{DATA_SCHEMA}].[Seasons] S ON M.season_id=S.season_id "
               f"LEFT JOIN [{DATA_SCHEMA}].[Series] SR ON M.series_id=SR.series_id")


def _stems(rows):
    out = [{"delivery_id": r["delivery_id"],
            "clip_stem": clip_stem(r.get("season"), r.get("gender_id"), r.get("match_length_id"),
                                   r.get("match_id"), r.get("video_file_name"))} for r in rows]
    return [x for x in out if x["clip_stem"]]


def _has_vid(r):
    return r.get("video_file_name") not in (None, "None", "none", "", "nan")


def _clips_from_rows(rows, cap):
    """Newest-first clip stems for a set of profile delivery rows (they already carry
    season / gender / match / video for clip_stem). Capped at `cap`."""
    rows = sorted(rows, key=lambda r: r.get("match_date") or "", reverse=True)
    out = []
    for r in rows:
        cs = clip_stem(r.get("season"), r.get("gender_id"), r.get("match_length_id"),
                       r.get("match_id"), r.get("video_file_name"))
        if cs:
            out.append({"delivery_id": r.get("delivery_id"), "clip_stem": cs})
        if len(out) >= cap:
            break
    return out


def bowler_clips_from_profile(P, cap_each=10, wcap=40):
    """(stock_clips, wicket_clips) built from the profile's coordinate-tagged rows, so the
    example clips match the card's 'Stock ball' phrase. Pace stock samples BOTH angles (the
    over-modal ball type + the round-modal ball type when they bowl round enough), combined
    into one playlist. Wickets pull a generous pool (wcap) so more survive the storage filter."""
    df = P.get("df") or []
    wicket = _clips_from_rows([r for r in df if r.get("is_wicket") and _has_vid(r)], wcap)
    legal = [r for r in df if r.get("is_legal") and r.get("ball_type") and _has_vid(r)]
    if P.get("is_pace"):
        over = [r for r in legal if r.get("is_round") is False]
        rnd = [r for r in legal if r.get("is_round") is True]
        ot = Counter(r["ball_type"] for r in over).most_common(1)
        rt = Counter(r["ball_type"] for r in rnd).most_common(1)
        stock = _clips_from_rows([r for r in over if ot and r["ball_type"] == ot[0][0]], cap_each)
        if rt and len(rnd) >= 30:                    # a genuine round-the-wicket tactic
            stock += _clips_from_rows([r for r in rnd if r["ball_type"] == rt[0][0]], cap_each)
    else:
        st = (P.get("ball_types") or {}).get("stock")
        key = (st["band"], st["region"]) if st else None
        stock = _clips_from_rows([r for r in legal if key and r["ball_type"] == key], cap_each * 2)
    return stock, wicket


def _angle_phrase(ms):
    """Natural 'a good length in the channel' phrase for one angle's modal ball (over/round),
    from _mode_stats output — matches the coordinate stock phrasing, not the raw group ids."""
    if not ms:
        return None
    region = _LINE_REGION.get(ms.get("modal_zone") or "")
    L = ms.get("med_len")
    band = _LEN_BAND.get(_zone_lbl(L, LENGTH_ZONES_PACE) or "") if L is not None else None
    if not region or not band:
        return None
    return f"{_LEN_ADJ.get(band, band.lower())} {region}"


def batter_clips(conn, cur, bid, cap=40):
    """(scoring_clips, dismissal_clips) — example Test deliveries with video where the batter scores
    a boundary (how they score) and where they were dismissed (how they get out). Newest first."""
    scoring = _stems(_q(conn, cur, f"""SELECT TOP {cap} {_CLIP_COLS}
        FROM [{DATA_SCHEMA}].[Deliveries] D {_CLIP_JOINS}
        WHERE D.striker_id='{bid}' AND D.legal_ball=1 AND {_TEST} AND D.video_file_name IS NOT NULL
          AND D.bat_score IN ('4','6')
        ORDER BY M.match_date DESC"""))
    dismissal = _stems(_q(conn, cur, f"""SELECT TOP {cap} {_CLIP_COLS}
        FROM [{DATA_SCHEMA}].[Deliveries] D {_CLIP_JOINS}
        WHERE D.striker_id='{bid}' AND D.striker_dismissed='1' AND {_TEST} AND D.video_file_name IS NOT NULL
        ORDER BY M.match_date DESC"""))
    return scoring, dismissal


def _test_balls(conn, cur, bid, role):
    """Legal Test balls the player has bowled ('bowl') or faced ('bat')."""
    col = "bowler_id" if role == "bowl" else "striker_id"
    r = _q(conn, cur, f"SELECT COUNT(*) n FROM [{DATA_SCHEMA}].[Deliveries] D "
                      f"JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id "
                      f"WHERE D.{col}='{bid}' AND D.legal_ball=1 AND {_TEST}")
    return int(float(r[0]["n"] or 0)) if r else 0


def _mode(rows, key):
    from collections import Counter
    c = Counter(r[key] for r in rows if r.get(key) not in (None, "None", ""))
    return c.most_common(1)[0][0] if c else None


def allfmt_bowler_facts(conn, cur, bid, type_label, LEN, LIN):
    """Format-robust bowler facts from ALL formats (type, pace, stock line/length) — labelled.
    No economy/average/wicket-rate (those don't translate across formats)."""
    rows = _q(conn, cur, f"""SELECT TRY_CONVERT(float, D.ball_speed) spd,
        D.pitch_length_group_pace_1_id len, D.pitch_line_group_pace_id lin,
        D.bowler_pace_spin_id ps
        FROM [{DATA_SCHEMA}].[Deliveries] D WHERE D.bowler_id='{bid}' AND D.legal_ball=1""")
    if len(rows) < 150:
        return None
    is_pace = _mode(rows, "ps") == "1"
    spds = [float(r["spd"]) for r in rows if r.get("spd") not in (None, "None", "")]
    facts = []
    if is_pace and len(spds) >= 60:
        facts.append(f"{type_label} — averages {sum(spds)/len(spds):.0f} km/h.")
    else:
        facts.append(f"{type_label}.")
    ln, li = LEN.get(_mode(rows, "len")), LIN.get(_mode(rows, "lin"))
    if ln and li:
        facts.append(f"Usually {ln.lower()} in the {li.lower() if 'line' not in li.lower() else li.lower()}.")
    facts.append("Limited Test record — the above is from all formats they've played.")
    return {"type": type_label, "is_pace": is_pace, "facts": facts, "order": len(rows), "source": "all-formats"}


def allfmt_batter_facts(conn, cur, bid, hand, STK, SQ):
    """Format-robust batter facts from ALL formats (main shot, scoring side, pace/spin false-shot)
    — labelled. No average / strike rate (they don't translate)."""
    rows = _q(conn, cur, f"""SELECT D.stroke_id, D.shot_quality_id sq, D.bowler_pace_spin_id ps,
        TRY_CONVERT(int, D.bat_score) runs, D.hit_to_angle ang
        FROM [{DATA_SCHEMA}].[Deliveries] D WHERE D.striker_id='{bid}' AND D.legal_ball=1""")
    if len(rows) < 200:
        return None
    facts = []
    # main scoring shot (by runs)
    from collections import Counter
    sc = Counter()
    for r in rows:
        s = STK.get(r["stroke_id"])
        if s and s not in ("None", "No Shot", "Leave"):
            sc[s] += int(r["runs"] or 0)
    if sc:
        facts.append(f"Main scoring shot is the {sc.most_common(1)[0][0].lower()}.")
    # false-shot vs pace vs spin
    def false_rate(psval):
        sub = [r for r in rows if r["ps"] == psval and r.get("sq") not in (None, "None", "")]
        if len(sub) < 80:
            return None
        return 100.0 * sum(1 for r in sub if str(r["sq"]) in _FALSE_SQ) / len(sub)
    fp, fs = false_rate("1"), false_rate("2")
    if fp is not None and fs is not None:
        weaker = "spin" if fs > fp + 1.5 else ("pace" if fp > fs + 1.5 else None)
        if weaker:
            facts.append(f"Plays {'pace' if weaker=='spin' else 'spin'} more securely — "
                         f"more false shots against {weaker}.")
    facts.append("Limited Test record — the above is from all formats they've played.")
    return {"hand": hand, "facts": facts, "order": len(rows), "source": "all-formats",
            "facts_pace": facts, "facts_spin": facts}


# batting-order role from the batter's most common Test position (counted by innings, not balls, so
# a top-order batter who faces more balls doesn't skew it). 1–2 opener · 3–4 top · 5–7 middle · 8+ tail.
_ROLE_BANDS = ((2, "Opener"), (4, "Top order"), (7, "Middle order"), (99, "Lower order"))


def batter_role(conn, cur, bid):
    r = _q(conn, cur, f"""SELECT TOP 1 pos, COUNT(*) n FROM (
            SELECT TRY_CONVERT(int, D.striker_batting_position) pos, D.match_id, D.match_innings
            FROM [{DATA_SCHEMA}].[Deliveries] D JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id
            WHERE D.striker_id='{bid}' AND {_TEST} AND TRY_CONVERT(int, D.striker_batting_position) BETWEEN 1 AND 11
            GROUP BY TRY_CONVERT(int, D.striker_batting_position), D.match_id, D.match_innings) t
        GROUP BY pos ORDER BY COUNT(*) DESC""")
    if not r or r[0].get("pos") in (None, "None"):
        return None
    pos = int(r[0]["pos"])
    return next((lbl for hi, lbl in _ROLE_BANDS if pos <= hi), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    ap.add_argument("--clips-only", action="store_true",
                    help="only add stock/wicket example clips to the existing json (fast, no re-profile)")
    args = ap.parse_args()

    dst = os.path.join(HERE, "data", f"opponent_about_{args.opp}.json")
    if args.clips_only:
        out = json.load(open(dst, encoding="utf-8"))
        conn, cur = set_conn_cursor()
        for bid, entry in out.get("bowlers", {}).items():
            try:                                          # re-profile so clips match the stock phrase
                st, wk = bowler_clips_from_profile(build_profile(bid, hand="All"))
                entry["stock_clips"], entry["wicket_clips"] = st, wk
                print(f"  bowler {entry.get('name', bid):<20} stock {len(st)} · wicket {len(wk)}")
            except Exception as e:
                print(f"  ! bowler {entry.get('name', bid)}: {type(e).__name__}: {e}")
        for bid, entry in out.get("batters", {}).items():
            sc, ds = batter_clips(conn, cur, bid)
            entry["scoring_clips"], entry["dismissal_clips"] = sc, ds
            print(f"  batter {entry.get('name', bid):<20} scoring {len(sc)} · dismissal {len(ds)}")
        conn.close()
        json.dump(out, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(f"updated {dst} with example clips")
        return

    p = os.path.join(project_path("matchupmodel"), "data", f"matchup_store_{args.opp}.json")
    store = json.load(open(p, encoding="utf-8"))
    bowlers = {c["bowler_id"]: (c["bowler"], c.get("bowler_type", "")) for c in store["we_bat"]}
    batters = {c["batter_id"]: (c["batter"], c.get("bat_hand", "")) for c in store["they_bat"]}

    conn, cur = set_conn_cursor()
    LEN = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2819")}
    LIN = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2823")}
    STK = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=24")}
    SQ = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2811")}

    out = {"opp": args.opp, "bowlers": {}, "batters": {}}
    for bid, (nm, ty) in bowlers.items():
        try:
            if _test_balls(conn, cur, bid, "bowl") >= TEST_FLOOR:
                P = build_profile(bid, hand="All")
                entry = {"name": nm, **distil_bowler(P, ty or "Bowler")}
                entry["stock_clips"], entry["wicket_clips"] = bowler_clips_from_profile(P)
                out["bowlers"][bid] = entry
                tag = f" · stock {len(entry['stock_clips'])} wkt {len(entry['wicket_clips'])}"
            else:                                        # thin Test record -> all-format fallback
                fb = allfmt_bowler_facts(conn, cur, bid, ty or "Bowler", LEN, LIN)
                if not fb:
                    continue
                out["bowlers"][bid] = {"name": nm, **fb}
                tag = " [all-formats fallback]"
            print(f"  bowler {nm}: {len(out['bowlers'][bid]['facts'])} facts{tag}")
        except Exception as e:
            print(f"  ! bowler {nm}: {type(e).__name__}: {e}")
    for bid, (nm, hand) in batters.items():
        try:
            if _test_balls(conn, cur, bid, "bat") >= TEST_FLOOR:
                out["batters"][bid] = {"name": nm, **distil_batter(build_batter_profile(bid), hand)}
                # card facts = the report's TL;DR summary (richer than distil; coach matchup dropped)
                for tw in ("pace", "spin"):
                    try:
                        pts = card_summary(bid, tw, include_matchup=False)
                        if pts:
                            out["batters"][bid][f"facts_{tw}"] = pts
                    except Exception as e:
                        print(f"  ! card summary {nm} ({tw}): {type(e).__name__}: {str(e)[:60]}")
                sc, ds = batter_clips(conn, cur, bid)
                out["batters"][bid]["scoring_clips"], out["batters"][bid]["dismissal_clips"] = sc, ds
                tag = f" · sco {len(sc)} dsm {len(ds)}"
            else:
                fb = allfmt_batter_facts(conn, cur, bid, hand, STK, SQ)
                if not fb:
                    continue
                out["batters"][bid] = {"name": nm, **fb}
                tag = " [all-formats fallback]"
            out["batters"][bid]["role"] = batter_role(conn, cur, bid)   # opener/top/middle/lower
            print(f"  batter {nm}: {len(out['batters'][bid]['facts'])} facts{tag}")
        except Exception as e:
            print(f"  ! batter {nm}: {type(e).__name__}: {e}")
    conn.close()

    dst = os.path.join(HERE, "data", f"opponent_about_{args.opp}.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {dst}: {len(out['bowlers'])} bowlers, {len(out['batters'])} batters")


if __name__ == "__main__":
    main()
