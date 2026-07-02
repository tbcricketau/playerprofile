# playerprofile — Claude Guidelines

> Parent guidelines at `C:\Ludis\CLAUDE.md` apply (no pandas/numpy, Python via `py -3.12`, Opta light theme, etc.).

## What this project is

Opposition scouting app — player profiles for Test cricket. Currently covers **bowling only**; batting and fielding sections are planned as future additions. Named `playerprofile` (not `bowlerprofile`) deliberately to signal that intent.

**Run:** `.\venv\Scripts\python.exe run.py` — starts Streamlit on port 8060.

## File structure

| File | Purpose |
|------|---------|
| `app.py` | Main Streamlit app — team → bowler selector, full profile layout |
| `data_loaders.py` | Three `@st.cache_data(ttl=3600)` SQL queries (see below) |
| `charts.py` | Plotly helpers: `pitch_scatter_map`, `beehive`, `speed_violin`, `spell_bar`, `danger_zone`, `spell_summary_df` |
| `theme.py` | Opta light theme — call `apply_theme()` at top of app |
| `config.py` | `DATA_SCHEMA = "GA20260618"` |
| `sql_functions.py` | Copy of livematchdashboard's `sql_functions.py` |
| `run.py` | Launch shim |
| `photos/` | Drop `{bowler_id}.jpg` here for player photos; cricket emoji placeholder shown otherwise |

## Data loaders

All use `@st.cache_data(ttl=3600)` and return `list[dict]` with **all values as strings** (including `None` → the string `"None"`).

- **Scope = official international Tests only** — all loaders filter on `Matches.series_id → Series.name = "International Tests M"` (via `ludis_cricket.config.international_series_sql("Test")`), **not** `match_length_id` (which mixes Tests with Sheffield Shield and inflates tallies). Verified to reproduce official Test records.
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

- Same DB schema (`GA20260618`), same `sql_functions.py`, same `config.py` structure
- `livematchdashboard` is **match-centric** (one match at a time); `playerprofile` is **player-centric** (career Test data for one player)
- Both sit under `C:\Ludis\` and share the Opta light theme

## Known gaps / pending work

- Zone label ordering (`PACE_LINE_ORDER`, `SPIN_LINE_ORDER` in `charts.py`) uses assumed strings — verify against actual DB lookup values if cells appear out of order
- Player photos not yet sourced — drop `{bowler_id}.jpg` in `photos/` when available
- Batting and fielding profile sections not yet built
- No `requirements.txt` (stack: streamlit, pyodbc, msal, plotly — same as livematchdashboard)
