# A-team packs — the LEVEL axis

Australia A tour of India, Sep–Oct 2026: two four-day matches and three one-days in Puducherry.
The first series where our opposition is a second XI, and the first bundle carrying two squads.

## The idea: format and level are different axes

A four-day A-team match is **Test-format cricket at a-team level**. The format is the shape of the
game — four innings, red ball, the report layout and kit that go with it. The level is its
standard — which series count as a player's record.

Everything in this estate scoped by format alone, because until now format and level always moved
together: an "International Tests M" match is Test-format *and* senior. Scoping an India A pack by
format alone would have simulated our second XI against senior India profiles.

    cricket_core.config.SERIES_LEVELS = {"international": …, "a-team": …}
    series_sql(fmt, level)          # the one definition
    international_series_sql(fmt)   # unchanged name for the senior case, every old caller intact

`level="international"` is the default everywhere, so every pre-existing series resolves byte for
byte as before. Verified: `TEST_FILTER` unchanged, the shipped profile CSVs untouched, the Zimbabwe
pack's report links identical.

| level | Test | ODI |
|---|---|---|
| international | International Tests M | International ODI M · World Cup · Champions Trophy |
| a-team | International 1st Class M · International Tour Matches M | International List A ODI M |

**T20I is deliberately absent at a-team level.** The warehouse has no men's A-team T20 bucket — the
only candidate, `International List A T20 F`, is women's cricket. `series_sql` raises rather than
quietly serving the wrong cricket.

Both a-team buckets carry the occasional senior side (a PM's XI game, a touring Test team against a
county). They are scoped by PLAYER, not by team, so a player with senior tour matches pools those
in. Measured and accepted, not silent.

## What the data actually supports

India A, measured 2026-09-04:

| bucket | balls | matches | tracked | last |
|---|---|---|---|---|
| International 1st Class M | 33,709 | 25 | 68.3% | 02-07-2026 |
| International Tour Matches M | 4,766 | 3 | 100% | 07-11-2024 |
| International List A ODI M | 4,188 | 8 | 99.2% | 21-06-2026 |

There is **no Indian domestic cricket in the warehouse** beyond the IPL — no Ranji, no Duleep, no
Vijay Hazare. India A's record there is the A-team buckets plus whatever senior and IPL cricket each
player has.

**Cricket-21 has it** (surveyed and pulled 2026-09-07 — see the C21 section below and
`cricket21/docs/INDIA_DOMESTIC.md`). 49 matches and 58,000 deliveries of Ranji, Duleep, Vijay Hazare
and the India A tours are now in the local mirror at 98-99% tracking, which is what the `source`
axis exists to read.

### The problem: A-team first-class cricket is barely tracked

2026 first-class A-team cricket is **38.5% tracked**. For the India A attack:

| bowler | balls | tracked | % |
|---|---|---|---|
| Gurnoor Brar | 575 | 367 | 63.8 |
| Harsh Dubey | 522 | 186 | 35.6 |
| Saransh Jain | 540 | 90 | 16.7 |
| Yash Thakur | 299 | 35 | 11.7 |
| Auqib Nabi | 316 | 30 | 9.5 |
| Anshul Kamboj | 366 | **0** | 0.0 |
| Zeeshan Ansari | 138 | **0** | 0.0 |

No `--min-balls` threshold rescues a bowler with nothing to threshold. They are simply absent from
`bowler_delivery_*.csv`, and `export_matchup_store` drops any bowler missing from it — so the pack
shows an attack that is mostly blank, without anything failing.

The one-day side does not have this problem: List A A-team cricket is 99.2% tracked and all eight
bowlers profile from their own record.

## The fix: borrow the shape, never the outcome

