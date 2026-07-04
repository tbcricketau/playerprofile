"""
build_reports.py — batch-generate one scouting PDF per bowler.

Player IDs come from either --ids or a CSV (default report_bowlers.csv, using
rows where include=Y — produced by find_bowlers.py).

Examples:
    py -3.12 build_reports.py --hand lhb                       # every include=Y row in report_bowlers.csv, vs LHB
    py -3.12 build_reports.py --hand all --ids 1300071 1300076 # explicit IDs
    py -3.12 build_reports.py --hand rhb --ids 1300071,1300076 # comma or space separated
    py -3.12 build_reports.py --hand all --out reports/round1   # custom output folder

The --hand argument is required; more filters (--position, --spell) can be added
later without changing callers.
"""
import argparse
import csv
import os
import sys
import warnings

warnings.filterwarnings("ignore")

from report import render_report

_HAND = {
    "all": "All", "lhb": "vs LHB", "rhb": "vs RHB",
    "vs lhb": "vs LHB", "vs rhb": "vs RHB",
}
DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "report_bowlers.csv")


def _ids_from_args(raw: list) -> list:
    """Accept space- and/or comma-separated IDs."""
    out = []
    for chunk in raw:
        out.extend(x.strip() for x in chunk.split(",") if x.strip())
    return out


def _ids_from_csv(path: str) -> list:
    if not os.path.exists(path):
        sys.exit(f"CSV not found: {path}\nRun find_bowlers.py first, or pass --ids.")
    ids = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("include") or "").strip().upper() in ("Y", "YES", "1", "TRUE"):
                ids.append(row["id"].strip())
    return ids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hand", required=True, help="Batter hand: all | lhb | rhb")
    ap.add_argument("--ids", nargs="+", help="Explicit bowler IDs (space or comma separated)")
    ap.add_argument("--csv", default=DEFAULT_CSV, help=f"CSV of players (default: {os.path.basename(DEFAULT_CSV)})")
    ap.add_argument("--out", default="reports", help="Output folder (default: reports)")
    # Room to grow — accepted now, threaded straight through to build_profile.
    ap.add_argument("--position", default="All positions", help='e.g. "Openers (1-2)", "Top 3", "Top 4"')
    ap.add_argument("--spell", default="All", help='e.g. "Opening (Spell 1)", "Later (Spell 2+)"')
    ap.add_argument("--length", default="Zones", help='"Zones", "1m bands", "0.5m bands"')
    ap.add_argument("--target-country", default="Australia",
                    help="Where the next series is played — orders video examples like-for-like "
                         "(that country's conditions first). Use 'none' for pure recency.")
    args = ap.parse_args()
    target_country = None if args.target_country.strip().lower() in ("none", "") else args.target_country

    hand = _HAND.get(args.hand.strip().lower())
    if hand is None:
        sys.exit(f"Invalid --hand '{args.hand}'. Use: all | lhb | rhb")

    ids = _ids_from_args(args.ids) if args.ids else _ids_from_csv(args.csv)
    if not ids:
        sys.exit("No bowler IDs to run (empty --ids and no include=Y rows in the CSV).")

    print(f"Generating {len(ids)} report(s) — hand={hand}, position={args.position}, "
          f"spell={args.spell}, video conditions={target_country or 'recency'}")
    ok, fail = 0, 0
    for i, bid in enumerate(ids, 1):
        try:
            path = render_report(bid, hand=hand, out_dir=args.out,
                                 position=args.position, spell=args.spell, length_mode=args.length,
                                 target_country=target_country)
            print(f"  [{i}/{len(ids)}] {bid} -> {os.path.basename(path)}")
            ok += 1
        except Exception as e:
            print(f"  [{i}/{len(ids)}] {bid} FAILED: {type(e).__name__}: {str(e)[:140]}")
            fail += 1
    print(f"\nDone: {ok} succeeded, {fail} failed. Output in: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
