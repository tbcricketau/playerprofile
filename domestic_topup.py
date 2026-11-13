"""domestic_topup.py — who has their domestic one-day cricket read beside a short ODI record, and how
the pack says so (Tom, 10-11-2026: "on the small sample size, can we increase the ones who are low
with domestic one day data?").

    venv/bin/python domestic_topup.py --slug england-odi-home-2026            # who, before the builders
    venv/bin/python domestic_topup.py --slug england-odi-home-2026 --reels    # after build_opponent_about

An opposition player whose ODI record in their role on the pack (batting for a batter card, bowling
for a bowler card) is under FLOOR balls, the floor for a full profile, has their domestic one-day
cricket added (`cricket_core.config.DOMESTIC_OD_SERIES`, the counties' One-Day Cup for England). Every
builder that reads their deliveries asks `level_for` and reads level "with-domestic" for them:
build_opponent_about (summary points and reels), build_pack_extras, build_shot_types and
build_over_split. A player with no domestic one-day balls is left as they are.

Tom's calls, 10-11-2026: under 300 ODI balls · it feeds every number and reel · labelled on the card.
Scouting reads ODIs only, except for a player with no ODI balls at all in the role, who reads their
domestic one-day cricket there too, labelled (Tom, 13-11-2026: `scouting_level`).
The warehouse holds every England One-Day Cup season since 2017 (66 to 77 matches a year, each with
its CricViz id), so nothing has to be pulled. The gaps are players who did not play it, mostly because
it runs alongside The Hundred.

Writes data/domestic_topup_<opp>.json:
  players  {pid: {"name", "bat"|"bowl": {"odi", "domestic", "first", "last", "topped"}}}
  reels    {pid: {about clip key: domestic clips among the first REEL_SHOWN}}   (--reels)

ODI packs only. A Test or T20 pack reads nothing from here.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

FLOOR = 300              # build_opponent_about.TEST_FLOOR: under it there is no full profile
LEVEL = "with-domestic"
REEL_SHOWN = 12          # build_player_site keeps the first 12 clips of a reel that play
_CACHE = {}


def _path(opp):
    return os.path.join(DATA, f"domestic_topup_{opp}.json")


def load(opp):
    if opp not in _CACHE:
        p = _path(opp)
        _CACHE[opp] = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _CACHE[opp]


def topped(opp, pid, role):
    """The record behind a topped-up role ({"odi", "domestic", "first", "last"}), else None."""
    r = (((load(opp).get("players") or {}).get(str(pid)) or {}).get(role)) or {}
    return r if r.get("topped") else None


def level_for(opp, pid, role, fmt, level="international"):
    """The level a builder should read this player at: "with-domestic" for a topped-up role on an
    ODI pack, else the pack's own."""
    if str(fmt) != "ODI" or level != "international":
        return level
    return LEVEL if topped(opp, pid, role) else level


def no_record(opp, pid, role):
    """The topped-up record of a player with no ODI balls at all in this role, else None."""
    r = topped(opp, pid, role)
    return r if r and not r.get("odi") else None


def scouting_level(opp, pid, role, fmt, level="international"):
    """The level Scouting reads a player at (the Bowling plans and Their bowlers cards, the planner and
    the web reports). Only a player with NO ODI record in the role reads their domestic one-day cricket
    there (Tom, 13-11-2026, for James Coles and Eddie Jack), so a short ODI record keeps the
    ODI-only Scouting card it already had."""
    if str(fmt) != "ODI" or level != "international":
        return level
    return LEVEL if no_record(opp, pid, role) else level


def label(rec):
    """The card's first summary point for a topped-up record, e.g. "Short ODI record (174 balls).
    These figures add 455 balls of domestic one-day cricket, 2021 to 2022.", or for a player with no
    ODI balls at all "No ODI record. These figures are 975 balls of domestic one-day cricket, 2021 to
    2026."."""
    span = str(rec["first"]) if rec["first"] == rec["last"] else f"{rec['first']} to {rec['last']}"
    if not rec.get("odi"):
        return f"No ODI record. These figures are {rec['domestic']:,} balls of domestic one-day cricket, {span}."
    return (f"Short ODI record ({rec['odi']:,} ball{'' if rec['odi'] == 1 else 's'}). These figures add "
            f"{rec['domestic']:,} balls of domestic one-day cricket, {span}.")


def sample_words(rec, plural="ODIs"):
    """How a card's sample line names a topped-up record: "Domestic one-day" with no ODI balls,
    "ODIs and domestic one-day" with some."""
    return "Domestic one-day" if not rec.get("odi") else f"{plural} and domestic one-day"


