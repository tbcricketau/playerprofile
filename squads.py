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


def opp_key(slug, path=None):
    """The token that names this series' opposition DATA FILES — matchup_store_{key}.json,
    h2h_{key}.json, overview_{group}_{key}.json, opponent_about_{key}.json, and the rest.

    It defaults to the slug's first token, which is what every consumer used to compute inline, so
    every existing series resolves exactly as before. It is overridable because that default breaks
    the moment two LIVE squads face the same opponent in different formats: `india-a-4day-2026` and
    `india-a-od-2026` both reduce to "india", and the four-day and one-day packs would then read
    and overwrite each other's store, h2h and overviews — silently, since each file is valid, just
    for the wrong format.

    Set `opp_key` on the squad in squads.json to separate them (e.g. "india_a_fc" / "india_a_la").
    This is the DATA key, not the warehouse team name: the team is still "India A" in both.
    """
    try:
        m = meta(slug, path)
    except KeyError:
        m = {}
    return str(m.get("opp_key") or str(slug).split("-")[0])


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


def _opp_data_paths(slug, path=None):
    """Every file that carries this series' OPPOSITION roster, by name."""
    key = opp_key(slug, path)
    try:
        from cricket_core.config import project_path
        mm = os.path.join(project_path("matchupmodel"), "data")
    except Exception:
        mm = os.path.join(HERE, "..", "matchupmodel", "data")
    return {
        "pin": os.path.join(mm, f"opp_squad_{key}.json"),
        "store": os.path.join(mm, f"matchup_store_{key}.json"),
        "about": os.path.join(HERE, "data", f"opponent_about_{key}.json"),
        "h2h": os.path.join(HERE, "data", f"h2h_{key}.json"),
        "series": os.path.join(HERE, "series.json"),
    }


def roster_check(slug, path=None):
    """Problems, as strings, where the five files that describe one series' opposition disagree.
    Empty means they agree. Pure file reads — no warehouse, milliseconds.

    A bowler swap has to touch the pin, the store, opponent_about, h2h AND series.json, and nothing
    checked that it had: swapping Maphaka for Lizaad Williams on 23-09 missed series.json, so the
    packs kept Maphaka's card with a link to a report that had just been deleted. Two India A one-day
    bowlers are pinned with no opponent_about entry and ship as "Not enough data" cards on every
    batting pack. Both are set differences between files on disk. So this is the gate.

    The rules, and why each direction is or is not an error:
      store ⊆ pin        the store is a model artefact; a pinned player under the sim floor is
                         absent from it BY DESIGN (footage-only card). A store player NOT in the
                         pin is a stale export.
      about == pin       an unpinned about entry is stale; a pinned player with no about entry is
                         an empty card.
      series == pin      series.json is the report roster; the packs union it into the opposition
                         roster, so a name left here survives every other swap.
      h2h ⊆ pin          a pairing for an unpinned player is a stale row.
    """
    p = _opp_data_paths(slug, path)
    out = []

    def _load(name):
        try:
            return json.load(open(p[name], encoding="utf-8"))
        except FileNotFoundError:
            out.append(f"{name}: missing — {p[name]}")
        except Exception as e:                                   # noqa: BLE001
            out.append(f"{name}: unreadable ({type(e).__name__}) — {p[name]}")
        return None

    pin, store, about, h2h, series = (_load(n) for n in ("pin", "store", "about", "h2h", "series"))
    if pin is None:
        return out
    names = pin.get("names", {})
    ids = lambda xs: {str(x) for x in xs}                       # noqa: E731
    label = lambda s: ", ".join(f"{i} {names.get(i, '')}".strip() for i in sorted(s))  # noqa: E731
    pin_bowl, pin_bat = ids(pin.get("bowlers", [])), ids(pin.get("batters", []))

    if store is not None:
        st_bowl = ids(c["bowler_id"] for c in store.get("we_bat", []))
        st_bat = ids(c["batter_id"] for c in store.get("they_bat", []))
        if st_bowl - pin_bowl:
            out.append(f"store has bowler(s) not in the pin (stale export): {label(st_bowl - pin_bowl)}")
        if st_bat - pin_bat:
            out.append(f"store has batter(s) not in the pin (stale export): {label(st_bat - pin_bat)}")
    if about is not None:
        ab_bowl, ab_bat = ids(about.get("bowlers", {})), ids(about.get("batters", {}))
        if pin_bowl - ab_bowl:
            out.append(f"pinned bowler(s) with NO opponent_about entry (empty card): {label(pin_bowl - ab_bowl)}")
        if ab_bowl - pin_bowl:
            out.append(f"opponent_about bowler(s) not in the pin (stale entry): {label(ab_bowl - pin_bowl)}")
        if pin_bat - ab_bat:
            out.append(f"pinned batter(s) with NO opponent_about entry (empty card): {label(pin_bat - ab_bat)}")
        if ab_bat - pin_bat:
            out.append(f"opponent_about batter(s) not in the pin (stale entry): {label(ab_bat - pin_bat)}")
    if series is not None:
        entry = next((s for s in series.get("series", []) if s.get("slug") == slug), None)
        if entry is None:
            out.append(f"series.json has no entry for {slug}")
        else:
            se_bowl = ids(r["id"] for g in entry.get("groups", [])
                          if "batter" not in g.get("slug", "") for r in g.get("reports", []))
            if pin_bowl - se_bowl:
                out.append(f"pinned bowler(s) missing from series.json (no report card): {label(pin_bowl - se_bowl)}")
            if se_bowl - pin_bowl:
                out.append(f"series.json bowler(s) not in the pin (stale roster line): {label(se_bowl - pin_bowl)}")
    if h2h is not None:
        h_bowl = ids(r["bowler_id"] for r in h2h.get("our_batting", []))
        h_bat = ids(r["striker_id"] for r in h2h.get("our_bowling", []))
        if h_bowl - pin_bowl:
            out.append(f"h2h pairing(s) for bowler(s) not in the pin (stale rows): {label(h_bowl - pin_bowl)}")
        if h_bat - pin_bat:
            out.append(f"h2h pairing(s) for batter(s) not in the pin (stale rows): {label(h_bat - pin_bat)}")
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
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "--check":
        probs = roster_check(sys.argv[2])
        print("\n".join(f"  ! {p}" for p in probs) or f"  {sys.argv[2]}: rosters agree")
        sys.exit(1 if probs else 0)
    print(describe())
