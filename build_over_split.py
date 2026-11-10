"""build_over_split.py — the overs an opposition bowler can be expected to bowl in each phase of a
full 50-over innings.

    venv/bin/python build_over_split.py --slug england-odi-home-2026

Tom, 10-11-2026: a bowler's summary in the player packs carries their expected over distribution as
its second point, "Expected overs: 4 PP · 4 Mid · 2 Death (last 20 ODIs)". Whole overs, no minimum
sample (the match count says how thin it is), ODI packs only for now.

It started as the plain average over their last 20 innings, which every short innings pulls down: a
rain cut, a chase won early, a side bowled out before the 41st over (no death overs to bowl). Jofra
Archer read 4-4-1 when he bowls his ten whenever the innings runs its course. So, as Tom set later
the same day, two questions are answered apart, both from the last 20 innings:

- HOW MANY. A frontline bowler bowls 10: one who averages FRONTLINE overs or more in the innings
  that ran the full 50 (reached its FULL_FROM-th over). Anyone else gets their own average in those
  innings, rounded. A series can name frontline bowlers too (`frontline_bowlers` in series.json),
  for one the data does not show.
- WHEN. Their share of overs by phase in those full-length innings, so a short innings does not
  shrink the death overs. Fewer than MIN_FULL of them and every innings is used instead.

The shares times the allocation, rounded so the three add up to it exactly (largest remainder).
Phases are `cricket_core.formats.phase_bands`, the same bands as the phase reels. An over counts in
an innings when they bowled any ball of it. A short ODI record is read with domestic one-day cricket
beside it (domestic_topup.py) and counts "one-day matches".

Writes `data/over_split_<opp>.json`, which build_hub_packs.py reads. Reads the warehouse (and the
CricViz cache, through the loader): run it on the build machine.
"""
import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LAST = 20
FULL_FROM = 49       # over numbers are 1-based: an innings that reached its 49th over ran the full 50
FRONTLINE = 8.0      # averaging this many overs in those innings makes a frontline bowler (Tom, 10-11)
ALLOCATION = 10
MIN_FULL = 5


def _innings(rows, fmt):
    """{(match, innings): {"date", "overs": {phase: set(over)}}} for this bowler."""
    from cricket_core.formats import match_phase
    inn = {}
    for r in rows:
        ph = match_phase(r.get("over_n"), fmt)
        if not ph:
            continue
        k = (str(r.get("match_id")), str(r.get("match_innings")))
        d = inn.setdefault(k, {"date": str(r.get("match_date") or ""), "overs": defaultdict(set)})
        d["overs"][ph].add(r["over_n"])
    return inn


def lengths(keys):
    """The last over each innings reached, whoever bowled it: the warehouse for its matches, the
    CricViz cache for the ones it has not loaded yet."""
    from cricket_core.warehouse import set_conn_cursor, run_query
    from config import DATA_SCHEMA as S
    import cricviz_source
    out = {}
    for r in cricviz_source._all_rows().get("ODI", []) if cricviz_source.enabled() else []:
        k = (str(r["match_id"]), str(r["match_innings"]))
        out[k] = max(out.get(k, 0), int(r["over"]))
    mids = sorted({m for m, _i in keys if (m, _i) not in out})
    if mids:
        conn, cur = set_conn_cursor()
        for i in range(0, len(mids), 400):
            ids = ",".join(f"'{m}'" for m in mids[i:i + 400])
            for x in run_query(f"SELECT match_id m, match_innings i, MAX(TRY_CONVERT(int, [over])) o "
                               f"FROM [{S}].[Deliveries] WHERE match_id IN ({ids}) GROUP BY match_id, match_innings",
                               conn, cur):
                out[(str(x["m"]), str(x["i"]))] = int(x["o"] or 0)
        conn.close()
    return out


def _share_out(shares, total):
    """Whole overs per phase adding up to `total`: floors, then the largest remainders."""
    raw = {p: shares[p] * total for p in shares}
    whole = {p: int(v) for p, v in raw.items()}
    for p in sorted(raw, key=lambda p: -(raw[p] - whole[p]))[:total - sum(whole.values())]:
        whole[p] += 1
    return whole


