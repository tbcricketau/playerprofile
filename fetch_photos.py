"""
fetch_photos.py — squad-level refresh CLI for the shared headshot store
(`cricket_core.headshots`; store = cricket-core/headshots/, source = cricket.com.au).

Reports fetch missing headshots on their own at render time (builders pass the player's name),
so this CLI is for BULK work when a new squad lands:

    .\\venv\\Scripts\\python.exe fetch_photos.py --resolve          # map players.json squad -> CA ids, fetch all variants
    .\\venv\\Scripts\\python.exe fetch_photos.py --scan-new         # page-scan CA ids beyond the API cap (newest players)
    .\\venv\\Scripts\\python.exe fetch_photos.py --scan-new 2677-3300
    .\\venv\\Scripts\\python.exe fetch_photos.py --force            # re-pull every mapped player (new season kit)

A player the resolver can't match (rare — brand-new and not yet scanned): run --scan-new, or
paste their id from the profile URL (cricket.com.au/players/CA:xxxx/…) into the store's
ca_ids.csv and re-run.
"""
import argparse
import json
import os

from cricket_core import headshots as hs

HERE = os.path.dirname(os.path.abspath(__file__))


def resolve_squad():
    """Map every players.json squad member into the store's ca_ids.csv."""
    players = json.load(open(os.path.join(HERE, "players.json"), encoding="utf-8"))
    rows = hs.read_map()
    have = {r["player_id"].strip() for r in rows}
    todo = {pid: rec["name"] for pid, rec in players.items() if pid not in have}
    if not todo:
        print("store already maps every squad player")
        return
    print(f"resolving {len(todo)} squad names…")
    for pid, name in todo.items():
        ca_id = hs.resolve_name(name)
        if ca_id:
            rows.append({"player_id": pid, "ca_id": str(ca_id), "name": name,
                         "variants": "", "pulled": ""})
            print(f"  [ok] {name:<22} -> CA:{ca_id}")
        else:
            print(f"  [??] {name:<22} not matched — try --scan-new, or paste the id from "
                  f"cricket.com.au/players/CA:xxxx/… into {hs.MAP_CSV}")
    hs.write_map(rows)
    # refresh the reference snapshot too (merge API list over the scanned entries)
    known = hs.read_reference()
    for p in hs.api_players():
        known.setdefault(int(p["Id"]), p["DisplayName"])
    hs.write_reference(known)
    print(f"map: {hs.MAP_CSV} ({len(rows)} rows) · reference: {len(known)} names")


def fetch_mapped(force=False):
    rows = hs.read_map()
    got = skipped = missed = 0
    for r in rows:
        if r.get("variants") and not force:
            skipped += 1
            continue
        found = hs.fetch_all_variants(r["ca_id"].strip(), r["player_id"].strip())
        name = (r.get("name") or r["player_id"]).strip()
        if found:
            r["variants"], r["pulled"] = "|".join(found), hs._today()
            print(f"  [ok] {name:<22} variants: {', '.join(found)}")
            got += 1
        else:
            print(f"  [--] {name:<22} nothing found for ca_id={r['ca_id']}")
            missed += 1
    hs.write_map(rows)
    print(f"\nfetched {got}, skipped {skipped} (already pulled), missed {missed}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-fetch even players already pulled")
    ap.add_argument("--resolve", action="store_true", help="map players.json squad -> CA ids first")
    ap.add_argument("--scan-new", nargs="?", const="", metavar="START-END",
                    help="page-scan CA ids beyond the API cap into the reference CSV")
    args = ap.parse_args()
    if args.scan_new is not None:
        hits = hs.scan_new(args.scan_new or None)
        for cid, nm in sorted(hits.items()):
            print(f"  CA:{cid}  {nm}")
        print(f"+{len(hits)} new names in the reference")
    if args.resolve:
        resolve_squad()
    fetch_mapped(force=args.force)


if __name__ == "__main__":
    main()
