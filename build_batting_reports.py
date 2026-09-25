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
    ap.add_argument("--out", default=None,
                    help="Output folder (default: reports, or reports/ateam at a-team level)")
    ap.add_argument("--mode", choices=("combined", "focused", "both"), default="combined",
                    help="combined = broad overview; focused = per-bowler-type exploit report")
    ap.add_argument("--fmt", default="Test", choices=("Test", "ODI", "T20I"),
                    help="which format's internationals to profile (default: Test)")
    ap.add_argument("--group", default="right_pace",
                    help=f"bowler group for focused mode: {', '.join(_GROUPS)}")
    ap.add_argument("--level", default="international", choices=("international", "a-team"),
                    help="which standard of cricket. 'a-team' scopes to International 1st "
                         "Class / Tour Matches / List A ODI and writes under reports/ateam/, "
                         "so an A-team report can never overwrite the senior one for the "
                         "same player (default: international)")
    ap.add_argument("--source", default="warehouse",
                    choices=("warehouse", "c21", "both"),
                    help="where the ball record comes from. 'both' adds Cricket-21 "
                         "Indian domestic cricket, which the warehouse does not hold at "
                         "all — see c21_source and cricket21/docs/INDIA_DOMESTIC.md")
    args = ap.parse_args()

    # LEVEL LIVES IN THE PATH, like format does. A player can hold both an A-team and a senior
    # record — Anshul Kamboj has 366 A-team first-class balls and 108 Test ones — and the filename
    # carries only the id, the hand and the group. Written to one folder, the second render would
    # silently overwrite the first and publish_site would bake whichever won. The same reasoning as
    # "format comes from the DIRECTORY, never from meta.format" in CLAUDE.md.
    out_dir = args.out or ("reports/ateam" if args.level == "a-team" else "reports")

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
            path = render_batting_report(bid, out_dir=out_dir, group=group, fmt=args.fmt,
                                         level=args.level, source=args.source)
            print(f"  [{i}/{len(jobs)}] {bid}{' vs ' + group if group else ''} -> {os.path.basename(path)}")
            ok += 1
        except Exception as e:
            print(f"  [{i}/{len(jobs)}] {bid} FAILED: {type(e).__name__}: {str(e)[:100]}")
            fail += 1
    print(f"Done: {ok} succeeded, {fail} failed. Output in: {os.path.abspath(out_dir)}")


if __name__ == "__main__":
    main()
    # Leave without waiting on Chrome's stderr readers — see report.finish_rendering.
    from report import finish_rendering
    finish_rendering()
