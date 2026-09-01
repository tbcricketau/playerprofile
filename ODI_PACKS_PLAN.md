# ODI_PACKS_PLAN — making the player packs format-aware

> Opened 2026-09-01 (Tom: "full ODI player packs", revive `tbcricketau/player-packs`).
> Driver: the Zimbabwe away ODI series. South Africa ODI needs the identical work, so this is
> built as **format generalisation**, not a Zimbabwe special case.

## Where it started

The **coach portal** half is done — `build_reports.py --format ODI` renders the bowler reports and
`publish_site` bakes them (`series.json` groups carry `"format"`, defaulting to Test). Nine Zimbabwe
bowlers are live in the gated portal.

The **player packs** are not, because they hang off a Test-only spine that reaches into a second
repo. `build_player_site` reads `matchup_store_{opp}.json` in five places — roster, hands,
opposition cards, h2h — and that store is produced by matchupmodel, where `TEST_FILTER` is a
hardcoded constant in `config.py` and the zone-response profiles are Test-derived CSVs.

**The trap that makes this worth doing properly:** running the existing Test pipeline for Zimbabwe
would *not* fail. The squad has 11,565 Test batting balls. It would emit plausible ODI plans built
from Test-length innings and Test fields — the failure that gets believed. Ben Curran strikes at
**76 in ODIs and 53 in Tests**; Ervine averages **28 vs 36**. Same players, different game.

## Layers, in dependency order

### ✅ Layer 1 — batting data access (playerprofile) — DONE 2026-09-01

- `batting_loaders.py` — every loader takes `fmt="Test"`; the five scope call sites use
  `_scope(fmt, 'M')` **imported from `data_loaders`** rather than a second local copy (the bowling
  side already owns the T20 pooling rule and a copy would drift). `load_test_batters` →
  `load_batters(min_runs, fmt)`, with the old name kept as a back-compat wrapper.
  `load_batter_info`'s team subquery is now format-scoped too — it previously answered "across all
  cricket", and an `fmt` that changed nothing would be worse than no `fmt`.
- `batter_profile.build_batter_profile(..., fmt="Test")`, threaded into the deliveries, innings,
  info and catch-position reads.

⚠ When `raw` is passed in, the caller has already scoped it — pass the **same** format or the
share-of-runs denominator comes from a different one.

Verified: Curran/Ervine profiles differ correctly by format and ball counts match the warehouse.

### ✅ Layer 2 — derived builders (playerprofile) — DONE 2026-09-01

Every one now takes `--fmt Test|ODI|T20I`, defaulting to Test:

| file | what changed |
|---|---|
| `profile.build_profile` | `fmt=` threaded to the (already format-aware) bowler loaders |
| `build_opponent_about.py` | `_TEST` → `_FMT_SQL[fmt]`; `--fmt` reaches both profile builders, `_test_balls`, `batter_role` and the clip picker |
| `build_overview.py` | `--fmt` through all three `build_batter_profile` calls |
| `build_shot_matrix.py` | `_INTL_TEST` constant → `_scope_sql(fmt)` |
| `build_conditions.py` | scope threaded (⚠ see below) |
| `batting_report.py` / `build_batting_reports.py` | `--fmt` through to the profile |

**The clip fallback order is now format-led.** `batter_clips_best` relaxed `Test → ODI → T20I`
with a rationale about Tests being "the format they'll actually play" — which inverts for an ODI
series. `_FMT_ORDER` now puts the pack's own format first and treats the other white-ball format as
the nearer neighbour: ODI → T20I → Test.

⚠ **`build_conditions` is scoped but not yet meaningful for white-ball.** `REF_CONDITIONS` is
NZ/SA/ENG — the SENA-away seam-and-bounce benchmark, a **Test** idea. `--fmt ODI` scopes the
deliveries correctly and then measures them against the wrong reference set. Either pick a
white-ball reference set or drop the conditions page from ODI packs. Flagged in the module.

`build_h2h.py` is already format-flexible (best available format per pairing) and the clip resolver
already walks Test → ODI → T20I. Neither needs work.

Verified: an AST pass confirms `fmt` is bound everywhere it is used across all ten touched files,
and the default path is unchanged (Curran 1003 balls / 537 runs, Raza 2633 balls — identical to
pre-refactor).

### ⏸ Layer 3 — the field engine (the deepest)

`field_engine.py` has `_FMT = "test"` at module level and uses it for `fields.gps_corrected_field`,
`OUT_LIMIT[_FMT]` and two `_FMT == "test"` behaviour branches. **This is not a parameter swap:**

- ODI phases are **powerplay / middle / death**, not new-ball / old-ball.
- Fielding restrictions differ per phase (2 out in PP1, 4 in the middle, 5 at the death) — the
  `OUT_LIMIT` table has to become phase-aware for ODI, not just format-aware.
- ODI field trigger norms do not exist; `build_field_trigger_norms.py` would need an ODI run.

### ✅ Layer 4 — matchupmodel — DONE 2026-09-01

- `config.format_filter(fmt, alias)` replaces the hardcoded scope; `TEST_FILTER` is kept as
  `format_filter("Test")` because every existing caller means Tests by it and the shipped profile
  CSVs are Test-derived.
