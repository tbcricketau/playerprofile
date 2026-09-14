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

⚠ **Until 2026-09-11 `--deep` could not pass a Fairplay bundle at all.** Its URL regex left the
`?sas` query string outside the capture group, so it HEADed every clip with the token stripped off,
which storage refuses whether the token is fresh or expired. It refused the Zimbabwe packs twice with a
token that served 200 when probed directly. Fixed and proven both ways: the re-stamped bundle passes,
the page as published on 09-03 fails with six 403s. Error lines now print the status code and never the
token. **To refresh an expired SAS without rebuilding**, re-stamp the bundle with
`archive_series.restamp_sas` and publish with `publish_packs.py <bundle> --no-assemble --deep`. No
builder runs, so no reel can move.

`publish_site.deploy_github()` runs the same check before the coach site goes out.

### Bake only the series you named — `--only` (2026-09-13)

`build()` cleared its whole output and re-baked every series in `series.json`, which is right for
the scheduled refresh and wrong for everything else: producing the nine Zimbabwe report pages the
packs link cost **93.7 minutes**, re-baking five untouched series and re-staging a 102 MB archive
with 5,286 SAS re-stamps.

```powershell
.\venv\Scripts\python.exe publish_site.py --out site --only zimbabwe-odi-away-2026
.\venv\Scripts\python.exe publish_site.py --out site --no-archive        # full bake, skip the archive
```

`--only` clears **just the named series' directories** and leaves every other series, the archive
and their index cards alone; it implies `--no-archive`. Measured on `australia-reference`:
**93.7 min → 18.2**, with every other series byte-identical in file count and mtime, the archive
untouched at 218 files, and Zimbabwe's 57 injected batter reports surviving — which a full bake
destroys. Default behaviour with no flag is unchanged, so the scheduled task is unaffected.

The cost is **~109s per report** with only ~2 min of fixed startup (`_sidecar_map` is 7s of it), so
the saving is proportional to reports skipped, not to overhead avoided. `_existing_card` keeps
un-rebuilt series on the landing page by counting report **stems** — counting `.html` files read
New Zealand as 32 reports when it has 16, because `.html` and `.player.html` both matched.

⚠ **`deploy_scouting.py` cannot reach these flags**: it calls `build(site, sas_hours)`
positionally, so an unflagged run is a full bake. Use `--no-build` to deploy the `site/` you just
baked — safe while the baked SAS is inside its ~6.5-day life, which is the thing to check first.

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

### Death overs are a reel too (2026-09-13) — and a new reel KIND means FOUR places

Tom asked for footage of who bowls the last ten overs. `bowler_clips_from_profile` takes
`death_from` and selects `over_n >= 41` — **`odi_profile._phase`'s own threshold**, so the pack
button and the report's `death` playlist pick the same balls rather than two definitions of
"death". Hand-scoped `dthL_`/`dthR_` like every other bowler reel: the ball a bowler goes to at the
death against a left-hander is not the one they go to against a right-hander.

- **Passed DOWN, never assumed.** Over 41 cannot occur in a T20 (20-over innings) and is simply
  mid-innings in a Test. Only a 50-over pack sets the threshold; everything else gets `None`.
- **No share gate.** `NEW_BALL_MIN_SHARE = 45` is right for the new ball and would delete every
  death bowler: the real ones sit at 8–17% of their deliveries (Muzarabani 17.3%, Evans 15.7%,
  Raza 13.2% — and Raza bowls the MOST death balls of anyone in that squad, 466). Having playable
  death footage is the gate.
- **`bowler_clips_from_profile` now returns FOUR reels.** Every caller unpacks it positionally and
  there are four such sites — `bowler_clips_best`, the `--clips-only` path, the main bowler loop,
  and `_store_hand_reels`. A capped grep found two of them and the run died on
  `ValueError: too many values to unpack`. Its docstring now says so.

