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

The link check runs on the staged copy **before** it is encrypted, and refuses the deploy on any
broken link (`--no-check` is the deliberate override, `--deep` also HEADs a sample of media URLs).
It has to sit there: once staticgate has rewritten each page into an encrypted shell there are no
links left to check, so `deploy_github`'s own gate passes anything it is given.
"""
import argparse
import os
import shutil
import stat
import sys


def _rmtree_force(path):
    """rmtree that clears the read-only bit on git object files (Windows) before retrying."""
    def _onerr(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if os.path.isdir(path):
        shutil.rmtree(path, onerror=_onerr)

import staticgate
from check_site import check as check_site
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
    ap.add_argument("--deep", action="store_true", help="also HEAD a sample of media urls")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the link check (deliberate override only)")
    args = ap.parse_args()

    pw = _password(args.password)
    if not pw:
        sys.exit("No password. Put it in .scouting_pw, set CRICKET_SCOUTING_PW, or pass --password.")

    if not args.no_build:
        build(os.path.join(HERE, "site"), args.sas_hours)

    site = os.path.join(HERE, "site")
    if not os.path.isdir(site):
        sys.exit("No site/ to deploy (run without --no-build first).")
    _rmtree_force(_STAGE)
    shutil.copytree(site, _STAGE, ignore=shutil.ignore_patterns(".git"))

    # The link check has to run HERE — on the staged copy, while it is still plaintext.
    # staticgate replaces every .html with an encrypted shell, so the check deploy_github runs
    # afterwards walks pages with no links left in them and passes whatever it is handed. The
    # gated coach site was therefore ungated against broken links from the day it was gated,
    # while CLAUDE.md claimed it was covered. Same failure shape as the packs: the build
    # succeeds, the bundle is broken, nothing complains.
    if not args.no_check:
        print(f"validating {_STAGE} before gating…")
        errors, warnings = check_site(_STAGE, deep=args.deep)
        for w in warnings[:10]:
            print(f"  WARN  {w}")
        for e in errors:
            print(f"  FAIL  {e}")
        if errors:
            sys.exit(f"\nREFUSING TO PUBLISH: {len(errors)} broken link(s)/asset(s). "
                     f"Nothing was deployed.")
        print("  validation clean")

    n = staticgate.encrypt_dir(_STAGE, pw, args.title)
    print(f"gated {n} pages with the shared password")
    # check=False is NOT a bypass here: the check ran above, on the same bytes, before they were
    # encrypted. Re-running it now would only re-confirm that an encrypted page has no links.
    deploy_github(_STAGE, args.repo, args.branch, check=False)
    print(f"Deployed the GATED scouting site to {args.repo}")


if __name__ == "__main__":
    main()
