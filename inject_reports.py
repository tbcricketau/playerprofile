"""inject_reports.py — bake the reports the PLAYER PACKS link into site/<series>/batters/.

`publish_site.py` bakes reports into the coach-site group folders named in series.json
(bowlers-vs-lhb, batters-to-pace, …). The packs link somewhere else: `_scouting_urls` in
build_player_site emits `scouting/<series>/batters/<base>.pmode.html` for every per-bowler-type
batter report ('_vs_right_pace', '_vs_off_spin', …), and no series.json group produces that folder.

It used to be filled by a script that lived outside the repo, so a plain `publish_site.py --out site`
silently removed it and the next assemble produced a bundle full of dead links — caught by the
publish gate on 2026-08-10, after the rebuild had already wiped the folder. Same class of gap as the
scratchpad assemblers: a pipeline step that isn't in the repo isn't part of the pipeline.

Run it after publish_site.py and before assemble_packs.py:
    .\\venv\\Scripts\\python.exe inject_reports.py --slug bangladesh-home-2026
"""
import argparse
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

from publish_site import _bake_report, DEFAULT_SAS_HOURS
from build_player_site import _scouting_urls

HERE = os.path.dirname(os.path.abspath(__file__))


def inject(slug, out="site", sas_hours=DEFAULT_SAS_HOURS):
    """Bake every batter report the packs link for `slug`. Returns (n_baked, missing)."""
    try:
        from publish_site import get_hawkeye_sas
        hk_sas = get_hawkeye_sas(ttl_hours=min(sas_hours, 167))
    except Exception as e:
        print(f"  (no hawkeye SAS: {type(e).__name__}) — baking without a video refresh")
        hk_sas = ""

    _bowl, bat, bat_groups = _scouting_urls(slug)
    bases = set()
    for url in list(bat.values()) + [u for g in bat_groups.values() for u in g.values()]:
        bases.add(re.sub(r"\.(pmode|player)?\.?html$", "", os.path.basename(url)))

    dest = os.path.join(HERE, out, slug, "batters")
    os.makedirs(dest, exist_ok=True)
    n, missing = 0, []
    for base in sorted(bases):
        if _bake_report(base, dest, hk_sas):
            n += 1
        else:
            missing.append(base)
    for m in missing:
        print(f"  ! no source in reports/ for {m} — the pack link will be dead")
    print(f"injected {n} batter report(s) -> {dest}"
          + (f" · {len(missing)} MISSING" if missing else ""))
    return n, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="bangladesh-home-2026")
    ap.add_argument("--out", default="site")
    ap.add_argument("--sas-hours", type=int, default=DEFAULT_SAS_HOURS)
    a = ap.parse_args()
    _n, missing = inject(a.slug, a.out, a.sas_hours)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
