# Field Settings Plan — justified fields without fielder-position data

**Goal:** for each batter × bowler group × phase (first 30 balls vs set), recommend a full
field (9 placements + keeper + bowler) where **every fielder is justified by a stat** the
coach can read and challenge. We never get the actual field placements per ball, so the
field must be *derived* from what the batter does — which is arguably the better
justification anyway ("this is where HIS runs and HIS edges go", not "this is what fields
he has faced").

## 1. What the warehouse gives us (data audit)

| Signal | Column(s) | Coverage | Use |
|---|---|---|---|
| Shot direction | `hit_to_angle` (absolute, flip LHB) | ~100% of **scoring** balls | run-flow sectors |
| Shot distance | `hit_to_length`, `hit_to_x/y_physical` | same | ring vs boundary split |
| Catch position | `DeliveryFielders.fielder_event_position_id` (lookup 33), catcher = `fielder_catch=1` | ~83% of catches | where he gets caught |
| False shots | `shot_quality_id` (2811): edges, top edge, mistimed, play-and-miss | ~38% | which strokes are risky |
| Stroke | `stroke_id` (24) → `STROKE_FAMILY` | ~50% of scoring balls | stroke → destination mapping |
| Intent | lookup 2810 (attacked/defended) | partial | early-phase intent |
| Phase | `ball_of_innings` (derived, in `batter_profile`) | 100% | early vs set split |

**Known holes:**
- **Dot balls have no placement** — defended/left balls are invisible in the wagon wheel.
- **Caught dismissals have no hit coordinates** — use the DeliveryFielders position label.
- **Aerial vs along-the-ground is not coded** — proxy: 6s + top-edge/mistimed = aerial;
  catches are aerial by definition; 4s treated as ground unless edged.

**✅ DeliveryFielders audit (done 2026-07-04) — the upgrade landed.** It codes **ordinary
fielded balls**, not just wickets: 4.36M distinct deliveries carry a fielder row, and
**97% have exactly one** — the fielder who *made the play on the ball*.
`fielder_event_position_id` (lookup 33, **90+ positions**, "Area: qualifier" naming e.g.
"Cover: deep", "Midwicket: regulation") is where that fielder stood = **where the ball
actually went and a fielder was there**. Plus `fielder_runs_saved` / `fielder_runs_cost`
(per event) and `fielder_catch`/`fielder_runout` bits. Coverage: **position known on 45%**
of fielder rows.
- **This gives three real signals** (not proxies): (1) a **catch map** — where he's actually
  caught, by bowler group (`fielder_catch=1` + position); (2) an **observed-field prior** —
  which positions are posted against him and how often (validates our recommendation against
  what captains already do); (3) **runs conceded / saved per position** — the high-value
  positions against him.
- **Bias to respect:** a fielder is logged only when one *makes a play*, so clean boundaries
  that beat the field are under-represented here. So **`hit_to_angle` (100% of scoring balls)
  stays the run-flow / boundary signal (Layer 1)**; DeliveryFielders drives the **catch map
  (Layer 2)** and the **observed-field cross-check**, where its "actual fielded position" is
  exactly right.

## 2. Method — three evidence layers

### Layer 1 — Run flow (containment fielders)
16-sector wagon (batter-relative, LHB mirrored) × 2 rings (inside ring / to+over the rope)
from `hit_to_angle` + `hit_to_length`, per bowler group × phase:
- runs per 100 balls per sector, boundary-runs share per sector
- **Justification stat:** "deep point cuts off the sector carrying 24% of his boundary
  runs vs off-spin" — straight from sector shares, with `n=`.

### Layer 2 — Catch generation (wicket-taking fielders)
Personal catch positions are thin (career ~30–60 caught dismissals, split by bowler type
→ 5–25 per type), so **blend with a cohort prior**:
1. New reference `build_catch_position_norms.py`: over ALL batters, the distribution
   **stroke family × bowler group → catch position** (lookup 33), e.g. "drives vs right-arm
   pace: 55% cordon, 12% cover, 9% mid-off…". This is stable (thousands of catches) and
   intuitive to a coach.
2. The batter's own false-shot profile: which strokes he mishits (shot_quality × stroke),
   by phase — already computed in the risk table.
3. Expected catch map = Σ over strokes: (his false-shot rate on stroke s) × (cohort
   destination distribution of stroke s) — **shrunk toward his own observed catch
   positions** (empirical-Bayes, K≈15 catches, house method).
- **Justification stat:** "his early false shots are 61% drives; drives vs RF pace go to
  the cordon 55% of the time; 6 of his 9 caught-vs-pace dismissals were slips/gully →
  three slips + gully."

### Layer 3 — Phase weighting (start vs set)
- **First 30 balls**: wicket-biased — rank catching positions first, accept leakage in his
  low-flow sectors (their run cost early is small: his early SR/bdry% are in the phase
  table).
- **Set**: containment-biased — boundary riders on his top Layer-1 sectors, retain only the
  top 1–2 catchers.
- The weighting itself is justified by the phase table ("4.0 vs 1.0 dismissals/100" ⇒
  attack early; "false shot 13% once set" ⇒ save runs later).

### Assembly
- Keeper + bowler fixed → choose 9. Score every candidate position:
  `value = w_phase · P(catch arrives there) + (1 − w_phase) · runs/100 it intercepts`.
- Positions snap to the **standard vocabulary** (lookup 33 names — cover, deep point,
  midwicket…) with fixed batter-relative polar coordinates defined once in
  `ludis_cricket.lookups.FIELD_POS`; mirror for LHB; annotate over/round-the-wicket with
  the bowling plan (field + plan are one artefact — reuse `plan_read`).
- Greedy fill with a diversity constraint (≤ N catchers behind square, cover both sides).

## 3. Output & the justification contract
- **Field diagram**: Plotly polar on the wagon-wheel ground (FIELD_COLOR), 11 dots +
  labels, catchers vs savers coloured differently. PDF section per report (per group ×
  phase: "Early field vs right-arm pace" / "Set field").
- **Justification table** (the part that matters): one row per fielder —
  `Position | Role (catch/save) | Why` — where *Why* is the stat + sample:
  "Deep square leg — save: pull/hook = 18% of his set-phase runs, 64% of it in boundaries
  (n=214 balls)".
- **Backtest line** (validation, printed on the report): "this early field would have been
  under **7 of his 9** caught dismissals vs off-spin" — computed by replaying his caught
  positions against the recommended catcher set; plus "% of his boundary runs through
  covered sectors". If the numbers are weak, the field doesn't ship.

## 4. Small-sample handling
- Sector rates and catch maps use the house empirical-Bayes shrinkage (K≈80 balls / K≈15
  catches) toward the bowler-group baseline; `n=` printed everywhere; minimum-ball floors
  (sector ≥ 25 balls, stroke ≥ 30) below which the cohort prior carries the estimate and
  the justification says so ("cohort prior — his own sample is 12 balls").

## 5. Build order
1. `ludis_cricket.lookups.FIELD_POS` — position id → (name, angle°, radius frac, catching?)
   for the lookup-33 vocabulary (define once; the diagram, the norms and the backtest all
   share it). *(offline-able)*
2. **[DB]** DeliveryFielders audit (section 6 queries) — decides the observed-field upgrade.
3. **[DB]** `referencebuilder/scripts/build_catch_position_norms.py` — stroke × bowler group
   → catch-position distribution (+ per-batter observed catch positions).
4. `playerprofile/field_engine.py` — layers 1–3 + assembly + backtest, off the existing
   `build_batter_profile` rows (phase + stroke + hit_to fields already there).
5. `charts.field_diagram()` + report section (combined report: early/set vs the report's
   group; focused report: that group only).

## 6. DB queries queued for when access returns
```sql
-- (a) DeliveryFielders columns
SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA='GA20260618' AND TABLE_NAME='DeliveryFielders';
-- (b) does it code ordinary fielded balls? events per delivery + share of deliveries covered
SELECT COUNT(*) n_rows, COUNT(DISTINCT delivery_id) n_delivs FROM [GA20260618].[DeliveryFielders];
SELECT TOP 50 * FROM [GA20260618].[DeliveryFielders] DF
JOIN [GA20260618].[Deliveries] D ON D.delivery_id=DF.delivery_id AND D.bat_score='0';
-- (c) full lookup-33 position vocabulary (for FIELD_POS)
SELECT id, description FROM [GA20260618].[Lookups] WHERE lookup_type_id=33 ORDER BY id;
-- (d) catch-position coverage by era/format (is 83% stable?)
```
