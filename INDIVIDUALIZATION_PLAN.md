# Profile Individualization — plan

Two audiences, two links. The existing scouting site stays as-is for coaches and selectors; a new
**player site** gives each of our squad players their own tailored pack plus footage of themselves
against the specific opposition players they are about to face.

## 1. The two products

| | General scouting site | Player site (new) |
|---|---|---|
| Audience | Coaches, selectors | Our players |
| Link | one URL, opposition-organised | one URL, a roster of our squad names |
| Navigation | Series → report type → opposition player | Series → our player → their pack |
| Content | the full opposition report set | per-player subset of the scouting material + their own vs-opponent footage |
| Builder | `publish_site.py` (unchanged) | `build_player_site.py` (new) |

The general site already exists (`publish_site.py` → `site/`, driven by `series.json`). The player
site is a parallel bundle built the same way (static, SSO-minted SAS, periodic refresh) so it inherits
the video model and needs no new IT grant.

## 2. What a player's pack contains

Every squad player lands on their own page. The page is assembled from **parts of the scouting
report**, chosen per player.

- **Every player gets a batting pack** — how the opposition bowlers will attack them, drawn from the
  opposition **bowling** scouting reports (their matchups vs this batter's hand, danger balls, setups).
- **Bowlers and all-rounders also get a bowling pack** — how to bowl to the opposition batters, drawn
  from the opposition **batting** scouting reports (each batter's vulnerabilities, fields, matchups).
- **All-rounders always get both, regardless of injury/availability** — allocation is by *role*, not
  by whether they will actually bowl in the series. Simpler, and cheap to over-provide.
- **Vs-opponent video playlists** (see §5) — footage of this player against each opposition player
  they have faced.

### The base pack
For now, **base = the whole report** — a player with no defined preferences gets everything their
role entitles them to. This is deliberately a placeholder. Once Tom has coach feedback we will define
a leaner base and let each player's stored preferences override it. Do not over-design the base yet.

## 3. Config model

Two JSON files, separating the three concerns Tom named — a Tom-supplied per-series roster, a derived
player registry, and preferences that persist across series.

- **`squads.json`** — the per-series roster Tom supplies. Series slug → `{name, opposition, format,
  players: [player_id, …]}`. One entry per series; edited by hand or seeded by `build_squad.py`.
- **`players.json`** — the persistent per-player registry, keyed by `player_id`:
  `{name, role, packs, prefs}`. `role`/`packs` are **derived** (§4); `prefs` holds each player's pack
  preferences and **follows the player across series** (Tom: "store preferences so a future series
  already knows what they want"). `prefs: "base"` for now.

`build_squad.py` resolves a supplied list of names for a series, writes the roster into `squads.json`,
and **merge-updates** `players.json` — it never clobbers an existing player's `prefs`, so preferences
survive a re-run and carry into the next series that names them.

## 4. Role derivation

Role is **derived from the warehouse; Tom confirms exceptions** (he expects it mostly right).

Classify each player from their career ball-by-ball record across all formats — batting position and
the **bowl-to-bat ball ratio**:

- `avg_pos ≥ 8` → **Bowler** (bats in the tail).
- top-order bat (`avg_pos ≤ 7`) **and** a real bowling load (`bowl_balls ≥ 1000` and
  `bowl/bat ratio ≥ 0.40`) → **All-rounder**.
- `ratio ≥ 0.9` → **Bowler**; otherwise → **Batter**.

The ratio matters because a part-timer accrues thousands of career overs but bowls little relative to
batting — a raw ball count alone misfiled Head, Labuschagne and Smith as all-rounders. Only the
batter-vs-(bowler|all-rounder) split gates a pack, so a borderline case is biased toward **getting**
the bowling pack (a genuine all-rounder without one is the costly error). Prior art:
presentationbuilder `predicted_squad._role`.

Verified on the Bangladesh-home extended squad (16 players): Head/Weatherald/Labuschagne/Smith/Carey/
Inglis/Renshaw → Batter; Green/Webster → All-rounder; Cummins/Starc/Lyon/Hazlewood/Boland/Doggett/
Murphy → Bowler. Nine get a bowling pack.

## 5. Vs-opponent video playlists

For each of our players, a playlist of footage of **that player against the specific opposition
player** — the exact matchup they are about to face:

- a **batter's** pack shows them **batting vs each opposition bowler**;
- a **bowler's** pack shows them **bowling to each opposition batter**.

Rules: **same format only**, only pairings they have **actually faced**, capped at **10–20 balls of
the most recent footage**. Ordering follows the **same conditions-precedence + recency logic the
scouting playlists already use** (`cricket_core.lookups.conditions_tier` → target-country bucket, then
recency). Clip access via the shared `cricket_core.video`; SAS minted at build/refresh time like the
scouting site.

## 6. Build pipeline

`build_player_site.py` builds `player_site/` mirroring `publish_site.py`:

- top index = the series' roster of our players (grouped by role), each linking to their page;
- per-player page = header (name, role, photo) + the allocated pack sections + vs-opponent playlists;
- static bundle, SSO-minted SAS, refreshed on the same cadence; deployable to the same class of host.

The page shell and cards come from `site_render.py` (shared with the scouting site and the audit
webapp) so the two sites look like one system.

## 7. Status

- ✅ Scoping decided; scaffold built + approved (roster, pack shells, role split, photos).
- ✅ Batting packs carry the **last-3-series attack card** (2-sentence read + plan table +
  dismissal table with ▶ vision) — `attack_cards.py` + `build_player_site.py`.
- ✅ **Vs-opponent vision LIVE** — `build_h2h.py` real meetings (Tests, ≤20 newest balls per
  opponent) → per-opponent playlists in each pack; honest empty-states for no-meetings /
  not-clipped. Smith v Taijul/Mehidy/Shakib resolve from the 2017 footage.
- ✅ Scouting side rebuilt around the same stores — `SCOUTING_REBUILD.md` (matrix page, vs-our-squad
  strip, batting report v0.3 with "Our Best Options").
- ⏸ Bowling packs' content (how to bowl to their batters — assembled from the upgraded batting
  reports once red-penned).
- 🔴 Base-pack definition — awaits Tom's coach feedback.
