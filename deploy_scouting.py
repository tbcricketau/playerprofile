"""Deploy the coach scouting site behind a shared-password gate (staticgate).

Builds the site (publish_site), then deploys an ENCRYPTED COPY — the plaintext `site/` is left
alone so the player-packs assembly (which players read) still uses it un-gated. The password is a
single shared value for all coaches/selectors.

    # one-time: put the password in a gitignored secret file (never committed)
    echo my-coach-password > .scouting_pw

    # deploy to the live coach site (gated):
    py -3.12 deploy_scouting.py --repo https://github.com/tbcricketau/scouting-reports.git
    # or a preview:
    py -3.12 deploy_scouting.py --repo https://github.com/tbcricketau/scouting-test.git

Reset the password: edit `.scouting_pw` (or set CRICKET_SCOUTING_PW) and re-run — every page
re-encrypts with the new password on the next deploy. `--no-build` reuses the existing `site/`.
"""
import argparse
import os
import shutil
import sys

import staticgate
from publish_site import HERE, DEFAULT_SAS_HOURS, build, deploy_github

_SECRET = os.path.join(HERE, ".scouting_pw")
_STAGE = os.path.join(HERE, "site_gated")


def _password(cli):
    if cli:
        return cli
    if os.environ.get("CRICKET_SCOUTING_PW"):
        return os.environ["CRICKET_SCOUTING_PW"]
    if os.path.exists(_SECRET):
        return open(_SECRET, encoding="utf-8").read().strip()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="GitHub repo URL to deploy the gated site to")
    ap.add_argument("--password", help="shared access password (else CRICKET_SCOUTING_PW / .scouting_pw)")
    ap.add_argument("--title", default="AUS Scouting", help="title shown on the password box")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--sas-hours", type=int, default=DEFAULT_SAS_HOURS)
    ap.add_argument("--no-build", action="store_true", help="reuse the existing site/ instead of rebuilding")
    args = ap.parse_args()

    pw = _password(args.password)
    if not pw:
        sys.exit("No password. Put it in .scouting_pw, set CRICKET_SCOUTING_PW, or pass --password.")

    if not args.no_build:
        build(os.path.join(HERE, "site"), args.sas_hours)

    site = os.path.join(HERE, "site")
    if not os.path.isdir(site):
        sys.exit("No site/ to deploy (run without --no-build first).")
    if os.path.isdir(_STAGE):
        shutil.rmtree(_STAGE, ignore_errors=True)
    shutil.copytree(site, _STAGE, ignore=shutil.ignore_patterns(".git"))
    n = staticgate.encrypt_dir(_STAGE, pw, args.title)
    print(f"gated {n} pages with the shared password")
    deploy_github(_STAGE, args.repo, args.branch)
    print(f"Deployed the GATED scouting site to {args.repo}")


if __name__ == "__main__":
    main()
