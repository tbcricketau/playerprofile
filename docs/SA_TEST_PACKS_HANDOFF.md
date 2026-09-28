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

## ✅ The blocker is gone (28-09) — the box builds without a SAS

`build_opponent_about.py` aborted on the box because the managed identity **cannot sign** a link,
and every builder read "cannot sign" as "cannot probe". The guard was right — on 13-09 a credential
failure silently rewrote reels shorter (Raza's wicket balls to left-handers 14 → 3) — but the
premise was too narrow: the identity **can read**, and a clip's existence is a read. The fix is in
`cricket_core.video.prime_vision` and `CLAUDE.md` § *A credential that can read but not sign*.
Proven the same day on this squad: about built in **12 min** with full reels, h2h and 62 renders
behind it, no token anywhere. The two routes below are kept for the GitHub Pages copy, which still
needs signed links at **publish** time — and for the laptop, which has no identity.

**What still needs Tom, and when:**

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
| `h2h_south_africa_test.json` | ✅ rebuilt 28-09, freeze-verified (100 identical, 18 added) | box + laptop `data/` |
| 11 SA bowler Test reports | ✅ all with sidecars, 60–80 clips each (9 re-rendered — the 27-09 ones had none) | box + laptop `reports/` |
| 12 combined + 48 focused batting reports | ✅ 62 renders, **27 min** on the box, 1 transient retry | box + laptop `reports/` |
| 6 Test overviews (JSON + HTML) | ✅ built on the box; **both** files synced | `data/` + `reports/overview_*_south_africa_test.html` |
| `opponent_about_south_africa_test.json` | ✅ **12 min in identity mode**, full reels | box + laptop `data/` |
| `series.json` entry | ✅ `01d6be2` — every bowler at `squad` until Tom names the XI | — |
| Bundle config | ✅ two squads | `publish_packs.py` → `BUNDLES["aus"]["squads"]` |
| **GitHub Pages** | ✅ **LIVE 29-09 01:41**, both squads nested, ODI URLs unchanged; 1,778 reels / 0 defects | `tbcricketau/player-packs` `1b9191f` |
| App (storage) + both coach views | see the board — pushed after this table was written | `packs/aus` |

The store and both squad pins are in the media store, so any machine can fetch them:
`py cricket-core/scripts/shared_data.py pull packs`.

## Resume, in order — two machines, and which does what

**The box does the unattended heavy steps and needs no token.** Run 28-09 in tmux sessions
(`ssh -i C:\Users\<you>\.ssh\ca_builder azureuser@20.70.69.5`, logs in `~/build_logs/`):

```bash
. ~/.ca_env && cd ~/projects/playerprofile
venv/bin/python build_opponent_about.py --opp south_africa_test --fmt Test      # 12 min, done
venv/bin/python build_h2h.py --opp south_africa_test --fmt Test                  # done, freeze-verified
venv/bin/python build_reports.py --format Test --hand all --ids 4090011 3200006 --target-country "South Africa"
venv/bin/python build_batting_reports.py --ids <12 batters> --fmt Test --mode combined
venv/bin/python build_batting_reports.py --ids <12 batters> --fmt Test --mode focused --group <G>   # x4
venv/bin/python build_overview.py --opp south_africa_test --fmt Test --group <G>  # pace spin right_pace left_pace off_spin left_orthodox
venv/bin/python squads.py --check south-africa-test-away-2026                    # "rosters agree"
```

⚠ **Do NOT run `build_player_site` or `publish_packs` on the box.** It holds no ODI reports and no
baked `site/`, so a bundle assembled there carries the Test squad alone and `publish_packs aus`
force-pushes it over the live ODI packs. The laptop has the ODI state.

**The laptop assembles both squads and publishes, with one sign-in.** Sync the Test outputs down
first (`reports/*_test_*` with their `.pmode/.player/.playlists` sidecars, `data/opponent_about_
south_africa_test.json`, `data/h2h_south_africa_test.json`, `data/overview_*_south_africa_test.json`).
The laptop has no identity, so its probing needs a SAS, and the GitHub push needs signed links
anyway — mint once while at the browser (`livematchdashboard/mint_fairplay_sas.py`, to a file, into
`FAIRPLAY_SAS`), then:

```powershell
# BOTH squads' coach bakes, not just the Test one: the scheduled refresh of 27-09 08:56 cleared
# site/ and then died on the expired sign-in (task result 267014), so site/ holds only .git.
.\venv\Scripts\python.exe publish_site.py --out site --only south-africa-odi-away-2026 south-africa-test-away-2026
.\venv\Scripts\python.exe inject_reports.py --slug south-africa-odi-away-2026
.\venv\Scripts\python.exe inject_reports.py --slug south-africa-test-away-2026
.\venv\Scripts\python.exe build_player_site.py --squad south-africa-odi-away-2026 south-africa-test-away-2026 --nest
.\venv\Scripts\python.exe build_coach_site.py --slug south-africa-test-away-2026      # Tom: yes, same as ODI
.\venv\Scripts\python.exe publish_packs.py aus --dry-run                                # every gate
.\venv\Scripts\python.exe publish_packs.py aus                                          # GitHub Pages
.\venv\Scripts\python.exe publish_packs.py aus --target storage --coach                 # the app
```

`--nest` keeps the ODI packs at `players/south-africa-odi-away-2026/…` — they were already nested
as the only squad precisely so adding this one would not move a published link (the Zimbabwe 404s
of 19-09). **Verify the bundle contains both slugs before either push.**

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

* **Do not run the overview groups in parallel on the box — measured 28-09.** Six
  `build_overview` processes plus a re-render sat 25 minutes at **5 s of CPU each**, and a bare
  `SELECT 1` from the box took **18.3 s**; with the six stopped the same probe took **0.4 s**. The
  link was slow because it was loaded, not on its own. Two processes on it is the regime that ran
  all evening; seven is what broke it. Sequentially a group is ~10 min with the link to itself.
* **A wedged warehouse call never times out, and it looks like slow work.** `build_overview` sat
  23 min on 10 s of CPU after a TCP blip, and a `build_reports` batch stalled at 6 of 9 the same way.
  Judge by `ps -o etime,cputime` — CPU flat over minutes is the wedge — kill it, and re-run the
  ids or group that were in flight. Every render that was re-run after a kill succeeded first time.
* **`pkill -f <script>` kills the shell that runs it.** The remote `bash -c` command line contains
  the script name, so `pkill -f build_overview.py` matched and killed the ssh session mid-script —
  twice, the second time through the `[b]uild` bracket form, because the launch string later in the
  same command still contained the literal name. Never put a `pkill` in the same command as a
  launch; clean up with `tmux kill-session` and check with `pgrep -af "[b]uild_…" | grep -v "bash -c"`.
* **The scheduled refresh clears `site/` BEFORE it needs the credential.** With the sign-in expired
  it wipes every baked series and then hangs on the device code; the task is killed (267014) and
  nothing is re-baked. After any expiry, assume `site/` is empty and re-bake every live slug before
  assembling a bundle — the assemble copies from it, and `check_site` would refuse on dead links
  rather than silently ship them, but only after the time was spent.
* **The nine bowler reports rendered 27-09 had no vision and no sidecar.** The pre-mint raised
  inside the `try` that builds the playlists, the block was skipped, and `.playlists.json` was never
  written — so `_sidecar_map` could not see them at all. Re-rendered 28-09 in identity mode: 60–80
  clips each. A report with no sidecar is invisible to the site, not merely vision-less.
* **`build_overview` writes TWO things, and `publish_site` reads the one you did not sync.** The
  JSON in `data/` feeds the packs' inline plan; the coach site's meeting-overview pages are copied
  from **`reports/overview_<group>_<opp>.html`** (`publish_site.py:383`), pre-rendered by the same
  run. Pulling `data/overview_*.json` off the box and a `reports/*_test_*` tar left the Test coach
  view with no plans tab, because `overview_pace_south_africa_test.html` ends in `_test.html` and
  matches no `*_test_*`. Sync both, and glob on the opponent key, not the format token.
* **Two squads in one build: anything deduped on player id alone is wrong.** Nine South Africans are
  in both squads. The opposition-headshot copy skipped them for the second squad (`_SITE_IMGS`,
  353 dead `img/` links, refused at the dry run) and `_scouting_urls` handed the ODI packs their
  Test bowling reports (no gate saw it). Both fixed 28-09; the pattern is the thing to remember.
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
