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
`BATTING_PLAN.md`, `PACK_MAINTENANCE_PLAN.md`, `CHANGELOG.md`. Before a report leans on a player's FC/ODI/T20 numbers to
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

`publish_site.deploy_github()` runs the same check before the coach site goes out.

**The gated coach site needs its check in a different place, and for a while it had none.**
`deploy_scouting.py` stages a copy of `site/`, encrypts every page with `staticgate`, then deploys —
and `staticgate.encrypt_dir` replaces each `.html` with an encrypted shell. So `deploy_github`'s gate
was walking pages that had no links left in them and passing whatever it was handed: the gated site
was ungated against broken links from the day it was gated, while this file claimed it was covered.
Fixed 2026-08-31 — the check now runs on the **staged copy while it is still plaintext**, and
`deploy_github` is called with `check=False` because the same bytes have already been checked. That
is not a bypass, and re-adding a check after encryption would only re-confirm that an encrypted page
has no links. `--no-check` is the deliberate override; `--deep` HEADs a sample of media URLs.

The general shape, now seen three times: **a gate that runs on the wrong artifact reports success
forever.** Check what is actually served, at the last point it is still readable.

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

**Verify the built pages, not the source data — and the publish gate now does.** `audit_pack_hands.py`
follows every play button in every batting pack through to its playlist, maps each clip back to a
delivery and checks the striker's hand. `publish_packs.py` runs it after `check_site` and **refuses
to push** on any mixed, wrong or unscoped reel.

It sits in `publish_packs.py`, **not** `check_site.py`: resolving who a clip is bowled to needs the
warehouse, and the link check is deliberately offline-only — folding it in would make every link
check depend on the VPN. It **fails closed**: an unreachable warehouse refuses the publish rather
than skipping the check, since a silent downgrade is exactly how the wrong-hand reels survived from
`a067e44` to 2026-08-10. `--no-hand-audit` is the deliberate override. Proven both ways — a clean
bundle reports 157 reels across 13 batting packs and pushes; one reel repointed at a pooled key is
named and refused with exit 1.

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

## Mid-series, a h2h refresh silently re-points every reel at the match just played

`build_h2h.py` takes the newest `MAX_BALLS` (20) of the best available format per pairing. The
moment a match is played it becomes the newest footage *and* usually upgrades the chosen format, so
a refresh doesn't add to a reel — it **replaces** it.

Measured on 2026-08-21, after the first BAN Test (13-08) and the CA XI tour match (06-08):

| | reels | from a single day | top dates |
|---|---|---|---|
| before | 26 | 58% | 2017-08-27, 2026-06-11, 2017-09-04 |
| after | 95 | **94%** | **2026-08-13 (592 balls)**, 2026-08-06 (346) |

Smith vs Taijul went from 20 balls across the 2017 tour to 20 balls from one day. Every top pairing
read 20/20 from 13-08. The pack looks identical — same button, same "20 balls" — while the content
has been quietly swapped for the game everyone just watched, which is the one thing a coach does
*not* need footage of. The format upgrades (ODI 20 → Test 20) make it read as an improvement.

**So during a series, freeze it.** Snapshot `data/h2h_{opp}.json` before running `build_h2h.py`,
then restore that file and merge in **only** the new player's rows:

```python
base = {(r["striker_id"], r["bowler_id"]): r for r in old[section]}   # the frozen reels
for r in new[section]:                                                # carry ONE player across
    if str(r[id_field]) == NEW_ID and (r["striker_id"], r["bowler_id"]) not in base:
        base[...] = r
```

Then verify no reel outside that player references the current series' dates. There is no flag for
this yet — see `PACK_MAINTENANCE_PLAN.md`, which argues the real fix (a builder-respected notion of
*frozen*, and a recency policy so a reel keeps its historical spread instead of collapsing).

Freezing has a second payoff: the reports are rendered against whatever h2h existed at render time,
so a refresh that isn't followed by a re-render leaves the reports' "Real meetings with this squad"
line disagreeing with the pack that links it — Hasan Mahmud's report said *7 balls across 4 batters*
while his pack would have said *224 across 19*. Freeze and they agree again.

