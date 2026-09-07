"""
build_c21_player_map.py — map warehouse player ids to Cricket-21 player ids, by name.

C21 keys players in its own namespace, so nothing joins to warehouse data without this. It is
written to a FILE and printed for review rather than matched at query time, because a name match
that quietly misses returns zero rows and reads exactly like "this player has no data" — which is
how Saransh Jain came to be reported as having none when he has 2,535 first-class deliveries.

    .\\venv\\Scripts\\python.exe build_c21_player_map.py --opp india_a_4day india_a_od
    .\\venv\\Scripts\\python.exe build_c21_player_map.py --opp india_a_4day --dry-run

Out: data/c21_player_map.json  {warehouse_id: {name, c21_ids, c21_name, balls, confidence}}

Every row prints its C21 name beside the squad name. Read that column — a surname-only match on a
common Indian surname is exactly where this goes wrong, and it is flagged.
"""
import argparse
import json
import os
import sqlite3
from collections import defaultdict

from cricket_core.config import project_path

HERE = os.path.dirname(os.path.abspath(__file__))
MIRROR = os.path.join(str(project_path("cricket21")), "data", "cricket21_mirror.sqlite")
OUT = os.path.join(HERE, "data", "c21_player_map.json")
MM = os.path.join(str(project_path("matchupmodel")), "data")
INDIA = ("Ranji", "Duleep", "Hazare", "Irani", "India A")


def _c21_players():
    """{c21_player_id: (name, bowl_balls, bat_balls)} across the Indian domestic matches."""
    con = sqlite3.connect(f"file:{MIRROR}?mode=ro", uri=True)
    like = " OR ".join(f"m.competition_name LIKE '%{k}%'" for k in INDIA)
    out = defaultdict(lambda: ["", 0, 0])
    for col, idx in (("bowler", 1), ("striker", 2)):
        q = (f"SELECT d.{col}_id AS pid, d.{col}_name AS nm, COUNT(*) AS n "
             f"FROM deliveries d JOIN matches m ON m.match_id = d.match_id "
             f"WHERE ({like}) AND d.{col}_id IS NOT NULL "
             f"GROUP BY d.{col}_id, d.{col}_name")
        for pid, nm, n in con.execute(q):
            rec = out[int(pid)]
            rec[0] = rec[0] or (nm or "").strip()
            rec[idx] += int(n)
    con.close()
    return {k: tuple(v) for k, v in out.items()}


