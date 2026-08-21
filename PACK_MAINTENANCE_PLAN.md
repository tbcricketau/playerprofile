# PACK_MAINTENANCE_PLAN — editing packs during a live series

> Status: **argued, not started** (2026-08-21, Tom). Two fronts that surfaced while adding one
> opposition bowler mid-series. Both reduce to the same missing idea: **the builders have no notion
> of state.** Nothing can be marked *frozen*, *archived* or *belonging to one squad*, so every
> builder treats every player and every reel as live and rebuildable.

## The problem, from the day it appeared

Adding Shoriful Islam to the Bangladesh packs should have touched Shoriful. It touched everything:

- `export_matchup_store.py` simulated **217** batter×bowler pairings when the Test squad needs 98.
  The excess was the 14 CA XI players, a squad **archived on 2026-08-10**.
- `build_h2h.py` moved **89 of 95** head-to-head reels onto a single day — the Test played eight
  days earlier — because it takes the newest 20 balls of the best available format.
- The head-to-head totals baked into the bowler reports count every name in `players.json`, so
  Taskin's report reads *21 batters* against a 31-name registry rather than the 14-man squad.

None of these were failures. Every builder did exactly what it was written to do.

## Front 1 — separate the teams in `players.json`

`players.json` is a flat registry keyed by player id, shared across every series and every squad.
It carries two kinds of field and only one of them belongs there:

| Field | True of the player | True of the player *in a squad* |
|---|---|---|
| `name`, `role`, `bowl_types`, `bowl_groups` | ✅ | |
| `tier` (Most likely XI / In the squad / Fringe) | | ✅ |
| `prefs`, `new_ball_footage`, `similar_bowler`, `release_detail` | arguable | arguable |

`tier` is the proof case. It is a statement about a player **in a series**, stored once on the
player, so a name in two squads can only hold one status. Everything else follows from the same
confusion:

- `squads_caxi.json` had to become a **separate file** with a `--squads` switch, plus a slug trick
  in `_opp_tiers` / `_opp_roster` to borrow the base opponent's data — rather than simply being
  another roster in `squads.json`.
- `build_squad.py` rewrites every entry preserving only `prefs`, which is why adding one player must
  be done by hand (see `CLAUDE.md`).
- Consumers read the **registry** rather than a roster. `export_matchup_store.py` is the expensive
  one; the h2h totals are the visible one.

**Shape of the fix.** One `squads.json` holding every roster keyed by slug, each with an explicit
`team` and each roster *entry* carrying its own per-series fields (`tier` at minimum). `players.json`
reduced to what is true of the player regardless of squad. Every consumer takes a **squad slug** and
resolves roster → player attributes → per-squad overrides. That one change fixes the pairing
blow-up and the head-to-head inflation together.

**Decide early:** does an archived squad stay in the file marked `archived`, or move out entirely?
Today's leak happened because "archived" meant only that the *site* was taken down — the names
stayed live in every consumer for eleven days.

## Front 2 — freeze, and a recency policy for reels

During a series we make repeated small edits. The default must be that **everything except the thing
being edited holds still**. Two distinct pieces:

### 2a. Freeze — a builder-respected "do not touch"

Merge flags exist for parts of this (`build_opponent_about --only-batters` / `--only-bowlers`,
`build_overview --only`, `build_player_site --only`) but they are per-builder and opt-in, and the
wholesale builders have no equivalent: `build_h2h.py` rebuilds every pairing, `publish_site.py`
re-bakes every report, `build_player_site.py` clears and rebuilds the lot.

Freezing by hand today means snapshotting the data file, running the builder, restoring the
snapshot and merging one player's rows back in — which is what was done on 2026-08-21 and is
written up in `CLAUDE.md`. It works, and it should not be a manual ritual.

### 2b. Recency — a reel should not collapse onto the newest match

