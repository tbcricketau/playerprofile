# Attack-card redesign — "How did they bowl to you?"

Plan to rework the pace plan cells in the batting packs (`attack_cards.py` `_pace_defs` +
`_diet_cells` + the summary sentence). Spin cells read well already; this is about the pace side,
which Tom flagged as *busy but missing the tactical picture*. The **key question the card must
answer in one read**: *how did they bowl to you* — e.g. "they came round the wicket and attacked
your stumps" or "they stuck to a good length in the channel".

## What's wrong now
- **Too many length buckets** — very full / full / fullish / good length / back of a length /
  short of a length / short = 7 rows. A reader can't hold that; most are natural variance.
- **No over/round-the-wicket axis** — the single biggest tactical choice against a batter isn't
  shown at all. "Round the wicket at the stumps" is exactly the kind of read Tom wants.
- **"On leg" is ambiguous** — is that *pitching* on leg (pitch map) or *at the stumps* on the leg
  side (beehive)? The house rule (CLAUDE.md) is to always disambiguate pitching line vs stump line.
- **Pace vs spin flag inconsistency** (the z-test issue, see below).

## Target output
Two layers, both plain-language:
1. **One-sentence read** at the top of the pace block, assembled from the 2–3 axes that actually
   moved: `{angle} + {length} + {line/target}`. Examples:
   - "They came **round the wicket** and attacked **your stumps** on a **good length**."
   - "They stuck to a **good length in the channel**, over the wicket."
   - "They went **fuller and straighter** than they did to your teammates."
2. **A compact table** (4–5 rows max) behind it, one row per axis, You vs Others + a flag — so the
   claim is auditable but not the first thing you read.

## The axes (replace the 7 length rows with 3 orthogonal axes)
1. **Angle** — over vs round the wicket (`over_the_wicket`). New. This is the headline tactical
   choice and reads naturally.
2. **Length** — collapse to **3 bands**: *pitched up* (full+), *good length*, *short* (back-of-a-
   length + shorter). Drop the fine 6-way split; keep the fine bands only in the underlying data for
   the dismissal detail, not the plan summary.
3. **Line** — **disambiguated**, and stated as the *target*, not a raw zone:
   - pitching-line channel vs at-the-stumps vs wide — labelled **"pitched …"**.
   - the stump-line target (beehive) as **"at the stumps / at your pads / outside off"** — labelled
     **"attacked …"** so it's clear it's where the ball ends up, not where it lands.
   - retire the bare "on leg"; split into *pitched on leg* vs *attacked your pads* explicitly.
4. Keep the two **composite danger balls** as they are useful and concrete: *cut ball* (short, wide
   off) and *full at the stumps* — these are already good and Tom likes the specificity.

## Fix the pace-vs-spin flag inconsistency (item I)
Current flag = a **two-proportion z-test** (`abs(z) >= 2.0`). z scales with sample size, and a Test
series has far more pace balls than spin — so the *same* percentage gap clears the bar for pace but
not spin (why an 18% vs 13% pace gap flags "more" while 39% vs 29% spin stays "even"). For a
player-facing read that's confusing.

**Change to a magnitude-first rule, identical for pace and spin:** flag "more/less" when the raw
gap `|you − others| ≥ ~8 percentage points` **and** a light reliability guard (`|z| ≥ ~1.3`, plus
the existing min-ball floor) so it isn't pure noise. Result: a ~10pp gap reads the same way whether
it's pace or spin, and trivially-small-but-significant pace gaps stop shouting. (Re-verify the P0
Weatherald / P1 Marnus cases still reproduce after the change — their flagged cells were large gaps,
so they should.)

## Build order
1. Add the **angle** axis + collapse length to 3 bands in `_pace_defs`; disambiguate the line labels.
2. Swap the flag gate to magnitude-first in `_diet_cells` (applies to spin too — consistency).
3. Write the **one-sentence read** assembler (pick the 1–3 axes with the biggest moves, phrase as
   angle → length → target).
4. Re-verify P0/P1; rebuild `data/attack_cards.json`; redeploy.
5. Mirror the same 3-band + angle treatment on the **scouting** batting reports' "how attacks bowl
   to them" section for consistency.
