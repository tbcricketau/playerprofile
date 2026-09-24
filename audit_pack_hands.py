"""audit_pack_hands.py — is every reel on every pack page scoped to what the pack is about?

It began as a hand check. The bowler reels (stock ball / wicket balls / new ball) were built at
hand="All" from the day they shipped, so every batting pack served both hands: Steve Smith's pack
showed Ebadot Hossain bowling to Ben Curran. Fixed 2026-08-10 by building the reels per hand; this
was the check that proved it. It reads the BUILT PAGES rather than the source data — the same
principle as check_site.py, since what matters is what gets served.

Since 24-09-2026 it opens BOTH pack page kinds and follows EVERY play button (an unrecognised key is
a refusal, not a skip), maps each clip back to a delivery via the filename (which encodes match +
end + innings + over + ball), and holds each reel to its kind's rule: the right player at the right
end (owner), the pack batter's hand, the bowler type the key declares, and the pack's red/white
format. See `_classify` for the kinds and CLAUDE.md §"The audit opens every pack page".

Needs the warehouse. Run after a build, before publishing:
    .\\venv\\Scripts\\python.exe audit_pack_hands.py --site player_site --opp bangladesh
Exit 1 if any reel is mixed or wrong, so it can gate a publish.
"""
import argparse
import html as _html
import json
import os
import re
import sys
from urllib.parse import unquote

from cricket_core.warehouse import set_conn_cursor, run_query
from config import DATA_SCHEMA
from build_player_site import _our_hands, PLAYERS

HERE = os.path.dirname(os.path.abspath(__file__))
# EVERY play button is collected — the pattern is deliberately loose. Until 24-09-2026 it named the
# reel kinds it knew (`stock|wkt|nb|dth|mid`), so a kind it did not know was never collected, never
# audited, and published in silence: 509 of the 1,123 buttons in the South Africa bundle — every
# head-to-head reel, every scoring/dismissal reel on a bowling pack, the release cells — were
# outside the gate while it reported "clean". Now an unrecognised key is a REFUSAL, so a new reel
# kind shows up as a new row in the histogram rather than as silence. `dth` (death overs) was
# added 2026-09-13 with the reel itself; the lesson of that entry stands, it is just enforced now.
KEY_RE = r'-vision\.html#([A-Za-z0-9_]+)'

# The reel kinds and what each is scoped to. `owner` is which side of the delivery must be the
# player the key names (the `_<id>` suffix) or the pack's own player (`page`).
#   opp_bowler  stock|wkt|nb|dth|mid + hand, on a BATTING pack: an opposition bowler's balls, all
#               bowled BY that bowler, TO the pack batter's hand, in the pack's red/white format.
#   opp_batter  sco|dsm + type code, on a BOWLING pack: an opposition batter's balls, all faced BY
#               that batter, FROM the bowler type the key declares (RP/LP/OS/LS/LO/LU exact; s/p
#               the declared macro fallback), in the pack's format.
#   h2h         hbat_<bowler> on a batting pack / hbowl_<striker> on a bowling pack: the pack
#               player at one end, the named opponent at the other, pack format.
#   own         rel<i> (release cells, bowler = pack player), s<i> / c<i>p<j> (attack-card
#               dismissals and cells, striker = pack player). No format rule — their own record.
#   manual      man_<id>_<key>: hand-supplied footage with no delivery id. Counted, not checked.
#   similar     the reference bowler's reel. Counted, not checked.
_TYPE_CODE = {"RP": "right_pace", "LP": "left_pace", "OS": "off_spin", "LS": "leg_spin",
              "LO": "left_orthodox", "LU": "left_unorthodox", "p": "pace", "s": "spin"}
_FAMILY = {"right_pace": "pace", "left_pace": "pace", "off_spin": "spin", "leg_spin": "spin",
           "left_orthodox": "spin", "left_unorthodox": "spin"}


def _classify(key):
    """(kind, detail) for a playlist key, or ('unknown', None)."""
    m = re.match(r'^(stock|wkt|nb|dth|mid)(X?)([LR])_(\d+)$', key)
    if m:
        return "opp_bowler", {"x": bool(m.group(2)), "hand": "lhb" if m.group(3) == "L" else "rhb",
                              "them": m.group(4)}
    m = re.match(r'^(sco|dsm)(RP|LP|OS|LS|LO|LU|s|p)_(\d+)$', key)
    if m:
        return "opp_batter", {"group": _TYPE_CODE[m.group(2)], "them": m.group(3),
                              "macro": m.group(2) in ("s", "p")}
    m = re.match(r'^h(bat|bowl)_(\d+)$', key)
    if m:
        return "h2h", {"dir": m.group(1), "them": m.group(2)}
    if re.match(r'^rel\d+$', key):
        return "own", {"side": "bowler"}
    if re.match(r'^(s\d+|c\d+[ps]\d+)$', key):
        return "own", {"side": "striker"}
    if key.startswith("man_"):
        return "manual", None
    if key == "similar":
        return "similar", None
    return "unknown", None