## Adding one opposition player — merge, don't rebuild

A full `build_opponent_about.py` run costs ~40 minutes and puts every other player's verified data
back through a build that stalls on a VPN drop. Both builders take a merge flag:

```powershell
.\venv\Scripts\python.exe build_opponent_about.py --opp bangladesh --only-batters 2700039
.\venv\Scripts\python.exe build_opponent_about.py --opp bangladesh --only-bowlers 3630141
.\venv\Scripts\python.exe build_overview.py --opp bangladesh --group right_pace --only 2700039
```

Each rebuilds only the named players and merges into the existing file. In merge mode **any** failure
aborts the write — with one player, a failure is the whole run. (That abort was documented here
before it existed: until 2026-08-21 the loops caught the exception, printed it and wrote anyway, so a
dropped connection reported success having merged nothing. It now raises before the write.) Check the
merge was surgical (every other row byte-identical) rather than assuming it — `--only-bowlers` was
verified that way on Shoriful Islam: one bowler added, zero changed, zero removed.

A player also has to exist in the **matchup store** first: the roster comes from its `they_bat` /
`we_bat` rows, so a squad member pinned only as a bowler has no batter card. Add the id to
`matchupmodel/data/opp_squad_{opp}.json` and re-run `export_matchup_store.py`. `--only-batters`
aborts with that instruction if the id isn't there. **Adding a batter adds them to EVERY bowling
pack**, not just one type's — the roster is shared, so build the overview row for each group you
care about or that pack falls back to the macro plan.

## Two files, and a consumer wants the ROSTER — never the registry

This is the distinction the whole squad front turns on, and `squads.py` is the one reader for it.

| | what it is | what it answers |
|---|---|---|
| **`players.json`** | the persistent **registry**, keyed by player id, shared across every series | what is true of the *player* — name, role, packs, prefs, `bowl_types`, `bowl_groups` |
| **`squads.json`** | the **rosters**, keyed by slug | who was picked, for which team, for which series, and whether that series is over |

**Iterating `players.json` builds for every player ever named in any squad.** That is how
`export_matchup_store.py` came to simulate our 31-name registry against the opposition when the Test
squad was 14 — the excess being a CA XI squad archived eleven days earlier, still costing full Monte
Carlo on every pair. Use the registry as a **lookup**; take the roster from `squads.py`:

```python
from squads import roster, live_slugs, resolve
for slug in live_slugs():                 # archived squads skipped by default
    for pid, rec in resolve(roster(slug)):
        ...
```

`python squads.py` prints every squad, its team, its size and its state.

### Archiving a squad

Set `"archived": "<date>"` on the slug in `squads.json`. The roster **stays in the file** so it can
be read, restored and audited — un-archiving is deleting one line — but no builder prepares for it:

- `build_player_site.py` skips archived slugs (`--squad` to name them, `--include-archived` to override)
- `attack_cards.py` builds for live squads only
- `export_matchup_store.py --squad` takes its roster from `squads.json`, and **refuses** when every
  squad is archived rather than falling back to the registry
- `build_squad.py` refuses to write to an archived slug — *before* it spends a warehouse round trip
  per name — because a new series wants a new slug

**Archiving the site is not archiving the squad, and the site went first.** CA XI's packs went
offline 2026-08-10 and its 14 names drove the store for another eleven days. Take both.

Archived so far: **`bangladesh-home-2026`** (2026-08-31) · **`bangladesh-caxi-2026`** (2026-08-10,
folded in from the retired `squads_caxi.json`).

### Adding ONE player to an existing squad — still by hand

`build_squad.py` resolves a *whole* squad from a name list, so it is the tool for a **new** series,
not for adding a name to a live one. To add one player, edit the two files:

- **`squads.json`** — append the id to that slug's `players` list.
- **`players.json`** — only if they are new. A player can already be here from another squad
  (Renshaw was, from the CA XI work) and need nothing but the roster line.

