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

### ✅ Layer 3 — the field engine — RESOLVED BY OMISSION 2026-09-01

**ODI packs ship without Suggested Fields, and say so.** `cricket_core.fields` already carries the
ODI half — stock fields and `OUT_LIMIT["odi"] = {"pp1": 2, "middle": 4, "death": 5}` — but the
*tactics* in `field_engine.py` are red-ball: `_STOCK_VARIANTS` is a Test-phase library, `_rules`
encodes Test logic ("R2 square early"), phases come from `is_early` rather than an over number, and
no ODI run of `build_field_trigger_norms.py` exists.

Generating a white-ball field from red-ball rules would be a plausible, unjustified answer — the
exact failure this codebase keeps finding. `build_overview._field_images` / `_field_parts` now
return empty for a non-Test format and print the reason once. Both call sites already tolerated a
`None`, so the section simply does not render.

To finish it properly later: derive phase from over number (`odi_profile._phase` already does),
map to `pp1/middle/death`, write an ODI `_STOCK_VARIANTS` library, and run the trigger norms for
ODI. That is cricket design work, not refactoring.

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

### ✅ Layer 5 — pack assembly + publish — CODE DONE 2026-09-01

- **The ODI/T20 reports now write a player-mode cut.** They wrote none, and the packs link
  `<base>.pmode.html`, so an ODI pack would have linked nothing. It is byte-identical to the coach
  page **on purpose** — Test's player mode exists to strip the coach-only "Vs Our Squad" verdicts
  and these reports have no such section. ⚠ If one is ever added, this must start stripping it.
- **The reel-scope star now compares against the pack's format.** It read `scope != f"Test:{group}"`,
  so an ODI pack would have starred every reel as mis-scoped even when perfectly scoped
  `ODI:off_spin` — a footnote that fires on everything means nothing. The pack's format is taken
  from the **squad**, which is where it is recorded.
- **`_scouting_urls` was doubly wrong for white-ball.** It globbed only `reports/` (ODI renders to
  `reports/odi/`) and *inferred* the folder as `bowlers-vs-{hand}`, which is only true because the
  Test groups happen to be named that — a white-ball group is `bowlers`, so every link would have
  404'd. It now scans all format dirs and takes the group from **series.json**. Verified: Zimbabwe
  resolves 9 links under `bowlers/` keyed `all`; South Africa is unchanged at 17 under
  `bowlers-vs-lhb` keyed `lhb`.
- **The batting packs fell back to nothing.** `hmap.get(hand)` with hand `rhb`/`lhb` finds nothing
  in a white-ball map keyed `all`, so an ODI batting pack linked no reports; it now falls back to
  the hand-agnostic report, which is what a both-hands report is.
- **`build_h2h` format order follows the PACK.** `_FMT_PRIORITY` was Test-first, so an ODI pack
  preferred a Test meeting over the ODI one it was preparing for. `_FMT_ORDER` now puts the pack's
  format first and red-ball last for white-ball packs.
- **`publish_packs.py` `aus` bundle revived** and repointed at `zimbabwe-odi-away-2026`
  (`opp: zimbabwe`). The archived note is replaced by a comment recording what the repo held
  before, that the `archived-2026-08-31` tag still holds it, and that publishing force-pushes over
  that state on `main`. Reviving Bangladesh later means rebuilding from source — its baked SAS
  expired 2026-08-27.

🔴 **Tom re-enables Pages on `tbcricketau/player-packs`** (Settings → Pages → main / root). It was
disabled when the series was archived, so the bundle can be pushed but will not serve until then.

## Rules this work must not break

- **Reels stay scoped to what the pack is about** — bowling pack = exact bowler type, batting pack
  = our batter's hand. `audit_pack_hands.py` gates the publish and fails closed.
- **`publish_packs.py` is the only sanctioned push.** Never `git push` a bundle by hand.
- **Never average an untracked length.** `cricket_core.charts.is_tracked_length` — Zimbabwe is 46%
  tracked in ODIs, and every new format-aware aggregate inherits that hazard.
- **Don't project across formats.** `CROSSFORMAT_TRANSLATION.md` — tempo/rates translate,
  averages and wicket rates do not.
