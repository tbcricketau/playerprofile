"""publish_packs.py — the ONLY way a player-pack bundle should reach the live site.

Assembles the bundle, validates it with check_site.py, and pushes only if it is clean. Broken links
have twice reached the live packs without the build ever failing — the build succeeded and produced
a bundle with dead links in it, so a gate at the build was never going to catch them. This gate sits
on the push, against the assembled bundle, which is what actually gets served.

    .\\venv\\Scripts\\python.exe publish_packs.py aus
    .\\venv\\Scripts\\python.exe publish_packs.py caxi --deep
    .\\venv\\Scripts\\python.exe publish_packs.py aus --no-assemble   # bundle already assembled

Exits non-zero without pushing if validation fails.
"""
import argparse
import datetime
import os
import subprocess
import sys

from check_site import check as check_site
from audit_pack_hands import run_audit

HERE = os.path.dirname(os.path.abspath(__file__))

BUNDLES = {
    # REVIVED 2026-09-01 (Tom) and repointed at the Zimbabwe away ODI series. The repo previously
    # served the Bangladesh home Tests, archived 2026-08-31 and still tagged archived-2026-08-31 —
    # that state is recoverable from the tag, though its baked-in SAS expired 2026-08-27, so a
    # revival of THAT series means rebuilding from source rather than checking the tag out.
    # The Bangladesh coach-side copy is unaffected: it stays frozen and gated in the scouting
    # portal at archive/bangladesh-home-2026, SAS-re-stamped on every refresh.
    # ⚠ Publishing here force-pushes over the archived Bangladesh state on `main`.
    "aus": {"assemble": "assemble_packs.py", "arg": "aus",
            "bundle": "player_pack_site",
            "repo": "https://github.com/tbcricketau/player-packs.git",
            "opp": "zimbabwe", "slug": "zimbabwe-odi-away-2026"},
    "caxi": {"assemble": "assemble_packs.py", "arg": "caxi",
             "bundle": "caxi_player_pack_site",
             "repo": "https://github.com/tbcricketau/caxi-player-packs.git",
             "archived": (
                 "CA XI packs were ARCHIVED 2026-08-10 (Tom) — the series is over and the site is "
                 "offline. GitHub Pages is disabled on tbcricketau/caxi-player-packs; the repo and "
                 "its history are intact and the last published state is tagged archived-2026-08-10.\n"
                 "To bring it back: re-enable Pages on the repo (branch main, root), rebuild, then "
                 "publish with --revive. NOTE the packs predate the 2026-08-10 fixes — the bowler "
                 "reels are not scoped to the batter's hand and the batter reels not to the exact "
                 "bowler type, so rebuild from source rather than re-pushing the tag.")},
}


def _run(args, cwd):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode and "nothing to commit" not in (r.stdout + r.stderr):
        raise SystemExit(f"git failed: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", choices=sorted(BUNDLES))
    ap.add_argument("-m", "--message", default="", help="commit message")
    ap.add_argument("--deep", action="store_true", help="also HEAD a sample of media urls")
    ap.add_argument("--no-assemble", action="store_true", help="validate/push what's already there")
    ap.add_argument("--no-hand-audit", action="store_true",
                    help="skip the warehouse hand audit (deliberate override only)")
    ap.add_argument("--revive", action="store_true",
                    help="publish a bundle that has been archived (see the note it prints)")
    a = ap.parse_args()
    cfg = BUNDLES[a.bundle]
    if cfg.get("archived") and not a.revive:
        raise SystemExit(f"{a.bundle}: {cfg['archived']}")
    out = os.path.join(HERE, cfg["bundle"])

    if not a.no_assemble:
        print(f"assembling {cfg['bundle']}…")
        r = subprocess.run([sys.executable, os.path.join(HERE, cfg["assemble"]), cfg["arg"]],
                           capture_output=True, text=True)
        print("  " + (r.stdout.strip().splitlines() or ["(no output)"])[-1])
        if r.returncode:
            raise SystemExit(f"assemble failed:\n{r.stderr}")

    print(f"validating {cfg['bundle']}…")
    errors, warnings = check_site(out, deep=a.deep)
    for w in warnings[:10]:
        print(f"  WARN  {w}")
    for e in errors[:40]:
        print(f"  FAIL  {e}")
    if len(errors) > 40:
        print(f"  … and {len(errors) - 40} more")
    if errors:
        # Name the usual cause instead of leaving 121 identical dead links to be diagnosed by
        # hand. The scheduled "Scouting Reports Refresh" task runs publish_site, which clears
        # site/ and re-bakes only what series.json lists — and NO series.json group produces
        # <slug>/batters/, so inject_reports' output is wiped every few days. That is documented
        # in CLAUDE.md and still cost a confused investigation on 2026-09-02.
        bat = [e for e in errors if "/batters/" in str(e).replace("\\", "/")]
        if bat:
            slugs = sorted({str(e).replace("\\", "/").split("/scouting/")[1].split("/")[0]
                            for e in bat if "/scouting/" in str(e).replace("\\", "/")})
            print(f"\n  {len(bat)} of these are under scouting/<slug>/batters/, which no "
                  f"series.json group produces.\n"
                  f"  That folder is filled by inject_reports.py and WIPED whenever publish_site "
                  f"runs — including\n  the scheduled refresh. Re-run it, then publish again:\n"
                  + "".join(f"      .\\venv\\Scripts\\python.exe inject_reports.py --slug {s}\n"
                            for s in slugs or ["<slug>"]))
        raise SystemExit(f"\nREFUSING TO PUBLISH: {len(errors)} problem(s). Nothing was pushed.")
    print("  clean")

    # Hand audit — check_site can't do this one: it needs the warehouse to resolve who each clip is
    # bowled to, and that gate is deliberately offline-only. Kept here so it still blocks the push.
    if not a.no_hand_audit:
        print(f"hand audit {cfg['bundle']}…")
        try:
            mixed, wrong, pooled, _u, n, pages = run_audit(out, opp=cfg.get("opp", "bangladesh"),
                                                           slug=cfg.get("slug", ""), quiet=True)
        except Exception as e:
            # A dropped VPN must not become a silent pass — this is the check that catches a pack
            # showing the wrong batter's footage, which shipped unnoticed for weeks.
            raise SystemExit(
                f"\nREFUSING TO PUBLISH: the hand audit could not run ({type(e).__name__}: "
                f"{str(e)[:120]}). It needs the warehouse — reconnect, or pass --no-hand-audit to "
                f"publish without it (deliberate override only). Nothing was pushed.")
        if mixed or wrong or pooled:
            raise SystemExit(
                f"\nREFUSING TO PUBLISH: {mixed} mixed-hand, {wrong} wrong-hand, {pooled} unscoped "
                f"reel(s) across {pages} batting packs. A pack is showing footage of the wrong "
                f"batter's hand. Nothing was pushed.")
        print(f"  clean — {n} reels across {pages} batting packs, all one hand")

    msg = a.message or f"publish {datetime.datetime.now():%Y-%m-%d %H:%M}"
    _run(["git", "add", "-A"], out)
    _run(["git", "-c", "user.name=tbcricketau", "-c", "user.email=tombody@gmail.com",
          "commit", "-q", "-m", msg], out)
    print(_run(["git", "push", "origin", "main"], out) or "  pushed")
    print(f"published {cfg['bundle']} -> {cfg['repo']}")


if __name__ == "__main__":
    main()