def _score(want, got):
    """How well a squad name matches a C21 name. Surname must match exactly; the given name decides
    confidence. 0 = no match.

    Indian names make this harder than the warehouse resolver's job. Two rules earned the hard way
    on 2026-09-07:

    * A prefix match needs THREE characters on BOTH sides. "Mohd Arshad Khan" matched
      "M Shahrukh Khan" because "mohd".startswith("m") — a different player, accepted at prefix
      confidence, and only a human reading the C21 name column would have caught it.
    * The squad's given name may sit in the MIDDLE of the full name: Tilak Varma is recorded as
      "Namboori Tilak Varma". That is the right player and scored surname-only until this looked
      past the first token.
    """
    w, g = want.split(), got.split()
    if not w or not g or w[-1].lower() != g[-1].lower():
        return 0
    wf, gf = w[0].lower(), g[0].lower()
    rest = [x.lower() for x in g[:-1]]
    want_rest = [x.lower() for x in w[:-1]]
    if wf == gf:
        return 3                              # exact given name
    if set(want_rest) & set(rest):
        # ANY given/middle name in common, in either order. "Mohd Arshad Khan" is recorded as
        # "Arshad Khan"; "Tilak Varma" as "Namboori Tilak Varma". Comparing first tokens alone
        # missed both and let "M Shahrukh Khan" and "Mohsin Khan" score higher than the real one.
        return 3
    if len(wf) >= 3 and len(gf) >= 3 and (gf.startswith(wf) or wf.startswith(gf)):
        return 2                              # a genuine shortening (Mohd/Mohammed), not an initial
    return 1                                  # surname only — flagged for review


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--opp", nargs="+", default=["india_a_4day", "india_a_od"],
                    help="opp_squad_{key}.json files supplying the names to map")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    a = ap.parse_args()

    want = {}
    for key in a.opp:
        p = os.path.join(MM, f"opp_squad_{key}.json")
        for pid, nm in (json.load(open(p, encoding="utf-8")).get("names") or {}).items():
            want.setdefault(str(pid), nm)

    c21 = _c21_players()
    print(f"{len(c21)} players appear in the mirror's Indian domestic cricket\n")
    print(f"  {'squad name':<24}{'warehouse':<10}{'C21 name':<24}{'bowl':>7}{'bat':>7}  conf")

    out, unmatched, weak, unresolved = {}, [], [], []
    for wid, nm in sorted(want.items(), key=lambda kv: kv[1]):
        cands = [(sc, cid, v) for cid, v in c21.items()
                 if (sc := _score(nm, v[0])) > 0]
        if not cands:
            unmatched.append(nm)
            print(f"  {nm[:23]:<24}{wid:<10}{'— no match —':<24}{'':>7}{'':>7}")
            continue
        best = max(c[0] for c in cands)
        top = [c for c in cands if c[0] == best]
        # Merge only IDENTICAL C21 names — the vendor does duplicate a player across ids. Two
        # different names scoring the same are two different people, and unioning them would
        # attribute one player's cricket to another without a word.
        chosen_name = max(top, key=lambda c: c[2][1] + c[2][2])[2][0]
        keep = [c for c in top if c[2][0] == chosen_name]
        rejected = [c[2][0] for c in top if c[2][0] != chosen_name]
        ids = [c[1] for c in keep]
        bowl = sum(c[2][1] for c in keep)
        bat = sum(c[2][2] for c in keep)
        cname = keep[0][2][0]
        conf = {3: "exact", 2: "prefix", 1: "SURNAME ONLY"}[best]
        extra = f"  (+{len(keep) - 1} more)" if len(keep) > 1 else ""
        if best == 1:
            # A surname-only match is NOT written. Picking the highest-volume candidate chose
            # "Mohsin Khan" for Mohd Arshad Khan and would have attributed 522 deliveries to the
            # wrong player. No map is recoverable; a wrong map is invisible.
            unresolved.append((nm, [c[2][0] for c in top]))
            print(f"  {nm[:23]:<24}{wid:<10}{'-- surname only, NOT mapped --':<24}")
            continue
        if best == 2 or rejected:
            weak.append((nm, cname, conf, len(keep), rejected))
        print(f"  {nm[:23]:<24}{wid:<10}{cname[:23]:<24}{bowl:>7}{bat:>7}  {conf}{extra}")
        out[wid] = {"name": nm, "c21_ids": ids, "c21_name": cname,
                    "bowl_balls": bowl, "bat_balls": bat, "confidence": conf}

    print(f"\n  mapped {len(out)} of {len(want)}")
    if unmatched:
        print(f"  no C21 record ({len(unmatched)}): {', '.join(unmatched)}")
    if unresolved:
        print(f"  !! AMBIGUOUS ({len(unresolved)}) - surname matched but no given name did, so "
              f"these are UNMAPPED rather than guessed.\n"
              f"     Add a c21_ids entry by hand to use them:")
        for nm, cands in unresolved:
            print(f"     {nm:<24} candidates: {', '.join(sorted(set(cands))[:6])}")
    if weak:
        print("  !! REVIEW these - a wrong map silently attributes another player's cricket:")
        for nm, cname, conf, n, rej in weak:
            note = f" | {n} ids merged" if n > 1 else ""
            note += f" | NOT merged: {', '.join(rej)}" if rej else ""
            print(f"     {nm:<24} -> {cname:<24} {conf}{note}")

    if a.dry_run:
        print("\n(dry run — nothing written)")
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
