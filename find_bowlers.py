"""
find_bowlers.py — resolve report player IDs by name.

Usage:
    py -3.12 find_bowlers.py cummins lyon starc          # search several names
    py -3.12 find_bowlers.py "bumrah" --csv               # also append matches to report_bowlers.csv

Prints candidate id · name · team · type · Test balls for each search term so you
can disambiguate duplicate surnames.  With --csv it appends any new matches to
report_bowlers.csv (columns: include,id,name,team,type,balls) — set include=Y on
the rows you want, then run build_reports.py.
"""
import argparse
import csv
import os
import sys
import warnings

warnings.filterwarnings("ignore")

from data_loaders import search_bowlers

CSV_PATH = os.path.join(os.path.dirname(__file__), "report_bowlers.csv")
CSV_COLS = ["include", "id", "name", "team", "type", "balls"]


def _load_existing_ids() -> set:
    if not os.path.exists(CSV_PATH):
        return set()
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        return {row["id"] for row in csv.DictReader(f)}


def _append_rows(rows: list) -> int:
    existing = _load_existing_ids()
    new = [r for r in rows if r["bowler_id"] not in existing]
    if not new:
        return 0
    write_header = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        if write_header:
            w.writeheader()
        for r in new:
            w.writerow({
                "include": "Y",
                "id": r["bowler_id"],
                "name": (r.get("player_name") or "").strip(),
                "team": (r.get("team_name") or "").strip(),
                "type": r.get("bowl_type") or "",
                "balls": r.get("balls") or "",
            })
    return len(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="+", help="One or more name fragments to search for")
    ap.add_argument("--csv", action="store_true", help=f"Append matches to {os.path.basename(CSV_PATH)}")
    args = ap.parse_args()

    all_matches = []
    for term in args.names:
        matches = search_bowlers(term)
        print(f"\n=== '{term}' — {len(matches)} match(es) ===")
        if not matches:
            print("  (no Test bowlers found)")
            continue
        print(f"  {'id':<10} {'name':<24} {'team':<16} {'type':<14} balls")
        for r in matches:
            nm = (r.get("player_name") or "").strip()
            tm = (r.get("team_name") or "").strip()
            print(f"  {r['bowler_id']:<10} {nm:<24} {tm:<16} {(r.get('bowl_type') or ''):<14} {r.get('balls')}")
        all_matches.extend(matches)

    if args.csv and all_matches:
        added = _append_rows(all_matches)
        print(f"\n{added} new row(s) appended to {CSV_PATH}")
        print("Edit the file: set include=N for any you don't want, then run build_reports.py")
    elif not args.csv:
        print("\n(tip: re-run with --csv to save these to report_bowlers.csv)")


if __name__ == "__main__":
    sys.exit(main())
