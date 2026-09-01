"""
build_squad.py — resolve OUR squad names for a series into player ids + derived roles, and write the
player-site config. See INDIVIDUALIZATION_PLAN.md §3-4.

Two outputs, merged (never clobbering hand edits / stored preferences):
  squads.json   — per-series roster Tom supplies: slug -> {name, opposition, format, players:[id,...]}
  players.json  — persistent per-player registry: id -> {name, role, packs, prefs}

Role is DERIVED from the warehouse (career, all formats) via the bowl-to-bat ratio; Tom confirms
exceptions. `packs` follows from role: everyone bats; bowlers + all-rounders also bowl.

Usage:
    .\\venv\\Scripts\\python.exe build_squad.py --series bangladesh-home-2026 --names names.txt
    .\\venv\\Scripts\\python.exe build_squad.py --series bangladesh-home-2026 --dry-run   # print, don't write
(names.txt = one "First Last" per line. Series meta is read from series.json when present.)
"""
import argparse
import datetime
import json
import os
import shutil

from config import DATA_SCHEMA
from cricket_core.warehouse import set_conn_cursor, run_query

HERE = os.path.dirname(os.path.abspath(__file__))
SQUADS = os.path.join(HERE, "squads.json")
PLAYERS = os.path.join(HERE, "players.json")
SERIES_JSON = os.path.join(HERE, "series.json")


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _role(avg_pos, bowl_balls, bat_balls):
    """Batter / Bowler / All-rounder from career volume. A part-timer accrues many career overs but
    bowls little relative to batting, so the bowl-to-bat RATIO — not the raw count — is the signal."""
    ratio = bowl_balls / max(bat_balls, 1)
    top = avg_pos is not None and avg_pos <= 7
    if avg_pos is not None and avg_pos >= 8:
        return "Bowler"                                  # bats in the tail
    if bowl_balls >= 1000 and ratio >= 0.40 and top:
        return "All-rounder"                             # top-order bat + real bowling load
    if ratio >= 0.9:
        return "Bowler"
    return "Batter"


def _packs(role):
    return ["batting", "bowling"] if role in ("Bowler", "All-rounder") else ["batting"]


def _given(wh_name, surname):
    """Given name(s) out of the warehouse `name` field ("Marsh, Shaun" -> "shaun")."""
    n = (wh_name or "").strip()
    if "," in n:
        return n.split(",", 1)[1].strip().lower()
    return n[:-len(surname)].strip().lower() if surname and n.lower().endswith(surname.lower()) else n.lower()


def _first_name_score(want, got):
    """How well the squad list's first name matches the warehouse's. Higher is better, 0 = no signal.

    Shortenings are the norm on a team sheet — Mitch/Mitchell, Matt/Matthew — so a prefix counts,
    but only one way round and only from 3 characters, or 'Ben' would match 'Benjamin' AND every
    other B name equally."""
    want, got = (want or "").lower(), (got or "").split()[0] if got else ""
    if not want or not got:
        return 0
    if want == got:
        return 3
    if len(want) >= 3 and (got.startswith(want) or want.startswith(got)):
        return 2
    return 0


