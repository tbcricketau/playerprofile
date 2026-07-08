"""
build_series_json.py — (re)generate series.json's report lists from the analyst's shortlist,
tagging each bowler with a default TIER (xi / squad / fringe) from recency so the site can
group + badge them. Tom overrides any tier by editing series.json directly.

Source: presentationbuilder/data/bowlers_for_reports.csv (shortlist=Y rows only).
Tier default:
  xi     — front-line bowler (role Bowler) who played the team's most recent Test series
           (last_test within 60 days of the team's latest shortlisted Test)
  squad  — any other shortlisted player with a Test in the last ~15 months
  fringe — last Test older than ~15 months (returning / out of the recent picture)

Series metadata (slug/name/subtitle/target_country/groups) is preserved; only the
bowlers-vs-lhb group's `reports` list is rewritten.

Run:  .\\venv\\Scripts\\python.exe build_series_json.py [--hand lhb]
"""
import argparse
import csv
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = r"c:\Projects\presentationbuilder\data\bowlers_for_reports.csv"
SERIES_JSON = os.path.join(HERE, "series.json")
TODAY = datetime.date(2026, 7, 6)
RECENT_DAYS = 15 * 30            # ~15 months = "squad" window
XI_WINDOW_DAYS = 60             # within this of the team's latest Test = "most recent series"

SERIES_OF = {"Bangladesh": "bangladesh-home-2026",
             "South Africa": "south-africa-away-2026",
             "New Zealand": "new-zealand-home-2026-27"}

# Our own bowlers — a reference set we know well, to sense-check the report format. Rendered
# for BOTH hands (separate LHB + RHB reports). tier "reference" → its own flat section.
REFERENCE_BOWLERS = [
    ("1300007", "Mitchell Starc"),
    ("1300076", "Patrick Cummins"),
    ("880149", "Josh Hazlewood"),
    ("2710059", "Scott Boland"),
    ("1300071", "Nathan Lyon"),
]


def _reference_series():
    groups = []
    for hand, gname, gslug in (("lhb", "Our Bowlers to LHB", "our-bowlers-vs-lhb"),
                               ("rhb", "Our Bowlers to RHB", "our-bowlers-vs-rhb")):
        groups.append({"slug": gslug, "name": gname,
                       "reports": [{"id": bid, "hand": hand, "tier": "reference", "name": nm}
                                   for bid, nm in REFERENCE_BOWLERS]})
    return {"slug": "australia-reference", "name": "Australia — Reference Bowlers",
            "subtitle": "Our bowlers · a sense-check set we know well (LHB + RHB)",
            "target_country": "Australia", "groups": groups}


def _date(s):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            pass
    return None


def _tiers(rows):
    """Assign xi/squad/fringe per row, using each team's own latest Test as the XI anchor."""
    team_max = {}
    for r in rows:
        d = _date(r["last_test"])
        if d and d > team_max.get(r["series"], datetime.date.min):
            team_max[r["series"]] = d
    out = []
    for r in rows:
        d = _date(r["last_test"])
        role = (r.get("role") or "").strip()
        tmax = team_max.get(r["series"])
        if d is None:
            tier = "fringe"
        elif tmax and (tmax - d).days <= XI_WINDOW_DAYS and role == "Bowler":
            tier = "xi"
        elif (TODAY - d).days <= RECENT_DAYS:
            tier = "squad"
        else:
            tier = "fringe"
        out.append(tier)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hand", default="lhb", choices=("lhb", "rhb", "all"))
    args = ap.parse_args()

    rows = [r for r in csv.DictReader(open(CSV, encoding="utf-8")) if r.get("shortlist") == "Y"]
    tiers = _tiers(rows)

    cfg = json.load(open(SERIES_JSON, encoding="utf-8"))
    # bucket shortlisted bowlers by series, tier-tagged, sorted xi -> squad -> fringe then by name
    order = {"xi": 0, "squad": 1, "fringe": 2}
    by_series = {}
    for r, tier in zip(rows, tiers):
        by_series.setdefault(SERIES_OF.get(r["series"]), []).append(
            {"id": r["player_id"], "hand": args.hand, "tier": tier, "name": r["player"]})
    for lst in by_series.values():
        lst.sort(key=lambda e: (order[e["tier"]], e["name"]))

    n = 0
    for s in cfg["series"]:
        reports = by_series.get(s["slug"], [])
        if not reports:
            continue
        grp = next((g for g in s["groups"] if g["slug"] == "bowlers-vs-lhb"), None)
        if grp is None:
            grp = {"slug": "bowlers-vs-lhb", "name": "Opposition Bowlers to LHB", "reports": []}
            s["groups"] = [grp] + s.get("groups", [])
        grp["reports"] = reports
        n += len(reports)
        counts = {}
        for e in reports:
            counts[e["tier"]] = counts.get(e["tier"], 0) + 1
        print(f"  {s['slug']}: {len(reports)} bowlers  "
              f"(xi {counts.get('xi',0)} / squad {counts.get('squad',0)} / fringe {counts.get('fringe',0)})")

    # Reference set — our bowlers, both hands. Replace any existing reference series.
    ref = _reference_series()
    cfg["series"] = [x for x in cfg["series"] if x.get("slug") != ref["slug"]] + [ref]
    n_ref = sum(len(g["reports"]) for g in ref["groups"])
    print(f"  {ref['slug']}: {len(REFERENCE_BOWLERS)} bowlers × LHB+RHB = {n_ref} reference reports")

    json.dump(cfg, open(SERIES_JSON, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nWrote {n + n_ref} report entries -> series.json")


if __name__ == "__main__":
    main()