Then re-run the pipeline below from `publish_site.py`. No warehouse rebuild is needed — nothing about
the opposition changed.

**`build_squad.py` is now safe to run for a new squad** (it was not before 2026-08-31): it snapshots
both files, **merges** into the registry instead of replacing entries — only `name`/`role`/`packs`
are derived, so `bowl_types`, `bowl_groups`, `new_ball_footage`, `similar_bowler`, `release_detail`
and `prefs` survive and it prints what it kept — and carries `team`/`archived` across a re-resolve.
Verified: re-resolving Renshaw into a new squad keeps his `bowl_groups`, leaves the other 29 registry
entries byte-identical, and leaves both archived flags alone.

⚠ **`role` IS still overwritten**, because it is derived from the warehouse. `packs` was too, and
that is fixed (2026-09-01): a player whose registry entry has hand-set `bowl_types` keeps
`"bowling"` even when the career ratio calls them a batter, and any pack already in the registry is
carried across. Renshaw was the case — derived `["batting"]`, kept `["batting","bowling"]` — and
losing it would have dropped him from `export_matchup_store`'s `our_bowl` while `bowl_types` kept
building his bowling page. The script prints every such `!` note.

**Name resolution matches the FIRST NAME, not just the surname** (fixed 2026-09-01). It used to
take whichever surname match had the most career balls, which on the Zimbabwe ODI squad silently
returned **Shaun** Marsh for Mitch Marsh, **Mitchell** Johnson for Spencer Johnson and **Alex**
Davies for Joel Davies — three of fifteen. Nothing in the output revealed it because only the
*input* name was printed back. It now scores exact > prefix (Mitch→Mitchell, Matt→Matthew), prints
the **warehouse** name in its own column, and flags both surname-only matches (Ollie→Oliver, no
first-name signal) and any alternate it could plausibly have picked. Always read that column.

`--format Test|ODI|T20I` records what the squad was picked for; nothing in `series.json` carries
format, so it cannot be inferred and defaults to Test.

### The field that fails silently: `bowl_groups`

`_our_bowl_groups()` types each of our bowlers from the **matchup store's `they_bat` rows**. A
part-time bowler has no sim profile, so they are not in those rows and the store cannot type them.
Without `bowl_groups` in `players.json` their pack still builds — it just links the **combined
overview** batter reports and the macro pace/spin plans instead of their own type's. The page looks
complete while serving plans built mostly from other bowling types, which is the same pooling defect
the reel-scoping rule exists to prevent.

So for any of our bowlers the store can't type, name the group explicitly:

```json
"2480059": {
  "name": "Matt Renshaw", "role": "Batter",
  "packs": ["batting", "bowling"],
  "bowl_types": ["spin"],
  "bowl_groups": {"spin": "off_spin"}
}
```

Verify it on the **built page**, not the config — the link targets are the tell:

```bash
grep -o "_batting_test_[a-z]*_vs_[a-z_]*\.pmode" player_site/matt-renshaw-bowling-spin.html | sort | uniq -c
```

It should match a known-good pack of the same type (Renshaw's off-spin links are identical to Lyon's).
A page with **no** `_vs_` links at all is the silent fallback.

Three smaller things worth knowing:

- **`bowl_types` creates the bowling page, not `role` or `packs`.** `build()` reads only `bowl_types`
  to decide which pages to write. `role` controls the roster grouping heading, `packs` is effectively
  documentation. A specialist bat who bowls a bit can stay `role: "Batter"` and still get both packs.
- **The batter's hand comes from the matchup store's `we_bat` rows**, so a player missing there
  defaults to `rhb` and their batting pack links the wrong hand's bowler reports. Check they're
  present before building — the hand audit will catch it at the publish gate either way.
- **Their attack card and h2h footage come from the matchup store too**, not from `squads.json`, so
  both are usually already built. `build_h2h.py` reads `we_bat` / `they_bat`, never the roster.

## The pack pipeline, in order — and the step that isn't obvious

