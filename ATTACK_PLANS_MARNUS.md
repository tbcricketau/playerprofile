# P1 verification — the Labuschagne change

> Second calibration case for `ATTACK_PLANS.md`. Claim: he used to score strongly off his legs
> (negating LBW) and from the channel — now he tends to nick off in the channel or late-cut to
> gully. Sample: **6,346 Test pace balls** (prior era 4,492 / recent 1,854), era split at
> **15-07-2023** per the recent-change convention (last 3 years), all official Tests, vs pace
> unless stated. Run 15-07-2026.

## Headline

| | balls | runs | outs | avg | balls/out |
|---|---|---|---|---|---|
| Prior (to 07-2023) | 4,492 | 2,204 | 41 | **53.8** | 110 |
| Recent (since) | 1,854 | 811 | 31 | **26.2** | 60 |

The decline is real and large — the average has halved against pace. The question is the mechanism.

## The claim, part by part

| Claimed | Verdict | The numbers |
|---|---|---|
| Was very strong off his legs | **Still is — the leg-side game has not decayed** | Flick/Worked/Glance SR *92 → 96*, 4 outs in each era. On balls pitching in line or on leg: SR *78 → 97*, **zero LBW or bowled** in the recent era. The LBW-negation is intact |
| Scored well from the channel | **The scoring held — the survival broke** | Channel SR *45 → 42* (modest), but balls/out *115 → 86*, and the **edge rate went 7.3% → 11.2%** (z +3.2 — clears the gate) |
| Now constantly nicks off in the channel | **Supported, and concentrated in 2025+** | By year, channel edge%: 2022 *8.8* · 2023 *7.4* · 2024 *9.0* · **2025 *37.9*** · 2026 *25.0* (2025-26 coded-ball samples are small — 66 and 12 — but the jump is far beyond noise at those n). Caught is now **26 of 31** dismissals (84%, was 66%), keeper + cordon dominant, and 10 of the recent caughts came off *defensive* strokes — he is nicking off defending |
| Late-cuts to gully | **Directionally supported — small n** | Gully catches 2 → 4 despite fewer total dismissals (7% → 15% of caughts); cut-family (cut/late cut/steer) out-rate roughly doubled, 1-per-31 balls → 1-per-13, with 3 recent Caught/Cut-or-dab. At n = 3–4 this is a lean, not a finding |

## The change, restated from the data

The popular version ("lost his leg-side game") is wrong. His leg-side scoring is untouched — if
anything he leans on it more, because the off side is what broke. What changed is **the channel
outcome**: roughly the same scoring rate off it, but the edge arrives ~1.5× as often era-on-era,
and in 2025 the edge rate went to several times his career norm. The dismissal profile followed —
caught-behind-the-wicket off defence and the drive, plus the emerging cut-to-gully mode. On this
evidence the right opposition plan against 2025-Marnus is the channel with a full cordon and a
gully — and the LBW plan that works on Weatherald is *not* the plan here (he still kills the
straight ball).

## Method notes (bank these for P2)

- **Stroke coding starts ~2020** — 2019 (his biggest year, 1,470 balls) has no stroke labels, so
  any stroke-based *share* comparison across eras is biased; restrict stroke metrics to 2020+ or
  compare rates, not shares. (The 22% → 38% leg-side run-share shift is partly this artefact —
  don't quote it.)
- **Shot-quality coding coverage varies by year** (2025: only 66 channel balls coded) — always
  print the coded-n beside an edge rate.
- **The 3-year era split diluted this case**: by-year shows the channel break is 2025+, not
  mid-2023. The plan-card builder should pair the era table with the by-year trajectory so a
  recent cliff isn't averaged away — same lesson as the bowler overlay's pace trajectory.
- Caught-position via `DeliveryFielders` was usable in both eras here (coverage is recent-heavy,
  which suits change detection).

## Next

P2 — productionise the plan cards (`ATTACK_PLANS.md` §5, layers 1–2) for the Bangladesh-series
squad packs, folding in the last-3-series view (§8) and passage/plan-cell playlists (§6).
Machinery status after two calibration cases: **recovers and sharpens named plans; declines to
invent sequences it can't support.**

*Analysis script: scratchpad `p1_marnus.py`, run 15-07-2026 against the live warehouse.*