def build(slug):
    from build_coach_site import _opp_key, _about
    from cricket_core.config import DOMESTIC_OD_SERIES
    from cricket_core.warehouse import set_conn_cursor, run_query
    from config import DATA_SCHEMA as S
    from data_loaders import _scope
    import cricviz_source
    opp = _opp_key(slug)
    bowlers, batters = _about(slug)
    roles = {}
    for pid in bowlers:
        roles.setdefault(str(pid), set()).add("bowl")
    for pid in batters:
        roles.setdefault(str(pid), set()).add("bat")
    names = {**{str(k): (v or {}).get("name") for k, v in bowlers.items()},
             **{str(k): (v or {}).get("name") for k, v in batters.items()}}
    ids = ",".join(f"'{p}'" for p in roles)
    dom = "(" + ", ".join(f"'{n}'" for n in DOMESTIC_OD_SERIES) + ")"
    conn, cur = set_conn_cursor()
    got = {}
    for role, col in (("bat", "striker_id"), ("bowl", "bowler_id")):
        for r in run_query(f"""SELECT D.{col} p, COUNT(*) n FROM [{S}].[Deliveries] D
                JOIN [{S}].[Matches] M ON M.match_id = D.match_id
                WHERE {_scope('ODI', 'M')} AND D.legal_ball = '1' AND D.{col} IN ({ids})
                GROUP BY D.{col}""", conn, cur):
            got.setdefault((str(r["p"]), role), {})["odi"] = int(r["n"])
        for r in run_query(f"""SELECT D.{col} p, COUNT(*) n, MIN(YEAR(M.match_date)) y0, MAX(YEAR(M.match_date)) y1
                FROM [{S}].[Deliveries] D JOIN [{S}].[Matches] M ON M.match_id = D.match_id
                JOIN [{S}].[Series] SR ON SR.series_id = M.series_id
                WHERE SR.name IN {dom} AND D.legal_ball = '1' AND D.{col} IN ({ids})
                GROUP BY D.{col}""", conn, cur):
            got.setdefault((str(r["p"]), role), {}).update(
                {"domestic": int(r["n"]), "first": int(r["y0"]), "last": int(r["y1"])})
    conn.close()
    out = {"slug": slug, "opp": opp, "fmt": "ODI", "floor": FLOOR,
           "built": datetime.date.today().isoformat(), "players": {}, "reels": {}}
    for pid, rs in sorted(roles.items(), key=lambda kv: names.get(kv[0]) or ""):
        for role in sorted(rs):
            g = got.get((pid, role), {})
            # the matches the warehouse has not loaded yet count as ODI balls too (cricviz_source)
            pulled = (cricviz_source.batter_rows if role == "bat" else cricviz_source.bowler_rows)(pid, "ODI")
            odi = g.get("odi", 0) + sum(1 for r in pulled if r.get("legal_ball") == "1")
            d = g.get("domestic", 0)
            rec = {"odi": odi, "domestic": d, "first": g.get("first"), "last": g.get("last"),
                   "topped": odi < FLOOR and d > 0}
            out["players"].setdefault(pid, {"name": names.get(pid) or pid})[role] = rec
            if odi < FLOOR:
                print(f"  {names.get(pid) or pid:18} {role:4} ODI {odi:5}  domestic {d:5}"
                      + (f" ({rec['first']}-{rec['last']})  topped up" if rec["topped"] else "  nothing to add"))
    json.dump(out, open(_path(opp), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {os.path.relpath(_path(opp), HERE)}: "
          f"{sum(1 for p in out['players'].values() for k, v in p.items() if k != 'name' and v['topped'])} role(s) topped up")
    return out


def reels(slug):
    """Count, per reel of each topped-up player in the about file, the clips among the first
    REEL_SHOWN that are domestic one-day footage, so the pack can star those reels."""
    from build_coach_site import _opp_key
    from cricket_core.config import DOMESTIC_OD_SERIES
    from cricket_core.warehouse import set_conn_cursor, run_query
    from config import DATA_SCHEMA as S
    opp = _opp_key(slug)
    doc = load(opp)
    if not doc:
        raise SystemExit(f"no {os.path.relpath(_path(opp), HERE)}: run without --reels first")
    about = json.load(open(os.path.join(DATA, f"opponent_about_{opp}.json"), encoding="utf-8"))
    want = {}
    for side, role in (("bowlers", "bowl"), ("batters", "bat")):
        for pid, e in (about.get(side) or {}).items():
            if not topped(opp, pid, role):
                continue
            for k, v in e.items():
                if isinstance(v, list) and "clips" in k:
                    ids = [str(c.get("delivery_id")) for c in v[:REEL_SHOWN] if isinstance(c, dict) and c.get("delivery_id")]
                    if ids:
                        want[(pid, k)] = ids
    every = sorted({i for ids in want.values() for i in ids})
    dom = set()
    if every:
        names = "(" + ", ".join(f"'{n}'" for n in DOMESTIC_OD_SERIES) + ")"
        conn, cur = set_conn_cursor()
        for i in range(0, len(every), 500):
            ch = ", ".join(f"'{x}'" for x in every[i:i + 500])
            for r in run_query(f"""SELECT D.delivery_id d FROM [{S}].[Deliveries] D
                    JOIN [{S}].[Matches] M ON M.match_id = D.match_id
                    JOIN [{S}].[Series] SR ON SR.series_id = M.series_id
                    WHERE D.delivery_id IN ({ch}) AND SR.name IN {names}""", conn, cur):
                dom.add(str(r["d"]))
        conn.close()
    doc["reels"] = {}
    for (pid, k), ids in sorted(want.items()):
        n = sum(1 for i in ids if i in dom)
        if n:
            doc["reels"].setdefault(pid, {})[k] = n
            print(f"  {pid} {k}: {n} of the first {len(ids)} clips are domestic one-day")
    json.dump(doc, open(_path(opp), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"updated {os.path.relpath(_path(opp), HERE)}: {sum(len(v) for v in doc['reels'].values())} reel(s) carry domestic footage")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--reels", action="store_true", help="mark the reels carrying domestic footage")
    a = ap.parse_args()
    reels(a.slug) if a.reels else build(a.slug)


if __name__ == "__main__":
    main()
