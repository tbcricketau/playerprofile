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


_GROUPS = ("right_pace", "left_pace", "off_spin", "leg_spin", "left_orthodox", "left_unorthodox")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="+", required=True, help="Batter IDs (space or comma separated)")
    ap.add_argument("--out", default="reports", help="Output folder (default: reports)")
    ap.add_argument("--mode", choices=("combined", "focused", "both"), default="combined",
                    help="combined = broad overview; focused = per-bowler-type exploit report")
    ap.add_argument("--group", default="right_pace",
                    help=f"bowler group for focused mode: {', '.join(_GROUPS)}")
    args = ap.parse_args()

    ids = _ids_from_args(args.ids)
    if not ids:
        sys.exit("No batter IDs given.")
    # (batter_id, group) jobs
    jobs = []
    for bid in ids:
        if args.mode in ("combined", "both"):
            jobs.append((bid, None))
        if args.mode in ("focused", "both"):
            jobs.append((bid, args.group))

    print(f"Generating {len(jobs)} batting report(s) — mode={args.mode}"
          + (f", group={args.group}" if args.mode != "combined" else ""))
    ok = fail = 0
    for i, (bid, group) in enumerate(jobs, 1):
        try:
            path = render_batting_report(bid, out_dir=args.out, group=group)
            print(f"  [{i}/{len(jobs)}] {bid}{' vs ' + group if group else ''} -> {os.path.basename(path)}")
            ok += 1
        except Exception as e:
            print(f"  [{i}/{len(jobs)}] {bid} FAILED: {type(e).__name__}: {str(e)[:100]}")
            fail += 1
    print(f"Done: {ok} succeeded, {fail} failed. Output in: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
