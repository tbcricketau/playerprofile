# playerprofile — Claude Guidelines

> Parent guidelines at `C:\Projects\CLAUDE.md` apply (no pandas/numpy, Python via `py -3.12`,
> Opta light theme, progress board). Warehouse guide: `../cricket-core/DATAWAREHOUSE.md` —
> read before any query. Shared code (charts/theme/lookups/warehouse/video) comes from the
> **cricket-core** package — the old local `charts.py`/`theme.py`/`sql_functions.py` copies
> are gone; import `cricket_core.*` instead.

## What this project is

Opposition scouting — player profiles (Test bowling + batting reports, ODI/T20 profiles)
and the published scouting-reports site. The main Streamlit app is bowling-profile centred;
report builders (`report.py`, `t20_report.py`, `odi_report.py`, `batting_report.py`) and
`publish_site.py` generate the hosted site (github.com/tbcricketau/scouting-reports,
refreshed by the "Scouting Reports Refresh" scheduled task via `refresh_site.bat`).
Other fronts have their own plan docs: `WEBAPP_PLAN.md`, `FIELD_PLAN.md`, `VIDEO_PLAN.md`,
`BATTING_PLAN.md`, `CHANGELOG.md`. Before a report leans on a player's FC/ODI/T20 numbers to
say anything about Tests, read **`CROSSFORMAT_TRANSLATION.md`** — what translates (tempo/rates)
and what must not be projected (averages, wicket rates), with the measured environment ratios.

**Setup:** `.\setup.ps1` (venv + requirements incl. `-e ../cricket-core`).
**Run:** `.\venv\Scripts\python.exe run.py` — starts Streamlit on port 8060.

## File structure (core app)

| File | Purpose |
|------|---------|
| `app.py` | Main Streamlit app — team → bowler selector, full profile layout |
| `data_loaders.py` | `@st.cache_data(ttl=3600)` SQL queries (see below) |
| `config.py` | Project config (`DATA_SCHEMA` re-exported from `cricket_core.config`) |
| `run.py` | Launch shim (local port 8060) |
| `photos/` | Drop `{bowler_id}.jpg` here for player photos; placeholder shown otherwise |

Charts come from `cricket_core.charts` (`pitch_scatter_map`, `beehive`, `speed_violin`,
`spell_bar`, `danger_zone`, `spell_summary_df`, …) and the theme from
`cricket_core.theme.apply_theme()`.

## Data loaders

All use `@st.cache_data(ttl=3600)` and return `list[dict]` with **all values as strings** (including `None` → the string `"None"`).

- **Scope = official international Tests only** — all loaders filter on `Matches.series_id → Series.name = "International Tests M"` (via `cricket_core.config.international_series_sql("Test")`), **not** `match_length_id` (which mixes Tests with Sheffield Shield and inflates tallies). Verified to reproduce official Test records.
- **`load_test_teams()`** — teams that appear as bowling side in international Tests
- **`load_team_bowlers(team_id)`** — bowlers with ≥60 legal balls in Tests for that team; returns `bowler_id`, `player_name`, `last_name`, `balls`
- **`load_bowler_deliveries(bowler_id, dev_limit=0)`** — all Test deliveries for the bowler; `dev_limit` caps rows for fast local testing

Key columns returned by `load_bowler_deliveries`:

| Column | Notes |
|--------|-------|
| `bowler_spell` | Spell number within innings (1 = opening spell) |
| `legal_ball` | `"1"` = legal delivery |
| `bowler_dismissal` | `"1"` = wicket on this delivery |
| `batter_missed_id` | Non-`"None"` = batter missed the ball (spin miss-zone analysis) |
| `ball_speed` | Pre-bounce speed in km/h (string → `float`) |
| `pitch_line`, `pitch_length` | Raw coordinates in **mm** — divide by 1000 for metres |
| `at_stumps_line`, `at_stumps_height` | Ball position at stump face in mm |
| `pitch_line_group_pace` | Categorical line zone (lookup_type_id 2823) |
| `pitch_length_group_pace` | Categorical length zone (lookup_type_id 2819) |
| `pitch_length_group_pace_2` | Finer length grouping (lookup_type_id 2820) |
| `pitch_line_group_spin` | Spin line zone (lookup_type_id 2824) |
| `pitch_length_group_spin` | Spin length zone (lookup_type_id 2821) |
| `striker_hand` | Text description — check `.lower()` contains `"left"` for LHB |
| `bowler_type_simple` | Derived CASE expression — `"Right Fast"`, `"Off Spin"`, etc. |

## Critical: string-valued rows

`run_query_to_df` returns everything as strings. Always:
- Boolean columns: `r.get("legal_ball") in ("1", "True", "true")`
- Numeric columns: `float(v)` inside try/except (or use `_safe_float`)
- Null check: `r.get("col") not in (None, "None", "none", "", "nan")`

