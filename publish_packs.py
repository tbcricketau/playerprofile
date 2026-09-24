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
    # Carried TWO squads from 2026-09-19; Zimbabwe came off on 09-21 when that series finished
    # (archived in squads.json, frozen into the coach portal at archive/zimbabwe-odi-away-2026,
    # and the last published pages tagged archived-zimbabwe-2026-09-21 on this repo). South Africa
    # stays NESTED under its slug even as the only squad — `build_player_site --nest` — because
    # those URLs are already published and flattening them would break every link a second time.
    # The single `opp`/`slug` pair this used to carry is gone ON PURPOSE: left in place on a
    # multi-squad bundle it resolved every page against ONE squad's opposition and hands, which is
    # the pooling error this gate exists to catch, committed by the gate itself.
    "aus": {"assemble": "assemble_packs.py", "arg": "aus",
            "bundle": "player_pack_site",
            "repo": "https://github.com/tbcricketau/player-packs.git",
            # `--target storage` uploads to the `packs` container under this prefix, for the
            # hosted playerpacks app, with vision rewritten to app paths (no SAS in any page).
            "prefix": "aus",
            "squads": ["south-africa-odi-away-2026"]},
    # Australia A in India, Sep-Oct 2026 — the first bundle carrying TWO squads, a four-day and a
    # one-day, on one landing page. `squads` replaces the single opp/slug pair: the hand audit is
    # per squad (it resolves our batters' hands from that squad's matchup store) and each squad's
    # packs sit in their own subfolder, so it runs once per subfolder rather than once per bundle.
    "ausa": {"assemble": "assemble_packs.py", "arg": "ausa",
             "bundle": "ausa_player_pack_site",
             "repo": "https://github.com/tbcricketau/australia-a-packs.git",
             "squads": ["india-a-4day-2026", "india-a-od-2026"]},
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


def _squad_fmt(slug):
    """The format the squad was picked for, so the audit can reject a red-ball clip in a
    white-ball pack. None (no format check) when the slug is unknown."""
    try:
        import json
        with open(os.path.join(HERE, "squads.json"), encoding="utf-8") as fh:
            return (json.load(fh).get(slug) or {}).get("format")
    except Exception:
        return None


def _opp_key(slug):
    """The opposition data key for a squad — which opponent_about/h2h files the audit reads.
    Falls back to the slug's first token, which is what every series before Australia A used."""
    try:
        from squads import opp_key
        return opp_key(slug)
    except Exception:
        return str(slug).split("-")[0] or "bangladesh"


