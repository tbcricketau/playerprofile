# Player pack redesign — audit and proposal (05-10-2026)

**Scope.** The packs the hub serves (`playerpacks`, "Player Packs" tile). The GitHub Pages copy on
tbcricketau stays exactly as it is until the South Africa Test series ends, then goes. Nothing here is
built yet: this is the audit and the mockups, for Tom's read.

**Mockups:** https://claude.ai/artifact/RTHK25zNNR2x51GV62UMky (private — squad index, Steve Smith's
batting pack and Pat Cummins' bowling pack at phone width, Smith's pack again at laptop width).

## What a player gets today

A pack page is a list. Every section is a closed `<details>`, so "The South Africa attack" opens as
eleven rows of name, type and a **View report** button, and "Your vision" is a closed bar. A tap on a
bowler opens six bullets of generated prose ("Right pace — averages 137 km/h, tops 147", "By angle —
over the wicket, a good length outside off; round the wicket …"), two or three small reel pills and a
"20 balls of you facing them" line. Nothing on the page is a picture except the headshots. The
bowling pack adds two coach tables (release point, the opposition overview with SET / MOVE / SPARE text
and PNG field chips in a lightbox) above the same list. **View report** opens the full 1.4 MB coach
report with the "Vs Our Squad" block removed.

The coach view built this week is the better player page: a card per opponent with the coaches'
notes, the scouting notes, the figures to that hand, the reels and the field drawn live. The pack has
none of that and the coach view has all of it, which is why the pack now reads as a coaching document
that players find hard to follow.

## Audit — what to change

1. **Everything is hidden.** Two taps before any content; the page as served is a roster. Open the
   cards. The only thing behind a link should be the full report.
2. **No coaching voice.** The coaches' notes and saved fields (the planner, `fieldplans.*`) never
   reach the packs. They are the thing a player wants first. **The store holds none yet** (checked
   05-10: zero fields, zero notes across every pack), so the page must read well on the generated
   scouting notes alone and show the coaches' block only when one exists — never "none yet, add them
   in the planner" on a player's page.
3. **Prose where a picture belongs.** "Stock ball: a good length outside off (28%)", "by angle …",
   "takes most wickets yorker/full, around 4th stump" are three sentences describing one pitch map.
   `cricket_core.cricviz` draws it; the planner's `fields.js` draws the field. Use them.
4. **The figures are in the sentences.** "Vs pace: averages 56 at a strike rate of 86, false-shot
   14%" buries three numbers a player scans for. Three or four tiles per card, chosen for the reader:
   a batter wants the bowler's pace, balls per wicket and short-ball share; a bowler wants BPD,
   false-shot rate and where the batter scores.
5. **Size mismatches.** Body text runs 10–13.5 px against a 22 px h1 and 72 px headshots; buttons
   are 11 px pills next to 14 px filled "View report" blocks; the overview tables are 560 px wide
   on a 390 px phone and scroll sideways. One scale: 15–16 px body, 13 px labels, 24–30 px names,
   44 px touch targets.
6. **Two visual systems.** The pages are built Opta (navy, Inter) and `hubstyle.py` repaints them
   green at serve time with literal colour overrides. Build them in Baggy green natively from
   `cricket_core.webcharts` tokens; `hubstyle` keeps dressing the reports.
7. **Coach material on a player page.** The release-point table, the overview tables, the "by
   angle" fact and SET / MOVE text are field-setting and selection reads. They belong to the coach
   view, which already has them.
8. **The field is a PNG.** 149 field PNGs (11 MB) rendered on the build box, served through a
   lightbox, and the planner's saved fields never replace them. Draw the field in the page from the
   `fielders` angle/radius the overviews and `bowler_plans_<opp>.json` already carry, and swap in the
   coaches' field from the API when one is saved — the coach view does exactly this.
9. **The roster index asks the reader to choose twice.** Every row has Batting and Bowling chips.
   One tile per player; the pack opens on Batting with Bowling as a tab.
10. **Footnotes do the explaining.** Starred reels, "(first-class, not Test)", C21-only notes, the
    other-hand fallback. Keep every caveat, but say it where it applies (on the button or the card)
    rather than at the foot of the page.
11. **The report link is the wrong size.** "View report" is the most prominent control on the page
    and opens the heaviest thing. Make it a quiet "Full report ›" at the card foot.
12. **The order is by balls bowled.** Group by the likely XI as now, but within the XI put the new-ball
    bowlers first on a batting pack and the batting order on a bowling pack (the overview already
    sorts by order band).

## The proposed player report

**One scrolling page per player and discipline, phone first.** Header (photo, name, hand or type,
series), a tab per discipline, a row of jump chips (one per opponent), then:

1. **From the coach** — a green band with the batting (or bowling) coach's note to this player, when
   one is written. New store row: `fieldplans.notes` with `pack = "us-bat" | "us-bowl"` and our
   player's id. Shown only when present.
2. **Their attack / Their batters · most likely XI** — a full card per opponent in the XI, then the
   rest of the squad as one-line rows that expand.
3. A footer with the format and hand the figures are for.

**Card anatomy, in reading order** (same shape on both packs):

| | Batting pack (their bowler, to my hand) | Bowling pack (their batter, against my type) |
|---|---|---|
| Who | photo · name · XI chip · type, pace, new ball | photo · name · XI chip · hand, order, one-line character |
| **Coaches' notes** | planner note for this bowler vs my hand (`vs_rhb` / `vs_lhb`) | planner note for this batter (`<group>` pack) |
| What the numbers say | Respect / Attack / Watch from `bowler_plans_<opp>.json` `how_to_play` | the plan sentence + "gets out most often to …" + "most often out …" from the overview row |
| Figures (3) | km/h and top · balls per wicket · short % (spin: economy, round-the-wicket %) | BPD · false-shot % · false v short ball (or off-side share) |
| The field | "The field they'll set you": New ball / Old ball / Bouncer (spin: New batter / Set batter), coaches' field when saved, else the estimate, spare named | "Your field to them": First 30 balls / Once set / Bouncer, Option 1 when saved |
| Picture | cricviz pitch map of their wicket balls to my hand + one line of band shares | cricviz wagon wheel vs my type + one line on the off/leg split |
| Watch | Stock ball · Wicket balls · New ball (when they take it) · **You v them · N balls** (filled) | How they score · How they get out · **You to them · N balls** |
| | Full report › | Full report › |

Everything on the card already exists in a file the build reads: `bowler_plans_<opp>.json` (per hand:
figures, how_to_play, fields with `fielders` and `spare_name`), `overview_<group>_<opp>.json` (plan,
threat, fields with `fielders`), `opponent_about_<opp>.json` (reels, clip scopes), `h2h_<opp>.json`.
The two new things are the pictures (two cricviz renders per card at build time) and the coaches'
notes and fields, fetched live from `/fields/<series>/api/fields?pack=…` the way the coach view does.

**Dropped from the player page:** the release-point table, the two overview tables, the "by angle"
and "usually takes the new ball" bullets (the latter becomes the New ball reel and the field tag),
SET / MOVE text, the lightbox and its PNGs, the whole-page footnotes.

## What has to be built

- **A new page builder** in `build_player_site.py` (or beside it) that emits the card markup above in
  Baggy green from `webcharts` tokens, with the Barlow fonts, and no Opta shell. `hubstyle.dress`
  must leave these pages alone (it classifies by sniffing; give the new pages a marker).
- **`fields.js` in the packs**, copied into the bundle by content hash as the coach view does, with
  a label-size option: at 330 px wide the planner's `.05` labels are 7 px; the mockups use `.068`.
- **The API for players.** `/fields/<s>/api/fields?pack=vs_rhb|vs_lhb` answers 403 to a viewer today
  (COACH_VIEW_PLAN: bowler-side fields "coach-only until used"). A batting pack needs a read of the
  notes and shared fields for the player's own hand. Decision for Tom, below.
- **Two cricviz renders per card** at build time: `pitch_map` of the bowler's wicket balls to the
  pack's hand (batting pack) and `wagon_wheel` of the batter against the pack's type (bowling pack).
  One Chromium per process (`cricviz.to_png`), ~2 s a picture — about 50 pictures a squad.
- **A per-player coach note**: one more `pack` value in `fieldstore` and a place to write it (the
  planner, or the coach view's series page).
- **Gates.** `check_site` must follow the new cards' `data-*` links (it learned the coach view's this
  week); `audit_pack_hands` is unchanged as long as the reel keys are (`stock*`, `wkt*`, `nb*`,
  `sco_*`, `dsm_*`, `hbat_`/`hbowl_`); `publish_packs.report_format_check` needs the "Full report ›"
  link to stay a bowling-report link.
- **The old pack page stays the GitHub Pages page** until the series ends; the new one is served only
  by the app. So the builder writes both for now (`--style hub|pages`), and the Pages one is retired
  with the site.

## Decisions (Tom, 06-10-2026)

1. **Players see the coaches' shared notes and fields on their batting pack** (their bowlers, to the
   player's hand). Private drafts never. The `vs_rhb` / `vs_lhb` side of the planner opens to viewers
   for reading.
2. **Phone first**, with a two-column layout on a laptop or iPad.
3. **Four to six figures per card.** Batting pack, pace: km/h and top · average · Bowl SR · economy ·
   short % · hit the stumps (with the type's rate). Spin: km/h and range · average · Bowl SR · economy
   · wickets · hit the stumps. Bowling pack: balls · average · balls per dismissal · false-shot % ·
   share of runs on the off side · false-shot % v the short ball (pace only).
4. **Build the per-player coach note** (the green band at the top of each pack), shown only when
   written.
5. **No report link on the player cards.** The reports stay coach documents.
6. **Order within the XI as mocked**: new-ball bowlers first on a batting pack, batting order on a
   bowling pack.
7. **Generated text states facts, everywhere it is generated** — reports, coach view and packs.
   Instructions ("Respect…", "Cash in…", "use your feet…", "Plan: bowl…", "get at them hard…",
   "watch the ball in the air") come only from coaches, in their notes. Each line keeps its number
   and loses the instruction: "Wicket ball: yorker / full on the stumps · 4.9 per 100 balls (4 in 45)",
   "Most expensive: full outside off · 4.0 an over, beats the bat 22%", "Length: more consistent than
   91% of Test spinners", "Lowest average: good length 24.8 · pitching outside off 23.5 (overall
   33.0)", "Movement: seaming in 18.8 · away 20.8 · straight 73.2", "First 30 balls: out every 39
   balls, then every 57".

**Tom's notes on round 1, all taken into round 2:** a wagon wheel switches between the spider and a
zones wheel with the run totals, drawn large enough to read; beehives sit beside the pitch maps;
captions are short ("Estimated from the data", "No available footage."); no explanatory footers
("Updated by the coaches…", "in batting order", "Drawn for a left-hander…").

## Build order

1. **Facts-only text at source** — `profile._how_to_play`, `batting_report.plan_sentence` /
   `_summary_points`, `build_opponent_about.distil_*`. The output becomes labelled facts
   (`[{label, text}]`) rather than Respect / Attack / Watch prose, so `report.py`, `coach_bowlers.js`
   and `build_coach_site.py` change with it. **The coach view is another session's live work —
   agree the shape with it before changing `coach_bowlers.js`.**
2. **The planner opens shared `vs_*` notes and fields to viewers**, and gains a per-player note
   (`pack = "us-bat" | "us-bowl"`, our player's id) with a place to write it.
3. **The new pack page** (`pack_page.py`), built from the existing JSON — `bowler_plans_<opp>.json`,
   `overview_<group>_<opp>.json`, `opponent_about_<opp>.json`, `h2h_<opp>.json` — in Baggy green from
   `cricket_core.webcharts` tokens, `fields.js` for the fields, the zones wheel drawn as inline SVG
   from `charts.wagon_sector`.
4. **Pictures at build time** — cricviz `pitch_map(metrics=False)` and `beehive` of a bowler's wicket
   balls to each hand, and of a batter's dismissals against each type; `wagon_wheel` for the spider.
   About 4 renders per opponent per hand or type.
5. **Gates** — `check_site` on the new pages (sidecars, `data-*` links), `audit_pack_hands` on the reel
   keys (unchanged if the keys are), `report_format_check` taught that hub pages carry no report
   link. The GitHub Pages pages stay as they are until the series ends.

## Build status (06-10-2026, first build — uploaded to `/packs/`, unlinked; not committed)

Tom's first note on the live look (06-10): the reel buttons were sized by their labels and did not line
up. They are now one full-width row per reel, the clip count on the right, the head-to-head row green.

1. **Facts-only text** — done in `profile`, `batting_report`, `build_opponent_about`, `build_overview`,
   `build_bowler_plans`, `report`, `coach_bowlers.js`. The live coach view and reports still carry the
   old wording until `bowler_plans_<opp>.json`, the overviews and the coach view are rebuilt.
2. **Planner** — viewers read shared notes and fields on every pack, `vs_*` included, and the API says
   `canEdit`. The per-player note is `pack = us_bat | us_bowl`, keyed by our player's id, written in
   place on the pack page by a coach (no planner page for it).
3. **The page** — `build_hub_packs.py` (not `pack_page.py`), writing `hub_pack_site/packs/<slug>/`,
   served by the playerpacks app at `/packs/<slug>/`. Cards are static HTML; `hub_pack.js` (served as
   `/packs/pack.js`) draws the fields with `fields.js`, switches Zones / Spider, and fetches the
   coaches' notes, fields and the note at the top. Styles in `hub_pack.css` over `webcharts.CSS`. The
   app's `hubstyle.dress` fills the page's `<!--hub-bar-->` slot with the hub bar and changes nothing
   else. Clips are the Pages packs' own sidecars, fetched from `/players/<slug>/<p>-clips.json`.
4. **Pictures and numbers** — `build_pack_extras.py` → `data/pack_extras_<opp>.json` and
   `reports/pics/<opp>/` (127 PNGs, 32 MB for South Africa). Full squad 06-10: 11 bowlers, 12 batters,
   ~17 min. During the series pass `--before 2026-10-09`.
5. **Gates** — `check_site.py hub_pack_site --with player_pack_site` (root-absolute links resolve in
   either bundle) and `audit_pack_hands.py --site hub_pack_site --with player_pack_site …`. Both run
   on the 06-10 build: 2,131 links clean; 817 reels on 31 pages, 0 defects, all resolved (16 declared
   ODI borrows, 28 declared wider-type reels). Proven both ways: a deleted picture and a repointed
   button fail the link check. `report_format_check` does not apply — no hub card links a report.

Uploaded 06-10 with `playerpacks/upload_packs.py --bundle hub_pack_site --prefix aus --apply`, which
now lists only the folders the bundle carries (`packs/`) — listing all of `aus/` failed every time
on a weak connection. Still to do: deploy the playerpacks app in both regions (the hub bar slot and
players reading `vs_*` notes) — blocked on Tom's Azure admin sign-in, which expired on the 14-day
rule; point the hub's Player Packs tile at `/packs/` when the players move over; wire the two gates
into a publish step rather than running them by hand.

## Checked, for the record

- Store contents 05-10: `fieldstore.list_fields` / `list_notes` return nothing for every pack of
  `south_africa_away_test`; the coach view's "Coaches' notes — none yet" is the live state.
- The notes in the mockups marked **Example** are illustrative text in a coach's voice, not data.
  Every figure, plan sentence, Respect / Attack / Watch line and field is from the built 04-10 pages
  and `bowler_plans_south_africa_test.json`; the pitch map and wheel are cricviz renders from the
  warehouse (Rabada's 192 wickets to right-handers; Markram's 2,973 balls against right-arm pace).