The `_process_rows()` function in `app.py` handles all this enrichment and adds parsed fields (`is_legal`, `is_wicket`, `is_lhb`, `is_miss`, `ball_speed_n`, `pitch_line_m`, `at_stumps_line_m`, etc.).

## Coordinate conventions

- DB stores `pitch_line` / `at_stumps_line` as **positive = off side**
- `_process_rows()` **negates** line values: `pitch_line_m = -ln / 1000`
- After negation: **negative = off side** (left on chart for RHB, right for LHB)
- For LHB views (`flip_x=True`), zone boundaries are mirrored in the sidebar sliders

## Charts (charts.py)

### `pitch_scatter_map(data, line_zones, length_zones, value, title, min_balls, flip_x)`
- Coordinate-based heatmap using `pitch_line_m` / `pitch_length_m`
- `value` ∈ `{"count", "wickets", "runs", "wkt_rate"}`
- `line_zones` / `length_zones` are lists of `(x0, x1, label)` tuples in metres

### `beehive(data, metric, title, line_zones, flip_x)`
- Stump-face heatmap using `at_stumps_line_m` / `at_stumps_height_m`
- Same `metric` values as pitch map

### `speed_violin(data, speed_col)`
- Violin of `ball_speed_n` split by Spell 1 vs Spell 2+

### `spell_bar(data, y_col, y_title, title, colour)`
- Bar chart of a metric averaged by spell number (≥10 balls per spell required)

### `danger_zone(data, line_col, length_col, line_order, length_order, min_balls)`
- Returns dict `{line, length, wickets, balls, rate}` for zone with highest wicket rate
- Returns `None` if no zone meets `min_balls` threshold

### `spell_summary_df(data, is_pace)`
- Returns `list[dict]` — one row per spell group (Spell 1 / Spell 2 / Spell 3+)
- Includes Balls, Overs, Wkts, Econ, Avg; pace adds Avg Speed, Max Speed, Avg Length, Short %

## App layout (app.py)

1. **Sidebar** — Opposition team → Bowler → Batter handedness (All/LHB/RHB) → Spell (All/Opening/Later) → Pitch line zone sliders
2. **Header** — Photo or placeholder; name + flag; 5 metric cards (Balls / Wickets / Economy / Avg Speed / Avg Length)
3. **Pitch Maps** — Pitch scatter map + Beehive side-by-side; metric radio (All deliveries / Wickets / Wicket rate / Runs)
4. **Spell Analysis** — Speed violin + length/speed bar; spell summary table; pace-by-spell callout
5. **Miss Zones** (spin only) — pitch map of where batter misses; typical line & length callout
6. **Danger Zones Summary** — two danger-box cards (all batters / vs LHB)
7. **Short-ball Profile** (pace only) — frequency %, wickets, economy from short balls

## Bowling type detection

```python
_pace_types = {"Right Fast", "Left Fast", "Right Medium", "Left Medium"}
_spin_types = {"Off Spin", "Left Orthodox", "Leg Break", "Left Unorthodox"}
primary_type = Counter(r["bowler_type_simple"] for r in raw if r["is_legal"]).most_common(1)[0][0]
is_pace = primary_type in _pace_types
is_spin = primary_type in _spin_types
```

## Relationship to livematchdashboard

- Same warehouse via `cricket_core.warehouse`; same shared theme/charts
- `livematchdashboard` is **match-centric** (one match at a time); `playerprofile` is **player-centric** (career data for one player)

## Publishing — the link check is mandatory, not optional

**Never `git push` a pack bundle by hand.** Broken links reached the live packs twice, and neither
was a build failure — the build succeeded and produced a bundle containing dead links, so nothing
complained. The gate therefore sits on the *push*, against the *assembled bundle*, which is what
actually gets served.

```powershell
.\venv\Scripts\python.exe publish_packs.py aus      # assemble -> validate -> push (refuses if broken)
.\venv\Scripts\python.exe publish_packs.py caxi --deep
.\venv\Scripts\python.exe check_site.py player_pack_site   # validate on its own
```

`check_site.py` fails the build (exit 1) on: a dead internal href/src, a zero-byte target, a
`#fragment` missing from the page it points at, or a play button whose playlist is absent or empty.
It warns on orphan pages — usually a leftover carrying a stale breadcrumb. `--deep` HEADs a sample
of media URLs, which is how you catch an expired Fairplay SAS before players do.

`publish_site.deploy_github()` runs the same check before the coach site goes out, so
`deploy_scouting.py` is covered too. `check=False` exists only for a deliberate override.

**The failure mode to remember:** changing which report a card links (e.g. adding `bowl_groups`, or
re-scoping a group) changes the link *targets*, so the reports must be re-injected before assembling.
Assemble copies only what the packs link, so a stale bake shows up as dead links — which is exactly
what the check catches.

## Vision reels are scoped to the EXACT bowler type — and say when they aren't