def resolve(names):
    """[full name] -> [{id, name, wh_name, role, packs, bat_balls, bowl_balls, avg_pos}].

    Matching is FIRST NAME then career volume. Surname alone silently picked the most famous
    holder of a common surname: a 2026-08-31 Zimbabwe ODI squad resolved Mitch Marsh to Shaun
    Marsh, Spencer Johnson to Mitchell Johnson and Joel Davies to Alex Davies, and nothing in the
    output showed it because only the INPUT name was printed back."""
    conn, cur = set_conn_cursor()
    surnames = sorted({n.split()[-1] for n in names})
    likes = " OR ".join(f"P.surname LIKE '%{s}%'" for s in surnames)
    players = run_query(
        f"SELECT P.player_id, P.name, P.surname FROM [{DATA_SCHEMA}].[Players] P WHERE {likes}",
        conn, cur)
    by_id = {r["player_id"]: r for r in players}
    idlist = ",".join(f"'{i}'" for i in by_id)
    bat = run_query(
        f"""SELECT D.striker_id pid, COUNT(*) balls,
                   AVG(TRY_CONVERT(float, D.striker_batting_position)) avg_pos
            FROM [{DATA_SCHEMA}].[Deliveries] D
            WHERE D.striker_id IN ({idlist}) AND D.legal_ball='1' GROUP BY D.striker_id""", conn, cur)
    bowl = run_query(
        f"""SELECT D.bowler_id pid, COUNT(*) balls
            FROM [{DATA_SCHEMA}].[Deliveries] D
            WHERE D.bowler_id IN ({idlist}) AND D.legal_ball='1' GROUP BY D.bowler_id""", conn, cur)
    conn.close()
    batm = {r["pid"]: r for r in bat}
    bowlm = {r["pid"]: r for r in bowl}

    out = []
    for full in names:
        parts = full.split()
        surname, want_first = parts[-1].lower(), (parts[0] if len(parts) > 1 else "")
        cands = []
        for pid, p in by_id.items():
            if surname not in (p["surname"] or "").lower():
                continue
            bb = int(_f((batm.get(pid) or {}).get("balls")))
            wb = int(_f((bowlm.get(pid) or {}).get("balls")))
            if bb + wb == 0:
                continue
            ap = (batm.get(pid) or {}).get("avg_pos")
            ap = _f(ap, None) if ap not in (None, "None") else None
            got = _given(p["name"], p["surname"])
            cands.append({"id": pid, "name": full, "wh_name": p["name"],
                          "role": _role(ap, wb, bb), "packs": None,
                          "bat_balls": bb, "bowl_balls": wb, "avg_pos": ap,
                          "score": _first_name_score(want_first, got), "_tot": bb + wb})

        if not cands:
            out.append({"id": None, "name": full, "wh_name": "", "role": "Unknown",
                        "packs": ["batting"], "bat_balls": 0, "bowl_balls": 0,
                        "avg_pos": None, "score": 0, "alts": []})
            continue

        # First name decides; career volume only breaks a tie WITHIN the best-matching tier.
        top = max(c["score"] for c in cands)
        tier = [c for c in cands if c["score"] == top]
        rec = max(tier, key=lambda c: c["_tot"])
        rec["packs"] = _packs(rec["role"])
        # Anything else we could plausibly have chosen, so a wrong pick is visible rather than
        # inferred from a career shape that happens to look right.
        rec["alts"] = [f'{c["wh_name"]} ({c["id"]}, bat={c["bat_balls"]} bowl={c["bowl_balls"]})'
                       for c in sorted(cands, key=lambda c: -c["_tot"])
                       if c["id"] != rec["id"] and (top == 0 or c["score"] == top)]
        out.append(rec)
    return out


def _series_meta(slug, fmt="Test"):
    """Series display meta. `format` is NOT derivable from series.json — nothing in there records
    it — so it is passed in and defaults to Test rather than being guessed from the slug."""
    if os.path.exists(SERIES_JSON):
        cfg = json.load(open(SERIES_JSON, encoding="utf-8"))
        for s in cfg.get("series", []):
            if s.get("slug") == slug:
                return {"name": s.get("name", slug),
                        "opposition": s.get("subtitle", ""), "format": fmt}
    return {"name": slug, "opposition": "", "format": fmt}