```
build_batting_reports.py / build_reports.py   render into reports/
publish_site.py --out site                    bake into the coach-site group folders
inject_reports.py                             bake into site/<series>/batters/   <-- REQUIRED
build_player_site.py --out player_site        the packs
publish_packs.py aus                          assemble -> link check -> hand audit -> push
```

**For a white-ball series, everything upstream takes `--fmt` and the opposition data comes first.**
The full chain, in dependency order (Zimbabwe ODI as the worked example):

```
matchupmodel/scripts/build_batter_response.py  --fmt ODI      profile CSVs, once per format
matchupmodel/scripts/build_bowler_delivery.py  --fmt ODI      (Test keeps unsuffixed filenames)
matchupmodel/data/opp_squad_zimbabwe.json                     pin the opposition XV by hand
matchupmodel/scripts/export_matchup_store.py --opp Zimbabwe --fmt ODI --squad <our slug>
build_opponent_about.py --opp zimbabwe --fmt ODI              ~40 min, the long pole
build_overview.py       --opp zimbabwe --fmt ODI --group …    once per bowler group
build_h2h.py            --opp zimbabwe --fmt ODI              format order follows the PACK
build_shot_matrix.py    --opp zimbabwe --fmt ODI
build_batting_reports.py --fmt ODI --ids <opposition batters>
build_reports.py --format ODI --ids <opposition bowlers>
render_matchups.py --opp zimbabwe
… then publish_site -> inject_reports -> build_player_site -> publish_packs as above
```

`build_conditions.py` is **skipped for white-ball**: it scopes correctly with `--fmt` but still
measures against `REF_CONDITIONS` = NZ/SA/ENG, the SENA-away seam-and-bounce benchmark, which is a
Test idea. Pick a white-ball reference set before using it.

**Suggested Fields are omitted from non-Test packs** and `build_overview` prints why. The ODI stock
fields and out-of-circle limits exist in `cricket_core.fields`, but `field_engine`'s tactics are
red-ball. See `ODI_PACKS_PLAN.md` Layer 3.

`inject_reports.py` exists because `_scouting_urls` links `scouting/<series>/batters/<base>.pmode.html`
and **no series.json group produces that folder**. It had been filled by a script outside the repo,
so a plain `publish_site.py --out site` wiped it and the next assemble produced a bundle full of dead
links (2026-08-10). Same lesson as the scratchpad assemblers: **a pipeline step that isn't in the repo
isn't part of the pipeline.** The scheduled "Scouting Reports Refresh" task runs `publish_site`, so it
wipes that folder every few days — re-run `inject_reports.py` before assembling.

`build_player_site.py` **clears `player_site/` before writing**, so an interrupted build leaves an
empty directory. Never publish a partial build; re-run it.

**A stalled file count is NOT the wedged signal — it's the normal shape of this build.** It writes
the photos and the roster index in the first minute (~154 files), then resolves clips for tens of
minutes writing *nothing*, then emits the ~34 player pages at the end. Measured 2026-08-21: flat at
154 files from 09:17 to 09:35, then complete. Judge it by **CPU accumulating** instead — that run
climbed 20s → 29s → 39s while the file count sat still. A wedged run is CPU flat as well, over tens
of minutes. It has hung with the warehouse perfectly reachable, so a stall is not proof of a VPN drop.

### Run a batch UNBUFFERED, or you cannot tell working from wedged

`python … | grep -v WARNING` block-buffers stdout, so a batch that prints one line per report shows
**nothing at all** until ~8 KB accumulates. Combined with the note above, that is a trap: an empty
log reads as "quiet phase, still working" when it may be a dead process.

It cost 45 minutes on 2026-09-02. A `build_reports` batch hung on a Chrome print — python at 4.1 s
of CPU after 45 minutes, Chrome up and idle, **zero** reports written — while the log showed only
the header line. The tell was file **mtimes**: the newest PDF was still from the previous evening.

- Run batches as `python -u …` **with no pipe**. The harness captures output either way, and `-u`
  plus no pipe means one visible line per report.
