"""build_over_split.py — the overs an opposition bowler bowls in each phase of a white-ball innings.

    venv/bin/python build_over_split.py --slug england-odi-home-2026

Tom, 10-11-2026: a bowler's summary in the player packs carries "their expected over
distribution" as its second point, e.g. "Overs: 4 PP · 4 Mid · 2 Death (last 20 ODIs)". For each
bowler in the series' about file: the overs they bowled in each phase per match, averaged over
their last 20 matches in the format and rounded to whole overs, so it can add to less than ten for
a bowler who does not usually bowl out. Phases are `cricket_core.formats.phase_bands`, the same
bands as the phase reels. An over counts in a match when they bowled any ball of it.

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


def split(rows, fmt, last=LAST):
    """{matches, first, last, overs: {phase: average}} over the latest `last` matches, or None."""
    from cricket_core.formats import match_phase, phase_bands
    bands = phase_bands(fmt)
    if not bands:
        return None
    overs, dates = defaultdict(lambda: defaultdict(set)), {}
    for r in rows:
        ph = match_phase(r.get("over_n"), fmt)
        if not ph:
            continue
        key = (str(r.get("match_id")), str(r.get("match_innings")))
        overs[key][ph].add(r["over_n"])
        dates[key] = str(r.get("match_date") or "")
    keys = sorted(overs, key=lambda k: dates[k])[-last:]
    if not keys:
        return None
    return {"matches": len(keys), "first": dates[keys[0]][:10], "last": dates[keys[-1]][:10],
            "overs": {ph: round(sum(len(overs[k][ph]) for k in keys) / len(keys), 2) for ph, _a, _b in bands}}


def text(s, fmt):
    """"Overs: 4 PP · 4 Mid · 2 Death (last 20 ODIs)", or "" without a split."""
    if not s:
        return ""
    o = s["overs"]
    whole = lambda v: int(v + 0.5)
    fw = {"ODI": "ODIs", "T20I": "T20Is", "T20": "T20s"}.get(fmt, fmt)
    return (f"Overs: {whole(o.get('powerplay', 0))} PP · {whole(o.get('middle', 0))} Mid · "
            f"{whole(o.get('death', 0))} Death (last {s['matches']} {fw})")


def build(slug):
    import profile as PR
    from build_coach_site import _series, _fmt_level, _opp_key, _about
    from data_loaders import load_bowler_deliveries
    entry = _series(slug)
    fk, level = _fmt_level(entry)
    fmt = {"odi": "ODI", "t20": "T20", "t20i": "T20"}.get(str(fk).lower())
    if not fmt:
        raise SystemExit(f"{slug} is not a white-ball series: no phases to split overs into")
    bowlers, _batters = _about(slug)
    out = {"slug": slug, "format": fmt, "last": LAST, "built": datetime.date.today().isoformat(), "bowlers": {}}
    for bid, meta in bowlers.items():
        rows = PR.process_rows(load_bowler_deliveries(bid, fmt=fmt, level=level))
        s = split(rows, fmt)
        if s:
            s["text"] = text(s, fmt)
            out["bowlers"][str(bid)] = s
        print(f"  {meta.get('name') or bid:20} {s['text'] if s else 'no ' + fmt + ' overs'}", flush=True)
    path = os.path.join(HERE, "data", f"over_split_{_opp_key(slug)}.json")
    json.dump(out, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote {os.path.relpath(path, HERE)} ({len(out['bowlers'])} bowlers)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True, help="the squad slug, as in series.json")
    build(ap.parse_args().slug)


if __name__ == "__main__":
    main()
