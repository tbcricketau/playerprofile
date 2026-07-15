# Opposition attack plans — research plan

The question a player pack must answer: **"how is this attack going to come at you?"** Not the
bowler's general profile (the scouting report has that) — the *plan* set against a specific batter:
where they bowl to him, how that differs from how they bowl to everyone else, and whether there is a
setup → dismissal sequence.

Two motivating cases, both to be verified against the data before anything is generalised:

1. **Weatherald, Ashes 2025-26.** Claimed plan: England's pacers set him up back of a length and
   short, denied him width (his cut is his strength), then attacked the stumps looking for LBW.
2. **Marnus Labuschagne.** Claimed change: he used to score strongly off his legs (negating LBW) and
   from the channel — now he tends to nick off in the channel or late-cut to gully.

Status: **research plan only — nothing implemented.** Feasibility checked against the warehouse
2026-07-15 (§2).

## 1. Framing: a plan is an input distribution, a sequence is a conditional one

The statistical lesson from matchupmodel applies directly: per-batter *outcome* deviations are mostly
noise, but *input* distributions — where the bowler chooses to bowl — are bowler-controlled and
stabilise fast. So the analysis has three layers, ordered from robust to ambitious:

- **Layer 1 — the static plan.** The length × line mix bowled *to this batter* vs a baseline (below).
  289 balls is ample to say "they bowled him 48% back-of-length-or-shorter vs 33% baseline" with a
  confidence interval. No sequencing needed — most real-world "plans" are already visible here.
- **Layer 2 — the state-conditioned plan.** The same mix conditioned on match state the bowler can
  see: ball of his innings (early vs set), ball age (new/old), spell position. "Deny him early, attack
  the stumps once he's set" lives here, and the states are few enough that the data supports it.
- **Layer 3 — sequence motifs.** True ball-to-ball structure: does a full straight ball follow a run
  of short balls more often than the bowler's own base rates predict, and do dismissals cluster after
  that pattern? This is the thinnest layer and needs the strictest gate (§5).

**The baseline matters more than the method.** "They bowled him short" is only a plan if it differs
from what the same attack did to comparable batters. The clean control for a series is **the same
bowlers, in the same matches, to other batters of the same hand** — same pitches, same conditions,
only the target changes. Fall back to the bowler's career mix vs that hand when the in-series sample
is thin.

## 2. Data feasibility (verified 2026-07-15)

`load_batter_deliveries` already pulls everything the analysis needs, in ball order
(`match_date, match_innings, over, ball_in_over`):

| Need | Column(s) | State |
|---|---|---|
| Ball ordering / passages | `over`, `ball_in_over`, `match_innings` | ✅ |
| Where it pitched / passed the stumps | `pitch_line/length`, `at_stumps_line/height` (mm) | ✅ |
| Shot played | `stroke_id` (lookup 24: Cut or dab, Pull, Flick, Glance, Leave, defences…) | ✅ rich on the Ashes balls |
| Shot outcome quality | `shot_quality_id` (false shot / edge coding) | ✅ present — decode values |
| Dismissal + mode | `striker_dismissed`, `how_out_id`, `batter_out_id` | ⚠ mode lookup id unresolved (type 15 returned null — find the right lookup_type_id; the batting report renders modes so it exists) |
| Fielder position on catches | `DeliveryFielders` (lookup 33) | ✅ (~45-54% coverage, recent-heavy) |
| Bowler identity/type | `bowler_id`, `bowler_type_simple` | ✅ |
| Vision | `delivery_id`, `video_file_name` per ball | ✅ |

Volumes: **Weatherald vs ENG = 289 balls / 9 outs** (2025-11-21 → 2026-01-04) — enough for Layers
1–2, thin for Layer 3 alone (the sequence read leans on repetition across his 9 innings, not raw n).
**Marnus: ~8.3k balls 2019–22 vs ~3.5k since 2023** — ample for an era comparison, and balls per
dismissal has already moved ~117 → ~41, so there is something to explain.

## 3. Part A — verify the Weatherald claim

Decompose the claim into five measurable propositions, each with its control:

| # | Proposition | Measure | Control |
|---|---|---|---|
| A1 | They bowled him short / back of a length | length-band mix (pitch_length) to Weatherald | same ENG pacers to other AUS LHB, same series |
| A2 | They denied him width | pitch-line distribution — share in his cut zone (wide of off) | same control + his career diet of width |
| A3 | The cut is his strength | runs/dismissals on *Cut or dab* vs other strokes, career-wide | his own career splits |
| A4 | Dismissal balls attacked the stumps | at-stumps line of the 9 dismissal balls + LBW/bowled share | his non-dismissal balls; ENG's dismissals of other AUS batters |
| A5 | The stump attack followed short setups | length mix of the 6–12 balls before each dismissal / before each full-straight ball, vs his innings-wide mix | permutation null (§5) |

