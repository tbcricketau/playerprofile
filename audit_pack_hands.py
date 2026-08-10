"""audit_pack_hands.py — does every reel in a batting pack contain ONLY the pack batter's hand?

The bowler reels (stock ball / wicket balls / new ball) were built at hand="All" from the day they
shipped, so every batting pack served both hands: Steve Smith's pack showed Ebadot Hossain bowling
to Ben Curran. Fixed 2026-08-10 by building the reels per hand; this is the check that proves it,
and it reads the BUILT PAGES rather than the source data — the same principle as check_site.py,
since what matters is what gets served.

For each *-batting.html page it follows every play button to its playlist, maps each clip back to a
delivery via the filename (which encodes match + end + innings + over + ball), and resolves the
striker's registered hand. Reports any reel holding both hands, or the wrong one.

Needs the warehouse. Run after a build, before publishing:
    .\\venv\\Scripts\\python.exe audit_pack_hands.py --site player_site --opp bangladesh
Exit 1 if any reel is mixed or wrong, so it can gate a publish.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import unquote

from cricket_core.warehouse import set_conn_cursor, run_query
from config import DATA_SCHEMA
from build_player_site import _our_hands, PLAYERS

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_RE = r'-vision\.html#((?:stock|wkt|nb)[A-Z]*_\d+)'


def _base(u):
    """The clip's basename — unique per delivery, and the one part of the path that survives both
    the stored stem and the resolved SAS url (the season segment differs between them)."""
    return os.path.splitext(os.path.basename(unquote(u.split("?")[0])))[0].upper()


def _batting_pages(site):
    """Every *-batting.html under `site`, at any depth — the built site keeps them flat, the
    assembled bundle nests them under players/."""
    for root, _dirs, files in os.walk(site):
        for fn in sorted(files):
            if fn.endswith("-batting.html"):
                yield root, fn


def run_audit(site, opp="bangladesh", slug="bangladesh-home-2026", quiet=False):
    """(mixed, wrong, pooled, unresolved, n_reels, n_pages) — 0/0/0 means every reel in every
    batting pack holds only that pack batter's hand. Raises if the warehouse is unreachable."""
    site = site if os.path.isabs(site) else os.path.join(HERE, site)

    hands = _our_hands(slug)
    players = json.load(open(PLAYERS, encoding="utf-8"))
    name2pid = {(r.get("name") or "").lower(): p for p, r in players.items()}
    about = json.load(open(os.path.join(HERE, "data", f"opponent_about_{opp}.json"),
                           encoding="utf-8"))

    stem2id = {}
    for grp in ("bowlers", "batters"):
        for v in about.get(grp, {}).values():
            for key, lst in v.items():
                if isinstance(lst, list) and "clips" in key:
                    for e in lst:
                        if isinstance(e, dict) and e.get("clip_stem"):
                            stem2id[_base(e["clip_stem"])] = e["delivery_id"]

    reels, allids = {}, set()
    for root, fn in _batting_pages(site):
        ps = fn[:-len("-batting.html")]
        page = open(os.path.join(root, fn), encoding="utf-8").read()
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        nm = re.sub(r"<[^>]+>", "", h1.group(1)).strip().lower() if h1 else ""
        vp = os.path.join(root, f"{ps}-vision.html")
        pls = {}
        if os.path.exists(vp):
            m = re.search(r'PLAYLISTS\s*=\s*(\{.*?\});', open(vp, encoding="utf-8").read(), re.S)
            pls = json.loads(m.group(1)) if m else {}
        for k in sorted(set(re.findall(KEY_RE, page))):
            ids = [stem2id[_base(it["url"])] for it in (pls.get(k) or {}).get("items", [])
                   if _base(it.get("url", "")) in stem2id]
            reels[(ps, nm, k)] = ids
            allids.update(ids)

    conn, cur = set_conn_cursor()
    hand_of, allids = {}, sorted(allids)
    for i in range(0, len(allids), 500):
        ch = allids[i:i + 500]
        q = (f"SELECT D.delivery_id did, PL.batting_hand_id bh FROM [{DATA_SCHEMA}].[Deliveries] D "
             f"LEFT JOIN [{DATA_SCHEMA}].[Players] PL ON PL.player_id=D.striker_id "
             f"WHERE D.delivery_id IN ({', '.join(chr(39) + str(x) + chr(39) for x in ch)})")
        for r in run_query(q, conn, cur):
            hand_of[r["did"]] = "lhb" if r["bh"] == "2" else "rhb"

    mixed = wrong = pooled = unres = 0
    pages = set()
    for (ps, nm, k), ids in sorted(reels.items()):
        pages.add(ps)
        if not re.match(r'^(stock|wkt|nb)[LR]_', k):
            pooled += 1
            print(f"  POOLED  {ps:<24} {k}  (not scoped to a hand)")
        if not ids:
            unres += 1
            if not quiet:
                print(f"  UNRESOLVED  {ps:<24} {k}")
            continue
        want = hands.get(name2pid.get(nm))
        got = {hand_of[i] for i in ids if i in hand_of}
        if len(got) > 1:
            mixed += 1
            print(f"  MIXED   {ps:<24} {k:<14} {len(ids):>3} clips -> {sorted(got)}")
        elif want and got and next(iter(got)) != want:
            wrong += 1
            print(f"  WRONG   {ps:<24} {k:<14} pack={want} reel={next(iter(got))}")

    print(f"  {len(reels)} bowler reels across {len(pages)} batting packs — "
          f"mixed {mixed} · wrong {wrong} · pooled {pooled} · unresolved {unres}")
    return mixed, wrong, pooled, unres, len(reels), len(pages)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="player_site")
    ap.add_argument("--opp", default="bangladesh")
    ap.add_argument("--slug", default="bangladesh-home-2026")
    a = ap.parse_args()
    mixed, wrong, pooled, _unres, _n, _p = run_audit(a.site, a.opp, a.slug)
    return 1 if (mixed or wrong or pooled) else 0


if __name__ == "__main__":
    sys.exit(main())
