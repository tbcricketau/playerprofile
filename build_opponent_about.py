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

from cricket_core.config import project_path, international_series_sql, series_sql
from cricket_core.warehouse import set_conn_cursor, run_query
from cricket_core.charts import is_tracked_length   # one estate-wide definition of "measured"
from cricket_core.lookups import BOWLER_TYPE_OVERRIDE, BOWLER_TYPE_LABEL, bowler_type_label
# The estate's phase vocabulary, so the over bands are defined once rather than restated here.
# ⚠ As of 2026-09-17 these live in an UNCOMMITTED change to cricket-core (another session's work,
# also consumed by videobuilder). If that change is reverted this import fails loudly on the next
# build, which is the right failure: a second local copy of the bands is how two definitions of
# "the death overs" start to drift apart.
from cricket_core.formats import phase_bands, PHASE_LABEL
from cricket_core.video import clip_stem
from config import DATA_SCHEMA, AMBIDEXTROUS_BOWLERS
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
    nb = P.get("new_ball_share")
    if P.get("is_pace") and nb is not None:
        if nb >= 45:
            facts.append("Usually takes the new ball.")
        elif nb >= 25:
            facts.append("Often takes the new ball.")
    pt = P.get("primary_type") or ""
    return {"type": type_label, "is_pace": bool(P.get("is_pace")),
            "arm": "left" if "Left" in pt else "right",            # for the over/round-by-hand card point
            "round_lhb": P.get("round_lhb"), "round_rhb": P.get("round_rhb"),
            "new_ball": P.get("new_ball_share"),                    # % of innings they take the new ball
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
    """Playable clip references for a set of rows. A Fairplay delivery yields a `clip_stem`
    (resolved with a fresh SAS at bake time); a Cricket-21 one yields a finished `url`, because
    C21 serves its own clips and there is nothing to resolve. See c21_source.clip_ref."""
    import c21_source
    out = []
    for r in rows:
        ref = c21_source.clip_ref(r, clip_stem(
            r.get("season"), r.get("gender_id"), r.get("match_length_id"),
            r.get("match_id"), r.get("video_file_name")))
        if ref:
            out.append({"delivery_id": r["delivery_id"], **ref})
    return out


def _has_vid(r):
    """Does this delivery have footage anywhere — Fairplay or Cricket-21?"""
    return (r.get("video_file_name") not in (None, "None", "none", "", "nan")
            or r.get("c21_video_url") not in (None, "None", "none", "", "nan"))


# A video_file_name is not footage. The warehouse names a clip for every coded ball whether or not
# Fairplay ever stored one, and Zimbabwe's record is mostly unclipped: almost nothing before 2022-23,
# and two of the three Bangladesh ODIs in July 2026. Taking the newest N named balls filled reels
# with clips that could not play, build_player_site dropped them at bake time, and the buttons
# vanished — Wellington Masakadza had 20 stock clips to left-handers stored and none that played,
# while older ODI balls and 127 T20I balls to left-handers did. A reel is built from clips that PLAY.
PROBE_CLIPS = True
_MATCH_PROBE = {}          # match folder -> [hits, misses]
_MATCH_MISS_LIMIT = 3      # this many misses and no hit = the match was never clipped


def _require_fairplay():
    """Fail the build if a Fairplay SAS cannot be minted.

    _plays reads "no SAS" as "the clip is not in storage", so a credential failure silently rewrites
    every reel to Cricket-21 clips and whatever was already cached. On 2026-09-13 the device-code
    credential hit a stale lock eleven times during a clips-only rebuild and the reels came out
    SHORTER than they went in: Sikandar Raza's wicket balls to left-handers 14 -> 3, Brad Evans
    14 -> 4, and all 51 dropped clips played when probed a few minutes later. A vision rebuild must
    never quietly remove vision, so this fails closed like the publish gate's hand audit."""
    from cricket_core.video import get_fairplay_sas
    try:
        if get_fairplay_sas(ttl_hours=6):
            return
    except Exception as e:
        raise SystemExit(
            f"ABORTING: no Fairplay SAS ({type(e).__name__}: {str(e)[:140]}). Every Fairplay clip "
            f"would read as missing and the reels would be written SHORTER than they are now. "
            f"Nothing was changed — fix the credential and re-run.")
    raise SystemExit("ABORTING: no Fairplay SAS (empty token). Nothing was changed.")


def _plays(ref):
    """Does this clip reference serve footage? A Cricket-21 url does (the vendor hosts it, nothing
    to resolve); a Fairplay stem is HEAD-probed once per stem, and a match whose first few clips are
    all missing is treated as unclipped without probing the rest of it."""
    if not PROBE_CLIPS or ref.get("url"):
        return True
    stem = ref.get("clip_stem") or ""
    _head, _sep, tail = stem.partition("/fairplay/")
    folder = "/".join(tail.split("/")[:4])            # season / gender / format / match
    tally = _MATCH_PROBE.setdefault(folder, [0, 0])
    if tally[0] == 0 and tally[1] >= _MATCH_MISS_LIMIT:
        return False
    from cricket_core.video import resolve_clip
    ok = resolve_clip(stem) is not None
    tally[0 if ok else 1] += 1
    return ok


_PROBE_POOL = None


def _playable_first(refs, cap, batch=16):
    """The first `cap` references that play, in the order given (newest first).

    Probed `batch` at a time. One at a time, four Zimbabwe bowlers took 23 minutes on 2026-09-11,
    which would have made a full opposition build several hours."""
    global _PROBE_POOL
    if _PROBE_POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _PROBE_POOL = ThreadPoolExecutor(batch)
    out = []
    for i in range(0, len(refs), batch):
        chunk = refs[i:i + batch]
        for ref, ok in zip(chunk, _PROBE_POOL.map(_plays, chunk)):
            if ok:
                out.append(ref)
                if len(out) >= cap:
                    return out
    return out


def _clips_from_rows(rows, cap):
    """Newest-first PLAYABLE clip references for a set of profile delivery rows (they already
    carry season / gender / match / video for clip_stem). Capped at `cap`."""
    import c21_source
    rows = sorted(rows, key=lambda r: r.get("match_date") or "", reverse=True)
    refs = []
    for r in rows:
        ref = c21_source.clip_ref(r, clip_stem(
            r.get("season"), r.get("gender_id"), r.get("match_length_id"),
            r.get("match_id"), r.get("video_file_name")))
        if ref:
            refs.append({"delivery_id": r.get("delivery_id"), **ref})
    out = _playable_first(refs, cap)
    return out


NEW_BALL_MIN_SHARE = 45   # only bowlers who open (new_ball_share ≥ this) get a New-ball playlist

# How many TRACKED deliveries a stock-length/line sentence needs before it may be stated at all.
# Below this the card simply omits it: a modal bucket off a handful of balls is not a stock ball,
# and saying nothing beats saying "usually a full toss" (see allfmt_bowler_facts).
MIN_TRACKED_FOR_LENGTH = 20


def _tracked_length_row(r):
    """Is this row's pitch_length a real measurement? ⚠ The column is MILLIMETRES and
    `is_tracked_length` takes METRES — the estate's most expensive unit trap, so convert here
    rather than at the call site. A missing or unparseable value is not tracked."""
    try:
        return is_tracked_length(float(r.get("plen")) / 1000)
    except (TypeError, ValueError):
        return False


# Death overs, per odi_profile._phase (Powerplay <= 10, Death >= 41). Passed DOWN from the caller
# rather than assumed here, because over 41+ is meaningless in a T20 (the innings ends at 20) and
# WRONG in a Test, where it is simply the middle of a long innings. Only a 50-over pack sets it.
DEATH_FROM_OVER = 41

# WHAT A PACK MAY BORROW, AND FROM WHICH PHASE OF IT (Tom, 2026-09-17).
#
# The rule until now was a hard red/white line: a white-ball pack could borrow the other white-ball
# format for any reel, and a red-ball pack could borrow nothing. That is too blunt in both
# directions. The bowling context is what has to match, not the colour of the ball — T20I middle
# overs are a different exercise from ODI middle overs, while Test bowling and ODI middle-overs
# bowling are close relatives.
#
#   (pack format, reel) -> ((source format, source phase), ...)
#
# A reel MISSING from this table borrows nothing and is built from the pack's own format alone.
# That is deliberate and it is the expensive half of the rule: the whole-innings reels (stock,
# wicket, and h2h over in build_h2h) no longer borrow at all in a white-ball pack. It costs real
# footage — Duan Jansen's 11 wicket clips and Nqobani Mokoena's 14 are T20I, so their cards carry
# no vision rather than vision from the wrong phase of the wrong format.
_BORROW = {
    ("Test", "stock"):     (("ODI", "middle"),),
    ("Test", "wicket"):    (("ODI", "middle"),),
    ("ODI", "new_ball"):   (("T20I", "powerplay"),),
    ("ODI", "middle"):     (("Test", None),),        # None = any over; a Test innings has no phases
    ("ODI", "death"):      (("T20I", "death"),),
    ("T20I", "new_ball"):  (("ODI", "powerplay"),),
    ("T20I", "death"):     (("ODI", "death"),),
}


def _borrow_for(fmt, kind):
    """[(source format, source phase)] this reel may be filled from, or () for pack-format-only."""
    return _BORROW.get((str(fmt), kind), ())


def _phase_slice(P, fmt, phase):
    """A shallow copy of a profile whose `df` holds only the deliveries in one phase of `fmt`.

    Borrowing is phase-scoped, and the reel builders pick from `df`, so the restriction has to
    happen on the ROWS before any clip is chosen — filtering the finished clips instead would work
    off entries that no longer carry an over number.
    """
    if phase is None:
        return P
    band = {name: (first, last) for name, first, last in (phase_bands(fmt) or ())}.get(phase)
    if not band:
        return None
    first, last = band
    Q = dict(P)
    Q["df"] = [r for r in (P.get("df") or [])
               if r.get("over_n") is not None and first <= r["over_n"] <= last]
    return Q


def bowler_clips_from_profile(P, cap_each=10, wcap=40, fmt=None):
    """{"stock", "wicket", "new_ball", "middle", "death"} -> clips, from the profile's tagged rows,
    so the example clips match the card's 'Stock ball' phrase. Pace stock samples BOTH angles (the
    over-modal ball type + the round-modal ball type when they bowl round enough), combined into one
    playlist. Wickets pull a generous pool (wcap). New-ball clips = the powerplay overs, only for
    pace bowlers who take the new ball (shown on the top-order batters' packs).

    Returns a DICT, not the positional tuple it returned until 2026-09-17. The tuple grew a fourth
    member on 09-13 and the run died on `ValueError: too many values to unpack` because a capped
    grep found two of the four unpack sites; a fifth member (the middle-overs reel) would have
    invited the same failure a second time. Reels are now addressed by name, which is also what the
    phase rule needs — a phase has a name, not an index.

    `fmt` supplies the phase bands via cricket_core.formats, so the over numbers are not restated
    here: one_day is 1-10 / 11-40 / 41-50 and t20 is 1-6 / 7-15 / 16-20. A red-ball format has no
    phases and gets only stock, wicket and the first-10-overs new-ball reel.
    """
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
    reels = {"stock": stock, "wicket": wicket, "new_ball": [], "middle": [], "death": []}

    # Over numbers are 1-BASED in the warehouse (verified: ODI overs run 1..50, T20I 1..20), which
    # is why this reads `<= last` and not `< last`. The old new-ball reel asked for `over_n < 10`
    # and so dropped the 10th over from every powerplay reel it built — off by one against
    # odi_profile._phase, which has always said `<= 10`.
    bands = phase_bands(fmt) if fmt else None
    last_of = {name: last for name, _first, last in (bands or ())}
    pp_last = last_of.get("powerplay", 10)
    if P.get("is_pace") and (P.get("new_ball_share") or 0) >= NEW_BALL_MIN_SHARE:
        nb = [r for r in df if r.get("is_legal") and _has_vid(r)
              and r.get("over_n") is not None and 1 <= r["over_n"] <= pp_last]
        reels["new_ball"] = _clips_from_rows(nb, wcap)   # newest first, generous pool

    # The other phases — deliberately NOT gated on a share threshold the way the new ball is.
    # Measured on the Zimbabwe squad, the genuine death bowlers sit at 8-17% of their deliveries
    # (Muzarabani 17.3%, Evans 15.7%, Raza 13.2%), so a NEW_BALL_MIN_SHARE-style gate would delete
    # every one of them. Having playable footage in the phase IS the gate.
    for name, first, last in (bands or ()):
        if name == "powerplay":
            continue                                 # that is the new-ball reel, built above
        rows = [r for r in df if r.get("is_legal") and _has_vid(r)
                and r.get("over_n") is not None and first <= r["over_n"] <= last]
        reels[name] = _clips_from_rows(rows, wcap)
    return reels


def bowler_clips_best(bid, fmt="Test", min_stock=6, level="international", source="warehouse"):
    """(stock, wicket, new_ball, source_format) — reels for this bowler, stepping formats until
    there is something to watch.

    A bowler with a thin record in the pack's format still has footage in another: Newman Nyamhuri
    has 192 ODI balls and no usable ODI reel, which left his card with no vision at all.

    ⚠ These are WHOLE-INNINGS reels, so since 2026-09-17 they step only where `_BORROW` allows it,
    and a white-ball pack allows nothing: an ODI stock reel built from T20I deliveries is footage of
    a different exercise. A red-ball pack may still reach for ODI middle-overs deliveries, which is
    the one borrow the new rule adds rather than removes. The cost is visible and intended —
    Nyamhuri's T20I fallback above is exactly what no longer fires.

    Returns the format it actually used so the card can say so."""
    steps = [(fmt, level, None)]
    for kind in ("stock", "wicket"):
        for src, phase in _borrow_for(fmt, kind):
            if (src, level, phase) not in steps:
                steps.append((src, level, phase))
    best = ([], [], [], "")
    for f, lv, phase in steps:
        try:
            P = build_profile(bid, hand="All", fmt=f, level=lv, source=source)
        except Exception:
            continue
        P = _phase_slice(P, f, phase)
        if P is None:
            continue
        R = bowler_clips_from_profile(P, fmt=f)
        st, wk, nb = R["stock"], R["wicket"], R["new_ball"]
        if len(st) >= min_stock or (st and not best[0]):
            return st, wk, nb, f
        if not best[0] and (st or wk):
            best = (st, wk, nb, f)
    return best


def bowler_clips_by_hand(bid, fmt="Test", min_stock=6, level="international",
                         source="warehouse"):
    """{"": {reel: clips}, "lhb": {...}, "rhb": {...}} — the bowler's reels built separately for
    each batter hand, plus the both-hands set as a fallback.

    Reels are keyed by NAME ("stock", "wicket", "new_ball", "middle", "death") since 2026-09-17.
    They were a positional tuple, which grew to four members on 09-13 and broke the run at two of
    its four unpack sites; the phase rule adds a fifth, and phases are named things anyway.

    A right-hander's pack was showing this bowler's deliveries to left-handers and vice versa: the
    reels were built once at hand="All" and served to every pack. The stock ball, the wicket balls
    and the angle all change with the batter's hand, so a pooled reel is showing the wrong thing.
    One query, three profiles — `raw` is loaded here and reused."""
    from profile import process_rows
    from data_loaders import load_bowler_deliveries

    raws = {}                 # format -> processed rows, for the recent-bowling fallback below

    def _build(f, lv=None, phase=None):
        # dedupe=False: this function picks CLIPS, and the published facts come from the separate
        # build_profile call in main(). A match held by both sources has footage in both, and the
        # statistics dedupe was throwing one side's clips away — see data_loaders.
        raw = process_rows(load_bowler_deliveries(bid, fmt=f, level=lv or level, source=source,
                                                  dedupe=False))
        if not raw:
            return None
        raws[f] = raw
        # The phase reels follow the FORMAT's own bands, so a T20I load is cut 1-6 / 7-15 / 16-20
        # and an ODI one 1-10 / 11-40 / 41-50. A red-ball format has no phases and gets none.
        built = {}
        for key, hand in (("", "All"), ("lhb", "vs LHB"), ("rhb", "vs RHB")):
            P = build_profile(bid, hand=hand, raw=raw, fmt=f, level=lv or level, source=source)
            if phase:
                P = _phase_slice(P, f, phase)
                if P is None:
                    return None
            built[key] = bowler_clips_from_profile(P, fmt=f)
        return built

    # The pack's own format FIRST. This used to call load_bowler_deliveries(bid) with no fmt at
    # all, so it silently defaulted to Test — every hand-scoped reel in an ODI pack was built from
    # red-ball deliveries. The hand audit could not catch it: it checks whose hand the clip is
    # bowled to, not which format it came from.
    out = _build(fmt)
    if out is None:
        # an empty load is a dropped connection far more often than a bowler with no deliveries;
        # writing the empty result would silently blank reels that were fine
        raise RuntimeError(f"no deliveries loaded for bowler {bid} in {fmt}")

    # PER HAND, PER REEL. A thin record in the pack's format leaves a hand with no vision, which is
    # the one thing a player can always use. This used to step formats for the whole bowler, and
    # only when BOTH hands' stock reels were short — counted before anyone checked the clips played —
    # so Wellington Masakadza stepped nowhere and every pack showed nothing.
    #
    # Each hand's reel now steps on its own, and WHERE IT MAY STEP comes from `_BORROW` (2026-09-17)
    # rather than from the red/white line. Every reel is offered its own borrows, which is how the
    # phase rule lands: an ODI death reel may take T20I death overs, an ODI middle-overs reel may
    # take Test deliveries, and an ODI stock or wicket reel may take nothing at all.
    floor = {"stock": min_stock, "wicket": 3, "new_ball": 3, "middle": 3, "death": 3}
    out = {k: dict(v) for k, v in out.items()}
    srcfmt, xhand, alts = {}, {}, {}

    def _alt(f, lv, slice_phase):
        """The source format's reels for this bowler, optionally built from one phase of it only.

        Cached per (format, slice) because a bowler has five reels per hand and several may ask for
        the same borrow. `slice_phase` is for a WHOLE-INNINGS borrow (a Test stock reel taking ODI
        middle-overs deliveries): the rows are cut before the stock ball is identified, so the ball
        type is read from middle-overs bowling rather than from a whole ODI innings. A PHASE reel
        needs no slice — the source's own death reel is already cut to the source's death band.
        """
        if (f, slice_phase) in alts:
            return alts[(f, slice_phase)]
        try:
            built = _build(f, lv, phase=slice_phase)
        except Exception as e:                      # a step that fails leaves the reel as it was
            print(f"    ! bowler {bid}: {f} fallback not built ({type(e).__name__})")
            built = None
        alts[(f, slice_phase)] = built
        return built

    # A borrowed PHASE names a phase of the source format; the reel that holds it is keyed by name,
    # and the powerplay lives in the reel called "new_ball".
    _PHASE_REEL = {"powerplay": "new_ball", "middle": "middle", "death": "death"}

    for h in ("lhb", "rhb"):
        for k in ("stock", "wicket", "new_ball", "middle", "death"):
            if len(out[h].get(k) or []) >= floor[k]:
                continue
            for src, phase in _borrow_for(fmt, k):
                whole_innings = k in ("stock", "wicket")
                alt = _alt(src, level, phase if whole_innings else None)
                take = (alt or {}).get(h, {}).get(k if whole_innings
                                                  else _PHASE_REEL.get(phase, k)) or []
                if len(take) > len(out[h].get(k) or []):
                    out[h][k], srcfmt[(h, k)] = take, src
                    break

    # No identifiable STOCK ball is not the same as no footage. The stock reel is picked from
    # TRACKED deliveries — length and line define the ball type — and the footage that plays for
    # Tanaka Chivanga and Wesley Madhevere is untracked, so none of it can be tagged as their stock
    # ball. A hand like that gets its most recent playable deliveries to that hand instead, flagged
    # so the button reads "Recent bowling" and never "Stock ball".
    general = set()
    # Only the pack's own format, plus whatever a stock reel is allowed to borrow — which for a
    # white-ball pack is nothing. "Recent bowling" is still a stock-slot reel, so it obeys the same
    # rule as the stock reel it stands in for.
    order = [fmt] + [f for f, _phase in _borrow_for(fmt, "stock")]
    for h in ("lhb", "rhb"):
        if out[h]["stock"]:
            continue
        for f in order:
            rows = [r for r in raws.get(f) or []
                    if r.get("is_legal") and bool(r.get("is_lhb")) == (h == "lhb") and _has_vid(r)]
            recent = _clips_from_rows(rows, 12)
            if recent:
                out[h]["stock"] = recent
                general.add((h, "stock"))
                if f != fmt:
                    srcfmt[(h, "stock")] = f
                break

    # Last resort, and STATED: a hand with nothing in any allowed format borrows the other hand's
    # reel. Tanaka Chivanga has 2 playable ODI balls to left-handers and no T20I footage, and Sean
    # Williams has no playable wicket to a left-hander in either white-ball format. Tom, 2026-09-11:
    # right-hand footage in a left-hander's pack is acceptable as long as the pack says so. It gets
    # its own playlist key and label in build_player_site, and audit_pack_hands checks it against
    # the hand it declares — so this is a labelled fallback, not a return of the pooled reel.
    for h, o in (("lhb", "rhb"), ("rhb", "lhb")):
        for k in ("stock", "wicket"):
            if not out[h][k] and out[o][k] and (o, k) not in xhand:
                out[h][k], xhand[(h, k)] = list(out[o][k]), o
                if (o, k) in srcfmt:
                    srcfmt[(h, k)] = srcfmt[(o, k)]
                if (o, k) in general:
                    general.add((h, k))
    out["_srcfmt"], out["_xhand"], out["_general"] = srcfmt, xhand, general
    return out, fmt


def _store_hand_reels(entry, byh):
    """Write the per-hand reels, and where each came from, onto an opponent_about entry.

    `clip_format_{kind}_{hand}` names a borrowed white-ball format, `clip_hand_{kind}_{hand}` names
    the other hand when its reel stands in, and `clip_general_{kind}_{hand}` marks a stock slot that
    holds recent untracked deliveries rather than an identified stock ball. build_player_site stars
    and labels from these."""
    for _h in ("lhb", "rhb"):
        R = byh[_h]
        entry[f"stock_clips_{_h}"], entry[f"wicket_clips_{_h}"] = R["stock"], R["wicket"]
        entry[f"new_ball_clips_{_h}"] = R["new_ball"]
        entry[f"middle_clips_{_h}"] = R["middle"]
        entry[f"death_clips_{_h}"] = R["death"]
    for (h, k), f in (byh.get("_srcfmt") or {}).items():
        entry[f"clip_format_{k}_{h}"] = f
    for (h, k), o in (byh.get("_xhand") or {}).items():
        entry[f"clip_hand_{k}_{h}"] = o
    for h, k in (byh.get("_general") or ()):
        entry[f"clip_general_{k}_{h}"] = True


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


# Scoped by EXACT bowler type, not just pace/spin: an off spinner's pack pooling all spin still
# served left-arm-orthodox footage (Noman Ali turning up in an off-spin reel). style ids mirror
# batting_loaders._BOWLER_TYPE_CASE; hand 1 = right, 2 = left.
_STYLE = {
    "pace": "D.bowler_style_id IN ('1','2','3')",
    "spin": "D.bowler_style_id IN ('4','5')",
    "right_pace": "D.bowler_style_id IN ('1','2','3') AND D.bowler_hand_id='1'",
    "left_pace": "D.bowler_style_id IN ('1','2','3') AND D.bowler_hand_id='2'",
    "off_spin": "D.bowler_style_id='4' AND D.bowler_hand_id='1'",
    "left_orthodox": "D.bowler_style_id='4' AND D.bowler_hand_id='2'",
    "leg_spin": "D.bowler_style_id='5' AND D.bowler_hand_id='1'",
    "left_unorthodox": "D.bowler_style_id='5' AND D.bowler_hand_id='2'",
}
_CLIP_GROUPS = ("pace", "spin", "right_pace", "left_pace", "off_spin", "left_orthodox",
                "leg_spin", "left_unorthodox")


def _fmt_sql(fmt="Test", level="international"):
    """Series scope for one format at one LEVEL of cricket.

    Was a format-keyed dict of internationals. An India A pack asking for "Test" must get
    A-team first-class cricket, not senior Test cricket — same format, different standard.
    Unknown pairs (there is no men's A-team T20 bucket) fall back to the senior scope for that
    format, which is what the fallback chain then steps past."""
    try:
        return (f"M.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
                f"WHERE name IN {series_sql(fmt, level)})")
    except ValueError:
        if fmt in ("Test", "ODI", "T20I"):
            return (f"M.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
                    f"WHERE name IN {international_series_sql(fmt)})")
        return _TEST
_MACRO_OF = {"right_pace": "pace", "left_pace": "pace", "off_spin": "spin",
             "left_orthodox": "spin", "leg_spin": "spin", "left_unorthodox": "spin"}


# Which formats to fall back through, per pack format. The PACK's format comes first: footage of
# a near-enough bowler type in the format they will actually play beats exact-type footage from a
# different one. For a white-ball pack the nearest neighbour is the other white-ball format, not
# Tests — an ODI pack falls back to T20I before it reaches for red-ball footage.
_FMT_ORDER = {"Test": ("Test", "ODI", "T20I"),
              "ODI": ("ODI", "T20I", "Test"),
              "T20I": ("T20I", "ODI", "Test")}

# At a-team level T20I is not a body of cricket that exists (no men's A-team T20 bucket), so
# asking for it raises — and a raise inside the step killed the whole bowler instead of moving on:
# Saransh Jain and Anshul Kamboj were dropped from the four-day file entirely by exactly that.
# The pooled "T20" scope takes its place: it is every major T20 league, level-agnostic by
# construction, and where an uncapped Indian player's footage actually lives.
# At A-TEAM level the fallback steps LEVEL, not across the red/white line.
#
# The first version of this stepped Test -> ODI -> T20, reasoning that the pooled T20 scope is where
# an uncapped Indian player's footage actually lives. It is — but T20 footage in a four-day pack is
# off-format, which is precisely what the reel rule forbids and what audit_pack_hands rejects. The
# publish gate refused the Australia A bundle with **58 off-format reels** across 15 batting packs,
# every one of them Kamboj or Ansari, whose A-team red-ball footage is thin. The gate was right.
#
# So a red-ball pack falls back to the same format at a different LEVEL (A-team first-class, then
# senior Tests) and never leaves red-ball; a white-ball pack moves among white-ball formats only.
# The entries are (format, level) pairs for that reason.
_ORDER_A = {
    "Test": (("Test", "a-team"), ("Test", "international")),
    "ODI":  (("ODI", "a-team"), ("ODI", "international"),
             ("T20I", "international"), ("T20", "international")),
    "T20I": (("T20I", "international"), ("T20", "international"),
             ("ODI", "a-team"), ("ODI", "international")),
}


def _fmt_order(fmt="Test", level="international"):
    """[(format, level)] to try, in order. The international table keeps its historical chain
    exactly — those packs are shipped and their cross-colour steps have never fired — and pairs
    each entry with the caller's level so behaviour is unchanged."""
    if level == "a-team":
        return _ORDER_A.get(fmt, _ORDER_A["Test"])
    return tuple((f, level) for f in _FMT_ORDER.get(fmt, _FMT_ORDER["Test"]))


def batter_clips_best(conn, cur, bid, against, cap=40, fmt="Test", level="international",
                      source="warehouse"):
    """Clips for this batter against `against`, relaxing only as far as needed, and saying how far.

    Order: the pack's format + exact type, then the same format with the wider pace/spin set, then
    the neighbouring formats (see _FMT_ORDER). Returns (scoring, dismissal, scope) where scope is
    e.g. 'ODI:off_spin' or 'ODI:spin'; anything but '{fmt}:{against}' means the pack should flag
    it."""
    macro = _MACRO_OF.get(against)
    # These are WHOLE-INNINGS reels, so they step exactly where a stock reel may step (2026-09-17):
    # nowhere at all for a white-ball pack, and into ODI middle overs for a red-ball one. Until then
    # a Test pack could take a whole ODI or T20I innings, and a white-ball pack was stopped only by
    # a red/white guard. The TYPE relaxation below (exact type -> macro pace/spin) is a different
    # axis and is unchanged; it is still reported through the returned scope string.
    order = [(fmt, level, None)] + [(src, level, ph) for src, ph in _borrow_for(fmt, "stock")]
    for f, lv, ph in order:
        # Cricket-21 rows join at the pack's OWN step only WHEN THE PACK IS A-TEAM. C21 holds Indian
        # domestic cricket with no level, so joining it at an a-team pack's fallback step would file
        # Ranji footage under a label claiming senior or neighbouring cricket. That is the case this
        # guard was written for and it still holds unchanged.
        #
        # A SENIOR pack is a different shape (Tom asked for this, 2026-09-13, Brendan Taylor). Its
        # fallback step is another SENIOR white-ball format, and c21_source already filters by fmt,
        # so the rows joining a T20I step are genuine T20Is — Zimbabwe's tri-series and World Cup
        # matches — not domestic cricket wearing a T20I label. Taylor is the case that shows why it
        # matters: all 200 of his ODI boundaries carry a Fairplay name and none of them PLAY
        # (Zimbabwe is barely clipped before 2022-23), while his 37 playable boundary clips sit in
        # C21's T20I record. Warehouse-only at the fallback step left his scoring reel empty.
        # audit_pack_hands still resolves every clip's series and refuses anything off-format.
        src = source if ((f, lv, ph) == order[0] or level == "international") else "warehouse"
        for grp in ([against, macro] if macro else [against]):
            if not grp:
                continue
            sc, ds = batter_clips(conn, cur, bid, cap=cap, against=grp, fmt=f, level=lv, source=src,
                                  phase=ph)
            if sc or ds:
                return sc, ds, f"{f}:{grp}"
    return [], [], ""


_WHITE = ("ODI", "T20I", "T20")


def _same_colour(f, fmt):
    """Is format `f` on the same side of the red/white-ball line as the pack's `fmt`? The bowler
    reels in a batting pack are held to this in BOTH directions by audit_pack_hands."""
    return (f in _WHITE) == (fmt in _WHITE)


_C21_BAT = {}


def _c21_batter_rows(bid, fmt):
    """Cricket-21 deliveries faced by this batter in `fmt`, loaded once per build. The reels ask for
    them per bowling type and per kind, sixteen times a batter."""
    key = (str(bid), fmt)
    if key not in _C21_BAT:
        import c21_source
        try:
            _C21_BAT[key] = c21_source.load_batter_deliveries(bid, fmt=fmt)
        except Exception as e:
            print(f"    ! batter {bid}: no Cricket-21 rows ({type(e).__name__}: {str(e)[:80]})")
            _C21_BAT[key] = []
    return _C21_BAT[key]


# _STYLE as a test on a warehouse-shaped row. C21 rows carry the same style and hand ids.
_STYLE_ROW = {
    "pace": lambda s, h: s in ("1", "2", "3"),
    "spin": lambda s, h: s in ("4", "5"),
    "right_pace": lambda s, h: s in ("1", "2", "3") and h == "1",
    "left_pace": lambda s, h: s in ("1", "2", "3") and h == "2",
    "off_spin": lambda s, h: s == "4" and h == "1",
    "left_orthodox": lambda s, h: s == "4" and h == "2",
    "leg_spin": lambda s, h: s == "5" and h == "1",
    "left_unorthodox": lambda s, h: s == "5" and h == "2",
}


def _style_ok(r, against):
    test = _STYLE_ROW.get(against)
    return True if test is None else test(str(r.get("bowler_style_id")), str(r.get("bowler_hand_id")))


def batter_clips(conn, cur, bid, cap=40, against=None, fmt="Test", level="international",
                 source="warehouse", phase=None):
    """(scoring_clips, dismissal_clips) — example Test deliveries with video where the batter scores
    a boundary (how they score) and where they were dismissed (how they get out). Newest first.

    `against` scopes to the bowling type the viewer actually bowls. Unscoped, a spinner's pack served
    whatever the batter's most recent boundaries were — overwhelmingly pace. Scoped only to the macro
    group, an off spinner still got left-arm-orthodox footage."""
    where = _STYLE.get(against)
    if where and against not in ("pace", "spin") and AMBIDEXTROUS_BOWLERS:
        # an arm-switcher is coded as one type but bowls two — keep them out of the exact-type reel
        where += " AND D.bowler_id NOT IN (" + ", ".join(
            f"'{i}'" for i in AMBIDEXTROUS_BOWLERS) + ")"
    filt = f" AND {where}" if where else ""
    # A borrowed body of cricket is cut to the phase that matches the pack (Tom, 2026-09-17): a Test
    # pack reading ODI footage takes the middle overs, where the bowling is doing the same job. The
    # cut is in SQL rather than on the returned rows because the query keeps only TOP `pool` by date
    # — filtering afterwards would throw away most of a reel that was never phase-scoped.
    if phase:
        band = {n: (a, b) for n, a, b in (phase_bands(fmt) or ())}.get(phase)
        if not band:
            return [], []
        filt += f" AND TRY_CONVERT(int, D.[over]) BETWEEN {band[0]} AND {band[1]}"
    scope = _fmt_sql(fmt, level)
    # Over-fetch, then keep the first `cap` that play — the newest named balls are often from a
    # match that was never clipped (see _plays).
    pool = cap * 6 if PROBE_CLIPS else cap
    wh_sc = _q(conn, cur, f"""SELECT TOP {pool} {_CLIP_COLS}, CONVERT(varchar(10), M.match_date, 23) match_date
        FROM [{DATA_SCHEMA}].[Deliveries] D {_CLIP_JOINS}
        WHERE D.striker_id='{bid}' AND D.legal_ball=1 AND {scope} AND D.video_file_name IS NOT NULL
          AND D.bat_score IN ('4','6'){filt}
        ORDER BY M.match_date DESC""")
    wh_ds = _q(conn, cur, f"""SELECT TOP {pool} {_CLIP_COLS}, CONVERT(varchar(10), M.match_date, 23) match_date
        FROM [{DATA_SCHEMA}].[Deliveries] D {_CLIP_JOINS}
        WHERE D.striker_id='{bid}' AND D.striker_dismissed='1' AND {scope}
          AND D.video_file_name IS NOT NULL{filt}
        ORDER BY M.match_date DESC""")
    if source != "warehouse":
        # Cricket-21 footage. The batter reels read the warehouse alone until 2026-09-12, so an India
        # A batter whose recent record is all Ranji had no scoring or dismissal vision in any pack:
        # Ayush Pandey (698 first-class balls), Yash Rathod (510) and Kumar Kushagra (568), every
        # ball with video, all showed nothing. Merged by match date, as the loaders are.
        # UNION, not merge. The statistics dedupe (merge_with_warehouse) keeps one copy of a match
        # so averages cannot double — right for numbers, wrong for footage: both sources filmed the
        # same match and hold DIFFERENT balls of it. Merging here dropped Ben Curran's left-arm
        # orthodox dismissals from 3 to 0 and Clive Madande's leg-spin scoring from 3 to 0
        # (2026-09-13), every one of which played when probed. _playable_first caps the reel, so the
        # union just gives it more to choose from, newest first.
        rows = [r for r in _c21_batter_rows(bid, fmt) if _style_ok(r, against)]
        wh_sc = wh_sc + [r for r in rows if r.get("legal_ball") == "1" and r.get("bat_score") in ("4", "6")]
        wh_ds = wh_ds + [r for r in rows if r.get("striker_dismissed") == "1"]
    newest = lambda rs: sorted(rs, key=lambda r: str(r.get("match_date") or ""), reverse=True)
    scoring = _playable_first(_stems(newest(wh_sc)), cap)
    dismissal = _playable_first(_stems(newest(wh_ds)), cap)
    return scoring, dismissal


def _test_balls(conn, cur, bid, role, fmt="Test", level="international", source="warehouse"):
    """Legal balls in this format the player has bowled ('bowl') or faced ('bat').

    This is the gate that decides a full profile against the thin all-formats fallback, so it has
    to count the SAME body of cricket the profile will be built from. Counting the warehouse alone
    while building from `source='both'` sent every player whose record is only in Cricket-21 down
    the fallback path — which is warehouse-only too, found nothing, and skipped them entirely.
    Aman Mokhade and Ayush Pandey have no warehouse record and 788 and 163 C21 balls."""
    col = "bowler_id" if role == "bowl" else "striker_id"
    r = _q(conn, cur, f"SELECT COUNT(*) n FROM [{DATA_SCHEMA}].[Deliveries] D "
                      f"JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id "
                      f"WHERE D.{col}='{bid}' AND D.legal_ball=1 AND {_fmt_sql(fmt, level)}")
    n = int(float(r[0]["n"] or 0)) if r else 0
    if source in ("c21", "both"):
        import c21_source
        bowl, bat = c21_source.coverage(bid, fmt=fmt)
        c = bowl if role == "bowl" else bat
        n = c if source == "c21" else n + c
    return n


def _mode(rows, key):
    from collections import Counter
    c = Counter(r[key] for r in rows if r.get(key) not in (None, "None", ""))
    return c.most_common(1)[0][0] if c else None


def _line_phrase(li):
    """Render a pitching-line label as a phrase. The lookup descriptions are inconsistent — some
    are bare regions ("4th Stump"), some already read as a line ("In Line") — and the guard that
    was meant to handle it tested a condition and then returned the same string either way, so the
    label doubled up: "Usually <1 m in the in line"."""
    t = (li or "").strip().lower()
    if not t:
        return ""
    if "line" in t or t.startswith("outside") or t.startswith("wide"):
        return t                       # already a phrase — "in line", "outside off"
    return f"in the {t}"               # a region — "in the 4th stump channel"


def _scope_label(fmt="Test", level="international"):
    """How to name the pack's own body of cricket in reader-facing prose. "Limited Test record" is
    wrong on an Australia A one-day pack in two ways at once."""
    if level == "a-team":
        return {"Test": "first-class A", "ODI": "List A"}.get(fmt, "A-team")
    return {"Test": "Test", "ODI": "ODI", "T20I": "T20I"}.get(fmt, fmt)


def _override_type(bid):
    """The hand-checked bowler type, for a player the matchup store has no label for.

    The store only carries bowlers it can simulate, so a squad-union addition arrives with an
    empty type and the card opened on the bare word "Bowler" — which is what a reader already
    knew. The estate keeps its corrections in one place; read them rather than guessing.
    """
    ov = BOWLER_TYPE_OVERRIDE.get(str(bid))
    return BOWLER_TYPE_LABEL.get(ov, ov) if ov else None


def _coded_type(conn, cur, bid):
    """The bowler's type as the FEED codes it, read from their own deliveries.

    Three sources answer "what does this bowler bowl", and the footage-only card had only two of
    them: the matchup store's label (empty for anyone it cannot simulate) and `_override_type`
    (only the hand-checked corrections). So a thin bowler's card opened on the bare word "Bowler"
    while the warehouse knew all along — Duan Jansen is coded left-arm fast on every one of his
    496 deliveries, and Ernest Masuku's live Zimbabwe card says "Bowler" for the same reason.
    Read what the feed says before saying nothing; the override still wins where one exists.
    """
    rows = _q(conn, cur, f"""SELECT D.bowler_style_id st, D.bowler_hand_id hd,
        D.bowler_pace_spin_id ps
        FROM [{DATA_SCHEMA}].[Deliveries] D WHERE D.bowler_id='{bid}' AND D.legal_ball=1""")
    if not rows:
        return None
    return bowler_type_label(_mode(rows, "st"), _mode(rows, "hd"), _mode(rows, "ps"),
                             player_id=bid)


def allfmt_bowler_facts(conn, cur, bid, type_label, LEN, LIN, scope_label="Test"):
    """Format-robust bowler facts from ALL formats (type, pace, stock line/length) — labelled.
    No economy/average/wicket-rate (those don't translate across formats)."""
    rows = _q(conn, cur, f"""SELECT TRY_CONVERT(float, D.ball_speed) spd,
        D.pitch_length_group_pace_1_id len, D.pitch_line_group_pace_id lin,
        D.bowler_pace_spin_id ps, TRY_CONVERT(float, D.pitch_length) plen
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
    # THE GROUP COLUMNS INHERIT THE UNTRACKED SENTINEL, and this read them raw (Tom, 2026-09-21).
    # An untracked delivery still gets a length group and it is always the FULLEST bucket, so a
    # bowler whose record is thinly tracked is described as bowling full tosses for a stock ball.
    # Measured on Nqobani Mokoena: 488 legal deliveries, 39% tracked, and all 297 untracked balls
    # landed in "<1 m" — which outvoted everything and put "usually <1 m" on his card. On the 191
    # tracked balls the answer is "6-8 m", a good length, which is what he actually bowls.
    # `is_tracked_length` is the estate's one definition; filter the ROWS, then take the mode.
    seen = [r for r in rows if _tracked_length_row(r)]
    ln = li = None
    if len(seen) >= MIN_TRACKED_FOR_LENGTH:
        ln, li = LEN.get(_mode(seen, "len")), LIN.get(_mode(seen, "lin"))
    if ln and li:
        # "pitching in line", not "in line" — the house rule is that a line is ambiguous unless it
        # says whether it is where the ball PITCHED or where it passed the stumps (Tom, 2026-09-21).
        facts.append(f"Usually {ln.lower()} pitching {_line_phrase(li)}.")
    facts.append(f"Limited {scope_label} record — the above is from all formats they've played.")
    return {"type": type_label, "is_pace": is_pace, "facts": facts, "order": len(rows), "source": "all-formats"}


def allfmt_batter_facts(conn, cur, bid, hand, STK, SQ, scope_label="Test"):
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
    facts.append(f"Limited {scope_label} record — the above is from all formats they've played.")
    return {"hand": hand, "facts": facts, "order": len(rows), "source": "all-formats",
            "facts_pace": facts, "facts_spin": facts}


# batting-order role from the batter's most common Test position (counted by innings, not balls, so
# a top-order batter who faces more balls doesn't skew it). 1–2 opener · 3–4 top · 5–7 middle · 8+ tail.
_ROLE_BANDS = ((2, "Opener"), (4, "Top order"), (7, "Middle order"), (99, "Lower order"))


def batter_role(conn, cur, bid, fmt="Test", level="international"):
    r = _q(conn, cur, f"""SELECT TOP 1 pos, COUNT(*) n FROM (
            SELECT TRY_CONVERT(int, D.striker_batting_position) pos, D.match_id, D.match_innings
            FROM [{DATA_SCHEMA}].[Deliveries] D JOIN [{DATA_SCHEMA}].[Matches] M ON D.match_id=M.match_id
            WHERE D.striker_id='{bid}' AND {_fmt_sql(fmt, level)} AND TRY_CONVERT(int, D.striker_batting_position) BETWEEN 1 AND 11
            GROUP BY TRY_CONVERT(int, D.striker_batting_position), D.match_id, D.match_innings) t
        GROUP BY pos ORDER BY COUNT(*) DESC""")
    if not r or r[0].get("pos") in (None, "None"):
        return None
    pos = int(r[0]["pos"])
    return next((lbl for hi, lbl in _ROLE_BANDS if pos <= hi), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", default="bangladesh")
    ap.add_argument("--only-batters", default="",
                    help="comma-separated batter ids — build just these and MERGE into the existing "
                         "file, leaving every other player (and the bowlers' per-hand reels) alone. "
                         "Adding one player shouldn't cost a 40-minute full rebuild.")
    ap.add_argument("--only-bowlers", default="",
                    help="comma-separated bowler ids — the same merge for an opposition bowler, "
                         "leaving every batter and every other bowler alone. Combinable with "
                         "--only-batters.")
    ap.add_argument("--fmt", default="Test", choices=("Test", "ODI", "T20I"),
                    help="which format's internationals to profile, and prefer footage "
                         "from (default: Test)")
    ap.add_argument("--level", default="international", choices=("international", "a-team"),
                    help="which standard of cricket the opposition's record is. 'a-team' "
                         "scopes to International 1st Class / Tour Matches / List A ODI, so an "
                         "India A pack never quotes senior India numbers")
    ap.add_argument("--source", default="warehouse",
                    choices=("warehouse", "c21", "both"),
                    help="where the ball record comes from. 'both' adds Cricket-21 Indian "
                         "domestic cricket, which the warehouse does not hold at all")
    ap.add_argument("--clips-only", action="store_true",
                    help="only add stock/wicket example clips to the existing json (fast, no re-profile)")
    args = ap.parse_args()
    if PROBE_CLIPS:
        _require_fairplay()      # fail closed: no SAS means every Fairplay clip reads as missing

    dst = os.path.join(HERE, "data", f"opponent_about_{args.opp}.json")
    if args.clips_only:
        out = json.load(open(dst, encoding="utf-8"))
        conn, cur = set_conn_cursor()
        n_err = 0
        for bid, entry in out.get("bowlers", {}).items():
            try:                                          # re-profile so clips match the stock phrase
                byh, _src = bowler_clips_by_hand(bid, fmt=args.fmt, level=args.level,
                                                 source=args.source)
                # Where a reel came from is now recorded per hand and per reel. The old whole-bowler
                # stamp would star every button on the card, so clear it along with stale per-reel keys.
                for _k in [k for k in entry if k == "clip_format"
                           or k.startswith(("clip_format_", "clip_hand_"))]:
                    entry.pop(_k)
                R = byh[""]
                st, wk, nb, dth = R["stock"], R["wicket"], R["new_ball"], R["death"]
                (entry["stock_clips"], entry["wicket_clips"], entry["new_ball_clips"],
                 entry["middle_clips"], entry["death_clips"]) = st, wk, nb, R["middle"], dth
                _store_hand_reels(entry, byh)              # a pack shows only its own batter's hand
                print(f"  bowler {entry.get('name', bid):<20} stock {len(st)} · wicket {len(wk)} · new {len(nb)}"
                      f" · mid {len(R['middle'])} · death {len(dth)}"
                      f"  | lhb {len(byh['lhb']['wicket'])}w · rhb {len(byh['rhb']['wicket'])}w")
            except Exception as e:
                n_err += 1
                print(f"  ! bowler {entry.get('name', bid)}: {type(e).__name__}: {e}")
        if n_err:
            raise SystemExit(
                f"ABORTING: {n_err} bowler clip rebuild(s) failed — almost certainly the warehouse "
                f"connection, not missing data. opponent_about_{args.opp}.json left untouched; "
                f"re-run when the connection is back.")
        for bid, entry in out.get("batters", {}).items():
            for _tw in _CLIP_GROUPS:
                _sc, _ds, _scope = batter_clips_best(conn, cur, bid, _tw, fmt=args.fmt, level=args.level,
                                                         source=args.source)
                entry[f"scoring_clips_{_tw}"], entry[f"dismissal_clips_{_tw}"] = _sc, _ds
                entry[f"clip_scope_{_tw}"] = _scope
            sc, ds = batter_clips(conn, cur, bid, fmt=args.fmt, level=args.level, source=args.source)
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

    # The store is a MODEL ARTEFACT, not the roster. A bowler with too few zoned balls to simulate
    # is dropped from it — and was therefore silently absent from this file, so their card in every
    # pack had no notes at all. Tanaka Chivanga (481 ODI balls) and Newman Nyamhuri (192) both
    # vanished that way while having live bowler reports in the portal.
    #
    # Take the roster from the pinned squad and let the per-player gates below decide how much can
    # be said: a full profile above TEST_FLOOR, the all-formats fallback beneath it. Something beats
    # an empty card.
    sq_path = os.path.join(project_path("matchupmodel"), "data", f"opp_squad_{args.opp}.json")
    if os.path.exists(sq_path):
        sq = json.load(open(sq_path, encoding="utf-8"))
        names = {str(k): v for k, v in (sq.get("names") or {}).items()}
        added = []
        for b in sq.get("bowlers", []):
            if str(b) not in bowlers:
                bowlers[str(b)] = (names.get(str(b), str(b)), "")
                added.append(names.get(str(b), str(b)))
        for b in sq.get("batters", []):
            if str(b) not in batters:
                batters[str(b)] = (names.get(str(b), str(b)), "")
                added.append(names.get(str(b), str(b)))
        if added:
            print(f"squad adds {len(added)} not in the sim store: {', '.join(added)}")

    conn, cur = set_conn_cursor()
    LEN = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2819")}
    LIN = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2823")}
    STK = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=24")}
    SQ = {r["id"]: r["description"] for r in _q(conn, cur, f"SELECT id,description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id=2811")}

    only_bat = [x.strip() for x in args.only_batters.split(",") if x.strip()]
    only_bowl = [x.strip() for x in args.only_bowlers.split(",") if x.strip()]
    merging = bool(only_bat or only_bowl)
    if merging:
        # merge mode: start from what's on disk so nothing else is touched
        out = json.load(open(dst, encoding="utf-8"))
        missing_bat = [b for b in only_bat if b not in batters]
        if missing_bat:
            raise SystemExit(
                f"ABORTING: {missing_bat} not in the matchup store's they_bat rows for {args.opp}. "
                f"Add the id to matchupmodel/data/opp_squad_{args.opp}.json 'batters' and re-run "
                f"export_matchup_store.py, otherwise there's no name/hand to build from.")
        missing_bowl = [b for b in only_bowl if b not in bowlers]
        if missing_bowl:
            raise SystemExit(
                f"ABORTING: {missing_bowl} not in the matchup store's we_bat rows for {args.opp}. "
                f"Add the id to matchupmodel/data/opp_squad_{args.opp}.json 'bowlers' and re-run "
                f"export_matchup_store.py, otherwise there's no name/type to build from.")
        bowlers = {b: bowlers[b] for b in only_bowl}
        batters = {b: batters[b] for b in only_bat}
        print("merge mode: rebuilding only "
              + ", ".join(nm for nm, _ in list(bowlers.values()) + list(batters.values())))
    else:
        out = {"opp": args.opp, "bowlers": {}, "batters": {}}
    n_err = 0
    for bid, (nm, ty) in bowlers.items():
        try:
            if _test_balls(conn, cur, bid, "bowl", fmt=args.fmt, level=args.level,
                           source=args.source) >= TEST_FLOOR:
                P = build_profile(bid, hand="All", fmt=args.fmt, level=args.level,
                                  source=args.source)
                # The type label comes from the matchup store, which drops any bowler it cannot
                # simulate — so a squad-union addition like Auqib Nabi had none and his card opened
                # "Bowler - averages 130 km/h". The profile knows what they bowl; use that before
                # falling back to a word that says nothing.
                entry = {"name": nm, **distil_bowler(
                    P, ty or _override_type(bid) or P.get("primary_type") or "Bowler")}
                R = bowler_clips_from_profile(P, fmt=args.fmt)
                (entry["stock_clips"], entry["wicket_clips"], entry["new_ball_clips"],
                 entry["middle_clips"], entry["death_clips"]) = (
                     R["stock"], R["wicket"], R["new_ball"], R["middle"], R["death"])
                byh, _src = bowler_clips_by_hand(bid, fmt=args.fmt, level=args.level,
                                                 source=args.source)   # a pack shows only its own hand
                _store_hand_reels(entry, byh)
                out["bowlers"][bid] = entry
                tag = f" · stock {len(entry['stock_clips'])} wkt {len(entry['wicket_clips'])} new {len(entry['new_ball_clips'])}"
            else:                                        # thin record -> all-format fallback
                fb = allfmt_bowler_facts(conn, cur, bid,
                                         ty or _override_type(bid) or _coded_type(conn, cur, bid)
                                         or "Bowler", LEN, LIN,
                                         scope_label=_scope_label(args.fmt, args.level))
                if not fb:
                    # Not enough to profile in any format — but there can still be footage, and the
                    # same fix already exists one branch down for batters (Shams Mulani). This
                    # fallback reads the WAREHOUSE only and needs 150 rows: Ernest Masuku has ~70
                    # there and 196 in Cricket-21 with video on 190 of them, so he was dropped from
                    # every pack while holding the most watchable record of any thin bowler in the
                    # squad. Keep a footage-only entry; it is deleted below, with a log line, only
                    # when nothing plays either.
                    note = [f"Limited {_scope_label(args.fmt, args.level)} record — "
                            f"not enough balls to profile."]
                    fb = {"type": ty or _override_type(bid) or _coded_type(conn, cur, bid)
                          or "Bowler", "is_pace": None,
                          "facts": note, "order": 0, "source": "footage-only"}
                entry = {"name": nm, **fb}
                # A thin record used to mean NO vision at all, which is the one thing a player can
                # always use. Step formats until there is something to watch and record which one,
                # so the card can say the footage is from another format.
                st, wk, nbc, src = bowler_clips_best(bid, fmt=args.fmt, level=args.level,
                                                     source=args.source)
                entry["stock_clips"], entry["wicket_clips"], entry["new_ball_clips"] = st, wk, nbc
                # `src` is the format the POOLED reel used, and it is no longer stamped as
                # clip_format: the batting packs never show the pooled reel, and the stamp starred
                # every hand-scoped button whatever format those came from. Per-reel provenance is
                # written by _store_hand_reels.
                # The BATTING packs read only the hand-scoped reels — an unscoped one is the pooled
                # defect this codebase forbids — so build those too or the card has no buttons.
                try:
                    byh, _hsrc = bowler_clips_by_hand(bid, fmt=args.fmt, level=args.level,
                                                       source=args.source)
                    _store_hand_reels(entry, byh)
                except Exception as e:
                    # was a bare pass: the card then had no buttons and nothing in the log said why
                    print(f"  ! bowler {nm}: hand reels not built ({type(e).__name__}: {str(e)[:80]})")
                out["bowlers"][bid] = entry
                if fb.get("source") == "footage-only":
                    # Nothing to say AND nothing to watch is the only case worth dropping.
                    _e = out["bowlers"][bid]
                    if not any(_e.get(k) for k in _e if k.endswith("_clips") or "_clips_" in k):
                        del out["bowlers"][bid]
                        print(f"  bowler {nm}: SKIPPED — nothing to say or show in any format")
                        continue
                tag = (f" [{fb.get('source')} · vision {src or 'none'}"
                       f" · stock {len(st)} wkt {len(wk)}]")
            print(f"  bowler {nm}: {len(out['bowlers'][bid]['facts'])} facts{tag}")
        except Exception as e:
            n_err += 1
            print(f"  ! bowler {nm}: {type(e).__name__}: {e}")
    for bid, (nm, hand) in batters.items():
        try:
            if _test_balls(conn, cur, bid, "bat", fmt=args.fmt, level=args.level,
                           source=args.source) >= TEST_FLOOR:
                out["batters"][bid] = {"name": nm,
                                       **distil_batter(build_batter_profile(
                                           bid, fmt=args.fmt, level=args.level,
                                           source=args.source), hand)}
                # card facts = the report's TL;DR summary (richer than distil; coach matchup dropped)
                for tw in ("pace", "spin"):
                    try:
                        pts = card_summary(bid, tw, include_matchup=False)
                        if pts:
                            out["batters"][bid][f"facts_{tw}"] = pts
                    except Exception as e:
                        print(f"  ! card summary {nm} ({tw}): {type(e).__name__}: {str(e)[:60]}")
                # per EXACT bowling type: pace/spin alone still pooled all spin together
                for _tw in _CLIP_GROUPS:
                    _sc, _ds, _scope = batter_clips_best(conn, cur, bid, _tw, fmt=args.fmt, level=args.level,
                                                         source=args.source)
                    out["batters"][bid][f"scoring_clips_{_tw}"] = _sc
                    out["batters"][bid][f"dismissal_clips_{_tw}"] = _ds
                    out["batters"][bid][f"clip_scope_{_tw}"] = _scope
                sc, ds = batter_clips(conn, cur, bid, fmt=args.fmt, level=args.level,
                                      source=args.source)      # unscoped TYPE, kept as fallback
                out["batters"][bid]["scoring_clips"], out["batters"][bid]["dismissal_clips"] = sc, ds
                tag = f" · sco {len(sc)} dsm {len(ds)}"
            else:
                fb = allfmt_batter_facts(conn, cur, bid, hand, STK, SQ,
                                         scope_label=_scope_label(args.fmt, args.level))
                if not fb:
                    # Not enough to profile in any format — but there can still be footage. Shams
                    # Mulani has 248 Cricket-21 first-class balls, under TEST_FLOOR, and the
                    # all-formats fallback reads the warehouse only, so he was skipped outright and
                    # his card showed no vision. Keep a footage-only entry; it is dropped below,
                    # with a log line, only when there is nothing to watch either.
                    note = [f"Limited {_scope_label(args.fmt, args.level)} record — not enough balls to profile."]
                    fb = {"hand": hand, "facts": note, "facts_pace": note, "facts_spin": note,
                          "order": 0, "source": "footage-only"}
                out["batters"][bid] = {"name": nm, **fb}
                # A thin record used to mean NO vision for a batter at all: this branch wrote facts
                # and no clips, so Brad Evans had no footage in any of the eleven bowling packs while
                # 31 ODI and 111 T20I balls of him batting play. Same reels as the full branch.
                for _tw in _CLIP_GROUPS:
                    _sc, _ds, _scope = batter_clips_best(conn, cur, bid, _tw, fmt=args.fmt, level=args.level,
                                                         source=args.source)
                    out["batters"][bid][f"scoring_clips_{_tw}"] = _sc
                    out["batters"][bid][f"dismissal_clips_{_tw}"] = _ds
                    out["batters"][bid][f"clip_scope_{_tw}"] = _scope
                sc, ds = batter_clips(conn, cur, bid, fmt=args.fmt, level=args.level, source=args.source)
                out["batters"][bid]["scoring_clips"], out["batters"][bid]["dismissal_clips"] = sc, ds
                if fb.get("source") == "footage-only":
                    _e = out["batters"][bid]
                    if not any(_e.get(k) for k in _e if k.endswith("_clips") or "_clips_" in k):
                        del out["batters"][bid]
                        print(f"  batter {nm}: SKIPPED — nothing to say or show in any format")
                        continue
                tag = f" [{fb.get('source')} · sco {len(sc)} dsm {len(ds)}]"
            out["batters"][bid]["role"] = batter_role(conn, cur, bid, fmt=args.fmt,
                                                      level=args.level)   # opener/top/middle/lower
            print(f"  batter {nm}: {len(out['batters'][bid]['facts'])} facts{tag}")
        except Exception as e:
            n_err += 1
            print(f"  ! batter {nm}: {type(e).__name__}: {e}")
    conn.close()

    # In merge mode the file on disk already holds everyone else's verified data, so a partial
    # write is worse than no write — a dropped connection would otherwise report success having
    # merged nothing, and with one player a failure is the whole run.
    if merging and n_err:
        raise SystemExit(
            f"ABORTING: {n_err} player rebuild(s) failed — almost certainly the warehouse "
            f"connection, not missing data. opponent_about_{args.opp}.json left untouched; "
            f"re-run when the connection is back.")

    dst = os.path.join(HERE, "data", f"opponent_about_{args.opp}.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {dst}: {len(out['bowlers'])} bowlers, {len(out['batters'])} batters")


if __name__ == "__main__":
    main()
