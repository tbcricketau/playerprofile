# Plan — link report insights to video, then playlists, then auto-cut reels

**Goal:** every data claim in a bowler report can be *seen*. Start by deep-linking specific
balls (e.g. "the stock ball") from the report to the actual clips; grow into per-insight
playlists; end with auto-cut highlight reels and (later) AI video review. The pitch: **build a
bowler report, then back the data with vision so we get the full picture.**

Status — **Phases 0–2 built (2026-07-03)**, all in the shared package so every project reuses them:
- **Phase 0 DONE** — `ludis_cricket.video`: `clip_url`/`clip_stem`/`resolve_clip` + SSO/RBAC SAS.
  playerprofile loader pulls `video_file_name`/season/gender/match_length; rows carry `clip_stem`.
- **Phase 1 DONE** — `playerprofile/playlists.py` builds Stock ball / Wickets / New-ball
  out-swinger playlists; `render_report` writes `<pdf>.playlists.json`. Shared schema/writer
  (`playlist_item`/`resolve_playlist`/`write_playlists`) in `ludis_cricket.video`.
- **Phase 2 DONE (v1)** — reusable `ludis_cricket.video.playlist_widget` (Streamlit) + a
  playerprofile page `video_viewer.py` (`streamlit run video_viewer.py --server.port 8061`).
- **Next:** more insight playlists (beaten bat, danger zone, in-swingers); live viewer inside the
  main app (build playlists for the selected bowler, cached) rather than only from sidecars; PDF
  deep-links to the viewer; then Phase 3 (ffmpeg auto-cut) and Phase 4 (vision).

Original foundation notes:
- The report already isolates specific ball *sets*: stock ball & each ball type, danger/beaten
  zones, wickets, new-ball out-swingers, over/round, crease bands, etc.

A delivery is identifiable by `delivery_id`; the clip is deterministic from `video_file_name`
(+ season/gender/format). So any set of deliveries the report computes can become a playlist.

---

## Phase 0 — plumbing: a delivery → clip resolver in playerprofile (small, do first)
- Add `video_file_name` (and confirm `delivery_id`, `season`, `match_length_id`, `gender`) to
  `data_loaders.load_bowler_deliveries` — mirror the sequencer's corrected path logic.
- Add `profile.clip_stem(row)` → the extension-less blob URL, and reuse
  `blob_auth.resolve_clip` (lift `blob_auth`/`resolve_clip` into the shared `ludis_cricket`
  package so both projects import one copy, rather than duplicating).
- **Coverage reality:** many older deliveries have no clip. The resolver returns `None`; every
  builder below must filter to deliveries that actually have a clip and show an availability
  count ("42 of 58 stock balls have vision").
- Schema note: report uses `GA20260618`, sequencer uses `GA20250130`. Confirm `video_file_name`
  exists and the blob layout matches in `GA20260618` before trusting it (spot-check a few).

## Phase 1 — per-insight playlists (the core deliverable)
- Define a **playlist** = ordered list of items `{delivery_id, clip_stem, caption, meta}` where
  `meta` carries the tracking used in the report (speed, swing/seam label + degrees, bounce,
  length/line, outcome). Captions are generated the same way the report describes a ball.
- At report-generation time, for each key insight collect the `delivery_id`s and emit a
  **playlist sidecar** next to the PDF: `reports/<name>.playlists.json`
  `{ "stock_ball": [...], "wickets": [...], "beaten_zone": [...], "new_ball_outswing": [...],
     "danger_zone": [...], "ball_type::a good length outside off": [...], ... }`.
- Order within a playlist: most representative / highest-quality first (e.g. clearest false
  shot, biggest swing, wickets first), so the first few clips make the point.
- Keep playlists small and honest: cap (e.g. 12), prefer tracked+clipped deliveries, note the
  denominator.

## Phase 2b — modal web player (DONE 2026-07-03)
`ludis_cricket.video.build_player_html(playlists, out, title, subtitle)` writes a **self-contained
modal player** (one HTML file, baked SAS): clip cards per playlist tab; clicking opens a lightbox
that **greys out the page** with the video, caption, counter, prev/next (arrow keys), Esc/backdrop
to close. Reports write a `<pdf>.player.html` sidecar and the ▶ links open it at
`…player.html#<key>` (jumps to a playlist). Fixes the "downloads / opens raw mp4, click back"
problem. **The player is angle-ready**: each clip item can carry `angles=[{label,url}]` and the
modal shows angle toggles — the hook for the Hawkeye front-on/side-on footage below.

## Phase 2c — Hawkeye front-on / side-on angles (PLAN — needs input)
Some matches have extra locked-off + slow-mo Hawkeye angles (front-on / side-on), e.g.
`2026-06-21_BangladeshM_v_AustraliaM_5461768/1359_1_001_01/Camera 1_1359_1_001_01.mp4` (+ ~6 mp4s
per ball). **These are NOT in the `fairplay` container** (checked) — they live in the AMS / another
store. Blockers to resolve before wiring:
1. **Access**: which storage account/container are they in, and does our SSO/RBAC (or a SAS) reach
   it? (fairplay account has only `fairplay` + `inventory` containers; the Hawkeye folders are in
   neither.)
