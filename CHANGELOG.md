# Report Version History

Bump `REPORT_VERSION` in `version.py` on every git commit that changes report
output, and record it here. The version + build date print in the top-right of
the front page.

## v1.2 — 4 July 2026
- **Video example precedence — like-for-like conditions.** Clips linked from the report are now
  ordered by where the next series is played: same country first, then the same conditions
  bucket (AUS↔SA/NZ; ENG; subcontinent; Caribbean), then the rest — most recent within each
  tier. Falls back to pure recency when no like-conditions footage exists (the common case for
  opposition bowlers touring Australia). `--target-country` on `build_reports.py` (default
  Australia); taxonomy in `ludis_cricket.lookups.conditions_tier`; loader now carries the venue
  country; clip captions show country + year. (Ordering is applied to the clips that actually
  resolve, so sparse-coverage tiers don't crowd out available clips.)
- **Bowler-type override** (`ludis_cricket.lookups.BOWLER_TYPE_OVERRIDE`) for warehouse
  mis-codes — e.g. Nahid Rana (express quick coded Medium) now reads Right Fast. Mirrors the
  batting-hand override pattern.
- **Bowling report — player-facing upgrade (shippable to players).** Four new content
  sections + video/UX polish:
  - **How to Play Him** — a counter-strategy synthesis (Respect / Score off / Watch for),
    every line drawn from his own danger zones, scoring leaks, match-ups and wicket set-ups
    (e.g. "His short ball is scoreable — economy 4.2, 13 wkts off 877"; short-ball line fires
    for pace only).
  - **Current Form** — last 5 Tests vs career (avg/econ/SR/false%/speed/length), with a read.
  - **Match-ups** — LHB/RHB, new/old ball, and batting position side by side (all batters,
    independent of the hand filter).
  - **Setup & wicket patterns** — the "ball before the wicket" length/pace read in Sequencing.
  - **Per-ball-type playlists** — a ▶ on every ball-type row opens that ball type's clips;
    **▶ watch danger balls** on Danger Zones (most-lethal-cell playlist).
  - **New ball vs old ball** split (one consistent 30-over threshold across the report):
    ball-type mix + "Danger by ball age" cards.
  - Speed & Spells: chart titles moved on top (matching the pitch maps) + the read now covers
    spell, innings **and** match day. Over/round now names the actual hand (LHB/RHB), never
    "this hand". Beaten grid: length labels moved into a clear gutter, y-scale aligned to the
    heatmap (a 6 m line matches on both) and auto-cropped to the data.
- **Stroke norms — how he scores vs the typical Test batter.** New reference
  `batter_stroke_norms.csv` (referencebuilder, 122-batter cohort, ≥500 stroke-coded Test balls):
  per batter × stroke family the share of runs/balls, runs-per-ball, outs/100 and boundary
  share, each with a cohort median + percentile. The batting report's "How He Scores" section
  gains a **"Scoring mix vs the typical Test batter"** table (his runs% · typical · index ·
  percentile; signature shot highlighted, ▼ = under-indexed) and a narrative read naming his
  most over/under-indexed scoring shots (e.g. Smith: ramp/scoop 7.3× the typical share, P98;
  cut only 5% vs 8% typical). Shares are within stroke-coded balls (coding coverage varies).
- **Modal video player + playlists (replaces raw clip links).** `ludis_cricket.video.
  build_player_html` writes a self-contained `<pdf>.player.html` beside each report: clip cards
  per playlist tab; clicking opens a **lightbox that greys out the page** (prev/next, arrow keys,
  Esc). The PDF ▶ links open it at `#<playlist>` — no more raw-mp4 download/click-back. Bowling:
  stock ball / wickets / new-ball out-swingers; batting: danger ball / risky stroke / dismissals.
  (Fixed a Jinja gotcha: `video.keys.x` silently failed — `.keys` collides with dict.keys.)
- **Hawkeye multi-angle footage wired in** (`amshawkeyeupload/hawkeyeupload`, same SSO/RBAC).
  Folder layout `<date_teams_matchid>/<HHMM_inn_over_ball>/Camera N_*.mp4` — the ball folder
  encodes the delivery, so `hawkeye_angles(match_id, inn, over, ball)` joins deterministically;
  `attach_hawkeye` adds per-clip **angle toggles (Broadcast + Camera 1–6)** to playlists
  automatically where a match has coverage (457 matches from 2026-04-04; per-match — e.g. the
  Ban v Aus T20s are fully covered, the Eng-NZ Test folder is an empty placeholder so far).
  Demo: `reports/_hk_demo_player.html`.
- **Batting profile v0.2 — vulnerability engine + two report types + fingerprint.** Measures how
  a batter fares vs **seam & swing (each way, from the coder labels), speed, length, pitching
  line, over/round, shot type, and dismissal mode**, with a length×line **danger cell**. Two
  reports off one engine (`batter_profile.build_batter_profile(group=...)`): a **combined
  overview** (all bowler types + a **batting fingerprint** — percentile vs Test batters on
  avg/SR/false-shot and false% vs pace/spin/seam/swing/short, from new reference
  `batter_vulnerability_profile.csv`, 203 batters) to find weaknesses fast; and a **focused
  per-bowler-type exploit report** (start `right_pace`; also left_pace/off_spin/leg_spin/
  left_orthodox/left_unorthodox) that filters to that group and adds a **bowling plan**. Loader
  gains swing/seam labels + bowler hand/style + video cols; `build_batting_reports.py` gets
  `--mode combined|focused|both --group`.
- **Example-video links in the reports** (both batting and bowling). `ludis_cricket.video.
  first_example` resolves one playable clip per key insight; the PDF now carries clickable
  "▶ watch" links — bowling: stock ball + a wicket; batting: danger ball + his risky stroke +
  a dismissal. Links use a 72h SAS (baked, time-limited); best-effort (absent if no clip).
- **Video: report insights are now backed by clips.** New shared module `ludis_cricket.video`
  (reusable by every project) resolves a delivery → a playable Fairplay URL via SSO/RBAC (SAS,
  no secret), handling the real blob layout + `.mp4`/`.MP4` case. `playerprofile.playlists`
  builds per-insight playlists — **Stock ball, Wickets, New-ball out-swingers** — with captions
  from the report vocabulary; `render_report` writes a `<pdf>.playlists.json` sidecar beside each
  PDF (best-effort, never breaks the report). `video_viewer.py` (`streamlit run`) plays them via
  the shared `playlist_widget`. Loader now pulls `video_file_name`/season/gender/match_length;
  rows carry `clip_stem`; ball rows tagged with `ball_type` for stock-ball pull. Plan +
  next phases in `VIDEO_PLAN.md`.
- **Swing/seam direction now comes from the coders' group labels, not a raw-degree gate.**
  `movement_in_air_group_swing_id` (2827: In/No/Out Swing; spin Drift In/No/Away) and
  `movement_off_pitch_group_seam_id` (2828: Seam In/No/Away; spin Turn In/No/Away) are
  **batter-relative** (verified: In = into the batter for both hands, so no sign flip), and the
  coder has already excluded non-moving balls. So direction is read from the label instead of
  `sign(movement) + 0.3°` — cleaner and un-diluted. Applied to: swing-by-ball-age
  (`_swing_age_split`), the Movement table's in/away split (`_label_dir_split`), and the
  ball-type Movement cells. Starc vs LHB new-ball out-swing reads **60%** (was a diluted 56%),
  old-ball in-swing **70%** — the flip is clearer. New loader cols + `profile.swing_dir/seam_dir`.

## v1.1 — 2026-07-02
- **Swing described by ball age (new vs old).** A bowler whose swing *direction* flips with
  ball age (e.g. Starc's new-ball out-swing that reverses back into the LHB when it's old) was
  read as a misleading "swinging both ways". Movement now splits swing by simple over bands
  (new ≤25, old ≥40) on the hand-filtered set (`profile._swing_age_split`): when the dominant
  direction flips between phases the archetype reads "swings it away with the new ball and
  reverses it back in when it's old", the ball-type cells read "swinging away, reverses in",
  and a swing-by-ball-age line is added under Movement. Hand-specific (the flip is opposite for
  LHB/RHB so it washes out across both); shown only for genuine swing bowlers.
- **Over vs Round the Wicket always shown** (table + both pitch maps), instead of being
  hidden when the split isn't a 15%+ two-way tactic. A lopsided/absent angle now gets a
  full comparative read only when it's a genuine tactic; otherwise a usage note that
  caveats a small sample ("rare change-up — 5%, 272 balls") or an absent one ("never goes
  round in this data"). Maps for sparse/empty angles are kept for layout consistency and
  captioned with their ball count. Surfaces e.g. Starc's round-the-wicket bouncer plan to
  LHB that the old gate hid.
- **Dismissal mix is now peer-normalised** (Threat Profile). "Most likely out" was
  tautological (caught is ~⅔ of all pace wickets), so it's replaced by a **"How he gets
  you out" index table**: his share of each dismissal type indexed against the population
  base rate for his peer group (pace/spin × batter hand). Index &gt;1 = he does it more
  than most (highlighted). New reference `referencebuilder/data/dismissal_baseline.csv`
  (`build_dismissal_baseline.py`); report falls back to raw split if absent. Example: Starc
  vs LHB over-indexes Bowled 1.43× and LBW 1.22×.
- **Ball-type Movement reports swing *and* seam.** The classifier used only
  `movement_off_pitch`, so a swing bowler was mislabelled "seaming". It now tracks swing
  (`movement_in_air`) alongside seam/turn and names whichever is material, dominant first
  (e.g. "swinging away, seaming back").
- **Danger-zone wicket denominator clarified.** The card now reads "% of **mapped** wickets"
  with a footnote counting wickets that pitched too full to place on the map (negative/
  at-crease tracked length) — reconciles the earlier "24 of 134" vs 137-wicket header.
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
- **Page layout tuned so sections land predictably** (verified pace + spin, both 6 pages):
  p3 = Pitch Maps + Speed & Spells, **p4 starts Over vs Round → Sequencing → Length by
  Match-up**, **p5 = Release Point & Crease Use** (+ Movement), p6 = Beaten Zones. Speed &
  Spells lost its forced page break; Movement moved to sit with Release Point; a page break
  now precedes Over vs Round and Release Point. Pitch-map and over/round-map charts trimmed
  ~25% (denser, still legible) so each page fills to its section boundary.
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
