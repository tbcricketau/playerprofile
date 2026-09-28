# South Africa Test packs — handoff

Written 28-09-2026. Everything up to the last build step is done; one credential stands between here
and a published bundle. Read this, then `CLAUDE.md` § *`pitch_length` is NOT NULL* before touching
anything that reads a length.

## The goal

Australia's Test packs for the South Africa tour, published to **`tbcricketau/player-packs`
alongside the existing SA ODI packs** — not replacing them (Tom, 27-09: *"won't be replacing the ODI
packs, they'll sit alongside"*). That is the two-squad shape `ausa` already proved: `build_player_site
--nest` writes a series selector and puts each squad under its own slug. Tom also wants the **new
site** (`playerpacks.cricketanalyticshub.com`) carrying the same content so he can compare.

## 🔴 The blocker — read this first

**`build_opponent_about.py` cannot run**, and nothing downstream of it can either:

```
ABORTING: no Fairplay SAS (RuntimeError: The managed identity cannot sign a link: a user
delegation key is an account-level operation and our grant is on the container …). Every
Fairplay clip would read as missing and the reels would be written SHORTER than they are
now. Nothing was changed — fix the credential and re-run.
```

That guard is **right** and must not be worked around — it exists because on 13-09 a credential
failure silently rewrote reels shorter (Raza's wicket balls to left-handers 14 → 3). `PROBE_CLIPS`
is a module constant with no flag, so there is no supported no-vision mode. Checked and confirmed:

* the **managed identity cannot sign** (container-scoped grant; `can_sign_links: False`),
* **no pre-minted SAS** exists in any reachable environment (`FAIRPLAY_SAS` unset locally; the Ludis
  copy no longer fetches),
* **Tom's own sign-in has expired** (`auth_report()` → `credential: user SSO`, `can_read: False`,
  and a device-code prompt that nobody answers).

**Two ways out, both needing Tom:**

1. **Mint a SAS** — `mint_fairplay_sas.py` from his signed-in laptop. Lasts ≤7 days. Fastest, and
   it unblocks today. ⚠ The script is in **`livematchdashboard/`**, not `playerprofile/` (corrected
   28-09). Run it without `--upload` to mint and print; **write it to a file rather than to a
   terminal** — a SAS is a credential, and `sig=` in a blob URL is exactly what the estate's
   secret-scan hook exists to catch.
   ⚠ It signs in by **device code, which lapses in about 15 minutes** and fails with
   `ClientAuthenticationError: Timed out waiting for user to authenticate`. Two codes went unanswered
   on 28-09 and the build sat idle. Mint it when someone is **at the browser**, not before.
2. **IT grant `Storage Blob Delegator`** at *account* scope on `auscricketfairplayase`. Permanent,
   and it is what lets a pack build run unattended on the build machine. See
   `cricket-core/docs/AZURE.md` — the cost of not having it is written up there.

## What is already built, and where

⚠ **The reports are on the build machine, not the laptop.** That is deliberate: `build_reports.py`
fetches vision, and on a laptop that means a Fairplay **device-code sign-in that times out and kills
the batch** when nobody is at a browser. The box reads Fairplay through the managed identity with no
prompt. See `cricket-core/docs/build-machine-CLAUDE.md`.

| Thing | State | Where |
|---|---|---|
| Australia Test squad (16) | ✅ committed `8570399` | `squads.json` → `south-africa-test-away-2026` |
| Neser + Kuhnemann registry entries | ✅ added 28-09 `753c645` | `players.json` — without them neither got a bowling page |
| South Africa squad (18) | ✅ **ANNOUNCED, re-pinned 28-09** | `matchupmodel/data/opp_squad_south_africa_test.json` |
| Test matchup store | ✅ **296 pairings** (120 + 176), rebuilt 28-09 | `matchupmodel/data/matchup_store_south_africa_test.json` |
| `h2h_south_africa_test.json` | 🔴 **needs rebuilding** — built on the 16-name pin | box: `~/projects/playerprofile/data/` |
| 9 SA bowler Test reports | ✅ 0 failed, but **2 short** (Nortje, Paterson) | box: `~/projects/playerprofile/reports/` |
| Ackerman batting report + 48 focused | ⬜ not started — blocked with everything else | 12 batters × 4 bowler groups |
| `opponent_about_south_africa_test.json` | 🔴 **BLOCKED** | — |
| `series.json` entry | ⬜ not started | needs the above |
| Bundle config | ✅ two squads | `publish_packs.py` → `BUNDLES["aus"]["squads"]` |

The store and both squad pins are in the media store, so any machine can fetch them:
`py cricket-core/scripts/shared_data.py pull packs`.

## Resume, in order

On the **build machine** (`ssh -i C:\Users\<you>\.ssh\ca_builder azureuser@20.70.69.5`, then `cc`
for a tmux session that survives a dropped phone connection):

```bash
. ~/.ca_env && cd ~/projects/playerprofile
export FAIRPLAY_SAS='?sv=…'                       # step 1 above; or skip once IT grants the role
venv/bin/python build_opponent_about.py --opp south_africa_test --fmt Test
venv/bin/python squads.py --check south-africa-test-away-2026     # must come back clean
venv/bin/python build_player_site.py --squad south-africa-test-away-2026 --nest
venv/bin/python publish_packs.py aus --dry-run                    # every gate, nothing pushed
venv/bin/python publish_packs.py aus                              # only when the dry run is clean
```

`squads.py --check` is the roster gate and it will tell you exactly what is missing — when this was
left it reported `about: missing`, `h2h: missing` (now built) and `series.json has no entry`.

⚠ **`publish_packs.py aus` force-pushes over the live SA ODI packs repo.** The two-squad config is
what keeps the ODI packs alive; verify the bundle contains *both* slugs before pushing.

## Decisions — one settled, one open

**Settled (Tom, 27-09): the untracked-length bug.** `attack_cards.py` was the last raw reader of the
warehouse's pre-bucketed length groups. Mulder's `<1 m` bucket held **322 balls of which 4 were
real** — his card said a quarter of the balls at him were pitched up when the truth is 0.5%. Fixed in
`325d648`: tracked balls on **both** sides of the ratio, cells below `MIN_TRACKED` (30) dropped.
Validated — Smith (100% tracked) unchanged, Mulder 27% → 12.7%, Brevis (41%) suppressed entirely.
Shipped work stays as it is and must not be rebuilt on or cited. **Expect four South Africans to show
no length plan**: Brevis 41%, Bosch 48%, Mulder 73%, Bedingham 88% tracked. That is correct, not a
build failure — two Harare Tests in 2025 at 0.0% tracked cause nearly all of it and **no source can
fill them** (`referencebuilder/docs/TRACKING_DATA_GAP.md` — the cricviz supplement covers 1.4% and
the mirror ends in 2024).

**Settled (28-09): the squad was announced, and the guess was 15 of 16.** Re-pinned from the team
sheet. **Out:** Dewald Brevis. **In:** Marques Ackerman (4353762), Anrich Nortje (4090011), Dane
Paterson (3200006) — each a *unique* surname match in the men's Players table, so no first-name or
career-volume guess was involved. Store rebuilt on it (296 pairings); all 12 of their batters and
all 11 bowlers are in it. The provisional pin and a timestamped `.bak` sit beside the live file.

Three consequences:

* **Two more bowler reports** (Nortje, Paterson) and **one more batting report** (Ackerman). Brevis's
  renders are surplus, not harmful.
* **`h2h_south_africa_test.json` must be rebuilt** — it was built against the 16-name pin, so it
  cannot carry the three new players. No freeze needed: the Test h2h order is Test/FC only, so the
  ODIs being played now cannot be pulled into it.
* ⚠ **Ackerman is UNCAPPED in Tests** — zero balls in `International Tests M`; his record is 498
  balls of `International 1st Class M` (a-team), 188 List A, some domestic T20. A Test-scope build
  finds nothing, so he carries the thin all-formats card rather than a plan. Correct, not a failure.

**Four bowler groups, not two** (measured 28-09, not assumed): `right_pace`, `left_pace` (Starc),
`off_spin` (Lyon, Head, Renshaw), `left_orthodox` (Kuhnemann, Connolly). So the focused batter set is
**12 × 4 = 48 renders**. The store types Cummins, Boland, Lyon and Starc itself; it does **not** type
Connolly or Renshaw, who are part-timers with no sim profile and are carried by `players.json` alone
— the silent-failure field, and both are covered.

## Traps

* **A length group is not evidence a length was measured.** The `_1_` columns this project uses
  (2819 / 2821) behave *differently* from the `_2_` ones matchupmodel uses — pace is worse (82.4%
  untracked, not 47.5%), spin much better (19.4%, not 79.6%). Do not carry a figure between them.
* **Filtering only the numerator is the same bug wearing a different hat** — it deflates every other
  zone. `odi_profile`'s `short%` had exactly that form.
* **13 hard-coded `c:\Projects\…` paths** across five files went through `project_path()` in
  `9606047`. They resolve identically on Windows; they are the only form that works on the box.
* **The renderer on the box needed three goes.** Snap Chromium is unusable under confinement, and the
  Chrome `choreo_get_chrome` fetches is missing 12 shared libraries — both fail with the same
  useless *"browser seemed to close immediately"*. `ldd <chrome> | grep "not found"` is the
  diagnosis. Already fixed there; do not re-solve it.