- Judge a suspected stall by **CPU accumulating** and **output-file mtimes**, never by log silence.
- Chrome hanging mid-print is a real failure mode with no timeout around it. Killing the task
  cleans up its Chrome processes; a single re-render then works (Raza: 73 s end to end), so a wedge
  is usually transient rather than a code fault — check before you go looking for a bug.
- For a long batch, put a watchdog on it (`Monitor` with a stall check) rather than reading silence
  as progress.

## Archiving a finished series

Two halves, because the two sites fail differently. The **coach portal** rebuilds itself from
nothing every refresh, so a finished series either keeps being rebuilt forever or gets frozen. The
**player-facing pack site** is a normal repo, so archiving it is a tag and a switch.

### The coach half — freeze it into the portal

```powershell
.\venv\Scripts\python.exe archive_series.py freeze bangladesh-home-2026
.\venv\Scripts\python.exe archive_series.py list
.\venv\Scripts\python.exe archive_series.py restore bangladesh-home-2026   # bring it back live
.\venv\Scripts\python.exe deploy_scouting.py --repo https://github.com/tbcricketau/scouting-reports.git
```

`freeze` copies the **built** pages from `site/<slug>` to `archive/<slug>`, stores the series.json
entry inside the copy, and lifts the entry out of `series.json`. `publish_site.build()` then stages
`archive/` into the portal at `archive/<slug>/`, behind the same password, reachable from one
**Archive** card on the index rather than as a peer of the current series. It copies, never moves,
and snapshots `series.json` first.

**Why freezing is necessary at all:** `build()` clears its output directory except `.git` and
re-bakes only what `series.json` lists ([publish_site.py:177]), and `deploy_github` force-pushes,
which discards the repo's history. Nothing survives on its own, and nothing hand-placed in
`scouting-reports` survives the scheduled refresh either — same lesson as `inject_reports.py`.

**Why an archive can't just be left alone:** clip URLs carry a read SAS baked into the HTML with a
~6.5-day life (`DEFAULT_SAS_HOURS`). A frozen page is a page whose vision dies within the week.
`restamp_sas()` rewrites the query string on every blob URL under the staged copy and touches
nothing else — no warehouse, no blob probing, no re-derivation — so the pages stay exactly as baked
while the footage keeps playing. It keys on the **container** (`fairplay` / `hawkeyeupload`), not
the storage account, so it needs no private `cricket_core` constants. Verified on the Bangladesh
archive: 5,286 URLs re-stamped across 127 pages, and every page byte-identical once the SAS is
stripped from both sides.

`restore` puts the entry back in `series.json` and leaves the frozen copy alone. The reports must
still be in `reports/` for the next build to bake them — that is what makes a restore possible, and
it is the thing to check before deleting anything.

Archiving adds **no new link-check findings** — the Bangladesh freeze measured 0 errors and the same
33 pre-existing orphan warnings as the live site (the `.pmode.html` player-mode pages, which only
the packs link). Once the pack site is offline those copies in the archive are the only surviving
player-mode pages, so keep them.

### The pack half — tag, note, Pages off

1. `git -C player_pack_site tag -a archived-<date> -F <msg file>` and push the tag.
2. Add an `archived` note to the bundle's entry in `publish_packs.py` — publishing then exits with
   that message unless given `--revive`.
3. **Tom disables GitHub Pages** on the bundle repo (Settings → Pages → source None). Repo and
   history stay intact.

Say in the note what the archive does *not* carry. Both archived bundles have a dead SAS baked in,
so reviving means rebuilding from source, never re-pushing the tag.

### Archived so far

- **AUS player packs — 2026-08-31.** Bangladesh home Tests. Pages off on `tbcricketau/player-packs`,
  tag `archived-2026-08-31`. Coach-side copy frozen at `archive/bangladesh-home-2026` and still
  served, gated, with live vision. The bundle's own SAS expired 2026-08-27.
- **CA XI packs — 2026-08-10.** Pages off on `tbcricketau/caxi-player-packs`, tag
  `archived-2026-08-10`. **These predate the 2026-08-10 fixes** — wrong-hand bowler reels and
  pooled-spin batter reels — so reviving means rebuilding from source.