def split(rows, fmt, last=LAST, named=False):
    """The expected overs per phase in a full innings, from the latest `last` innings, or None."""
    from cricket_core.formats import phase_bands
    bands = phase_bands(fmt)
    if not bands:
        return None
    phases = [ph for ph, _a, _b in bands]
    inn = _innings(rows, fmt)
    keys = sorted(inn, key=lambda k: inn[k]["date"])[-last:]
    if not keys:
        return None
    reach = lengths(keys)
    total = lambda ks: sum(len(v) for k in ks for v in inn[k]["overs"].values())
    full = [k for k in keys if reach.get(k, 0) >= FULL_FROM]
    avg_all = total(keys) / len(keys)
    avg_full = total(full) / len(full) if full else None
    basis = full if len(full) >= MIN_FULL else keys
    n = total(basis)
    if not n:
        return None
    shares = {ph: sum(len(inn[k]["overs"].get(ph, ())) for k in basis) / n for ph in phases}
    usual = avg_full if len(full) >= MIN_FULL else avg_all
    frontline = named or usual >= FRONTLINE
    alloc = ALLOCATION if frontline else min(ALLOCATION, int(usual + 0.5))
    if alloc < 1:
        return None
    return {"matches": len(keys), "first": inn[keys[0]]["date"][:10], "last": inn[keys[-1]]["date"][:10],
            "full": len(full), "avg_all": round(avg_all, 2), "avg_full": round(avg_full, 2) if full else None,
            "frontline": frontline, "named": named, "allocation": alloc,
            "shares": {ph: round(v, 3) for ph, v in shares.items()},
            "expected": _share_out(shares, alloc),
            "overs": {ph: round(sum(len(inn[k]["overs"].get(ph, ())) for k in keys) / len(keys), 2) for ph in phases}}


def text(s, fmt, domestic=False):
    """"Expected overs: 4 PP · 4 Mid · 2 Death (last 20 ODIs)", or "" without a split. A bowler read
    with their domestic one-day cricket (domestic_topup.py) counts "one-day matches"."""
    if not s:
        return ""
    e = s["expected"]
    fw = "one-day matches" if domestic else {"ODI": "ODIs", "T20I": "T20Is", "T20": "T20s"}.get(fmt, fmt)
    return (f"Expected overs: {e.get('powerplay', 0)} PP · {e.get('middle', 0)} Mid · "
            f"{e.get('death', 0)} Death (last {s['matches']} {fw})")


def build(slug):
    import profile as PR
    from build_coach_site import _series, _fmt_level, _opp_key, _about
    from data_loaders import load_bowler_deliveries
    from domestic_topup import level_for
    entry = _series(slug)
    fk, level = _fmt_level(entry)
    fmt = {"odi": "ODI", "t20": "T20", "t20i": "T20"}.get(str(fk).lower())
    if not fmt:
        raise SystemExit(f"{slug} is not a white-ball series: no phases to split overs into")
    named = {str(b) for b in entry.get("frontline_bowlers") or []}
    bowlers, _batters = _about(slug)
    out = {"slug": slug, "format": fmt, "last": LAST, "full_from": FULL_FROM, "frontline_overs": FRONTLINE,
           "built": datetime.date.today().isoformat(), "bowlers": {}}
    for bid, meta in bowlers.items():
        lvl = level_for(_opp_key(slug), bid, "bowl", fmt, level)
        rows = PR.process_rows(load_bowler_deliveries(bid, fmt=fmt, level=lvl))
        s = split(rows, fmt, named=str(bid) in named)
        if s:
            s["text"] = text(s, fmt, domestic=lvl != level)
            out["bowlers"][str(bid)] = s
        how = ("" if not s else f"  [{'named' if s['named'] else 'frontline' if s['frontline'] else 'support'} "
               f"{s['allocation']} · full innings {s['full']} avg {s['avg_full']} · all avg {s['avg_all']}]")
        print(f"  {meta.get('name') or bid:20} {s['text'] if s else 'no ' + fmt + ' overs'}{how}", flush=True)
    path = os.path.join(HERE, "data", f"over_split_{_opp_key(slug)}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {os.path.relpath(path, HERE)} ({len(out['bowlers'])} bowlers)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="the squad slug, as in series.json")
    build(ap.parse_args().slug)


if __name__ == "__main__":
    main()