def _run(args, cwd):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode and "nothing to commit" not in (r.stdout + r.stderr):
        raise SystemExit(f"git failed: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def plan_scope_check(out, slug):
    """Does every bowling pack link batter reports scoped to its OWN bowler family?

    The reel rule has always been enforced on VISION. The PLANS were never checked at all, and a
    pack linking the combined batter report is the same pooling defect one layer up: Adam Zampa's
    South Africa leg-spin pack linked reports carrying 14 mentions of pace, 8 of seam and ZERO of
    leg spin. It passed two clean publishes, because `check_site` only asks whether a link
    resolves and `audit_pack_hands` only looks at reels. Tom found it by reading the pack.

    Works off the bundle alone — no build logic duplicated. Returns (stale, missing, checked):
      stale   links taking the COMBINED report although a same-family focused one is right there
              (a stale bake, or a bowler the store failed to type),
      missing packs whose whole family has no focused report in the bundle (the renders were
              never run — real, but it must be a decision rather than a silent default).
    """
    import glob
    import re
    focused = {}                                    # batter stem -> {group, …}
    for p in glob.glob(os.path.join(out, "scouting", slug, "batters", "*_vs_*.pmode.html")):
        m = re.match(r"(.+?)_vs_([a-z_]+)\.pmode\.html$", os.path.basename(p))
        if m:
            focused.setdefault(m.group(1), set()).add(m.group(2))

    stale, missing, checked = 0, [], 0
    for page in sorted(glob.glob(os.path.join(out, "players", slug, "*-bowling-*.html"))):
        html = open(page, encoding="utf-8", errors="ignore").read()
        links = set(re.findall(r"batters/([a-z0-9_]+)\.pmode\.html", html))
        if not links:
            continue
        checked += 1
        # The pack's OWN group, read from the scoped links it already carries. Deliberately not
        # the macro family off the filename: a leg-spin pack linking Masakadza's combined report
        # is CORRECT when the only focused reports for him are off_spin and the pace ones, and a
        # family-level test called all ten of those stale on a bundle that was fine.
        groups = {s.split("_vs_", 1)[1] for s in links if "_vs_" in s}
        if not groups:
            missing.append(os.path.basename(page))
            continue
        stale += sum(1 for s in links
                     if "_vs_" not in s and (focused.get(s, set()) & groups))
    return stale, missing, checked


def publish_to_storage(out, prefix, overrides):
    """Upload the gated bundle to the `packs` container for the hosted app, with every vision link
    rewritten to the app's /vision/ route.

    The gates ran on the bundle as built — signed links and all, since `check_site --deep` HEADs a
    sample of them. The rewrite happens on a COPY in %TEMP% (an intermediate another process reads
    must not sit inside the repo — root CLAUDE.md, the DLP rule), and the copy is refused if any
    signed link survives it. The GitHub Pages bundle is untouched: it keeps its baked links until
    that site is retired after the South Africa series."""
    import re
    import shutil
    import tempfile
    from cricket_core.video import rewrite_vision_links
    tmp = tempfile.mkdtemp(prefix="packs_storage_")
    dst = os.path.join(tmp, prefix)
    shutil.copytree(out, dst, ignore=shutil.ignore_patterns(".git", ".github", "__pycache__"))
    n_files = n_links = 0
    for root, _d, files in os.walk(dst):
        for f in files:
            if not f.endswith((".html", ".json", ".js")):
                continue
            p = os.path.join(root, f)
            text = open(p, encoding="utf-8", errors="replace").read()
            new = rewrite_vision_links(text)
            if new != text:
                n_files += 1
                n_links += len(re.findall(r"/vision/fairplay/", new)) - len(re.findall(r"/vision/fairplay/", text))
                open(p, "w", encoding="utf-8").write(new)
    left = [os.path.relpath(os.path.join(r, f), dst) for r, _d, fs in os.walk(dst) for f in fs
            if f.endswith((".html", ".json", ".js"))
            and "sig=" in open(os.path.join(r, f), encoding="utf-8", errors="replace").read()]
    if left:
        raise SystemExit(f"\nREFUSING TO UPLOAD: {len(left)} file(s) still carry a signed link after "
                         f"the rewrite, e.g. {left[0]}. Nothing was uploaded.")
    print(f"vision -> app paths: {n_links:,} links rewritten across {n_files:,} files, no signed "
          f"link remains")
    if overrides:
        print("!! OVERRIDES ACTIVE: " + ", ".join("--" + o.replace("_", "-") for o in overrides))
    up = os.path.join(HERE, "..", "playerpacks", "upload_packs.py")
    r = subprocess.run([sys.executable, up, "--bundle", dst, "--prefix", prefix, "--apply"],
                       capture_output=True, text=True)
    print("\n".join("  " + ln for ln in r.stdout.strip().splitlines()[-4:]))
    if r.returncode:
        raise SystemExit(f"upload failed:\n{r.stderr[-2000:]}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"published {os.path.basename(out)} -> packs/{prefix} (served by the playerpacks app)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", choices=sorted(BUNDLES))
    ap.add_argument("-m", "--message", default="", help="commit message")
    ap.add_argument("--deep", action="store_true", help="also HEAD a sample of media urls")
    ap.add_argument("--no-assemble", action="store_true", help="validate/push what's already there")
    ap.add_argument("--no-hand-audit", action="store_true",
                    help="skip the warehouse hand audit (deliberate override only)")
    ap.add_argument("--allow-combined-plans", action="store_true",
                    help="publish bowling packs that link the COMBINED batter report because no "
                         "type-scoped render exists for their family (deliberate override — the "
                         "plans are then pooled across every bowling type)")
    ap.add_argument("--revive", action="store_true",
                    help="publish a bundle that has been archived (see the note it prints)")
    ap.add_argument("--no-roster-check", action="store_true",
                    help="skip the offline check that the pin, store, opponent_about, h2h and "
                         "series.json name the same opposition (deliberate override only)")
    ap.add_argument("--allow-duplicates", action="store_true",
                    help="publish although the bundle serves a report that exists under two "
                         "filenames and this is the OLDER one (deliberate override only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="run every gate and stop before git — nothing is committed or pushed")
    ap.add_argument("--target", choices=("github", "storage"), default="github",
                    help="github = push the bundle to its GitHub Pages repo (the default, signed "
                         "vision links baked in). storage = upload it to our `packs` container for "
                         "the hosted playerpacks app, with every vision link rewritten to the app's "
                         "/vision/ route so nothing in a page expires. Same gates either way.")
    a = ap.parse_args()
    cfg = BUNDLES[a.bundle]
    if cfg.get("archived") and not a.revive:
        raise SystemExit(f"{a.bundle}: {cfg['archived']}")
    if a.revive and cfg.get("archived"):
        print(f"!! --revive: {cfg['archived']}")
    out = os.path.join(HERE, cfg["bundle"])
    squads = cfg.get("squads") or [cfg.get("slug", "")]

    # Every override that weakens a gate is named up front and again in the commit, so a push
    # that skipped a check can never be mistaken for one that passed it.
    overrides = [f for f in ("no_assemble", "no_hand_audit", "allow_combined_plans",
                             "no_roster_check", "allow_duplicates", "revive") if getattr(a, f)]
    if overrides:
        print("!! OVERRIDES ACTIVE: " + ", ".join("--" + o.replace("_", "-") for o in overrides))

    # ROSTER — the five files that describe the opposition must agree before anything is built
    # from them. Offline and instant. A bowler swap that misses series.json, or a pinned player
    # with no opponent_about entry, is a set difference on disk, not a judgement call.
    if not a.no_roster_check:
        from squads import roster_check
        print("roster check…")
        for slug in squads:
            probs = roster_check(slug)
            for p in probs:
                print(f"  ! {slug}: {p}")
            if probs:
                raise SystemExit(
                    f"\nREFUSING TO PUBLISH: the opposition roster for {slug} is inconsistent "
                    f"across its data files ({len(probs)} problem(s) above). Fix the file(s) "
                    f"named and rebuild what reads them, or pass --no-roster-check (deliberate "
                    f"override only). Nothing was pushed.")
            print(f"  {slug}: pin, store, opponent_about, h2h and series.json agree")

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

    # DUPLICATE REPORTS — a link that resolves can still be the wrong file. The same report under
    # two filenames (a player rendered under two spellings) is served by whichever the maps kept;
    # they now keep the newest and record the loser. Refuse if the bundle carries a loser.
    from publish_site import sidecar_collisions
    served = {os.path.basename(f).split(".")[0] for _r, _d, fs in os.walk(out) for f in fs}
    stale_served = [(k, keep, drop) for k, keep, drop in sidecar_collisions() if drop in served]
    if stale_served:
        for k, keep, drop in stale_served[:10]:
            print(f"  STALE  {drop} is served but {keep} is the newer render of the same report")
        if not a.allow_duplicates:
            raise SystemExit(
                f"\nREFUSING TO PUBLISH: {len(stale_served)} report(s) in the bundle are the OLDER "
                f"of two renders under different filenames. Delete the stale render from reports/ "
                f"(or rename to match), re-inject and rebuild — or pass --allow-duplicates "
                f"(deliberate override only). Nothing was pushed.")

    # Hand audit — check_site can't do this one: it needs the warehouse to resolve who each clip is
    # bowled to, and that gate is deliberately offline-only. Kept here so it still blocks the push.
    if not a.no_hand_audit:
        print(f"hand audit {cfg['bundle']}…")
        # One entry per squad in the bundle. A bundle used to be one squad, so opp/slug sat on the
        # bundle; a two-squad bundle audited that way would resolve every page against ONE squad's
        # hands and format, which is the pooling error this gate exists to catch, committed by the
        # gate itself. Each squad's packs live in their own subfolder when the bundle is multi-squad.
        jobs = ([(s, os.path.join(out, "players", s)) for s in cfg["squads"]]
                if cfg.get("squads") else [(cfg.get("slug", ""), out)])
        totals = dict(n=0, pages=0)
        for slug, site in jobs:
            if not os.path.isdir(site):
                raise SystemExit(
                    f"\nREFUSING TO PUBLISH: {slug} has no pack folder at "
                    f"{os.path.relpath(site, HERE)} — the bundle does not contain the squad it "
                    f"claims to. Rebuild the player site for every live squad and re-assemble.")
            try:
                r = run_audit(site, opp=_opp_key(slug), slug=slug, fmt=_squad_fmt(slug))
            except Exception as e:
                # A dropped VPN must not become a silent pass — this is the check that catches a
                # pack showing the wrong batter's footage, which shipped unnoticed for weeks.
                raise SystemExit(
                    f"\nREFUSING TO PUBLISH: the hand audit could not run for {slug} "
                    f"({type(e).__name__}: {str(e)[:120]}). It needs the warehouse — reconnect, or "
                    f"pass --no-hand-audit to publish without it (deliberate override only). "
                    f"Nothing was pushed.")
            if r["mixed"] or r["wrong"] or r["pooled"] or r["offfmt"] or r["owner"] or r["type"]:
                raise SystemExit(
                    f"\nREFUSING TO PUBLISH: {slug} has {r['mixed']} mixed-hand, {r['wrong']} "
                    f"wrong-hand, {r['pooled']} unscoped, {r['offfmt']} off-format, {r['owner']} "
                    f"wrong-player, {r['type']} wrong-bowler-type reel(s) across {r['pages']} pack "
                    f"pages. A pack is showing footage of the wrong player, hand, bowler type or "
                    f"side of red/white ball. Nothing was pushed.")
            if r["unknown"]:
                raise SystemExit(
                    f"\nREFUSING TO PUBLISH: {slug} has {len(r['unknown'])} play button(s) of a kind "
                    f"the audit does not recognise, so they were NOT checked: "
                    f"{', '.join(r['unknown'][:4])}. Add the kind to audit_pack_hands._classify "
                    f"with its scoping rule. Nothing was pushed.")
            # COVERAGE. "Clean" is only a result on the reels the audit could see. A page whose
            # name resolved to no hand, a reel whose clips resolved to no delivery, an empty hands
            # dict or an unknown format each mean part of the bundle went unchecked — and every one
            # of those has previously printed as clean.
            if r["hands_empty"] or r["blind"] or r["unres"] or not r["fmt_checked"]:
                why = []
                if r["hands_empty"]:
                    why.append("no batter hands at all (matchup store missing or mis-keyed)")
                if r["blind"]:
                    why.append(f"{len(r['blind'])} page(s) whose name resolves to no player: "
                               f"{', '.join(r['blind'][:4])}")
                if r["unres"]:
                    why.append(f"{r['unres']} reel(s) whose clips resolve to no delivery")
                if not r["fmt_checked"]:
                    why.append(f"format unknown for {slug} in squads.json, so no off-format check")
                raise SystemExit(
                    f"\nREFUSING TO PUBLISH: the hand audit could not check all of {slug} — "
                    + "; ".join(why) + ". An unchecked reel is what this gate exists to prevent. "
                    f"Nothing was pushed.")
            print(f"  {slug}: clean — {r['n'] - r['unchecked']} reels across {r['pages']} pack pages, "
                  f"every page's player resolved, format {_squad_fmt(slug)} checked"
                  + (f", {r['unchecked']} manual/similar reel(s) not checkable" if r["unchecked"] else ""))
            totals["n"] += r["n"] - r["unchecked"]
            totals["pages"] += r["pages"]
        print(f"  clean — {totals['n']} reels verified across {totals['pages']} pack pages")

    # PLAN SCOPING — the reels were guarded, the plans were not. Offline, so unlike the hand audit
    # it costs nothing and cannot be skipped by a dropped VPN.
    print(f"plan scope {cfg['bundle']}…")
    for slug in (cfg.get("squads") or [cfg.get("slug", "")]):
        stale, missing, checked = plan_scope_check(out, slug)
        if stale:
            raise SystemExit(
                f"\nREFUSING TO PUBLISH: {slug} has {stale} batter link(s) taking the COMBINED "
                f"report while a focused one for that bowler's own family sits in the bundle. "
                f"The bake is stale, or the bowler was never typed — re-inject and rebuild the "
                f"player site. Nothing was pushed.")
        if missing and not a.allow_combined_plans:
            raise SystemExit(
                f"\nREFUSING TO PUBLISH: {slug} has {len(missing)} bowling pack(s) with NO "
                f"type-scoped batter report in the bundle — they serve plans pooled across every "
                f"bowling type, which is what a pack exists to avoid. First: "
                f"{', '.join(missing[:3])}.\nRender them with `build_batting_reports.py --mode "
                f"focused --group <g>` and re-inject, or pass --allow-combined-plans to publish "
                f"anyway (deliberate override). Nothing was pushed.")
        note = f" ({len(missing)} pack(s) on combined plans, allowed)" if missing else ""
        print(f"  {slug}: clean — {checked} bowling packs type-scoped{note}")

    if a.dry_run:
        print("dry run — every gate passed; nothing committed or pushed")
        return
    if a.target == "storage":
        return publish_to_storage(out, cfg.get("prefix", a.bundle), overrides)
    msg = a.message or f"publish {datetime.datetime.now():%Y-%m-%d %H:%M}"
    if overrides:
        msg += " [overrides: " + ", ".join("--" + o.replace("_", "-") for o in overrides) + "]"
        print("!! OVERRIDES ACTIVE: " + ", ".join("--" + o.replace("_", "-") for o in overrides))
    _run(["git", "add", "-A"], out)
    _run(["git", "-c", "user.name=tbcricketau", "-c", "user.email=tombody@gmail.com",
          "commit", "-q", "-m", msg], out)
    print(_run(["git", "push", "origin", "main"], out) or "  pushed")
    print(f"published {cfg['bundle']} -> {cfg['repo']}")


if __name__ == "__main__":
    main()