def _load(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", required=True, help="series slug (matches series.json)")
    ap.add_argument("--names", help="text file, one 'First Last' per line")
    ap.add_argument("--dry-run", action="store_true", help="print the resolution, write nothing")
    ap.add_argument("--team", help="whose squad this is (e.g. Australia, CA XI) — stored on the "
                    "squad, kept across a re-resolve")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a squad marked `archived` (deliberate override)")
    ap.add_argument("--format", default="Test", choices=("Test", "ODI", "T20I"),
                    help="which format this squad was picked for (default: Test)")
    args = ap.parse_args()

    if not args.names:
        ap.error("--names is required (a text file of one 'First Last' per line)")

    # Refuse BEFORE resolving — resolution is a warehouse round trip per name, and a run that was
    # never going to be allowed to write should not pay for it.
    prior = _load(SQUADS).get(args.series, {})
    if prior.get("archived") and not args.force:
        raise SystemExit(
            f"{args.series} was ARCHIVED {prior['archived']} — that series is over. Writing to it "
            f"would revive a finished squad under its own slug.\nUse a new --series slug for the "
            f"new squad, or pass --force to overwrite this one deliberately.")

    names = [ln.strip() for ln in open(args.names, encoding="utf-8") if ln.strip()]
    resolved = resolve(names)

    # Print the WAREHOUSE name, not the one we were given — the input name always looks right.
    print(f"{'name':<22}{'id':>10}  {'warehouse':<26}{'role':<12}{'packs'}")
    for r in resolved:
        print(f"{r['name']:<22}{str(r['id']):>10}  {(r.get('wh_name') or '-')[:25]:<26}"
              f"{r['role']:<12}{'+'.join(r['packs'])}"
              f"   (bat={r['bat_balls']} bowl={r['bowl_balls']} pos="
              f"{None if r['avg_pos'] is None else round(r['avg_pos'],1)})")
    missing = [r["name"] for r in resolved if r["id"] is None]
    if missing:
        print(f"\n! no warehouse match: {', '.join(missing)}")

    weak = [r for r in resolved if r["id"] and not r.get("score")]
    for r in weak:
        print(f"\n? {r['name']} matched on SURNAME ONLY -> {r['wh_name']} ({r['id']}) — "
              f"the first name did not match, so this is a career-volume guess. Check it.")
    for r in resolved:
        if r["id"] and r.get("alts"):
            print(f"\n? {r['name']} -> {r['wh_name']} ({r['id']}); also matched: "
                  f"{'; '.join(r['alts'][:4])}")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        return

    squads = _load(SQUADS)
    players = _load(PLAYERS)

    prior = squads.get(args.series, {})            # re-read after resolution; guarded up top

    # Both files are hand-maintained and gitignored-adjacent: snapshot before overwriting.
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for p in (SQUADS, PLAYERS):
        if os.path.exists(p):
            shutil.copy(p, f"{p}.bak-{stamp}")

    meta = _series_meta(args.series, args.format)
    # Carry the squad's own state across a re-resolve — `team` and `archived` are facts about the
    # squad that no name list can supply, and a wholesale replace silently dropped them.
    keep = {k: prior[k] for k in ("team", "archived") if k in prior}
    if args.team:
        keep["team"] = args.team
    squads[args.series] = {**meta, **keep, "players": [r["id"] for r in resolved if r["id"]]}

    # MERGE into the registry, never replace it. Only name/role/packs are derivable from a name
    # list; `bowl_types`, `bowl_groups`, `new_ball_footage`, `similar_bowler`, `release_detail` and
    # `prefs` are hand-set and were being dropped from every player this script resolved — which is
    # why CLAUDE.md said to add one player by hand rather than run this.
    changed, notes = [], []
    for r in resolved:
        if not r["id"]:
            continue
        existing = dict(players.get(r["id"], {}))
        kept = [k for k in existing if k not in ("name", "role", "packs")]

        # `packs` is derived from a career ratio, but `bowl_types` is HAND-SET and is what actually
        # builds the bowling page. Deriving alone dropped "bowling" from any part-timer whose recent
        # window is light — Renshaw, a Batter by ratio with bowl_types ["spin"] — which quietly cut
        # them from export_matchup_store's our_bowl while their bowling page kept building. Never
        # lose a pack the registry already asserts.
        packs = list(r["packs"])
        if existing.get("bowl_types") and "bowling" not in packs:
            packs.append("bowling")
            notes.append(f"{r['name']}: kept 'bowling' (bowl_types is set, career ratio says batter)")
        for p in existing.get("packs", []):
            if p not in packs:
                packs.append(p)
                notes.append(f"{r['name']}: kept '{p}' from the registry")

        if existing.get("role") and existing["role"] != r["role"]:
            notes.append(f"{r['name']}: role {existing['role']} -> {r['role']} (derived)")
        existing.update({"name": r["name"], "role": r["role"], "packs": packs})
        players[r["id"]] = existing
        if kept:
            changed.append(f"{r['name']} (kept {', '.join(sorted(kept))})")

    for path, data in ((SQUADS, squads), (PLAYERS, players)):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    print(f"\nwrote {os.path.basename(SQUADS)} ({len(squads[args.series]['players'])} players) "
          f"+ {os.path.basename(PLAYERS)} ({len(players)} total); "
          f"previous copies kept as *.bak-{stamp}")
    for c in changed:
        print(f"  registry preserved: {c}")
    for n in notes:
        print(f"  ! {n}")


if __name__ == "__main__":
    main()