Freezing is a blunt instrument. It preserved everyone's historical reels but also froze out footage
that was genuinely new and wanted: Ebadot Hossain had **no** head-to-head reel before the Test and
164 balls after it, and the freeze removed him again.

So the real fix is a recency policy in `build_h2h.py`, not just a freeze. Options, to be argued:

- **exclude the current series** — a reel never draws on the matches being prepared for
- **cap balls per match** (e.g. ≤8 of 20 from any one day) so a reel keeps its spread by construction
- **pin on approval** — a reel, once reviewed, holds until explicitly refreshed

The cap is the most attractive: it needs no state, it fails safe, and it makes "20 balls" mean
twenty balls of *evidence* rather than two overs of one innings. The exclusion rule is the most
faithful to what a coach wants. They compose.

## Front 3 — "rebuild only the new player" is not currently possible

Adding Shoriful Islam on 2026-08-21 took **eight** steps. **Two** had a clean per-player path, and
one of those was written that morning:

| Step | Scoped? | Wholesale cost |
|---|---|---|
| `build_reports --ids` | ✅ | — |
| `build_opponent_about --only-bowlers` | ✅ *(added 2026-08-21)* | — |
| `export_matchup_store` | ❌ `--opp` only | re-simulates every pairing (217 for a 98-pairing squad) |
| `build_h2h` | ❌ `--opp` only | re-picks every reel — **this is the reel collapse** |
| `render_matchups` | ❌ `--opp` only | inherent: it is one grid |
| `publish_site` | ❌ | re-bakes all 76 reports |
| `inject_reports` | ❌ | re-bakes all 93 |
| `build_player_site --only` | ⚠️ **trap** | clears `player_site/` first → a bundle of *only* those players |

### The distinction to build around: re-render vs re-derive

- **Re-render** (`publish_site`, `inject_reports`, `build_player_site`) — fixed inputs, same output.
  Running these wholesale costs wall-clock and mints a fresh SAS. Harmless, and arguably *should*
  stay wholesale so the bundle is always complete and internally consistent.
- **Re-derive** (`export_matchup_store`, `build_h2h`) — goes back to the warehouse and samples the
  world **as it is now**. Wholesale means silent drift: fresh Monte Carlo on every pair, and reels
  re-picked to whatever was played most recently.

**So the rule is not "rebuild less" — it is: never re-derive what you are not changing.** Only two
steps re-derive, and neither can currently be scoped. That is the whole gap.

### What to build

1. **`build_h2h.py --only <ids>`** — merge semantics identical to `--only-batters` / `--only-bowlers`:
   load the existing file, rebuild only the named players' pairings, abort the write on any failure.
   This alone removes the need for the hand-freeze recipe in `CLAUDE.md`.
2. **`export_matchup_store.py --only <ids>`** — pairs are independent, so keep the existing rows and
   simulate only the new player's row/column. Also fixes the wasted 119 pairings (Front 1).
3. **`build_player_site.py --only`** — either make it merge into the existing bundle instead of
   clearing, or rename it `--preview` and have `publish_packs` refuse a bundle whose roster is
   smaller than `squads.json`. It currently looks like the safe flag and is the dangerous one.
4. **One entry point** — `add_player.py --opp bangladesh --bowler 3630141` (or `--batter`) running
   the right steps, in order, with the right flags, and printing what it deliberately did *not*
   touch. Today that sequence lived in a chat transcript and two scratchpad scripts.

Worth noting for (4): the verification steps matter as much as the build steps. Today's run checked
that the merge was surgical (every other row byte-identical) and that no reel outside the new player
referenced the current series' dates. Both were one-off scripts. They belong in the entry point.

## Why this is worth doing before the next series

The failure mode is silent in every case. A pack whose reels have collapsed looks identical to one
that hasn't — same button, same ball count — and a pack built from a stale registry looks complete
while carrying another squad's players in its numbers. Nothing errors, nothing fails the publish
gate, and the link check and hand audit both pass. These are exactly the defects that the
reel-scoping rule was written for, arriving on a different axis.
