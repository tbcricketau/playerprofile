# Coach view — Plans and Their players

Status: **plan, for Tom to read (04-10-2026). Nothing built.** Asked for after the field planner
went live: the series page of the coach view (Scouting → a series) "feels a bit messy" and repeats
the player packs. First the Plans section, then Their players. A draft mock-up follows once the
shape here is agreed.

## What is there now (South Africa Test series page)

1. **Plans** — six plain links: Left-arm orthodox, Left-arm pace, Off spin, Pace, Right-arm pace,
   Spin. Each opens a page of two tables over the same 12 batters: *plan for the type + field
   options*, then *how they score and get out*. Six pages, twelve tables, no pictures, "← Series"
   to get back.
2. **Their bowlers / Their batters** — a full-width row per player (headshot, name, type, tier
   chip, View report, ▶ Vision), grouped Most likely XI / In the squad / Fringe.

## What the numbers say about the Plans pages

- **The macro page and its main sub-type repeat each other.** South Africa's record against pace is
  mostly against right-arm pace (median 87% of a batter's pace balls, 78–100%). Pace vs Right-arm
  pace: the same plan sentence for 8 of 12 batters and the same field for 7 of 12. Left-arm pace is
  the one that differs (the same plan for 1 of 12), on a median 15% of the balls.
- **Spin splits more evenly** (off spin a median 44% of a batter's spin balls, left-arm orthodox
  49%), and the plans differ more: Spin vs Off spin agree on 4 of 12, Spin vs Left-arm orthodox on
  6 of 12. So the sub-type matters more for spin than for pace, and a Spin pack has to keep it in
  view.
- Every overview already carries, per batter: the plan sentence, the field (set / move / spare),
  **three field images** (early · once set · bouncer plan, 36 PNGs per group for this squad), balls,
  BPD, false-shot %, scoring side, short-ball read and most-common dismissal. The pages show the
  words and numbers and leave the pictures to the pack.

## Where the same batter is shown today

Markram's plan against right-arm pace appears on: the Right-arm pace overview, the Pace overview
(same row), each right-arm pace bowler's pack (five packs, as a card with his headshot, the plan
sentence, his dismissal facts and reels), his coach report, and now the field planner (Tom's
notes and Option 1). The coach view's *Their batters* list is the same twelve cards again, with a
report link and no plan. The REPLACEMENT_PLAN (coachhub `docs/`, §2) counts the plan at three
surfaces from one source and the roster at four; this page adds the fourth and fifth surface for
the plan.

## Proposed shape

### Plans → two packs: **Pace** and **Spin**

One page each, a card per batter, in batting-order groups (Most likely XI · In the squad · Fringe)
with the headshot, name, hand · role and tier chip the squad list already has.

- **A technique switch at the top of the page**, not six pages: Pace shows *All pace · Right-arm ·
  Left-arm*; Spin shows *All spin · Off spin · Left-arm orthodox* (and leg spin where a squad has
  one). Every card re-reads from the chosen sub-type without a reload, with the balls beside each
  option so the sample is in view ("Left-arm · 540 balls"). Default: All pace / All spin.
- **Each card carries what the two tables carry now, laid out as a card:** the plan sentence
  (length and line in bold, movement after it), a row of small figures (balls · BPD · false shot ·
  scores mostly · short ball · most often out), and the field.
- **The field on the card is the coaches' field when one has been saved, else the engine's.** The
  field planner holds Option 1 (and any further options) per batter per bowling type, set by the
  coaches; where none is saved yet the card shows the engine's suggested field (the existing
  early / once set / bouncer images). A "Set field" link opens that batter in the planner. The
  planner's notes for the batter sit on the card too. This is the one place the human judgement and
  the engine's read are side by side, and it is why the card is worth more than the table.
- **Vision on the card**: scoring shots and dismissals against the chosen type, from the batter's
  own coach-report playlist (the sidecar already exists beside every coach-cut report), and View
  report.
- **The second table goes.** Its columns are the figures row on each card. The match-ups grid and
  unorthodox-shot options stay as they are, listed under Plans beside the two packs.

What it removes: four pages and the near-duplicate Pace / Right-arm pace pair. What it keeps: every
sub-type's plan, one click away on the same page.

### Their players → the bowlers only, and lighter

- **Their batters comes off the series page.** Every batter is a card in the Pace and Spin packs
  with the View report link on it, so the list beneath is the same twelve faces a third time.
- **Their bowlers stays**, since no pack covers them, as a compact grid (headshot, name, type, tier)
  rather than full-width rows with two buttons each. ▶ Vision moves inside the report, where it
  already is; the card opens the report.
- A bowler who bats (Jansen, Mulder, Maharaj) appears once in the bowlers grid and as a batter card
  in the packs; today they are in both lists.

🔴 **Call for Tom:** dropping Their batters from the series page, or keeping it as a one-line
"Their batters: Markram · de Zorzi · …" that jumps to the cards.

### What does not change

The player packs keep their per-bowler opposition cards: a player wants the batters against *their*
type, on their own page, and that is the pack's job. The roster unification (one pin feeding every
builder) is REPLACEMENT_PLAN §5 and is separate from this.

## Where the data comes from — all of it exists

| on the card | source | state |
|---|---|---|
| headshot, hand, role, tier | the coach view's own `img/` and `series.json` tiers | built |
| plan, set / move / spare, three field images, figures | `data/overview_<group>_<opp>.json` per group, six per squad | built |
| coaches' field and notes | field planner store, `/fields/<series>/api/fields?pack=<type>` | live |
| vision | the batter's coach report sidecar (`reports/<base>.clips.json`) | built |

The page is static in the bundle like the rest of the coach view; a small script asks the planner
API for the current notes and fields when a coach opens it, so an edit in the planner shows in the
Pace pack without a rebuild. The planner's own drawing code (`playerpacks/static/fields.js`,
`drawField`) draws the saved field on the card, so the two never disagree about geometry.

Formats: the engine's suggested fields are Test-only (`field_engine`), so a white-ball Pace pack
shows the coaches' field or none, and gains the phase once the planner carries it. The plan
sentence and figures already exist for ODI squads (Zimbabwe, SA ODI overviews).

## Build

- `build_coach_site._plans` composes `plans/pace.html` and `plans/spin.html` from the group
  overviews instead of copying `site/<slug>/overview-*.html`. The six overview pages keep being
  built for the gated portal until that is retired.
- Card markup and CSS in `site_render` (Baggy green through `playerpacks/hubstyle.py` like every
  coach page); the technique switch and the planner fetch in one script file in the bundle.
- The bowlers grid replaces the two report-card sections on the series index.

## Sequence

1. Tom reads this and says yes / change / no on the shape and the Their batters call.
2. **Draft mock-up** of the Pace pack with three real batters (Markram RHB, de Zorzi LHB, Bavuma),
   the technique switch working, one card with a saved planner field and one with the engine's.
3. Build both packs and the bowlers grid; screenshot-check desktop and phone; deploy to both
   regions; the pack pages are unchanged.
4. Later, with the ODI phases in the planner: the same packs for a white-ball series.
