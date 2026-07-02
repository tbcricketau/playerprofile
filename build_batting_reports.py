"""
build_batting_reports.py — batch-generate one batting scouting PDF per batter.

Batter IDs come from --ids (space or comma separated).

Examples:
    py -3.12 build_batting_reports.py --ids 940135 2480058
    py -3.12 build_batting_reports.py --ids 940135,3080014 --out reports/batting
"""
import argparse
import os
import sys
import warnings

warnings.filterwarnings("ignore")

from batting_report import render_batting_report


def _ids_from_args(raw: list) -> list:
    out = []
    for chunk in raw or []:
        out.extend(p for p in chunk.replace(",", " ").split() if p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="+", required=True, help="Batter IDs (space or comma separated)")
    ap.add_argument("--out", default="reports", help="Output folder (default: reports)")
    args = ap.parse_args()

    ids = _ids_from_args(args.ids)
    if not ids:
        sys.exit("No batter IDs given.")

    print(f"Generating {len(ids)} batting report(s)")
    ok = fail = 0
    for i, bid in enumerate(ids, 1):
        try:
            path = render_batting_report(bid, out_dir=args.out)
            print(f"  [{i}/{len(ids)}] {bid} -> {os.path.basename(path)}")
            ok += 1
        except Exception as e:
            print(f"  [{i}/{len(ids)}] {bid} FAILED: {type(e).__name__}: {str(e)[:100]}")
            fail += 1
    print(f"Done: {ok} succeeded, {fail} failed. Output in: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
