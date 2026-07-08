# Batting profile — plan (build on v0.1, add the vulnerability dimensions + fingerprint)

> **Status (2026-07-03): v0.2 built & verified.** Loader/profile/analytics/reference/fingerprint
> done; **combined** + **focused (right_pace)** reports render (verified on Smith); example-video
> links added to both batting & bowling reports; `build_batting_reports.py --mode --group` wired.
> Next: the other five bowler-group focused reports, weakness-by-innings-phase, pace short-ball,
> and paring back per feedback.

**Aim:** scout a batter's weaknesses in enough detail to plan dismissals. Two reports:

1. **Combined overview** — how the batter fares vs *everything*, so we can quickly nail the
   weaknesses: which bowler type, then which lengths / lines / speeds / seam / swing / over-round
   / shots / dismissal modes trouble them. Includes a **batting fingerprint** (vulnerability
   percentiles vs peer batters). This is the "where's the soft underbelly" report.
2. **Focused, per-bowler-type** (start **right-arm pace**) — the same battery of analysis but
   restricted to that bowler group, written as an exploit plan for *our* right-pace bowler:
   his best lengths/lines/seam/swing vs this batter, the danger zones, how right-pacers have
   dismissed him, and a recommended plan. Later: left pace, off spin, leg spin, left orthodox,
   left unorthodox — one report each (same engine, different filter).

Both reports are **the same analytics engine** with an optional bowler-group filter, so the
focused report is just the combined analysis run on a subset + a plan read.

## Dimensions we measure the batter against
Per bucket: **balls, avg (runs/out), SR, false-shot %, dismissals/100, boundary %**, and a
weakness flag (high false%/dismissals, low avg vs the batter's own baseline).

- **Seam** (`movement_off_pitch` + 2828 label): Seam-in / No-seam / Seam-away (batter-relative,
  reuse the verified label convention), plus a big-seam band.
- **Swing** (`movement_in_air` + 2827 label): Swing-in / No-swing / Swing-away, plus big-swing band.
- **Speed** bands (pace): e.g. <130 / 130–140 / 140+ ; (spin handled separately / omitted).
- **Length** zones (full / good / back-of-a-length / short) — reuse `LENGTH_ZONES_*`.
- **Line** — pitching line zones (reuse `build_line_zones`) and stump line (beehive) where useful.
- **Over vs round** the wicket (`over_the_wicket`).
- **Length × line grid** — the danger cells (highest dismissals / false-shot), reuse `zone_concentration`/`danger_*`.
- **Dismissal modes** — bowled/caught/LBW/… **normalised** vs the batting base rate (a
  batter dismissal-index, mirroring the bowling report's "how he gets you out" table) + which
  bowler type / length / line got them.
- **Shot type** (`stroke_family`) — runs %, false-shot %, dismissals → which strokes are risky.

## Batting fingerprint (vs peer batters)
A `fingerprint_strip` per metric (reuse `cricket_core.charts.fingerprint_strip`), percentile vs a
peer cohort (Test batters with ≥ N balls; later split by top-order / hand). Metrics (vulnerability
framed — **higher percentile = more of a target**, invert the "good batter" ones):
Average · Strike rate · False-shot % · Dismissals/100 vs pace · …vs spin · False% vs seam
movement · False% vs swing · False% vs short · False% vs full · Boundary %.
Peer reference built in `referencebuilder` (`build_batter_vulnerability_profile.py`) → CSV, same
pattern as the bowler references (CSV is source of truth; DB upload later).

## Architecture / files
- **batting_loaders.py** — add cols: `movement_in_air_group_swing_id`, `movement_off_pitch_group_seam_id`,
  `bowler_hand_id`, `bowler_style_id`, plus `delivery_id` + video fields (season/gender/match_length/
  video_file_name) for clip links later.
- **batter_profile.py** — parse `swing_dir`/`seam_dir` (batter-relative labels), `is_round`,
  `speed_band`, length/line zone tags; add reusable `dimension_split(rows, key)` and
  `grid_danger(rows)`; add `BOWLER_GROUPS`; make `build_batter_profile(batter_id, group=None)` so
  the same engine serves both reports; add `_dismissal_index` (vs batting baseline) and the
  fingerprint assembly (`_fingerprint`).
- **batting_report.py** — extend the existing report into the **combined** report (add the new
  dimension sections + fingerprint), keep the layout language/theme consistent with the bowling
  report (cards, scouting summary, fingerprint grid, dimension tables, danger grid, wagon).
- **batting_report_focused.py** (new) — the per-bowler-type exploit report (right pace first):
  header states the matchup; the dimension analysis on that group; danger zones; how that group
  dismisses him; a "plan" read; (later) video playlists of him nicking off vs that group.
- **build_batting_reports.py** — flags: `--mode combined|focused`, `--group right_pace`, ids/CSV.
- **referencebuilder/scripts/build_batter_vulnerability_profile.py** — per-batter metrics +
  cohort percentiles → `data/batter_vulnerability_profile.csv`.
- **Video** (later): reuse `cricket_core.video` — playlists of the batter's false shots / dismissals
  vs a bowler group, backing the plan.

## Order of implementation (starting now, pare back after)
1. Loader cols + profile parsing (seam/swing labels, over/round, speed/length/line tags).
2. `dimension_split` + `grid_danger` + `BOWLER_GROUPS` + group filter in `build_batter_profile`.
3. Dismissal index (batting baseline) + reference builder + run it.
4. Fingerprint assembly.
5. Combined report (extend batting_report.py) — render + verify a top-order Test batter.
6. Focused right-pace report — render + verify.
7. Wire build script. Then iterate / pare back.