`build_bowler_delivery.py --supplement test,t20` (Tom's call, 2026-09-04).

- **WHERE a bowler pitches it** may be read from another body of cricket, nearest format first.
  Mechanics travel — a bowler's lengths and lines are theirs.
- **OUTCOMES DO NOT TRAVEL** and are never supplemented. `bowler_effectiveness` stays on the pack's
  own scope, so an IPL economy can never become an A-team wicket rate. A supplemented bowler
  simulates at the type baseline.
- Every supplemented row records its `source`, carried into the matchup store as `shape_source`,
  so the page can say whose cricket it is showing.

Two new gates make the borrowing possible and honest:

- `q_present()` asks who **bowls** in the scope at all, tracking not required. The zone grid can
  only see tracked bowlers, so a bowler with 366 untracked balls looked like a bowler who does not
  exist. Whether someone bowls is a fact about the fixture list, not about the tracking vendor.
- `--min-present` / `--min-supp` decide when a supplement is worth taking.

Result on the India A four-day attack: **6 of 7 bowlers profiled, up from 2.** Jain and Kamboj from
senior Test, Thakur and Ansari from the T20 pool, Brar and Dubey from their own A-team record. Auqib
Nabi has 30 tracked A-team balls and 52 IPL — under threshold everywhere, so he carries no plan,
which is the honest answer.

## Two squads, one opponent — the collisions this exposed

`india-a-4day-2026` and `india-a-od-2026` are both live, both against India A. That is new, and it
broke three assumptions at once.

**1. Opposition data keyed off `slug.split("-")[0]`.** Both slugs reduce to `india`, so the two
formats would have shared — and overwritten — one `matchup_store`, `h2h`, `opponent_about` and set
of overviews. Now `squads.opp_key(slug)` reads an explicit `opp_key` from squads.json, defaulting to
the old derivation so every existing series is unchanged. `export_matchup_store --key` separates the
data key from the warehouse team name, and refuses when the key does not match what playerprofile
will look for.

**2. Batting reports carry their format in the FILENAME, not the folder.** Every one renders into
`reports/`, tagged `_batting_test_` / `_batting_odi_`. `publish_site._sidecar_map` took format from
the directory — correct for bowling reports, wrong for these — so a player's Test and ODI batting
reports collided on `(id, hand, kind, group)` and the Test one won the sort. It had never bitten,
because no two squads had shared a player across formats. These two share four (Gaikwad, Thakur,
Kamboj, Badoni). The rule is unchanged — take the format the *builder* chose, never `meta.format` —
it is only that for these it chose a filename.

**3. `build_player_site` nests packs under a slug folder whenever more than one squad is live.**
Adding two live squads would move the Zimbabwe packs from the bundle root into a subfolder and
change every URL already shared. Australia A therefore builds into its own bundle
(`ausa_player_site` → `ausa_player_pack_site`), and the Zimbabwe publish keeps naming its squad.

## Where level had to be carried

- **`reports/ateam/`** — level lives in the PATH, like format. A player can hold both records
  (Kamboj: 366 A-team first-class balls, 108 Test) and the filename carries neither.
- **`publish_site._sidecar_map`** keys on `(id, hand, kind, group, fmt, level)`.
- **`build_h2h`** — an Australia A v India A four-day meeting classifies as `FC`, which the senior
  format orders rank dead last. At a-team level the order inverts: the fixture the players are
  actually preparing for comes first, senior meetings are the fallback.
- **`audit_pack_hands._series_fmt`** — the A-team buckets matched none of its tests and returned
  `''`, which the caller skips, so a four-day pack could have carried a List A reel and passed as
  clean. The same shape of hole as the hand audit that never looked at format.
- **`odi_profile._supplement_rows`** — the T20I step is skipped at a-team level rather than
  attempted-and-swallowed. The pooled T20 step still applies at both levels: that scope is all major
  T20 leagues, level-agnostic by construction, and where an uncapped Indian player's white-ball
  footage actually lives.

## Opposition — the announced squads (re-pinned 2026-09-12)

India A named both squads on 2026-09-12, and `opp_squad_india_a_4day.json` /
`opp_squad_india_a_od.json` are re-pinned from them. The provisional pins from the June–July block
sit beside them as `*.provisional-2026-09-04.json`. **9 of the 15 four-day names and 7 of the 15
one-day names were new.**

Before the rebuild, Cricket-21 was surveyed for every named player over the last 12 months and 11
matches the mirror lacked were pulled — the Irani Cup 2025/26, seven Ranji 2025/26 matches, both
South Africa A in India unofficial Tests and one Vijay Hazare game (`cricket21/docs/INDIA_DOMESTIC.md`).
**The one-day pack now builds with `--source both` as well.** It was left warehouse-only for the
provisional squad, when half the names gained nothing. With this squad C21's List A adds footage
for Padikkal, Prabhsimran Singh, Thakur, Nigam, Gurjapneet Singh and Pandya.

Yash Rathod and Nachiket Bhute have no warehouse record at all and carry reserved ids — see
`CLAUDE.md` § SOURCE. The rebuild also added the bowler-type groups the first build had skipped:
left-arm orthodox and leg spin for the four-day pack (Kellaway, Jason Sangha), left-arm pace for
the one-day pack (Dwarshuis, Spencer Johnson). Without them those bowlers' packs fell back to the
macro pace/spin plans. `--only-batters` / `--only-bowlers` still merge one player without a rebuild.

## Still open

- **C21 has Ranji Trophy, and it is the fix for the four-day pack** (surveyed 2026-09-07 with Tom's
  authorisation — the check needed a forced login, which logs him out of the portal). Full survey:
  `cricket21/docs/INDIA_DOMESTIC.md`. In short:

  - Ranji, Duleep and Irani live in C21's **db=2**, which `client_comps()` does not list at all —
    they are reachable only through `find_competition()`, which searches both databases.
  - Coded and available: **173,646 balls** across Ranji 2024 / 2024/25 / 2025/26, plus Duleep, the
    India A tours of England and Sri Lanka, and Vijay Hazare Elite. Ranji seasons are ~25–33% coded.
  - Quality is far better than the warehouse for this cricket: **98.5–99% tracked** against the
    warehouse's 38.5% for A-team first-class, and **100% video**. Ranji carries **no ball speed**
    (0.2%), so pace cards off it will have none.
  - The players who need it most are well covered: Auqib Nabi (no plan at all today) has **1,967
    first-class bowling balls**, Anshul Kamboj (zero tracked in the warehouse) **2,193**, Saransh
    Jain **2,535**. Four of the six batters with no card at all get 400–750 balls.
  - **An 18-month window is the right pull**: 49 matches instead of 106, keeping every player who
    clears a plan threshold. Being pulled into the mirror now.
  - **It does not fix the one-day packs.** Vijay Hazare coverage of this squad is thin (2,065
    batting / 1,855 bowling balls) and Varma, Suryavanshi, Sindu and Arshad Khan have none. The
    missing ODI spin plans stay missing.

  **The overlay is BUILT** (2026-09-07) — `source` is a third axis beside format and level:

      format   the shape of the game        Test / ODI / T20I / T20
      level    the standard of the game     international / a-team
      source   where the record comes from  warehouse / c21 / both

  `c21_source.py` returns mirror rows in the warehouse row shape (same names, same string
  conventions, `"None"` for what C21 lacks) so no consumer can tell them apart.
  `build_c21_player_map.py` maps the id namespaces into a reviewable file — 24 of 26 India A names,
  all at exact confidence. `source=` is threaded through both delivery loaders, `build_profile`,
  `build_batter_profile`, `render_report`, `render_batting_report`, `build_overview` and
  `build_opponent_about`, defaulting to `warehouse` so nothing existing moves.

  Measured on the rebuilt four-day pack:

  | | before C21 | after |
  |---|---|---|
  | batters with a card | 6 of 10 | **9 of 10** |
  | with a plan (right_pace / off_spin) | 3 / 3 | **6 / 7** |
  | with a plan (macro pace / spin) | 3 / 3 | **7 / 9** |
  | Nabi tracked bowling balls | 30 | **1,132** |
  | Mokhade batting balls | 64 | **538** |
  | Rasheed batting balls | 202 | **523** |

  Mokhade, Dubey and Pandey had no card at all and now have one; Rasheed and Gaikwad had cards with
  no plan and now have plans in both groups. Only Auqib Nabi still lacks a batting card — 137 balls,
  a genuine number eleven, which is the honest answer rather than a gap.

  ⚠ **matchupmodel's profile CSVs are still warehouse-only.** `build_bowler_delivery.py` queries the
  warehouse directly rather than through the loaders, so the store's `shape_source` still reads
  `test`/`t20` for Jain, Thakur, Ansari and Kamboj even though their profile-level data is now C21.
  That feeds the SIMULATED matchup numbers, and by design no matchup number reaches a player pack —
  the plans and cards the packs show are C21-backed. Rebuilding matchupmodel against C21 is a
  separate piece of work.

  Three things learned building it, all in CLAUDE.md §SOURCE:

  - **A gate must count the source it builds from.** `_test_balls` decides full profile against the
    thin fallback; counting the warehouse while building from `both` sent every C21-only player down
    a warehouse-only fallback that found nothing and skipped them without a word.
  - **The id map must not guess.** A surname-only match picked `Mohsin Khan` (522 balls) for Mohd
    Arshad Khan over the correct `Arshad Khan` (25). Surname-only matches are now left unmapped and
    reported — no map is recoverable, a wrong map is invisible.
  - **C21 carries its own sentinel**, and it is a cluster rather than a value: an untracked ball
    calibrates to around the per-hand intercept — −1810 mm for a right-hander, −2195 for a
    left-hander — on 14.9% / 15.4% of deliveries. An equality test would miss most of it; filter on
    the tracked RANGE.

  **The ONE-DAY pack stays warehouse-only, deliberately.** C21's Vijay Hazare coverage of that squad
  is 583 bowling and 335 batting balls across fourteen players, seven of whom gain nothing at all
  (Varma, Suryavanshi, Sindu, Arshad Khan, Badoni, Kamboj, Gaikwad). That is not worth a full
  rebuild, and mixing sources for a negligible gain buys inconsistency without information. C21 is
  applied where it changes the answer.

  **The stroke vocabularies barely overlap, and that was nearly missed.** Of 32 C21 stroke names only
  five are warehouse spellings, so passing them through raw left every other C21 ball with
  `stroke_family = None` — a batter with 500 C21 balls and 60 warehouse ones would have had their
  "go-to shot", a headline card fact, derived from the 60 while the profile claimed 538. `_STROKE` in
  `c21_source` maps the vocabulary (C21 is finer — Cover/Off/On/Straight/Square Drive all collapse to
  "Drive"), taking Mokhade from ~0% to 50% of balls with a recognised shot family.

  **C21 VISION IS WIRED** (2026-09-07). Its clips are direct, unauthenticated
  `hdvod.cricket-21.com` URLs rather than Fairplay blobs, so an item carries either a **stem** (to
  resolve with a fresh SAS at bake time) or a finished **url** (nothing to resolve, and re-stamping
  it would corrupt it). `c21_source.clip_ref()` decides, and Fairplay always wins where both exist —
  a warehouse delivery is never displaced by a mirror one.

  Four places had to change, and three of them were silently discarding the footage:

  - `cricket_core.resolve_playlist` overwrote `url` from the stem and DROPPED anything that would
    not resolve, so a source with a clip on every ball produced empty reels.
  - `build_player_site` filtered six call sites on `clip_stem` alone (`_clip_item` / `_playable`).
  - `build_opponent_about._has_vid` asked only about `video_file_name`.
  - **`audit_pack_hands` could not see them at all** — and an unresolvable clip is dropped from the
    reel's id list, so a reel made entirely of C21 footage would have looked EMPTY and passed as
    clean *without being checked*. It now indexes url-bearing entries and resolves their hand and
    red/white format from the mirror (`c21_source.delivery_facts`), selecting them by PROVENANCE
    rather than id shape: C21 ids are six digits and warehouse ids sixteen, which cannot collide
    today but is an observed fact about two id spaces, not a guarantee.

  Result on the four-day pack — **668 of 1,997 clip entries (33%) now come from Cricket-21**, all
  red-ball:

  | bowler | before | after |
  |---|---|---|
  | Zeeshan Ansari | no vision at all | 20 stock |
  | Anshul Kamboj | 0 stock · 6 wkt | 20 stock · 22 wkt · 40 new-ball |
  | Auqib Nabi | 10 stock · 6 wkt | 20 stock · 40 wkt · 40 new-ball |
  | Gurnoor Brar | 20 stock · 21 wkt | 20 stock · 36 wkt |

  Probed before shipping, because a C21 `VideoPath` is constructed rather than confirmed and the
  host answers a missing clip with a ~1.5 KB stub instead of a 404: six sampled URLs returned
  12–20 MB of `video/mp4`, no stubs, no auth.

  ⏸ **The shot matrix stays warehouse-only.** It bins on `stroke_id`, a warehouse lookup id that
  C21 has no equivalent of — only the stroke NAME maps. Its roster still grows to 9 batters because
  that comes from `opponent_about`.

  Two C21 bugs found on the way, both fixed or documented there: an expired session answered with a
  redirect JSON that `_looks_like_login` did not recognise, so a dead cookie read as "you have no
  competitions"; and the SQL passthrough returns **empty rather than erroring** on a wrong table or
  column name, which produced three false "no data" conclusions in one sitting.
- **Suggested Fields are built for the FOUR-DAY pack and omitted from the one-day pack** — the
  split follows format, and nothing about level reaches `field_engine` (`_FMT = "test"`). So the
  four-day pack's field placements read a batter's scoring pattern at a-team level, correctly, but
  set it against **senior Test** field norms and red-ball tactics. That is an approximation, not a
  scoped answer: an A-team field-norm set is new work, not a parameter. Worth reviewing before a
  coach acts on a placement.
- **`build_conditions.py` is skipped** — it measures against `REF_CONDITIONS` = NZ/SA/ENG, a
  SENA-away Test idea. A reference set for A-team cricket in India has to be chosen first.
- **Auqib Nabi carries no bowling plan.** 30 tracked A-team balls, 52 IPL.
- **The Test/international profile CSVs still carry the untracked-zone contamination** documented in
  CLAUDE.md. Unchanged by this work and still Tom's decision.
