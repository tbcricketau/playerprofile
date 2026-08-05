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

HERE = os.path.dirname(os.path.abspath(__file__))

BUNDLES = {
    "aus": {"assemble": "assemble_packs.py", "arg": "aus",
            "bundle": "player_pack_site",
            "repo": "https://github.com/tbcricketau/player-packs.git"},
    "caxi": {"assemble": "assemble_packs.py", "arg": "caxi",
             "bundle": "caxi_player_pack_site",
             "repo": "https://github.com/tbcricketau/caxi-player-packs.git"},
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
    a = ap.parse_args()
    cfg = BUNDLES[a.bundle]
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
    for e in errors:
        print(f"  FAIL  {e}")
    if errors:
        raise SystemExit(f"\nREFUSING TO PUBLISH: {len(errors)} problem(s). Nothing was pushed.")
    print("  clean")

    msg = a.message or f"publish {datetime.datetime.now():%Y-%m-%d %H:%M}"
    _run(["git", "add", "-A"], out)
    _run(["git", "-c", "user.name=tbcricketau", "-c", "user.email=tombody@gmail.com",
          "commit", "-q", "-m", msg], out)
    print(_run(["git", "push", "origin", "main"], out) or "  pushed")
    print(f"published {cfg['bundle']} -> {cfg['repo']}")


if __name__ == "__main__":
    main()
