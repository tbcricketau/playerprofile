# Coach view — Plans and Their players

Status: **built and live (04-10-2026)** — Pace and Spin packs, the tab row, the bowlers grid; the Batting tab for our batters is the next piece. Asked for after the field planner
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

**Decided (Tom, 04-10-2026): Their batters comes off the series page.** The Pace and Spin packs are
where the batters live.

### One way to move around a series (Tom, 04-10-2026)

Today a series has two navigations: "Field plans" is a button in the top bar, everything else is a
link on the page. The draft shows one: **a row of tabs in the series band** — Their bowlers · Pace ·
Spin · Field plans · Match-ups · Unorthodox shots — on every page of the series, with the crumb above
it back to Scouting, and **no button in the top bar**. The field planner is already per series
(`/fields/<series>/`), so it is a tab like the others, and its bowler-type tabs become its own second
row. On the players' side the planner stops being a bar button too and becomes a card on the packs
index ("Field plans — the fields the coaches have set"), beside the squad list. The hub bar then
carries only the crumb trail, which is what it is for.

### Batting plans and bowling plans (Tom, 04-10-2026 — plan and draft, not built)

**Navigation.** After choosing a series, the top row is two tabs: **Batting plans** and **Bowling
plans**. Each has its own second row:

| Batting plans (their bowlers, for our batters) | Bowling plans (their batters, for our bowlers) |
|---|---|
| **Their bowlers** — a card per bowler, with a **vs RHB / vs LHB** switch | **Pace** — as built |
| **Set Field Plans** — the planner, for their bowlers | **Spin** — as built |
| Match-ups (where built) | **Set Field Plans** — the planner, as built |
| | Unorthodox shots (where built) |

The series page opens on Batting plans → Their bowlers, which replaces today's bowlers grid. The
crumb above both rows goes back to Scouting.

**Their bowlers — the mirror of the Pace and Spin cards.** A card per bowler, grouped Most likely XI ·
In the squad · Fringe, with the hand switch at the top of the page (vs right-handers / vs
left-handers, with the balls behind each). On each card, for the chosen hand:

- **Who**: headshot, name, type, tier chip.
- **How to play them**: the bowling report's `how_to_play` lines for that hand (what to respect,
  where to attack, what to watch) — the batting twin of the bowling plan sentence.
- **Coaches' notes**: from the planner, kept per bowler per hand.
- **Figures**: balls to that hand, average, economy, Bowl SR, pace (average and p99 top speed; spin
  shows none), short % for pace, round-the-wicket %.
- **The field they are likely to set**, by **category**: the categories each bowler gets come from
  their record — **New ball** when they take it (Rabada 57% of new-ball overs, Paterson 23%;
  threshold to settle, 20% in the draft), **Old ball** for every pace bowler, **Bouncer plan** for
  pace; spinners get **Attacking** and **Holding**. Chips under the field switch between them, the
  same as the bowling cards, with the spare named underneath.
- **Vision and the report**: their stock-ball and wicket reels to that hand, and the coach report.

**Where the fields come from.** We hold no record of the fields South Africa actually set, so the
auto-generated field is **our best estimate of theirs**, built in two steps:

1. The stock field for the bowler's type, our batter's hand and the phase — the same GPS-corrected
   stock the bowling-side engine starts from (`cricket_core.fields.gps_corrected_field`), and the
   bouncer field (`fields.SHORT_BALL`). **The draft shows this step only.**
2. **(build)** Adjusted to the bowler: where they concede runs to that hand (their run flow) and
   where their catches have gone (their caught positions), with the spare — the
   `field_engine.build_field` logic run on the bowler's deliveries instead of a batter's. The engine
   reads batter-shaped rows (early/set, false shots, run flow), so this needs a bowler adapter, and
   it is the one piece of new analysis here. It should say so on the card until it is checked against
   real fields we can watch on vision.

**Set Field Plans for their bowlers.** The same planner, a second side: a page per batter hand
(vs RHB, vs LHB) with a card per bowler — notes, the field (Option 1 from the auto-generated field,
editable, renameable, more options added), arrows, the spare. Tags for this side: **New ball, Old
ball, Second new ball, Bouncer plan, vs Tail, Over the wicket, Round the wicket, Reverse swing, Into
the wind, Day 1, Day 4-5, Attacking, Holding**, and coaches add their own as on the bowling side. The
store is the planner's: a field belongs to a series, a page and a player, so their bowlers fit it by
using the hand as the page (`vs_rhb`, `vs_lhb`) and the bowler as the player.

**What is new to build**: the bowler field adapter (step 2); an export of their bowlers for the
planner (headshot, notes start empty, the categories and their fields, runs-conceded wheels per
hand); the Batting plans pages; the planner's second side and tags. What exists: the per-hand
profile (`profile.build_profile(hand="vs RHB")`), `how_to_play`, the per-hand reels in
`opponent_about`, the coach reports, the planner and its store.

**Draft (04-10-2026): https://claude.ai/artifact/YCgoD5tduq54s4UzMpFJet** — four bowlers (Rabada, Jansen, Maharaj, Harmer), real per-hand figures from the build machine, the two tab rows, the hand switch, stock fields per category, and an example coaches' field on Rabada vs right-handers. It showed one defect to fix in the build: `profile._how_to_play` writes he/his/him, which reader-facing text may not (the draft rewrites the lines; the bowling reports carry the same lines).

**Questions for Tom** — (1) the new-ball threshold (20% of new-ball overs in the draft); (2) spinners'
categories: Attacking and Holding, or something else (into the rough, vs tail); (3) whether the
series opens on Batting plans or Bowling plans; (4) whether the players' packs get the bowler-side
fields too, as they get the batter-side planner.

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

1. ✅ Tom read this (04-10): yes to the shape, Their batters dropped.
2. ✅ **Draft mock-up** of the Pace pack — https://claude.ai/artifact/T1iFV27g72grZLbsypfQex (five real batters, the switch
   working, Markram with a planner field, the rest with the engine's, the thin cases). One thing it
   shows that the plan did not: the engine's suggested fields are PNGs in a different drawing from
   the planner's, so a page mixes two field styles. The fix is to export the engine's fielders as
   angle/radius beside the images and draw both with the planner's code — a small change to
   `build_overview._field_images`.
3. ✅ **Built and live (04-10).** `build_coach_site.py` writes `plans/pace.html` and `plans/spin.html`
   (`coach_pack.js` + the planner's `/static/fields.js` draw every field, engine's and coaches'),
   the series page is the bowlers grid under the tab row, the planner carries the same row, and
   the packs index gets a Field plans card. The six SA Test overviews were rebuilt on the box so
   each suggested field carries its fielders (rows, plans and figures unchanged). Checked: 12
   browser checks locally (fields drawn, the switch, the planner's field and notes arriving) and
   the live check in both regions.
4. Later, with the ODI phases in the planner: the same packs for a white-ball series.
5. ✅ **Fixes after use (04-10)**: Pace and Spin show the techniques only (no All); one field panel
   for both kinds (label and tags on top, options underneath, the spare); set/move gone, spare kept
   (the engine names one per auto field, coaches set one in the planner); no short-ball figure on
   Spin; the planner tab is Set Field Plans and the planner page is light like the rest.
6. **Batting plans** — plan above, draft out; build on Tom's word.