def _base(u):
    """The clip's basename — unique per delivery, and the one part of the path that survives both
    the stored stem and the resolved SAS url (the season segment differs between them)."""
    return os.path.splitext(os.path.basename(unquote(u.split("?")[0])))[0].upper()


def _series_fmt(series_name):
    """Coarse RED/WHITE-ball format of a Series.name — 'Test' / 'ODI' / 'T20' / '' (unknown).

    This is a red-vs-white check, not a level one: 'Test' here means red-ball, so A-team
    first-class cricket belongs in it. It has to, because the gate only rejects what it can
    classify — 'International 1st Class M' and 'International Tour Matches M' matched none of
    these tests and came back '' , which the caller skips. An Australia A four-day pack could then
    have carried a List A reel and been passed as clean, the same shape of hole as the hand audit
    that never looked at format.

    Order matters: 'International List A ODI M' has to reach the white-ball test, so the
    first-class check names its buckets rather than matching a loose 'class'/'tour'."""
    n = (series_name or "").lower()
    if "1st class" in n or "first class" in n or "tour matches" in n:
        return "Test"                       # A-team / tour red-ball cricket
    if "test" in n:
        return "Test"
    if "odi" in n or "one day" in n or "one-day" in n or "list a" in n:
        return "ODI"
    if "t20" in n or "hundred" in n or "t10" in n:
        return "T20"
    return ""


def _pack_pages(site):
    """Every pack page under `site`, at any depth — (root, filename, 'batting'|'bowling', page slug).
    The built site keeps them flat, the assembled bundle nests them under players/. Bowling packs
    were never opened before 24-09-2026, which is how 45% of the reel buttons went unaudited."""
    for root, _dirs, files in os.walk(site):
        for fn in sorted(files):
            if fn.endswith("-batting.html"):
                yield root, fn, "batting", fn[:-len("-batting.html")]
            elif "-bowling-" in fn and fn.endswith(".html"):
                yield root, fn, "bowling", fn.split("-bowling-")[0]


