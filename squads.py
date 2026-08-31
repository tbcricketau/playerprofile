"""squads.py — the one reader for `squads.json`, and the one definition of what a squad IS.

Two files describe our players and they answer different questions:

    players.json   the PERSISTENT REGISTRY, keyed by player id, shared across every series.
                   What is true of the player: name, role, packs, prefs, bowl_types, bowl_groups.
    squads.json    the ROSTERS, keyed by slug. Who was picked, for which team, for which series,
                   and whether that series is over (`archived`).

**A consumer wants a roster, never the registry.** Iterating `players.json` builds for every player
who has ever been in any squad — which is how `export_matchup_store.py` came to simulate our whole
31-name registry against the opposition when the Test squad is 14, and why 14 CA XI players kept
being simulated for eleven days after their site was taken offline. The registry is a lookup table:
resolve ids through it, don't enumerate it.

    from squads import roster, live_slugs, resolve

    for slug in live_slugs():          # archived squads are skipped by default
        for pid, rec in resolve(roster(slug)):
            ...

`archived` is a date string, and it means the series is over: the roster stays in the file so it can
be read, restored and audited, but no builder prepares for it any more. Un-archiving is deleting one
line. See CLAUDE.md §Archiving a squad.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SQUADS = os.path.join(HERE, "squads.json")
PLAYERS = os.path.join(HERE, "players.json")


def load(path=None):
    """The whole rosters file, archived squads included."""
    return json.load(open(path or SQUADS, encoding="utf-8"))


def registry(path=None):
    """The persistent per-player registry. For LOOKUP — see the module docstring before you loop."""
    return json.load(open(path or PLAYERS, encoding="utf-8"))


def slugs(include_archived=False, path=None):
    sq = load(path)
    return [s for s, m in sq.items() if include_archived or not m.get("archived")]


def live_slugs(path=None):
    return slugs(include_archived=False, path=path)


def archived_slugs(path=None):
    sq = load(path)
    return [s for s, m in sq.items() if m.get("archived")]


def meta(slug, path=None):
    sq = load(path)
    if slug not in sq:
        raise KeyError(f"no squad {slug!r} in {os.path.basename(path or SQUADS)} — "
                       f"have {', '.join(sq) or '(none)'}")
    return sq[slug]


def roster(slug, path=None, allow_archived=False):
    """The player ids picked for one squad. Refuses an archived squad unless asked, because the
    whole point of archiving is that a routine build stops preparing for a series that is over."""
    m = meta(slug, path)
    if m.get("archived") and not allow_archived:
        raise SystemExit(
            f"{slug} was ARCHIVED {m['archived']} — the series is over and no builder prepares for "
            f"it. Pass --include-archived (or allow_archived=True) to work on it deliberately, or "
            f"remove the \"archived\" line from squads.json to bring it back.")
    return [str(p) for p in m.get("players", [])]


def resolve(ids, path=None):
    """[(id, registry record)] for the given ids — the registry used as a lookup, not a loop.
    An id with no registry entry still comes back, so a roster line can never silently vanish."""
    reg = registry(path)
    return [(pid, reg.get(pid, {"name": pid, "role": "Unknown", "packs": ["batting"]}))
            for pid in ids]


def all_live_ids(path=None):
    """Every player in every LIVE squad, de-duplicated, in roster order. The honest replacement for
    `list(players)` where a consumer genuinely wants 'everyone we are currently preparing'."""
    seen, out = set(), []
    for s in live_slugs(path):
        for pid in roster(s, path):
            if pid not in seen:
                seen.add(pid)
                out.append(pid)
    return out


def describe(path=None):
    """One line per squad, for a CLI to print."""
    out = []
    for s, m in load(path).items():
        a = m.get("archived")
        a = f"archived {a[8:10]}-{a[5:7]}-{a[:4]}" if a and len(a) == 10 else (a or "live")
        out.append(f"  {s:<26} {m.get('team', '?'):<10} {len(m.get('players', [])):>3} players  {a}")
    return "\n".join(out) or "  (no squads)"


if __name__ == "__main__":
    print(describe())
