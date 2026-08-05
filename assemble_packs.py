"""assemble_packs.py — build the deployable player-pack bundle: players/ (the packs) + scouting/
carrying ONLY the player-mode report pages those packs link. No coach index, matchups or full
reports; the landing page redirects into the roster.

Both bundles are assembled the same way — the AUS Test packs and the (temporary) CA XI packs differ
only in which build dir they come from and where they land.

    .\\venv\\Scripts\\python.exe assemble_packs.py aus
    .\\venv\\Scripts\\python.exe assemble_packs.py caxi

Prefer `publish_packs.py`, which runs this, validates the result and only then pushes.
"""
import argparse
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")          # coach scouting site — source of the baked reports

BUNDLES = {
    "aus": {"player": "player_site", "out": "player_pack_site", "title": "Player packs"},
    "caxi": {"player": "caxi_player_site", "out": "caxi_player_pack_site",
             "title": "CA XI player packs"},
}


def assemble(which):
    cfg = BUNDLES[which]
    player = os.path.join(HERE, cfg["player"])
    out = os.path.join(HERE, cfg["out"])
    for d in (SITE, player):
        if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "index.html")):
            raise SystemExit(f"missing built bundle: {d}")

    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):                    # keep .git (the deploy remote), clear the rest
        if f == ".git":
            continue
        p = os.path.join(out, f)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)

    shutil.copytree(player, os.path.join(out, "players"), ignore=shutil.ignore_patterns(".git"))

    def _pack_html():
        for root, _dd, files in os.walk(player):
            for f in files:
                if f.endswith(".html"):
                    yield open(os.path.join(root, f), encoding="utf-8").read()

    ref_slugs, wanted = set(), set()
    for text in _pack_html():
        ref_slugs.update(re.findall(r'\.\./scouting/([^/"]+)/', text))
        wanted.update(re.findall(r'\.\./scouting/([^"#]+\.html)', text))
    # a report's fallback href points at its own standalone player page, so the pair travels together
    for rel in list(wanted):
        for a, b in ((".pmode.html", ".player.html"), (".player.html", ".pmode.html")):
            if rel.endswith(a):
                wanted.add(rel[: -len(a)] + b)
    print(f"series linked by packs: {sorted(ref_slugs)}")

    # Only what the packs link: site/ keeps every report ever baked, and copying the lot dragged
    # stale pages (~22 MB) into the bundle — leftovers from earlier link configurations.
    n_reports = 0
    for rel in sorted(wanted):
        src = os.path.join(SITE, rel.replace("/", os.sep))
        if not os.path.exists(src):
            continue                              # check_site.py reports these as dead links
        dest = os.path.join(out, "scouting", os.path.dirname(rel.replace("/", os.sep)))
        os.makedirs(dest, exist_ok=True)
        shutil.copy(src, os.path.join(dest, os.path.basename(src)))
        n_reports += 1

    for slug in ref_slugs:                        # images sit beside the reports
        for root, _dd, files in os.walk(os.path.join(SITE, slug)):
            imgs = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg", ".svg"))]
            if not imgs:
                continue
            dest = os.path.join(out, "scouting", os.path.relpath(root, SITE))
            os.makedirs(dest, exist_ok=True)
            for f in imgs:
                shutil.copy(os.path.join(root, f), os.path.join(dest, f))

    # The standalone overview pages are deliberately NOT copied: the overview renders inline in the
    # pack, so nothing links them, and their "← Series" breadcrumb points at a coach-site index that
    # doesn't exist here — an orphan carrying a dead link. They stay on the gated coach site.

    open(os.path.join(out, ".nojekyll"), "w").close()
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(
        '<!doctype html><meta charset="utf-8">'
        '<meta http-equiv="refresh" content="0; url=players/index.html">'
        f'<title>{cfg["title"]}</title>'
        f'<a href="players/index.html">{cfg["title"]} &rarr;</a>')

    def _n(d):
        return sum(len(f) for _r, _dd, f in os.walk(d))
    print(f"assembled {out}: players {_n(os.path.join(out, 'players'))} files, "
          f"scouting {_n(os.path.join(out, 'scouting'))} files ({n_reports} report pages)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", choices=sorted(BUNDLES))
    assemble(ap.parse_args().bundle)


if __name__ == "__main__":
    main()
