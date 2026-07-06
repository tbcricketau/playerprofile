# Field Settings v2 — stock-first fields with justified deviations (PLAN, 2026-07-05)

**Status (2026-07-06): stock dictionary + GPS-corrected base BUILD & SIGNED OFF by Tom. Ready to
build the v2 assembly + batting-report wiring — see ▶ HANDOVER below.**

## ▶ HANDOVER — build the GPS-grounded field assembly (2026-07-06)

A new playerprofile session picks up here. Field GPS work is done in the sibling **catapultgps**
project; this project builds the batter-facing assembly + report. Tom has **signed off the
GPS-corrected fields** — proceed to the engine.

**What's already done (don't rebuild):**
- **§2 stock dictionary** — `ludis_cricket.fields.STOCK`, `stock_field(fmt, bowler_type, hand, phase)`,
  `validate_stock()` (all legal). 6 scenarios (pace_same/across, finger/wrist × in/away).
- **§3b GPS corrections** — GPS now measures manning directly (what §3 said the warehouse couldn't).
  **`ludis_cricket.fields.gps_corrected_field(fmt, bowler_type, hand, phase, with_changes=False)`**
  returns the stock with the ≤3 strongest GPS-evidenced, legality-checked swaps applied (falls back
  to raw stock for Test / unbuilt cells). Evidence CSVs in `catapultgps/data`
  (`field_corrections.csv`, `field_validation.csv`) read via
  `ludis_cricket.gps.load_field_corrections()` / `load_field_validation()`. **This is the base to
  start the assembly from — not raw `STOCK`.**
- **field_engine.py** currently holds the **v1 data-derived** `build_field` (run_flow +
  expected_catches + `_backtest` + `field_diagram`). Keep those as the **value model + renderer**;
  rework only the **assembly**.

**Build next, in order:**
1. **`referencebuilder/build_field_trigger_norms.py`** *(DB, one query family)* — cohort percentile
   distributions for the R1–R8 trigger stats (§4) per phase × group × format (sector share, lap/
   reverse rate, square-early scoring, etc.). The per-batter rules need these baselines.
2. **Rework `field_engine.build_field` → assembly v2 (§5):**
   - `base = fields.gps_corrected_field(fmt, bowler_type, hand, phase)` (GPS-corrected stock).
   - Evaluate R1–R8 (§4) on the batter; apply the **top ≤3 fired** rules, each swap re-validated with
     `fields._is_out` / `fields._behind_square_leg` / `fields.OUT_LIMIT[fmt][phase]` (9 fielders,
     out-of-circle limit, ≤2 behind square leg).
   - Tag each fielder `base | moved | added`; justify (base = GPS-corrected stock line, using the
     `with_changes` string; deviation = his-stat line from the rule).
   - **Backtest vs the untouched GPS-corrected base** (reuse `_backtest`); if no gain → return base,
     note "no deviation earned".
3. **`batting_report.py`** — Stock/Change column + a deviations-only read line
   ("GPS-corrected pace field, 2 changes: …").
4. **Verify renders** — Smith (RHB benchmark), a LHB (Khawaja/Head), a sweeper vs spin (R1), a
   square-scorer (R2); eyeball against real fields bowled to them.

**Dimension mapping (report `group`/over → stock keys):**
- `fmt` = `'test' | 'odi' | 't20'` (lowercase). `hand` = `'RHB' | 'LHB'`.
- `bowler_type` STRINGS for `scenario()`: pace = `"Right Fast"|"Left Fast"|"Right Medium"|"Left Medium"`,
  spin = `"Off Spin"|"Left Orthodox"|"Leg Break"|"Left Unorthodox"`. Derive from warehouse
  `bowler_style_id` (1,2=Fast · 3=Medium · 4=Off/LA-orthodox · 5=Leg/LA-unorthodox) + `bowler_hand_id`
  (1=R,2=L).
- `phase`: t20 `powerplay`(<6)/`middle`/`death`(≥15); odi `pp1`(<10)/`middle`/`death`(≥40);
  test `attack`/`defend`.

**Gotchas:**
- **GPS corrections are white-ball only** (Test `attack`/`defend` has no per-ball GPS label yet) →
  `gps_corrected_field` returns raw stock for Test. Test reports use the hand-built base for now.
- The base is already close to reality → **deviations should be small**; backtest vs the corrected
  base, not raw stock. If a batter's report shows 0 earned deviations, that's fine — the corrected
  stock is the answer.
- `FIELD_POS` / stock lists are **batter-relative** (angle 0 = to bowler, +off/−leg, ±180 behind);
  the LHB mirror is baked into the scenario. `field_diagram` handles rendering (house convention).
- `load_field_validation()` also gives per-position **median GPS location** — useful for a "where he's
  actually manned" evidence panel or to nudge a moved fielder's exact spot.

## 0. Why the rework (review verdict on v1)

v1 (shipped 2026-07-05, reviewed same day) assembled fields bottom-up from the batter's own
data: rank expected-catch positions, fill the rest from his run sectors. Every *fielder* was
justified, but the *field* wasn't credible as a whole — Smith's set field had **seven boundary
riders**, which no Test captain sets; catcher counts floated free of match practice; nothing
anchored the shape to how fields are actually set in each format.

**Tom's steer:** fields should be **generally close to stock**, with a small number of
deviations backed by strong reasoning — *does he lap/reverse? does he look to score square
early?* — not a from-scratch rebuild per batter.

v1 pieces that survive: the run-flow sectors (Layer 1), the false-shot × cohort catch-carry
model (Layer 2), the phase split, the diagram (orientation + single-colour fixed 2026-07-05),
the report wiring. What changes is the **assembly**: stock template first, deviations second.

## 1. Target output (per batter × bowler group × phase)

A field that is **STOCK ± at most 3 deviations**, rendered as:
- the field diagram (house orientation: bowler bottom, striker top, uniform markers);
- a justification table — `Fielder | Stock/Change | Why`:
  - **stock** fielders carry the orthodoxy line ("standard new-ball cordon");
  - **changes** carry *his* stat ("he laps 14% of balls vs off spin (cohort P88, n=41) —
    45 saver in, deep backward square back");
- a **backtest vs pure stock**: "this field = stock + 2 changes; those changes put fielders
  under N more of his caught dismissals / intercept M% more of his boundary flow than the
  stock field." **If the deviated field doesn't beat stock on either metric, ship pure stock**
  and say so — that IS the strong-reasoning bar.

## 2. Stock field library (investigation part A — codify, don't derive)

**✅ BUILT 2026-07-05 → `ludis_cricket/fields.py`** (was a draft table; now the live dictionary).
A field follows how the ball behaves *relative to the batter*, so the 12 (bowler-type × hand)
combinations collapse to **six scenarios** + a resolver; each carries a field per format × phase.
`stock_field(fmt, bowler_type, batter_hand, phase)` returns the 9 names. `validate_stock()`
gates every entry on: 9 fielders, the format's **out-of-circle limit** (ODI 2/4/5, T20 2/5/5 —
all sit exactly at limit), and the **≤2-behind-square-leg Law** — all 54 pass. Reviewable page:
the scenario table + six Test shapes rendered + full matrix (artifact `stock-dictionary-v1`).
The tables below are the source for that dictionary — Tom red-pens here, code tracks it.

Hand-written templates in the FIELD_POS vocabulary, one per
**format × bowler group × phase (× batter hand by mirror)**, grounded in the lit review
(§2a) — reviewed by Tom before any code.

### 2a. Lit review — base-level stock fields (web, 2026-07-05)

Sources triangulated: Wikipedia *Fielding (cricket)* + *Slip (cricket)*, ESPNcricinfo
(Ramnarayan on leg slip), Australian Cricket Tours & Cricketers Hub fielding guides,
CricketWorld "From Orthodox to Funky". (PitchVision has a per-scenario field-settings series
— right-arm fast in/outswing new-ball long-format etc. — but the domain is unreachable
[DNS dead / archive blocked]; the Australian Cricket Institute swing-field PDF is vector
art with outlined text, unreadable programmatically. Neither blocks the consensus below.)

**Consensus findings:**
1. **The standard Test start field** (multiple guides, near-identical wording): keeper,
   2–3 slips, gully, point, cover, mid-off, mid-on, midwicket, square leg, fine leg /
   third man — trading the last ring fielder for a 3rd slip. With 3 slips that is exactly:
   `K · S1 S2 S3 · gully · point · cover · mid-off · mid-on · fine leg` (+1 of
   square leg / midwicket / third man when only 2 slips).
2. **Attacking = 7–2**: 3–4 slips, 1–2 gullies (up to six in the arc), + mid-off, mid-on,
   fine leg; large gaps in front are deliberate bait (Wikipedia).
3. **Swing direction changes less than folklore says, at elite level**: inswing bowlers at
   the top level still bowl to a **three-slip, no-leg-slip** field — leg slip is a junior/
   club sight (ESPNcricinfo). The inswing adjustment is straighter ring fielders (midwicket
   in for cover), not a leg cordon.
4. **Hard law constraint**: **max 2 fielders behind square on the leg side** (anti-bodyline,
   Law 28.4/41.5 in sources) — binds every leg-side template, especially short-ball plans.
5. **Left-arm over to RHB** (angle across): the cordon + gully stay the core; sources add
   that the ball is *"likely to go square"* — so backward point / third man live for the
   cut, and the cordon effectively sits a touch wider. Elite composition commonly runs
   **2 slips + gully (or 2 gullies)** rather than 3 slips. *(Weakest-sourced cell — Tom to
   confirm from his eye; see Q1.)*
6. **Short-ball / bouncer trap**: the two allowed behind-square leg riders go back —
   **deep square leg + deep fine leg** (or deep backward square as one of the two) — with
   the catcher **in front of square (leg gully / short midwicket)**, cordon trimmed to one
   slip (Wikipedia leg-trap description + law).
7. **Spin cordons are smaller by geometry** (Wikipedia Slip) — matches the pilot's event
   data (short leg is the offie's signature catcher, not a slip wall).
8. **Philosophy check**: CricketWorld's coaching line — orthodox fields persist *because
   they work*; deviate only from batter-specific reasoning, and never set a funky field to
   bad bowling — is exactly the v2 stance.

### Tests (to RHB; LHB = mirror unless noted) — post-review draft
| Template | 9 fielders (+ keeper, bowler) | Source basis |
|---|---|---|
| **RF pace — new ball / attack** | S1 S2 S3, gully, point, cover, mid-off, mid-on, fine leg | consensus #1/#2 verbatim |
| **RF pace — set / older ball** | S1 S2, gully, point, cover, mid-off, mid-on, midwicket, fine leg | #1 (2-slip start variant) |
| **RF pace — inswing lean** (adjustment, not separate field) | as new-ball but midwicket for point | #3 |
| **LF pace — new ball / attack (over, angling across)** | S1 S2, gully, backward point, point, cover, mid-off, mid-on, fine leg | #5 (2 slips + strong square-off cover) |
| **LF pace — set** | S1, gully, backward point, cover, mid-off, mid-on, midwicket, square leg, fine leg | #5 + #1 |
| **Pace — short-ball plan** (named variant, both arms) | S1, leg gully, point, cover, mid-off, mid-on, midwicket, deep square leg, deep fine leg | #4/#6 — exactly 2 behind square leg |
| **Off spin — attack** | S1, short leg, silly point, point, cover, mid-off, mid-on, midwicket, square leg | #7 + pilot |
| **Off spin — contain / set** | S1, short leg, backward point, cover, mid-off, long-on, deep midwicket, square leg, short fine leg | #7 |
| **Leg spin — attack** | S1, leg slip, gully, point, cover, mid-off, mid-on, midwicket, fine leg | #7 (≤2 behind sq. leg ✓) |
| **SLA — attack** (turning away from RHB) | S1, gully, backward point, cover, mid-off, mid-on, midwicket, square leg, short fine leg | #7 |
| **SLA — contain / set** | S1, backward point, cover, extra cover, long-off, mid-on, deep midwicket, square leg, short fine leg | #7 |

**Hand/arm equivalence (angle logic):** RF→RHB ≡ LF→LHB (mirror); **LF→RHB ≡ RF→LHB**
(mirror) — so the two pace shapes above cover all four arm×hand combinations. Spin resolves
by *turn direction* relative to the batter, not group name. Over/round-the-wicket noted per
template where it changes the shape.

### ODI (fielding restrictions are hard constraints)
| Phase | Constraint | Pace stock | Spin stock |
|---|---|---|---|
| P1 overs 1–10 | max 2 out | S1 S2, point, cover, mid-off, mid-on, midwicket, **third man, fine leg (out)** | rare; treat as P2 |
| P2 11–40 | max 4 out | S1 or extra ring, ring 5, **deep point/third man, deep square, long-on, deep midwicket** | ring 5 + **long-on, long-off, deep midwicket, deep square** |
| P3 41–50 | max 5 out | ring 4, **third man, fine leg, deep cover, long-off/on, deep midwicket** | ring 4 + 5 out (both straight boundaries) |

### T20
| Phase | Constraint | Stock notes |
|---|---|---|
| Powerplay 1–6 | max 2 out | pace: third man + fine leg (or deep cover) out; ring 7. slip only over 1–2 |
| Middle 7–15 | max 5 out | pace: third man, fine leg, deep cover, deep midwicket, long-on · spin: long-off, long-on, deep midwicket, deep square, deep cover |
| Death 16–20 | max 5 out | yorker field: third man, fine leg, long-off, long-on, deep cover/deep midwicket by plan |

Plus the legality checker: circle counts per phase, **leg-side max 5 always**, (T20 behind-square
leg-side max 2 in PP). Encoded once, applied to every generated field.

## 3. What the data can and cannot verify (pilot run 2026-07-05)

`referencebuilder/scripts/pilot_stock_fields.py` (read-only scoping):

**Coverage (position-known fielder events on legal balls):** Test **350,878** events /
635 matches (53.3% of fielder rows) · ODI **227,758** / 1,434 (57.3%) · T20I **107,765** /
1,092 (**78.5%** — best coded). → All three formats have enough volume for cohort work.

**De-facto position ranking, Test vs RHB (share of position-known events):**
- right-arm pace: Keeper 40.9%, short extra cover 7.6%, bowler 5.0%, mid-on 4.6%, point 4.5%,
  mid-off 3.7%, short midwicket 3.6%, midwicket 3.5%, cover 3.2%, gully 3.2%, … deep fine leg
  2.1%, deep backward square 2.0%, deep midwicket 1.9%, short leg 1.9%.
- off spin: bowler 12.5%, **short leg 11.4%**, short midwicket 8.5%, keeper 8.2%, midwicket
  7.2%, short extra cover 5.6%, **long-on 5.5%**, silly point 5.4%, silly mid-on 5.2%,
  deep midwicket 4.5%.

**Findings that shape the method:**
1. **The pace slip cordon is nearly invisible in event data** (no slip in the pace top-20
   despite being manned ~100% of new-ball overs) — slips only "make a play" on the rare edge.
   Event frequency = manning × ball-flow, so **stock fields cannot be derived from event
   frequency**. They must be **codified** (§2). This kills the "derive stock empirically"
   shortcut *before* we built it.
2. Ring events skew to short/silly qualifiers (short extra cover 7.6%, silly mid-on for
   pace!?) → `fielder_event_position_id` often records **where the ball was fielded** (mid-off
   running in to a block) rather than the stationed post. Fine for catch maps (a catch is
   taken where the fielder is), weak for manning.
3. **Spin close-catchers ARE visible** (short leg 11.4% — bat-pad makes plays constantly),
   and deep riders register cleanly in both lists → event data remains useful as a
   *sanity check* on ring/deep structure and as the runs-saved/cost source.
4. So DeliveryFielders' roles in v2: **catch-position norms** (already built, solid) +
   **runs saved/cost per position** + **rider-frequency sanity checks**. Nothing else.

## 3b. GPS now measures manning directly — corrected stock base (2026-07-06)

§3 concluded the warehouse **cannot** derive manning (event frequency = manning × ball-flow, so
the ~100%-manned pace slip is invisible). **Catapult GPS on our own players closes that exact gap.**
The `catapultgps` project (bulk-run over **39 matches, 2024/25 → now**) places every fielder at the
GPS-detected release and, in `validate.py`, tallies **how often each named position is actually
manned** per (format × scenario × phase) over **5,547 classified deliveries** — the direct manning
evidence this section said didn't exist.

**Finding (consistent across scenarios):** the hand-built stock **over-calls the slip cordon and
under-calls the deep sweepers + midwicket**, sharpest through the middle/death overs — AUS sets more
defensive fields than the attacking stock defaults. Visual overlay:
`https://claude.ai/code/artifact/263f1806-e49b-40a1-9a41-c26e00d455b0`.

**How it feeds the engine — the corrected stock base.** `ludis_cricket.fields.gps_corrected_field()`
returns the stock with the **≤3 strongest GPS-evidenced, legality-checked swaps** applied (drop the
least-manned stock position, add the most-manned position the stock omits; 9 fielders + out-of-circle
limit + ≤2-behind-square-leg all re-validated — 24/24 corrected cells legal). It falls back to raw
`stock_field` where there's no correction (Test attack/defend has no per-ball label yet; unbuilt
cells). Evidence tables: `catapultgps/data/field_corrections.csv` (the swaps) + `field_validation.csv`
(per-position manning), read via `ludis_cricket.gps.load_field_corrections()`.

So the assembly (§5) **starts from `gps_corrected_field` instead of raw `stock`**, then applies the
per-batter deviations below on top. The base is now empirically grounded; the batter rules stay the
"strong reasoning" layer. Example — T20 pace vs RHB, powerplay: drop Fine leg (2% manned) → add
Midwicket (77%); drop Deep square leg (5%) → add Deep backward square (68%).

## 4. Deviation rule library (investigation part C — the "strong reasoning")

Each rule: trigger stat (his) → threshold (vs cohort) → the change it makes to the stock
template → justification sentence template. A rule that doesn't fire leaves stock intact.

| # | Rule | Trigger (computed today from profile rows) | Fires when | Change (≤2 fielders) | Justification template |
|---|---|---|---|---|---|
| R1 | **Lap / reverse** (Tom's example) | (Sweep + Ramp/Scoop) share of scoring shots vs spin; reverse split if stroke coded | ≥ cohort P75 and n≥20 | short fine leg → **45 back / deep backward square**; reverse → backward point stays deep | "He laps/reverses X% vs spin (P__): protect behind square both sides" |
| R2 | **Scores square early** (Tom's example) | early-phase run share, point + square-leg sectors | ≥ P75 and n≥60 early balls | early field: point → **backward point deeper**; mid-on → **square leg saver** | "X% of his first-30-ball runs go square (P__): square savers early" |
| R3 | **Down-ground driver** | straight-sector run share (mid-off/straight/mid-on) | ≥ P75 (set) | spin: mid-off/mid-on → **long-off/long-on**; pace: straight mid-off deeper | "X% of his runs go straight (P__): straight boundaries back" |
| R4 | **Cut-heavy** | Cut family run share vs pace | ≥ P75 | gully retained into set field OR **deep point** rider | "Cuts carry X% of his runs (P__)" |
| R5 | **Pull/hook** | Pull/Hook share + SR vs short balls | ≥ P75 | activates the **short-ball variant** template as a named alternative field | "Pulls X% at SR Y: bumper plan field" |
| R6 | **Edge-prone starter** | early false-shot % (has_shot_q rows) | ≥ P75 | **+1 slip** over stock early (3→4); extend attack phase 30→40 balls | "False shot X% in his first 30 (P__): extra slip, stay attacking longer" |
| R7 | **Leg-side nudger** | Work/Nudge leg-side share | ≥ P75 | **leg slip** early; midwicket squarer | "X% of his early scoring is worked to leg (P__)" |
| R8 | **Charger vs spin** | stumped share of dismissals vs spin ≥2, or Slog early | flag | keep **long-off back even early** vs spin | "Stumped N times / advances early: keep the straight boundary back" |

- **Evidence bar:** default **cohort P75** + minimum sample (n printed in the table);
  P80+ for exotic positions (leg slip, 45). Below the bar → stock stands.
- **Cap:** ≤3 deviations per field, ranked by (percentile strength × runs-or-wickets value);
  each must displace the *least-valuable* stock fielder for that batter, never a cordon
  fielder unless the rule is specifically about the cordon (R6).
- Cohort percentile sources: stroke-family shares already exist (`batter_stroke_norms.csv`
  percentiles); **new small build** for sector-share and phase distributions →
  `referencebuilder/build_field_trigger_norms.csv` (one job, Tests first, ODI/T20 same query
  with the format flag).

## 5. Assembly algorithm v2

```
stock = fields.gps_corrected_field(fmt, type, hand, phase)   # §3b — GPS-corrected base,
                                                             # falls back to raw §2 template
legal = restrictions[format][phase]               # circle counts, leg-side max 5
cands = [rule.evaluate(P) for rule in R1..R8]     # each: fired?, percentile, value, change
apply top-k fired rules (k≤3, ranked), each swap validated against `legal`
tag every fielder stock | moved | added
justify: stock line (orthodoxy) or his-stat line (rule)
backtest vs the untouched stock template (catch coverage + run interception)
if backtest shows no gain → return pure stock, note "no deviation earned"
```

## 6. Report changes (small — wiring already exists)

- Table gains a **Stock/Change** column; changes highlighted.
- The read line lists **only the deviations** ("Stock new-ball field, two changes: …").
- Both backtest numbers printed: ours vs stock.
- Diagram unchanged (orientation/colour conventions now in `c:\Ludis\CLAUDE.md`).

## 7. Build order (after sign-off)

1. ✅ `ludis_cricket/fields.py` — stock templates (§2) + legality checker. **DONE + GPS-corrected
   base (§3b): `fields.gps_corrected_field()`. Signed off 2026-07-06.**
2. `referencebuilder/build_field_trigger_norms.py` — cohort percentile distributions for the
   R1–R8 trigger stats (phase × group × format). *(DB, one query family)* — **NEXT.**
3. Rework `playerprofile/field_engine.py` — assembly v2 (§5); **base = `gps_corrected_field`**,
   keep run_flow/expected_catches as the value model inside rules + backtest.
4. `batting_report.py` — Stock/Change column + deviations-only read. *(small)*
5. Verify renders: Smith (RHB benchmark), a LHB (Khawaja/Head), a known sweeper vs spin
   (checks R1), a square-scorer (checks R2); eyeball vs real fields bowled to them.
6. ✅ White-ball GPS corrections already live (§3b); ODI/T20 loaders + templates go live with the
   white-ball reports.

## 8. Open questions for Tom (answer on the plan, then we build)

1. **Template red-pen (§2)** — now lit-grounded (§2a); the cells the sources left thin:
   **(a) LF-pace to RHB cordon** — review says 2 slips + gully/backward point over 3 slips;
   right? **(b)** is **third man** stock in the RF set field (sources waver between third
   man / midwicket / square leg as the flex fielder)? **(c)** spin contain shapes.
2. **Cap ≤3 deviations** and **P75 evidence bar** — right levels?
3. **Short-ball plan (R5)**: separate named variant field in the report, or a note on the set field?
4. Keeper counted implicitly (9 + keeper + bowler) — any case for keeper-up-to-pace as a
   deviation (needs evidence source)?
5. Verification batters for step 5 — who would you trust your eye on most?

---

## Appendix — v1 data audit (still valid, unchanged)

| Signal | Column(s) | Coverage | Use in v2 |
|---|---|---|---|
| Shot direction | `hit_to_angle` (absolute, flip LHB) | ~100% of scoring balls | run-flow sectors (rule triggers + backtest) |
| Shot distance | `hit_to_length`, `hit_to_x/y_physical` | same | ring vs rope split |
| Catch position | `DeliveryFielders.fielder_event_position_id` (lookup 33) | ~83% of catches | catch maps + backtest |
| False shots | `shot_quality_id` (2811) | ~38% | R6 + catch-carry model |
| Stroke | `stroke_id` (24) → `STROKE_FAMILY` | ~50% of scoring | R1/R4/R5/R7 triggers |
| Phase | `ball_of_innings` (derived) | 100% | early/set split |
| Fielder events | DeliveryFielders (1 row/ball, 97%) | position known 45% | catch norms, runs saved/cost, rider sanity checks — **not** manning (see §3) |
