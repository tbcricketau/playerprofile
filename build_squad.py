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


def resolve(names):
    """[full name] -> [{id, name, role, packs, bat_balls, bowl_balls, avg_pos}] (best match each)."""
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
        surname = full.split()[-1].lower()
        best = None
        for pid, p in by_id.items():
            if surname not in (p["surname"] or "").lower():
                continue
            bb = int(_f((batm.get(pid) or {}).get("balls")))
            wb = int(_f((bowlm.get(pid) or {}).get("balls")))
            if bb + wb == 0:
                continue
            if best is None or bb + wb > best[1]:
                ap = (batm.get(pid) or {}).get("avg_pos")
                ap = _f(ap, None) if ap not in (None, "None") else None
                best = ({"id": pid, "name": full, "role": _role(ap, wb, bb), "packs": None,
                         "bat_balls": bb, "bowl_balls": wb, "avg_pos": ap}, bb + wb)
        if best is None:
            out.append({"id": None, "name": full, "role": "Unknown", "packs": ["batting"],
                        "bat_balls": 0, "bowl_balls": 0, "avg_pos": None})
        else:
            rec = best[0]
            rec["packs"] = _packs(rec["role"])
            out.append(rec)
    return out


def _series_meta(slug):
    if os.path.exists(SERIES_JSON):
        cfg = json.load(open(SERIES_JSON, encoding="utf-8"))
        for s in cfg.get("series", []):
            if s.get("slug") == slug:
                return {"name": s.get("name", slug),
                        "opposition": s.get("subtitle", ""), "format": "Test"}
    return {"name": slug, "opposition": "", "format": "Test"}


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

    print(f"{'name':<22}{'id':>10}  {'role':<12}{'packs'}")
    for r in resolved:
        print(f"{r['name']:<22}{str(r['id']):>10}  {r['role']:<12}{'+'.join(r['packs'])}"
              f"   (bat={r['bat_balls']} bowl={r['bowl_balls']} pos="
              f"{None if r['avg_pos'] is None else round(r['avg_pos'],1)})")
    missing = [r["name"] for r in resolved if r["id"] is None]
    if missing:
        print(f"\n! no warehouse match: {', '.join(missing)}")

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

    meta = _series_meta(args.series)
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
    changed = []
    for r in resolved:
        if not r["id"]:
            continue
        existing = dict(players.get(r["id"], {}))
        kept = [k for k in existing if k not in ("name", "role", "packs")]
        existing.update({"name": r["name"], "role": r["role"], "packs": r["packs"]})
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


if __name__ == "__main__":
    main()