- `config.profile_csv(stem, fmt)` — **Test keeps the original unsuffixed filenames** so the
  existing store and every shipped artifact stay valid; other formats get `_odi` / `_t20`. The two
  stores coexist rather than one overwriting the other.
- `build_batter_response.py --fmt`, `build_bowler_delivery.py --fmt`, `simulate.load_profiles(fmt)`,
  `recent_batters/recent_bowlers(fmt=)`, `export_matchup_store.py --fmt`.
- `data/opp_squad_zimbabwe.json` pinned — 11 batters / 9 bowlers, from the XI that played all three
  July 2026 ODIs v Bangladesh plus Sean Williams. **Not a published squad** (Zimbabwe had not named
  one); re-check and re-export before the series.

ODI profiles built: **17,262** batter-response rows (476 batters), **9,778** bowler-delivery rows
(606 bowlers). Test CSVs verified untouched by mtime.

⚠ **The build script's completion message was hardcoded to the Test filename** and reported
`-> data/batter_response.csv` after writing the ODI file. Fixed — it now names the file it wrote.
A build that misreports where it wrote is how a clobbered artifact goes unnoticed.

**Coverage, and the floor that isn't the problem.** ODI own-profile coverage for the pinned squad
is **8/11 batters** (Evans, Masakadza, Ngarava fall to the cohort read — all tail-enders, which is
the right behaviour) and **8/9 bowlers**. Newman Nyamhuri is the miss: 192 ODI balls of which only
**60 carry a usable pitch coordinate**. Dropping the floor 200 → 150 did *not* add him, so this is
a data-coverage limit, not a threshold to tune — the floor was left at the Test default rather than
diverging the methodology for no gain.

### 🔴 The sentinel is inside the SIMULATION, and it reaches the live Test store

Found 2026-09-01 while sanity-checking the first Zimbabwe store, which returned a plan of
`danger: "full toss, middle/off"`. The sim bins by the warehouse's **pre-bucketed** group columns
(`pitch_length_group_pace_2_id`), not the raw coordinate, so the `-20000` sentinel looked
irrelevant. It is not: **an untracked ball still gets a group id, and it is always the fullest
bucket** — pace `12999` "full/yorker", spin `10999` "full toss".

Measured across all men's internationals. Every other length bucket is **0.0%** untracked:

| | contaminated bucket | untracked share |
|---|---|---|
| Test · pace | full/yorker | **47.5%** |
| ODI · pace | full/yorker | **56.2%** |
| Test · spin | full toss | **79.6%** |
| ODI · spin | full toss | **90.6%** |

So the sim's fullest zone was half to nine-tenths deliveries nobody measured, and any
"danger: full toss / full-yorker" plan was largely fabricated. Fixed by `config.ZONE_TRACKED_SQL`,
applied in both grid queries.

🔴 **The Test profile CSVs still carry it, and they are live.** Rebuilding them would move numbers
that have already been signed off — the Bangladesh packs and the SA / NZ series reports were all
produced from the contaminated grids. **That rebuild is Tom's call, not a side effect of this
front.** The ODI CSVs are new, so they were simply rebuilt clean. When Test is rebuilt, expect the
full/yorker and full-toss zones to shrink sharply and any plan that named them to change.

⚠ **Batters and bowlers degrade differently.** A batter with no per-zone profile falls back to the
cohort response and is flagged confidence "None". A bowler with no profile is **filtered out of the
sim entirely** (`if str(b) in bmeta`), even when pinned in the squad file. The count is printed
("N bowlers of M named") so it is visible, but the asymmetry is worth closing.

### ⏸ Layer 5 — pack assembly + publish

- `build_player_site.py` — format awareness end to end.
- ⚠ **The reel-scope star is hardcoded to Test.** `build_player_site.py:1138` reads
  `scope != f"Test:{group}"`, so in an ODI pack **every** reel would be starred as mis-scoped even
  when it is perfectly scoped `ODI:off_spin`. The footnote would fire on all of them and stop
  meaning anything — the star has to compare against the pack's own format.
- **The ODI report has no player-mode cut.** `report.py` writes `.pmode.html` (116 exist); ODI and
  T20 write none. The packs link `.pmode.html`, so this must be added or the packs link nothing.
- `publish_packs.py` — revive the `aus` bundle (Tom's call): re-point it at the Zimbabwe series,
  clear the `archived` note, publish with `--revive`. **Rebuild from source, never re-push the
  tag** — the archived bundle's SAS expired 2026-08-27.
- Tom re-enables Pages on `tbcricketau/player-packs` (Settings → Pages → main / root).

## Rules this work must not break

- **Reels stay scoped to what the pack is about** — bowling pack = exact bowler type, batting pack
  = our batter's hand. `audit_pack_hands.py` gates the publish and fails closed.
- **`publish_packs.py` is the only sanctioned push.** Never `git push` a bundle by hand.
- **Never average an untracked length.** `cricket_core.charts.is_tracked_length` — Zimbabwe is 46%
  tracked in ODIs, and every new format-aware aggregate inherits that hazard.
- **Don't project across formats.** `CROSSFORMAT_TRANSLATION.md` — tempo/rates translate,
  averages and wicket rates do not.