**Archiving the site is not archiving the squad.** It never has been: CA XI went offline on
2026-08-10 and its 14 names were still driving `export_matchup_store.py` eleven days later, at 217
simulated pairings for a 98-pairing squad. `freeze` removes the series from `series.json` only —
`players.json`, `squads.json` and the matchup store still carry the squad. Front 1 of
`PACK_MAINTENANCE_PLAN.md` is the real fix; until then, check those three by hand before building a
new opposition.

## `pitch_length` is NOT NULL even when nothing was tracked — it carries `-20000`

This is the most dangerous data fact in the project, because the obvious guard does nothing.
`r.get("pitch_length_m") is not None` reads like a coverage check and **passes every ball**: an
untracked delivery is stamped with the sentinel `-20000` mm (`-20.0` m), not NULL.

Coverage is not a rounding error, and it varies by **where the match was played**:

| venue | usable pitch_length | ball speed |
|---|---|---|
| Australia | 99.9% | 17.8% |
| Sri Lanka / South Africa / NZ / WI | 99.5–100% | varies |
| England · India · Bangladesh | 95–97% | — |
| **Zimbabwe** | **46% ODI · 33% Test** | **4.8%** |
| Ireland · Netherlands · Scotland | 40.6% · 0.1% · 0% | 0% |

**A median does not fence out a sentinel.** That was the defence in both `profile.py` and
`odi_profile.py` ("bad lengths wreck the mean") and it only holds while the bad values are a
minority. Sentinels sort first, so the median lands at roughly the *(50 − untracked%) / tracked%*
percentile of the real lengths — biased low in proportion to the untracked share, and outright
`-20.00 m` past 50%. Measured: Raza (55.5% tracked) printed **3.50 m** when the truth was 6.50 m,
Ngarava (44.4%) printed **-20.00 m**, Bosch (45.8%) printed **-20.00 m on a live Test report**,
Henry (94.3%) was quietly 0.14 m low, Lyon (100%) was correct. The visibly broken ones were the
lucky cases — the plausible-looking wrong numbers are the problem.

**Use `cricket_core.charts.is_tracked_length` (one definition, estate-wide) before averaging.**
`profile.tracked_lengths(rows)` is the list helper. Both `avg_len_m` builders now also return
`tracked_len_pct`, and `report_style._length_sub` prints "tracked on N% of balls" under the Avg
length card below 80% — a length built on 46% of deliveries has to say so.

**Charts that bin into zones were already safe** (`pitch_scatter_map`, `danger_length/line/cell`,
`zone_concentration`, `pitch_heatmap`): a sentinel falls outside every zone and is dropped by the
`if ez is None: continue`. Anything that **averages, medians or thresholds** was not.

**The threshold case is the one that reached a coach.** `build_odi_playlists` selected yorkers with
`pitch_length_m is not None and < 2.0` — and `-20.0 < 2.0`. Ngarava's pack served **eight
"yorkers", all eight confirmed `-20000`**, six of them bowled in overs 1.1–5.6. With the fix he has
*no* yorker reel, which is the honest answer. When auditing, grep for comparisons against a length,
not just for `is not None`.

### 🔴 And the warehouse's own length GROUPS carry it too — this one reaches the simulation

The worst instance, because it defeats the defence above. `pitch_length_group_pace_2_id` /
`..._spin_2_id` are the warehouse's pre-bucketed zones, so code that bins by them looks safe from a
bad coordinate. **It isn't: an untracked ball still gets a group, and it is always the fullest
one** — pace `12999` "full/yorker", spin `10999` "full toss". Every other bucket is 0.0% untracked;
these are 47.5% (Test pace), 56.2% (ODI pace), 79.6% (Test spin) and **90.6% (ODI spin)**.

matchupmodel's zone grids bin on exactly those columns, so its fullest zone was mostly deliveries
nobody measured — a "danger: full toss" plan largely fabricated. Fixed by `config.ZONE_TRACKED_SQL`
in both `build_batter_response.py` and `build_bowler_delivery.py`.

