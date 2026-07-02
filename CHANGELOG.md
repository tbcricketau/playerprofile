# Report Version History

Bump `REPORT_VERSION` in `version.py` on every git commit that changes report
output, and record it here. The version + build date print in the top-right of
the front page.

## Unreleased
- **Scope = official international Tests only** (via `Matches.series_id → Series.name`,
  `ludis_cricket.config.international_series_sql`), not `match_length_id` — reproduces
  official Test tallies; Sheffield Shield etc. excluded.
- **Batting-hand corrections** (`ludis_cricket.lookups.BATTING_HAND_OVERRIDE`) for a few
  mis-recorded players (e.g. Rizwan) — fixes vs-LHB/RHB splits.
- **Release point & crease** expanded in Sequencing: release-height percentile (tall/low),
  crease-width percentile, variation percentile, and an over/round tight/standard/wide
  usage table — all benchmarked vs **hand × pace/spin** peers (release ref rebuilt
  Test-only, `bowler_crease_profile.csv` gains `peer_group`, `release_height_cm`,
  `height_pctl`). Release data is modern-era (2017+); shown with `n=`.
- **Release-point map** (`ludis_cricket.charts.release_map`): a release-point cloud seen
  from behind the bowler — lateral position × release height. Purple density (like the
  pitch map), **Over/Round labelled on the plot** (no legend), dotted tight/standard/wide
  + return-crease guides, and a mean-release-height line. **Over/round drawn as two
  self-normalised density traces** so the minority angle stays visible, and the **x-axis
  is reversed** so a right-armer's over-the-wicket side sits on the LEFT (behind-the-bowler
  view; left-armers mirror to the right).
- **Release Point & Crease Use** is its own section, now placed **below Length by Match-up**:
  an outcomes-by-band table (avg/wkts/econ/SR when tight/standard/wide) + the over/round
  usage mix, with the map underneath. Crease-position mix across the over added to the
  Sequencing read.
- **Bowling Fingerprint** panel (after the Scouting Summary): 7–8 StatsBomb-style
  distribution cards (`ludis_cricket.charts.fingerprint_strip`) — pace, release height,
  crease width/variation, seam/turn, swing/drift, bounce, repeatability — each a mini peer
  distribution with the bowler marked by a **line** + `Pnn` percentile. Release/crease vs
  hand × pace/spin; movement/speed/repeatability vs pace/spin (labelled per card). Caption
  now explains repeatability (high P = tighter/metronomic, low P = varies length more).
- **Threat Profile**: five cards on one row (`.tcards`); pace now gets **Avg seam** +
  **Avg swing** cards (mirroring spin's Avg turn + Avg drift).
- **Page numbers** on the PDF via CSS `@page` margin boxes (`n / total` bottom-right,
  "{name} · bowling scout" bottom-left) — Chromium print-to-pdf honours margin boxes.
- Charts: `automargin=True` + axis-title `standoff` to stop axis titles overlapping ticks
  (documented in `c:\Ludis\CLAUDE.md`).

## Batting profile v0.1 (in progress) — 2026-07-02
- New: `batting_loaders.py`, `batter_profile.py`, `batting_report.py`,
  `build_batting_reports.py`. Test/red-ball batting scouting PDF.
- Novel **share-of-runs** metric: % of the team's off-bat runs (career volume-
  weighted + median per innings) and % of match runs, plus a "carries the innings"
  rate (≥25% of team). Verified: Smith 17.2% career / 13.7% median, carries 26%.
- Analytics: vs each bowler type (avg/SR/false-shot/dismissal-rate) + weakness read;
  shot groups (reusing STROKE_FAMILY); scoring direction (off/leg/straight via
  hit_to_angle — off_bat_angle is empty); dismissal modes + which bowler type gets
  them; wagon wheel. Auto scouting summary (themes/strengths/weaknesses).
- Naming: `firstname_surname_batting_test_{lhb|rhb}.pdf`.
- NEXT: weakness-by-pitch-zone and by ball-type (where they nick/miss), early-innings
  vs set, vs pace short-ball, peer-benchmarking, polish.

## v1.0 — 2026-07-01
- First versioned report.
- Sections: Scouting Summary, Threat Profile, Stock Ball & Variations,
  Danger Zones, Scoring Profile, Pitch Maps & Scoring, Over vs Round the Wicket
  (adaptive), Speed & Spells, Movement (with bowler-archetype read),
  Length by Match-up, Beaten Zones.
- Ball classification: each delivery bucketed into a length-band × line-region
  "ball type", enriched with movement + where it passes the stumps, ranked by
  frequency so the modal type is the genuine stock ball (with its variations).
- Sequencing & Over Construction (B1–B4): style-relative length-spread read
  (metronomic vs variety); how length/short%/economy shift across the six balls
  of an over; and ball-to-ball set-ups computed over consecutive deliveries —
  short-ball usage (double-up vs one-off) and how he sets up his wickets (fuller
  / shorter / straighter than the previous ball).
- Peer-benchmarked repeatability: length-spread percentile vs same-type bowlers
  (referencebuilder/data/bowler_repeatability_profile.csv).
- Crease use: wide vs tight to the stumps and how much he varies his release
  position, peer-benchmarked (bowler_crease_profile.csv), from
  release_line_unmirrored.
- Language: "rotated" not "milked"; "minor variations" for related stock balls;
  "pitching line" vs "stump line" disambiguated; over/round stated on danger line
  and wicket zone; "Caught (Pos Unkwn)"; movement column in the ball-type table.
- LHB pitch maps / beehive render off side on the right (bowler's-eye view),
  with Off/Leg labels.
- Natural cricket phrasing for length/line (replaces the "Full / Stumps" slash
  notation).