**The fourth place is `audit_pack_hands`, and it is the one that matters.** That file has TWO
regexes: `KEY_RE` decides what is **collected**, the classifier decides what each key *is*. A kind
missing from `KEY_RE` is never collected, never audited, and publishes in silence — the "a gate
only checks what it was built to check" failure this project keeps rediscovering. Both were
changed together, and it was proven afterwards rather than assumed: the gate's own `KEY_RE` finds
312 keys on the built packs (120 stock + 120 wkt + 72 dth), matching the 312 it reported.

### The rule behind it: a reel is scoped to whatever the pack is about

Both pack types serve footage, and each has an axis it must be scoped on. Get one right and the
other wrong and the pack looks fine while showing the wrong player entirely. Three separate reports
in one day, all the same defect on a different axis:

| Pack | Reel | Must be scoped to |
|------|------|-------------------|
| Bowling pack (our bowler) | opposition batter's scoring / dismissal clips | the **exact bowler type** the pack's bowler bowls |
| Batting pack (our batter) | opposition bowler's stock / wicket / new-ball clips | **our batter's hand** |
| Either, white-ball | every reel | the pack's **FORMAT** — red-ball footage never belongs in a white-ball pack |

**The format axis, added 2026-09-02, and it was 203 for 203.** `bowler_clips_by_hand` called
`load_bowler_deliveries(bid)` with no `fmt`, so it took the Test default: every hand-scoped reel in
the Zimbabwe ODI packs was red-ball footage, and the packs were published three times that way.
`audit_pack_hands` reported them **clean** each time, because it resolves whose *hand* a clip is
bowled to and format was never something it looked at — the audit now resolves the clip's series
too and `publish_packs` refuses on an off-format reel.

Borrowing the *neighbouring white-ball* format is deliberate and still allowed: `build_opponent_about`
steps ODI → T20I → T20 when a bowler's record in the pack's own format leaves both hands with
nothing, and records `clip_format` so the card can say so. A T20I clip in an ODI pack is worth
watching. A Test one is not.

The batting-pack half went unnoticed from `a067e44` until 2026-08-10: the reels were built from
`build_profile(bid, hand="All")`, so Steve Smith's pack showed Ebadot Hossain bowling to Ben Curran.
`bowler_clips_by_hand()` now builds all three (both hands, to LHB, to RHB) off one delivery load.

**No pooled fallback on the batting packs — but a DECLARED other-hand one (2026-09-11).** Ebadot has
10 wicket clips to left-handers and none of them resolve to a playable blob. Falling back to the
pooled reel served a left-hander's pack 40 wicket balls that were all to right-handers, unlabelled,
and that stays forbidden. What replaced "omit the button" is a stated fallback, which Tom asked for
on the Zimbabwe packs: "even if we have to use RHB vision for LHB, we just need to state it".

### A reel is built from clips that PLAY, and falls back in a fixed, labelled order

A `video_file_name` is not footage. The warehouse names a clip for every coded ball whether or not
Fairplay stored one, and Zimbabwe's record is mostly unclipped — almost nothing before 2022-23, and
two of the three Bangladesh ODIs in July 2026. Taking the newest N named balls filled reels with dead
clips, the bake dropped them, and the buttons vanished: Wellington Masakadza had no vision in any pack
while 127 T20I balls of him bowling to left-handers played. `build_opponent_about._plays` now
HEAD-probes each stem (16 at a time, skipping a match after 3 misses and no hit), and each hand's
stock and wicket reel falls back in this order:

1. the pack's format, clips that play
2. a neighbouring format on the SAME side of red/white (ODI ↔ T20I) — starred and footnoted
3. stock only: **"Recent bowling"**, the latest playable deliveries to that hand, when the footage that
   plays is untracked and no stock ball can be identified (Tanaka Chivanga, Wesley Madhevere)
4. the **other hand's** reel — playlist key `stockXR_` / `wktXL_`, button "… — to right-handers",
   footnoted

`audit_pack_hands` holds an `X` reel to the hand it DECLARES (and fails it if that is the pack's own
hand), and every other reel to the pack's hand as before. The entry keys are
`clip_format_{kind}_{hand}`, `clip_hand_{kind}_{hand}` and `clip_general_{kind}_{hand}`, written by
`_store_hand_reels`. The old whole-bowler `clip_format` stamp is no longer written — it starred every
button whatever format each came from.