def run_audit(site, opp="bangladesh", slug="bangladesh-home-2026", quiet=False, fmt=None):
    """A dict of counts — mixed / wrong / pooled / offfmt are defects; unres, blind, hands_empty
    and fmt_checked say how much of the bundle the audit could actually see. Raises if the
    warehouse is unreachable.

    The coverage fields exist because this gate has passed things it never looked at. A page whose
    name could not be matched to a player id (`Fergus O&#x27;Neill` — the h1 is HTML-escaped and
    the lookup was not) had `want=None`, which skipped the wrong-hand test for every reel on it
    while the summary still read "clean, all one hand". An empty `hands` dict (a moved or mis-keyed
    matchup store) did the same to every page. And the unresolved count was returned and thrown
    away by the caller. A gate must report what it did not check, or "clean" means nothing."""
    site = site if os.path.isabs(site) else os.path.join(HERE, site)

    hands = _our_hands(slug)
    players = json.load(open(PLAYERS, encoding="utf-8"))
    name2pid = {(r.get("name") or "").lower(): p for p, r in players.items()}
    about = json.load(open(os.path.join(HERE, "data", f"opponent_about_{opp}.json"),
                           encoding="utf-8"))

    stem2id, c21_ids = {}, set()

    def _index(e):
        # Index BOTH clip sources. A Fairplay entry carries an extension-less stem; a Cricket-21
        # entry carries a finished url. Indexing only stems left every C21 clip unresolvable, and
        # an unresolvable clip is dropped from the reel's id list — so a reel made entirely of C21
        # footage would have looked EMPTY and passed as clean without being checked at all.
        if isinstance(e, dict) and e.get("delivery_id"):
            if e.get("clip_stem"):
                stem2id[_base(e["clip_stem"])] = str(e["delivery_id"])
            elif e.get("url"):
                stem2id[_base(e["url"])] = str(e["delivery_id"])
                c21_ids.add(str(e["delivery_id"]))

    for grp in ("bowlers", "batters"):
        for v in about.get(grp, {}).values():
            for key, lst in v.items():
                if isinstance(lst, list) and "clips" in key:
                    for e in lst:
                        _index(e)
    # The head-to-head reels' clips live in h2h_<opp>.json, and the release-cell reels' in
    # release_detail.json, not opponent_about — without these every hbat_/hbowl_/rel button
    # resolves to nothing.
    h2h_path = os.path.join(HERE, "data", f"h2h_{opp}.json")
    if os.path.exists(h2h_path):
        h2h = json.load(open(h2h_path, encoding="utf-8"))
        for sec in ("our_batting", "our_bowling"):
            for r in h2h.get(sec, []):
                for d in r.get("deliveries", []):
                    _index(d)
    rel_path = os.path.join(HERE, "data", "release_detail.json")
    if os.path.exists(rel_path):
        for rec in json.load(open(rel_path, encoding="utf-8")).values():
            for c in rec.get("cells", []):
                for e in c.get("clips") or []:
                    _index(e)

    reels, allids, kinds, unknown = {}, set(), {}, []
    for root, fn, pkind, ps in _pack_pages(site):
        page = open(os.path.join(root, fn), encoding="utf-8").read()
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        # unescape: the builder writes the name through html.escape, so an apostrophe arrives as
        # &#x27; and a raw comparison against players.json misses the player entirely.
        nm = _html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip().lower() if h1 else ""
        vp = os.path.join(root, f"{ps}-vision.html")
        pls = {}
        if os.path.exists(vp):
            m = re.search(r'PLAYLISTS\s*=\s*(\{.*?\});', open(vp, encoding="utf-8").read(), re.S)
            pls = json.loads(m.group(1)) if m else {}
        # A button whose text ends in `*` is the builder's DECLARED fallback — the reel was built
        # from a wider bowler type or a neighbouring format than the pack asked for, and the page
        # footnotes it. It is held to the family it fell back to. An unstarred reel is held to the
        # exact type its key declares, so a pooled reel with no label still fails.
        starred = {m.group(1) for m in re.finditer(
            r'<a[^>]*data-pl="([A-Za-z0-9_]+)"[^>]*>[^<]*\*\s*</a>', page)}
        for k in sorted(set(re.findall(KEY_RE, page))):
            kind, det = _classify(k)
            kinds[kind] = kinds.get(kind, 0) + 1
            if kind == "unknown":
                unknown.append(f"{fn}#{k}")
                continue
            if det is not None and k in starred:
                det = {**det, "starred": True}
            items = (pls.get(k) or {}).get("items", [])
            ids = [stem2id[_base(it["url"])] for it in items if _base(it.get("url", "")) in stem2id]
            reels[(fn, pkind, nm, k)] = (kind, det, ids, len(items))
            allids.update(ids)

    conn, cur = set_conn_cursor()
    # Resolve the FORMAT of each clip's match alongside the hand. This audit checked only whose
    # hand a clip was bowled to, so it reported 203/203 clean while every hand-scoped reel in the
    # Zimbabwe ODI packs was built from Test deliveries (build_opponent_about called the loader
    # with no fmt and got the Test default). A gate only checks what it was built to check.
    # …and WHO is at each end and what the bowler bowls, so a reel can be held to its owner and
    # its declared bowler type, not just to a hand. facts[did] = {hand, fmt, striker, bowler, group}
    facts, allids = {}, sorted(allids)
    for i in range(0, len(allids), 500):
        ch = allids[i:i + 500]
        q = (f"SELECT D.delivery_id did, PL.batting_hand_id bh, SR.name series, "
             f"D.striker_id sid, D.bowler_id bid, "
             f"CASE WHEN D.bowler_style_id IN ('1','2','3') AND D.bowler_hand_id='1' THEN 'right_pace' "
             f"     WHEN D.bowler_style_id IN ('1','2','3') AND D.bowler_hand_id='2' THEN 'left_pace' "
             f"     WHEN D.bowler_style_id='4' AND D.bowler_hand_id='1' THEN 'off_spin' "
             f"     WHEN D.bowler_style_id='4' AND D.bowler_hand_id='2' THEN 'left_orthodox' "
             f"     WHEN D.bowler_style_id='5' AND D.bowler_hand_id='1' THEN 'leg_spin' "
             f"     WHEN D.bowler_style_id='5' AND D.bowler_hand_id='2' THEN 'left_unorthodox' "
             f"     ELSE NULL END grp "
             f"FROM [{DATA_SCHEMA}].[Deliveries] D "
             f"LEFT JOIN [{DATA_SCHEMA}].[Players] PL ON PL.player_id=D.striker_id "
             f"LEFT JOIN [{DATA_SCHEMA}].[Matches] M ON M.match_id=D.match_id "
             f"LEFT JOIN [{DATA_SCHEMA}].[Series] SR ON SR.series_id=M.series_id "
             f"WHERE D.delivery_id IN ({', '.join(chr(39) + str(x) + chr(39) for x in ch)})")
        for r in run_query(q, conn, cur):
            facts[str(r["did"])] = {"hand": "lhb" if r["bh"] == "2" else "rhb",
                                    "fmt": _series_fmt(r.get("series")),
                                    "striker": str(r["sid"]), "bowler": str(r["bid"]),
                                    "group": r.get("grp") if r.get("grp") not in (None, "None") else None}
    # Cricket-21 deliveries are not in the warehouse — resolve those from the mirror, or every
    # C21 reel goes unchecked. The gate has to be able to see all the footage it is gating.
    #
    # Selected by PROVENANCE (the entry carried a url, not a stem), never by id shape. C21 ids are
    # six digits and warehouse ids sixteen, so they cannot collide today — but that is an observed
    # fact about two independent id spaces, not a guarantee, and if one ever did collide the
    # warehouse query above would have answered it with a different player's hand. Where an id is
    # known to be C21, the mirror's answer wins.
    unseen = [i for i in allids if str(i) in c21_ids]
    if unseen:
        try:
            import c21_source
            facts.update(c21_source.delivery_facts(unseen))
        except Exception as e:
            raise SystemExit(
                f"the hand audit could not resolve {len(unseen)} Cricket-21 clip(s) "
                f"({type(e).__name__}: {str(e)[:100]}). Refusing rather than skipping them — "
                f"an unchecked reel is what this gate exists to prevent.")

    mixed = wrong = pooled = unres = offfmt = xhand = owner = typ = macro = 0
    want_fmt = {"test": "Test", "odi": "ODI", "t20i": "T20", "t20": "T20"}.get(str(fmt or "").lower())
    red, white = {"Test"}, {"ODI", "T20"}
    pages, blind, unchecked = set(), set(), 0

    def _fmt_check(fn, k, ids):
        # FORMAT. A reel may legitimately borrow a neighbouring white-ball format when the pack's
        # own is thin (build_opponent_about steps ODI -> T20I -> T20), but a RED-ball clip in a
        # white-ball pack is never right, and vice versa.
        nonlocal offfmt
        if want_fmt:
            fgot = {facts[i]["fmt"] for i in ids if i in facts and facts[i]["fmt"]}
            bad = (fgot & red) if want_fmt in white else (fgot & white)
            if bad:
                offfmt += 1
                print(f"  OFF-FORMAT {fn:<30} {k:<16} pack={want_fmt} reel={sorted(fgot)}")

    def _owner_check(fn, k, ids, side, who):
        # OWNER. Every clip must have `who` at the `side` end — a reel of the right hand and format
        # but the wrong player entirely passed every earlier version of this audit.
        nonlocal owner
        got = {facts[i][side] for i in ids if i in facts and facts[i].get(side)}
        if got and got != {str(who)}:
            owner += 1
            print(f"  OWNER   {fn:<30} {k:<16} {side} should be {who}, reel has {sorted(got)[:3]}")

    for (fn, pkind, nm, k), (kind, det, ids, n_items) in sorted(reels.items()):
        pages.add(fn)
        pid = name2pid.get(nm)
        if kind in ("manual", "similar"):
            unchecked += 1                # no delivery ids to resolve; counted so it is visible
            continue
        if pid is None:
            blind.add(fn)                 # this page's player is unknown: nothing below can bind
            if not quiet:
                print(f"  BLIND   {fn:<30} name {nm!r} resolves to no player")
        if not ids:
            unres += 1
            if not quiet:
                print(f"  UNRESOLVED  {fn:<26} {k:<16} ({n_items} clips, none map to a delivery)")
            continue

        if kind == "opp_bowler":
            if pkind != "batting":
                wrong += 1
                print(f"  WRONG   {fn:<30} {k:<16} a batter-hand reel on a bowling pack")
            want = hands.get(pid)
            # A DECLARED other-hand reel — key stockXR_ / wktXL_ — is the stated fallback for a
            # bowler with no footage at all to this pack's hand (Tanaka Chivanga has 2 playable ODI
            # balls to left-handers). The button says which hand it shows. It is still checked,
            # against the hand it DECLARES: it must be entirely that hand, and that hand must not
            # be the pack's own, or the label is wrong.
            if det["x"]:
                xhand += 1
                if want and det["hand"] == want:
                    wrong += 1
                    print(f"  WRONG   {fn:<30} {k:<16} labelled other-hand, but the pack is {want}")
                want = det["hand"]
            got = {facts[i]["hand"] for i in ids if i in facts}
            if len(got) > 1:
                mixed += 1
                print(f"  MIXED   {fn:<30} {k:<16} {len(ids):>3} clips -> {sorted(got)}")
            elif want and got and next(iter(got)) != want:
                wrong += 1
                print(f"  WRONG   {fn:<30} {k:<16} pack={want} reel={next(iter(got))}")
            _owner_check(fn, k, ids, "bowler", det["them"])
            _fmt_check(fn, k, ids)

        elif kind == "opp_batter":
            if pkind != "bowling":
                wrong += 1
                print(f"  WRONG   {fn:<30} {k:<16} a bowler-type reel on a batting pack")
            _owner_check(fn, k, ids, "striker", det["them"])
            # TYPE. The key declares the bowler type the clips must come from. An exact code must
            # match exactly; the macro codes (s/p) are the starred fallback and are held to the
            # family, and counted so the number of pooled reels in a bundle is on the record.
            groups = {facts[i]["group"] for i in ids if i in facts and facts[i].get("group")}
            if det["macro"] or det.get("starred"):
                macro += 1
                fam = det["group"] if det["macro"] else _FAMILY.get(det["group"])
                bad = {g for g in groups if _FAMILY.get(g) != fam}
            else:
                bad = groups - {det["group"]}
            if bad:
                typ += 1
                print(f"  TYPE    {fn:<30} {k:<16} declares {det['group']}, reel has {sorted(groups)}")
            _fmt_check(fn, k, ids)

        elif kind == "h2h":
            me, them = ("striker", "bowler") if det["dir"] == "bat" else ("bowler", "striker")
            if (det["dir"] == "bat") != (pkind == "batting"):
                wrong += 1
                print(f"  WRONG   {fn:<30} {k:<16} h2h direction does not match the pack")
            if pid is not None:
                _owner_check(fn, k, ids, me, pid)
            _owner_check(fn, k, ids, them, det["them"])
            _fmt_check(fn, k, ids)

        elif kind == "own":
            if pid is not None:
                _owner_check(fn, k, ids, det["side"], pid)

    hist = " · ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
    print(f"  {len(reels)} reels across {len(pages)} pack pages — "
          f"mixed {mixed} · wrong {wrong} · owner {owner} · type {typ} · off-format {offfmt} · "
          f"unresolved {unres} · declared other-hand {xhand} · declared macro-type {macro}")
    print(f"  kinds — {hist}")
    print(f"  coverage — player resolved on {len(pages) - len(blind)} of {len(pages)} pages"
          f"{' (NO batter hands at all: matchup store missing?)' if not hands else ''} · "
          f"format {want_fmt or 'NOT CHECKED'} · {len(reels) - unres - unchecked} of {len(reels)} "
          f"reels resolved · {unchecked} manual/similar reels not checkable · "
          f"{len(unknown)} unrecognised keys")
    return {"mixed": mixed, "wrong": wrong, "pooled": pooled, "offfmt": offfmt, "owner": owner,
            "type": typ, "macro": macro, "unres": unres, "blind": sorted(blind),
            "hands_empty": not hands, "fmt_checked": bool(want_fmt), "unknown": unknown,
            "unchecked": unchecked, "kinds": kinds, "n": len(reels), "pages": len(pages),
            "xhand": xhand}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="player_site")
    ap.add_argument("--opp", default="bangladesh")
    ap.add_argument("--slug", default="bangladesh-home-2026")
    ap.add_argument("--fmt", default=None, help="pack format (Test/ODI/T20I) — also checks that no "
                                                "clip comes from the wrong side of red/white ball")
    a = ap.parse_args()
    r = run_audit(a.site, a.opp, a.slug, fmt=a.fmt)
    return 1 if (r["mixed"] or r["wrong"] or r["pooled"] or r["offfmt"] or r["owner"] or r["type"]
                 or r["unres"] or r["blind"] or r["hands_empty"] or r["unknown"]) else 0


if __name__ == "__main__":
    sys.exit(main())