Output: a one-page verification note — each proposition **supported / not supported / can't say**,
with the numbers. If A1–A4 hold but A5 doesn't clear the gate, the honest read is "a static plan
(short, no width, attack the stumps) — the data can't confirm deliberate ball-by-ball sequencing,"
which is still exactly what a player pack needs to say.

## 4. Part B — the Marnus change

This is the batter-side version of the recent-change overlay (same date-based window + ball floor +
noise gates), applied to *how he scores and gets out* rather than raw output:

- **Leg-side strength**: runs and dismissal rate on balls at/into the pads (at-stumps line on leg),
  share of scoring from Flick/Worked/Glance strokes, era vs era.
- **Channel behaviour**: on 4th–5th-stump-line balls — false-shot/edge rate (`shot_quality_id`),
  dismissal mode mix (caught behind/slip/gully share once the how-out mapping is resolved), and
  scoring rate. The claim predicts: scoring down, edge rate up.
- **The late-cut-to-gully mode**: stroke = late cut/steer × caught, fielder position = gully
  (`DeliveryFielders`) — era vs era.
- **LBW exposure**: LBW rate per ball at the stumps, era vs era (the flick negating LBW is the
  mechanism claimed).

Split: default to the same recent window as the bowler overlay (~3 years, ball floor) rather than
hunting a change-point first — if the era contrast is strong, a simple by-year trajectory of the two
or three headline measures shows *when* it moved without any change-point machinery.

## 5. Part C — generalising: the opposition-plan detector

For each of **our batters × the opposition attack** (and later each of our bowlers × their batters,
the mirror), produce a standard **plan card**:

1. **What they bowl him** — length × line mix with lift vs the baseline (§1), only cells that clear
   a proportion-gap gate at the available n.
2. **When** — the early/set and new/old-ball conditioning, where it differs from the unconditioned mix.
3. **How he's been got out** — dismissal modes + the at-stumps/pitch location of dismissal balls.
4. **Sequence motifs, if any clear the gate** — setup → payoff patterns stated in cricket terms
   ("three or more back-of-length, then full at the stumps").

**The sequence gate (Layer 3).** Encode each ball as a token (length band × line band, pace/spin
kept separate). For a candidate motif, compute how often the payoff ball follows the setup run vs
how often it would under a **within-innings shuffle** of the same balls (the permutation null — this
kills the "they bowl short a lot anyway, so short balls precede everything" artefact). Require:
(a) the lift beats the null at the sample size, (b) the motif repeats in **at least two separate
innings/matches**, and (c) it survives being stated at one coarser tokenisation (a motif that only
exists at one exact zone boundary is an artefact). Expect most candidates to die here — that is the
gate working. Three output states, as with the recent-change overlay: *plan identified / no plan
beyond the bowler's normal pattern / not enough data*.

**Where it lands:** the plan card is the natural core of the individualization batting pack — "how
Bangladesh will bowl to you" becomes this card plus its linked vision, per squad batter.

## 6. Vision linkage

Every ball carries `delivery_id` + `video_file_name`, so evidence links directly to footage:

- **Passage playlists** — for each dismissal: the dismissal ball plus the preceding ~6 balls from the
  same bowler, as one passage. This *shows* a setup better than any stat, and works even when Layer 3
  can't statistically confirm the sequencing.
- **Plan-cell playlists** — the balls in any flagged plan cell (e.g. the short/at-body diet), most
  recent first, house cap 10–20 balls.
- Coverage is per-delivery and recent-heavy, which suits this use — plans are read from recent series.

## 7. Phasing

- **P0 — Weatherald verification** (§3). One analysis script, one note. Also resolves the how-out
  lookup id and decodes `shot_quality_id` — groundwork every later phase reuses.
- **P1 — Marnus era read** (§4). Reuses the recent-change window machinery.
- **P2 — plan cards** (§5, layers 1–2 only) for the Bangladesh squad batters, feeding the player-pack
  batting sections.
- **P3 — sequence motifs + passage playlists** (§5 layer 3, §6).

P0/P1 are also the calibration exercise: two cases where a human has named the expected answer. If
the machinery can't recover *these*, it isn't ready to run unsupervised on the whole squad.

## 8. Future development (Tom, 2026-07-15)

- **"How he was attacked — last 3 series"** as a standing section in the **bowler packs**: for each
  opposition batter, the plan cards (§5) computed per series over his last three, so our bowlers see
  what other attacks tried and what worked. The P0 Weatherald analysis is exactly one such card — this
  generalises it to a rolling window.
- **The mirror for our own batters** in the general scouting pack: how the last three opposition
  attacks bowled to each of our batters (their diet, their dismissal pattern, the withheld balls) —
  both as self-scout and as a preview of what the next opposition will likely copy.