Probing means `build_opponent_about` needs Fairplay access (`PROBE_CLIPS = False` turns it off). The
all-formats fallback branch for **batters** now builds clips as well: it wrote facts only, so Brad
Evans had no batting vision in any of the eleven bowling packs.

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

### The batting half is format-aware too (2026-09-02)

`batting_loaders`, `batter_profile`, `build_opponent_about`, `build_overview` and
`build_shot_matrix` all take `fmt`. `build_h2h.py` picks the best available format per pairing and
the clip resolver walks the pack's format first. Still Test-pinned: **`field_engine`** (`_FMT =
"test"`, so Suggested Fields are omitted from non-Test packs) and **`build_conditions.py`** (it
measures against `REF_CONDITIONS` = NZ/SA/ENG, a SENA-away Test idea).

ODI phases (powerplay / middle / death) and ODI field norms are new work, not a parameter.

## LEVEL is a second axis, and it is not FORMAT (2026-09-04)

A four-day Australia A match is **Test-format cricket at a-team level**. Format is the shape of the
game — four innings, red ball, the report layout and kit. Level is its standard — which series
count as a player's record. Everything scoped by format alone until now because the two always
moved together: an "International Tests M" match is Test-format *and* senior.

```python
from cricket_core.config import series_sql          # series_sql(fmt, level)
series_sql("Test")                # ('International Tests M')
series_sql("Test", "a-team")      # ('International 1st Class M', 'International Tour Matches M')
series_sql("ODI",  "a-team")      # ('International List A ODI M')
```

`level="international"` is the default in every signature, so **every pre-existing series resolves
byte for byte as before** — verified against the shipped CSVs and the Zimbabwe pack's links.
`international_series_sql(fmt)` is retained as the senior case. There is no men's A-team T20 bucket
in the warehouse, so `series_sql("T20I", "a-team")` **raises** rather than serving the women's
`International List A T20 F`.

Threaded through: `data_loaders._scope`, `batting_loaders`, `profile`, `odi_profile`,
`batter_profile`, `build_opponent_about`, `build_overview`, `build_shot_matrix`, `build_h2h`,
`build_reports`, `build_batting_reports`, `publish_site`, `build_player_site`, `audit_pack_hands`,
and matchupmodel's `format_filter` / `profile_csv` / both profile builders / `export_matchup_store`.

Design, measurements and what is still open: **`A_TEAM_LEVEL_PLAN.md`**.

## SOURCE is a third axis — where the ball record comes from (2026-09-07)

```
format   the shape of the game        Test / ODI / T20I / T20
level    the standard of the game     international / a-team
source   where the record comes from  warehouse / c21 / both
```

All three are orthogonal and all three default to the old behaviour, so nothing existing moves.

`source` exists because **the warehouse holds no Indian domestic cricket at all** — no Ranji, no
Duleep, no Vijay Hazare, only the IPL. An India A bowler's record there is a few hundred balls at
38% tracking; Cricket-21 has thousands at 98% with video on every one. `c21_source.py` reads the
C21 mirror and returns rows in the **warehouse row shape** — same column names, same string
conventions, `"None"` for what C21 lacks — so no consumer can tell where a row came from.

```powershell
.\venv\Scripts\python.exe build_c21_player_map.py            # warehouse ids <-> C21 ids, once
.\venv\Scripts\python.exe build_opponent_about.py --opp india_a_4day --fmt Test --level a-team --source both
.\venv\Scripts\python.exe build_overview.py --opp india_a_4day --fmt Test --level a-team --source both --group right_pace
```

Measured on the four-day pack: batters with a plan went **3 of 6 to 5 of 6**, Mokhade 64 → 538
balls, Rasheed 202 → 523, Nabi's bowling 30 tracked balls → 1,132. Survey and limits:
`cricket21/docs/INDIA_DOMESTIC.md`, design in `A_TEAM_LEVEL_PLAN.md`.

**The coordinates are safe to pool, and that was checked rather than assumed.** C21's raw line axis
correlates with the warehouse at r = −0.14 because the two mirror left-handers differently — the
classic way to publish a plan that is right for one hand and backwards for the other.
`cricket21/calibrate.py` fits the transform per hand (opposite slopes, which IS the mirroring) and
an independent check on 2026-09-07 found the distributions agree: RHB median 344 (warehouse) vs 337
(C21), LHB 172 vs 188.

**A gate must count the SAME source it builds from.** `_test_balls` decides full profile against the
thin all-formats fallback. Counting the warehouse while building from `both` sent every player whose
record is only in C21 down the fallback — which is warehouse-only too, found nothing, and skipped
them silently. Aman Mokhade and Ayush Pandey have no warehouse record at all.

**Four things that break a C21 join — all found 2026-09-12, re-pinning India A:**

- **A C21 player id belongs to ONE database.** Multi-day and white-ball number players
  independently: 6314 is Devdutt Padikkal in white-ball and Imran Qayyum in multi-day.
  `c21_player_map.json` carries `c21_ids_multiday` / `c21_ids_white`, and `c21_source._rows` takes
  the list for the database the format's matches come from. The old mixed `c21_ids` is only a
  fallback for entries not yet split. Resolve per database, on date of birth, never on name alone.
- **C21 holds duplicate records of one person** (Ayush Pandey three, Yash Rathod two, V Vyshak two,
  same date of birth). Map all of them.
- **A match can be in BOTH sources.** India A's unofficial Tests in Sri Lanka are in the warehouse
  (0% tracked) and the mirror (98%), and `source="both"` simply concatenated them — eight players'
  balls counted twice in the four-day pack published 2026-09-07 (Sudharsan 484 → 968).
  `c21_source.merge_with_warehouse` keys on the player's match date and keeps the fuller copy,
  C21 on a tie. Outcome numbers (runs, dismissals, BPD) moved when it landed. Lengths and lines did
  not, because the duplicate warehouse copy was untracked.
- **A player with no warehouse record at all gets a RESERVED id**, `99` + their C21 multi-day id —
  Yash Rathod `990010366`, Nachiket Bhute `990020028` — mapped by hand in `c21_player_map.json`.
  Warehouse queries return nothing for it and every C21 path works. `load_batter_info` /
  `load_bowler_info` fall back to the map for the name. Without that the report was titled
  "Batter 990010366".

**What C21 does not give:** ball speed in Ranji (0.2% — pace cards get lengths and lines but no
speed), seam/swing movement, bowler spell. The zone GROUP columns are deliberately left `None`
rather than synthesised: those are the columns that stamp an untracked ball "full toss".

### A flag that is accepted and discarded is worse than one that is missing (2026-09-13)

`build_reports` has taken `--source` since the axis landed and **passed it only on the Test
branch**. The ODI branch called `render_odi_report(...)` without it, which took no such parameter,
so every white-ball report has been warehouse-only while reporting success. Ernest Masuku rendered
on 66 warehouse balls with 7 clips while 196 Cricket-21 balls with video on 190 sat unused; with
the fix, 180 legal balls and 34 clips, and he gains death, yorker and bouncer reels he had none of.

Threaded `render_odi_report` → `build_odi_profile` → the loaders **and `_supplement_rows`**. Fixing
only the first leaves the mechanics supplement warehouse-only, so a bowler thin in the warehouse
would read C21 for his ODI rows and then silently fall back to warehouse-only T20I to map his
lengths. 🔴 **`render_t20_report` still has this gap** and takes neither `source` nor `level`.

**A bowler with nothing to say can still have something to show.** `allfmt_bowler_facts` reads the
warehouse alone and needs 150 rows, so a bowler under `TEST_FLOOR` whose cricket is only in C21 was
dropped from the packs entirely. The batter branch was fixed for exactly this (Shams Mulani); the
bowler branch never was. It now keeps a **footage-only** entry and deletes it, with a log line, only
when nothing plays either. Masuku went from absent in all 15 packs to a card with 45 hand-scoped
reels including 30 death clips, carrying *"Limited ODI record — not enough balls to profile"*
instead of a fabricated plan: he genuinely fails the 300-ball floor at 262.

**So a squad pin whose players are C21-only must say `--source both` in its note.** Tripurana Vijay
has 12 warehouse bowling balls and 348 in C21; without the flag he is a footage-only card, with it
he is a full profile. `opp_squad_india_a_4day.json` records that requirement where the next person
will look.

### A clip is a STEM or a URL — never assume the stem

Fairplay clips are stored extension-less and resolved with a fresh read SAS at bake time, so they
travel as a `clip_stem`. **Cricket-21 serves its own footage** from a complete, unauthenticated
`hdvod.cricket-21.com` URL: nothing to resolve, no SAS to mint, and re-stamping it would corrupt it.
A playlist entry therefore carries **one or the other** — `c21_source.clip_ref(row, stem)` decides,
and a Fairplay stem always wins where both exist, so a warehouse delivery is never displaced.

Anything that reads a clip must accept both. Four places assumed the stem, and three of them threw
the footage away without a word:

- `cricket_core.resolve_playlist` overwrote `url` from the stem and DROPPED whatever would not
  resolve — a source with a clip on every ball produced empty reels.
- `build_player_site` filtered six call sites on `clip_stem` (now `_clip_item` / `_playable`).
- `build_opponent_about._has_vid` asked only about `video_file_name`.
- **Two more, found 2026-09-12.** `batter_clips` queried the warehouse alone, so Ayush Pandey,
  Yash Rathod and Kumar Kushagra had no scoring or dismissal vision in any pack despite 500–700
  C21 first-class balls each. It now takes `source` and merges C21 rows by match date, at the
  pack's own format step only. And `playlists.py` filtered on `clip_stem` in three places, so the
  REPORTS' watch buttons carried no C21 footage either — Aman Mokhade's four-day batting report had
  one playlist clip, 32 after `_has_clip` / `_with_url`.
- 🔴 **`audit_pack_hands` could not see them at all.** An unresolvable clip is dropped from the
  reel's id list, so a reel made entirely of C21 footage would have looked **empty and passed as
  clean without ever being checked** — the "gate that only checks what it was built to check"
  failure once more. It now indexes url-bearing entries and resolves hand + red/white format from
  the mirror via `c21_source.delivery_facts`, selecting them **by provenance, never by id shape**
  (C21 ids are 6 digits, warehouse 16 — they cannot collide today, but that is an observation about
  two independent id spaces, not a guarantee).

**Probe before trusting a C21 clip URL.** The vendor path is *constructed*, not confirmed, and the
host answers a missing clip with a valid ~1.5 KB stub rather than a 404 — check the size, not the
status. Six sampled on 2026-09-07 returned 12–20 MB of `video/mp4`.

**C21 has its own sentinel.** An untracked ball has LengthY at or near 0, which the calibration
maps to a CLUSTER around its per-hand intercept — about **−1810 mm for a right-hander, −2195 for a
left-hander** (RHB −1810.2/−1798.0/−1785.9, LHB −2195.4/−2182.9/−2145.5), on **14.9% of right-hand
and 15.4% of left-hand deliveries**. Same trap as the warehouse's −20000, with no single value to
match on: use the RANGE. Never `is not None`, never an equality test.

### Where level has to be CARRIED, not just passed

- **`reports/ateam/`** — level lives in the PATH, like format. A player can hold both records
  (Anshul Kamboj: 366 A-team first-class balls, 108 Test) and the filename carries neither, so one
  render would silently overwrite the other. `_sidecar_map` keys on `(id, hand, kind, group, fmt,
  level)`.
- **A stepping fallback must skip what does not exist at the level.** `bowler_clips_best` /
  `batter_clips_best` step Test → ODI → T20I; at a-team the T20I step *raises*, and the raise killed
  the whole bowler rather than moving on — Saransh Jain and Anshul Kamboj vanished from the four-day
  file with only a `! bowler` line to show it.
- **…and it must not cross the red/white line to do it.** The first repair made the a-team order
  Test → ODI → **T20**, reasoning that the pooled league scope is where an uncapped Indian player's
  footage actually lives. It is — and T20 footage in a four-day pack is off-format, which is the
  thing the reel rule forbids. **The publish gate refused the bundle with 58 off-format reels across
  15 batting packs**, every one Kamboj or Ansari. The gate was right and the chain was wrong.
  `_fmt_order` now returns **(format, level) pairs**: a red-ball pack falls back on LEVEL — A-team
  first-class, then senior Tests — and never leaves red-ball; a white-ball pack moves among
  white-ball formats only. The international table keeps its historical chain, whose cross-colour
  steps have never fired in a shipped pack; if one ever does, this same gate stops it.
- **`build_h2h`'s format preference inverts.** An Australia A v India A four-day meeting classifies
  as `FC`, which the senior orders rank dead last — the pack for that very fixture would have
  preferred a senior Test meeting between two of the players over the game they played against each
  other.
- **`audit_pack_hands._series_fmt`** is a red-vs-white check, so A-team first-class cricket has to
  read as `Test`. It matched none of the tests and returned `''`, which the caller skips — a
  four-day pack could have carried a List A reel and passed as clean.
- **`inject_reports` bakes from the level's directory.** It resolves report NAMES through
  `_scouting_urls`, which is level-aware, but `_bake_report` defaults to `reports/` — so for an
  A-team squad every name resolved and every source was missing, and it injected **zero of 61**
  reports while printing a wall of "no source in reports/". The names being right is what makes this
  one look like a data problem rather than a path one.

### A-team first-class cricket is barely tracked — borrow the SHAPE, never the outcome

2026 A-team first-class cricket is **38.5% tracked**. Two of the seven India A bowlers have *zero*
tracked deliveries against 366 and 138 bowled, and no `--min-balls` threshold rescues a bowler with
nothing to threshold — they are simply absent from `bowler_delivery_*.csv`, and
`export_matchup_store` drops any bowler missing from it, so the pack shows an attack that is mostly
blank without anything failing.

```powershell
.\venv\Scripts\python.exe scripts\build_bowler_delivery.py --fmt Test --level a-team `
    --min-balls 100 --supplement test,t20
```