A pack's footage must match the bowler whose pack it is. Scoped to the macro pace/spin group, an
off spinner's pack served Jadeja, Abrar Ahmed and Noman Ali — the same pooling error that told Lyon
to turn it away from a right-hander. `batter_clips_best()` (`build_opponent_about.py`) resolves by
exact type (style id + hand) and relaxes in a fixed order, recording how far it went in
`clip_scope_{group}`:

1. this format + exact type · 2. same format, wider pace/spin set · 3. ODI · 4. T20I

Test footage of a near-enough bowler type beats ODI footage of the exact type — Tests are what they
play. Anything but `Test:{group}` stars the button (`Scoring shots*`) and triggers the footnote at
the foot of the section. The star is **per button**: a batter can have real footage scoring against
that type but none of getting out to it. It also fires when the clips exist in the warehouse but no
blob resolves, which is the honest answer — the reel being served is the wider one either way.

**Adding a new bowler type means three places, not one**: `_STYLE`/`_CLIP_GROUPS` in
`build_opponent_about.py`, the `opp_clips` group list and the `_build_vision` kinds list in
`build_player_site.py`. Miss the last and that type silently falls back to the macro group forever.

### The rule behind it: a reel is scoped to whatever the pack is about

Both pack types serve footage, and each has an axis it must be scoped on. Get one right and the
other wrong and the pack looks fine while showing the wrong player entirely. Three separate reports
in one day, all the same defect on a different axis:

| Pack | Reel | Must be scoped to |
|------|------|-------------------|
| Bowling pack (our bowler) | opposition batter's scoring / dismissal clips | the **exact bowler type** the pack's bowler bowls |
| Batting pack (our batter) | opposition bowler's stock / wicket / new-ball clips | **our batter's hand** |

The batting-pack half went unnoticed from `a067e44` until 2026-08-10: the reels were built from
`build_profile(bid, hand="All")`, so Steve Smith's pack showed Ebadot Hossain bowling to Ben Curran.
`bowler_clips_by_hand()` now builds all three (both hands, to LHB, to RHB) off one delivery load.

**No pooled fallback on the batting packs.** Ebadot has 10 wicket clips to left-handers and none of
them resolve to a playable blob; falling back to the pooled reel served a left-hander's pack 40
wicket balls that were all to right-handers. If a hand has no playable footage the button is
omitted — showing nothing beats showing the wrong hand.

**Verify the built pages, not the source data.** `audit_pack_hands.py` follows every play button in
every batting pack through to its playlist, maps each clip back to a delivery and checks the
striker's hand. Run it after a build, before publishing (exit 1 on any mixed or wrong reel). It
needs the warehouse, which is why it isn't wired into `check_site.py` — the publish gate is
deliberately offline-only.

### Bowlers the feed can't classify — `data/bowler_type_overrides.json`

Every delivery carries the bowler's *registered* style and hand, so a bowler who switches arms is
stamped with one of them for all their balls. **Tharindu Rathnayake** bowls left-arm orthodox and
off spin; all 767 of his deliveries are coded right-arm off spin, and the Players table agrees —
both come from the same feed, so nothing in the warehouse contradicts it. Only the footage does.

Ids listed under `ambidextrous` are dropped from the exact-type reels and profiles and kept in the
macro pace/spin groups (the ball is still spin). It was skewing the plans as well as the video:
Shanto's "off spin" record was 28% Rathnayake, and dropping those balls moved his sample 714 → 516
and changed Mehidy's plan from *good length* to *full*. Add an id when footage disagrees with the
coded type, and say who verified it.

## CA XI packs — ARCHIVED 2026-08-10

The site is offline (GitHub Pages disabled on `tbcricketau/caxi-player-packs`); the repo, history
and the last published state (tag `archived-2026-08-10`) are intact. `publish_packs.py caxi` refuses
unless given `--revive`. **Those packs predate the 2026-08-10 fixes** — wrong-hand bowler reels and
pooled-spin batter reels — so reviving means rebuilding from source, not re-pushing the tag.

## Known gaps / pending work

- Zone label ordering (`PACE_LINE_ORDER`, `SPIN_LINE_ORDER`) uses assumed strings — verify against actual DB lookup values if cells appear out of order

## Player photos (2026-07-15 — shared `cricket_core.headshots`)

Headshots live in the **estate-wide store** `cricket-core/headshots/` via `cricket_core.headshots`
(cricket.com.au source, format-aware kit variants, auto-resolve by name, page-scan for the newest
ids — full pipeline in that module's docstring; the old SharePoint/Graph backend is retired).
This project's `photos.py` wraps it, checking the local `photos/` folder FIRST (hand-collected
opposition photos + per-player overrides). **Report builders pass `name=` so a brand-new player's
headshot fetches itself at render time.** Bulk tooling for a new squad: `fetch_photos.py`
(`--resolve` · `--scan-new` · `--force`).