2. **Join**: the ball-folder code (`1359_1_001_01`) → delivery (innings/over/ball) mapping, or a
   manifest. Folder is under a match-id-named parent (`…_5461768`), which joins to our `match_id`.
   The normal-footage equivalent is `2026/Men/T20/5461768/A/1/5461768A100101.mp4`.
3. **Angle labels**: which of Camera 1..6 are front-on vs side-on (a convention, a manifest, or the
   analysis tool below).
Once resolved: add `angles` to each playlist item (broadcast + front-on + side-on) — the modal
already switches between them.

## Phase 4b — footage analysis (STARTED 2026-07-03 — `c:\Ludis\footageanalysis`)
v0 pipeline **built & validated**: per-match camera→viewpoint maps from the Hawkeye clips.
`pipeline.py --match <id> --date <YYYY-MM-DD>` samples ball folders, downloads each camera's
clip (SSO SAS), extracts frames (bundled imageio-ffmpeg exe — runs under AppControl; no
numpy/OpenCV, Pillow+stdlib only), classifies **end_on vs side_on** (primary cue: grass vs
ad-boards at frame top — 6/6 cameras at two venues, 100% frame agreement), writes
`data/camera_angles/<match_id>.json` + keeps frames for audit. `ludis_cricket.video` consumes
the maps: player angle buttons read **End-on N / Side-on N** (end-on first). Layout variance
handled (some matches nest `1st INNINGS/2nd INNINGS` above the ball folders; ball folder =
`HHMM_inn_over_ball` parsed at any depth). **Next (v1):** behind-bowler vs batter-end
front-on disambiguation (motion/person cues — Camera 1 is behind-bowler at one venue,
batter-end at another); slow-mo detection; batch-run maps for all covered matches; variation
classification from vision (ties into the wobble thread); Virtualeye (home Tests) once its
location is known.

## Phase 2 — a playlist viewer (reuse the sequencer)
- The sequencer already plays an ordered set of clips with the pitch map + beehive beside them.
  Generalise it to accept an **arbitrary playlist** (a `.playlists.json` entry or a list of
  `delivery_id`s) via a URL query param / file picker, instead of only its striker-sequence query.
- Show the report's caption + the ball's tracking overlay per clip; prev/next; autoplay.
- **Deep links from the PDF:** the report is printed via Chromium, which preserves `<a href>`
  links. Put a small "▶ watch (n)" link next to each insight pointing at the viewer with the
  playlist id, e.g. `http://localhost:8501/?playlist=<report>&key=stock_ball`. Works while the
  local viewer runs; if we later deploy the viewer, the links point at the deployed URL.

## Phase 3 — auto-cut single reels (ffmpeg)
- Instead of (or in addition to) a viewer, concatenate a playlist into one shareable mp4.
- Pipeline: `resolve_clip` → download (SAS) → optional trim to the delivery window → optional
  burnt-in caption/overlay (ffmpeg `drawtext`: bowler, ball type, speed, swing/seam) → `concat`
  → write `reports/<name>.<insight>.mp4`.
- ffmpeg is the one new dependency; everything else is stdlib + existing SAS. Cache downloads.
- Overlays can also stay as a sidecar (VTT/JSON) if we don't want to re-encode.

## Phase 4 — vision / AI review (later, exploratory)
- Verify/enrich what tracking can't see: wobble-seam vs away-swinger by grip/seam axis (ties
  directly into [[swing-wobble-next]] — the 2827×2828 label proxy wants video confirmation).
- Auto-detect key frames (release / bounce / contact) for precise trimming and to QA tracking
  (does the coded swing/seam match what's visible?).
- Longer term: auto-assemble the report's video companion; natural-language "show me every ball
  he nicked off the good-length outside off" → playlist.

---

## Recommended MVP (smallest thing that delivers value)
1. Phase 0 resolver + shared `blob_auth` in `ludis_cricket`.
2. Playlist sidecar for **three** insights first: **Stock ball**, **Wickets**, **New-ball
   out-swingers** (the swing thread we just reworked).
3. Generalise the sequencer to play a playlist file.
4. Add the three "▶ watch" deep links to the PDF.
5. Only then: ffmpeg auto-cut for those three; vision QA.

## Open decisions (for review)
- **Viewer host:** extend the sequencer vs a new minimal viewer page? (Recommend: extend it.)
- **Link target while local:** localhost viewer (needs the app running) vs pre-cut mp4s that open
  in any player (no app needed, but re-encode cost). Could do both — link to viewer, "download
  reel" for the mp4.
- **Where playlists live:** sidecar JSON next to the PDF (simple, portable) vs a small DB table.
- **Caption source of truth:** reuse the report's phrasing functions so the video captions and
  the report say the same thing (single vocabulary).
- **Trimming:** are the Fairplay clips already one-delivery long (so concat needs no trim), or do
  they need cutting to the ball? (The samples looked per-delivery — confirm.)