- **WHERE a bowler pitches it** may be read from another body of cricket, nearest format first.
- **OUTCOMES ARE NEVER SUPPLEMENTED.** `bowler_effectiveness` stays on the pack's own scope, so an
  IPL economy can never become an A-team wicket rate; a supplemented bowler simulates at the type
  baseline. Every row records its `source`, carried into the store as `shape_source`.
- `q_present()` asks who **bowls** in the scope at all, tracking not required — the zone grid can
  only see tracked bowlers, so a bowler with 366 untracked balls looked like one who does not exist.

Result: **6 of 7 profiled, up from 2.** Auqib Nabi (30 tracked A-team, 52 IPL) stays under
threshold and carries no plan, which is the honest answer.

### Two live squads against one opponent — three things that assumed there was only ever one

- **Opposition data keyed off `slug.split("-")[0]`.** `india-a-4day-2026` and `india-a-od-2026`
  both reduce to `india` and would have shared and overwritten one `matchup_store`, `h2h`,
  `opponent_about` and set of overviews. Use **`squads.opp_key(slug)`** — an explicit `opp_key` in
  squads.json, defaulting to the old derivation. `export_matchup_store --key` separates the data key
  from the warehouse team name and **refuses** when it does not match what playerprofile will read.
- **Batting reports carry their format in the FILENAME, not the folder** (`_batting_test_` /
  `_batting_odi_`, all in `reports/`). `_sidecar_map` took format from the directory — right for
  bowling reports, wrong for these — so a player's Test and ODI batting reports collided and the
  Test one won. It had never bitten because no two squads had shared a player across formats; these
  two share four (Gaikwad, Thakur, Kamboj, Badoni).
- **A multi-squad build nests packs under `players/<slug>/`, so `../scouting/` is one level short.**
  `_scouting_urls` takes `up=`. It also means adding a live squad silently re-homes every *other*
  live squad's packs — which is why Australia A builds into its own bundle (`ausa_player_site` →
  `ausa_player_pack_site` → `tbcricketau/australia-a-packs`) and Zimbabwe keeps naming its squad.

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
