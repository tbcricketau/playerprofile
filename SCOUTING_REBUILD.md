# Scouting report rebuild — Bangladesh home Tests 2026

Approved design (Tom, 2026-07-15): **one matchup store, two projections; exceptions, not the
matrix, inside player reports; numbers from the simulation, vision from the real meetings.**

## Architecture

```
matchupmodel (own repo)                    playerprofile
  engine.expected_matchup  ──export──►  data/matchup_store.json   (their XI × our squad, both directions)
                                            │
warehouse head-to-head balls ─────────►  data/h2h_bangladesh.json  (real-meeting delivery ids + clip stems)
                                            │
              ┌─────────────────────────────┼──────────────────────────────┐
   scouting site                      opposition report                player pack
   Match-ups MATRIX page              "vs our squad" strip             their row of the store
   (their bowlers × our batters       (2-4 gated exceptions +          + "Your vision vs BAN"
    + mirror, colour-coded,           structural line + ▶ vision       playlists (h2h store)
    the ONE full view)                links; silence = average)
```

## Decisions (locked)

1. **The full matrix lives once** — a top-level "Match-ups" section of the series on the scouting
   site, alongside the report groups. Player reports never enumerate it.
2. **Numbers come from the match simulation** (matchupmodel — glossed for readers as "simulated
   matchups", the tool that plays each pairing out thousands of times), plus the structural
   left/right layer. **Real head-to-head balls are evidence, not statistics** — at 10–30 balls they
   power playlists and one-line context, never quoted averages.
3. **Exceptions-only in reports** — a pairing appears in Rana's "vs our squad" strip only when the
   simulation puts it materially away from his baseline; average matchups are silence. A structural
   sentence ("as an off-spinner, stronger vs our LHB: …") covers a class in one line.

## Build sequence

- [x] Design agreed
- [x] `matchup_store` — `matchupmodel/scripts/export_matchup_store.py` → `matchup_store_bangladesh.json`
      (302 pairings, both directions, per-cell row/col percentile ranks + confidence; cohort-only
      cells flagged `confidence: "None"` — quote them only as cohort reads)
- [x] `h2h store` — `build_h2h.py` → `data/h2h_bangladesh.json` (27 pairings with real Test meetings,
      all 2017 tour; 454 balls, every one clip-stemmed — clips resolve at build time)
- [x] Match-ups matrix page — `render_matchups.py` → `reports/matchups_{opp}.html`; publish_site
      shows it as a series-level card. Preview artifact: claude.ai/code/artifact/552f8d38….
- [x] Player packs: "Your vision vs Bangladesh" live — real per-opponent playlists (Smith v Taijul/
      Mehidy/Shakib resolve from storage); honest empty-states for no-meetings / not-clipped
- [x] **"vs our squad" strip in the bowling report builder** — `report.py _vs_squad_ctx` + template
      section after Match-ups. Gate: frontline batters only (role ≠ Bowler — "he beats our No.10"
      is trivially true, not intel), confidence ∈ {Med, High}, and a MATERIAL deviation vs his
      median against our frontline (≤0.75× = threat, ≥1.3× = target). Structural sentence covers
      hand-classes; h2h shown as a ball/wicket count only. Verified: Rana → Smith the lone target;
      Taijul → no individual exceptions, structural-RHB line carries it; Shoriful → silent.
- [ ] Re-render the BAN bowling set so the strips appear in the shipped reports (mechanical;
      report code unchanged otherwise). Batting mirror = "Our Best Options" (shipped in v0.3).
- [ ] Site refresh (`publish_site.py`) — builds locally fine; **deploying to the live
      scouting-reports repo stays a Tom decision.**

## Notes

- matchupmodel profiles were last built ~07-07-2026 (pre-migration pause). Career profiles move
  slowly — usable for this rebuild; flag a profile refresh in that repo as follow-up.
- The BAN squad for the matrix = the predicted-squad / series.json report set (the XI + squad
  tiers), our side = squads.json.