🔴 **The Test profile CSVs still carry it and are live** — the Bangladesh packs and the SA/NZ
reports were produced from contaminated grids. Rebuilding them moves signed-off numbers, so it is
a deliberate decision, not a side effect. See `ODI_PACKS_PLAN.md`.

**The general rule:** a pre-bucketed category is not evidence that a measurement exists. Filter on
the underlying coordinate before trusting any zone, group or band derived from it.

## White-ball reports, and the format-aware publish path

`build_reports.py --format Test|ODI|T20I` is the one batch driver for all three (it dispatches to
`render_report` / `render_odi_report` / `render_t20_report`). `--hand` applies to **Test only** —
the ODI and T20 reports carry both hands in their match-ups table and render one PDF per bowler.
Failed ids are printed at the end for a straight retry, which matters because a VPN drop kills a
whole batch.

```powershell
.\venv\Scripts\python.exe build_reports.py --format ODI --target-country Zimbabwe --ids 1310087 4352462
```

**A series.json group carries `"format"`, defaulting to Test**, so every pre-existing entry
resolves exactly as before. `publish_site._sidecar_map()` keys on
`(player_id, hand, kind, bowl_group, fmt)` and scans `reports/`, `reports/odi/` and `reports/t20/`
— white-ball builders write to their own subfolders, so a scan of `reports/` alone could not see
them, and their filenames have no `_(all|lhb|rhb)` suffix for the old regex to match.

⚠ **Format comes from the DIRECTORY, never from `meta.format`.** `t20_report` shares
`build_odi_playlists`, which hardcoded `"format": "ODI"` — so every T20 sidecar claimed to be an
ODI one. Keying off that field filed Starc's *T20* report as his *ODI* one and silently overwrote
the real entry. The stamp is now a parameter and is correct, but the directory is what the builder
actually chose and is the only thing that cannot lie.

**The attack section is skipped for a non-Test squad.** `attack_cards.py` derives "how bowlers have
attacked our squad" from **Test** deliveries. Rendering it under an ODI series would put Test plans
on an ODI page for whatever fraction of the roster happens to have a card — the pooling defect
again — so `publish_site` skips it with a printed reason when the squad's `format` isn't Test.

### What is NOT yet format-aware — the batting half

The bowler reports are done. **The batting half is still hardwired to Test**, so there are no ODI
*player packs* yet: `batting_loaders.py` has no `fmt` parameter at all (`_intl_test()`,
`load_test_batters`), and `batter_profile`, `build_opponent_about`, `build_overview`,
`build_shot_matrix`, `build_conditions` and `field_engine` (`_FMT = "test"`) all pin
`international_series_sql('Test')`. `build_h2h.py` is already format-flexible (it picks the best
available format per pairing) and the clip resolver walks Test → ODI → T20I.

ODI phases (powerplay / middle / death) and ODI field norms are new work, not a parameter.

## Known gaps / pending work

- Zone label ordering (`PACE_LINE_ORDER`, `SPIN_LINE_ORDER`) uses assumed strings — verify against actual DB lookup values if cells appear out of order
- The warehouse spells Blessing **Muzarabani** as "Muzaurabani", and report titles use the feed's
  name — a name-override store would be new machinery, so it is currently just wrong on the page
- Opposition headshots fall back to initials (the shared store sources cricket.com.au, which has no
  Zimbabwe players) — 5 of 9 Zimbabwe bowlers resolved, the rest show initials by design

## Player photos (2026-07-15 — shared `cricket_core.headshots`)

Headshots live in the **estate-wide store** `cricket-core/headshots/` via `cricket_core.headshots`
(cricket.com.au source, format-aware kit variants, auto-resolve by name, page-scan for the newest
ids — full pipeline in that module's docstring; the old SharePoint/Graph backend is retired).
This project's `photos.py` wraps it, checking the local `photos/` folder FIRST (hand-collected
opposition photos + per-player overrides). **Report builders pass `name=` so a brand-new player's
headshot fetches itself at render time.** Bulk tooling for a new squad: `fetch_photos.py`
(`--resolve` · `--scan-new` · `--force`).
