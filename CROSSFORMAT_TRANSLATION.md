# Cross-format translation — what a report may and may not claim

*Guidance distilled from the matchupmodel cross-format-prior investigation (2026-07-15). Applies to
any report or pack that describes a player with a thin Test record using their FC / ODI / T20
numbers — new caps, uncapped Shield candidates, "who else" panels. Full evidence:
`../miscellaneous/matchupmodel-crossformat-prior-investigation.pdf`, and
`../matchupmodel/docs/LEAGUE_ADJUSTMENT_PLAN.md` §9–10.*

## The governing result

Cross-competition translation was measured twice, independently, with the same answer:

- **Tempo and rate metrics translate.** Dot-ball %, boundary rate, scoring rate: cross-league
  R² 0.7–0.8 (LAF v1.21 self-validation, confirmed in shape by our holdout).
- **Outcome metrics do not.** Batting average R² 0.17, bowling average 0.08, wickets 0.26. In our
  own temporal holdout, a batter's league-adjusted cross-format outcome record predicted their
  later Test outcomes *worse than the plain Test cohort average* for players with no prior Test
  data — at every recency half-life tried (1 / 2.5 / 5 yr).

How a player scores carries across competitions. How often they get out does not.

## What a report MAY do

- **State the cross-format record as record.** "Averages 52.1 in Shield cricket since 2023
  (12,237 FC balls)" is a fact and always fine.
- **Use population-level context to frame it.** The fitted class ratios below are cricket-correct
  and stable — use them to caption *how the environments differ*, never to compute a player's
  projected number.
- **Translate tempo.** Comparing a player's dot-ball %, boundary %, or scoring shape across
  formats (with the format shift named) is supported: "his Shield scoring tempo is
  Test-appropriate — 78% dots vs the 80% Test norm".
- **Keep the T20 league-strength adjustment** (`build_t20_league_strength.py`) exactly as is. It
  adjusts *economy and rate percentiles* — the class of metric that translates — and it is fitted
  with same-year form control. This investigation reinforces it rather than undermining it.

## What a report MUST NOT do

- **Project a Test average or dismissal rate from another format.** Not "his Shield 45 is worth
  ~38 in Tests", not a T20-derived wicket-rate read, not an ODI-average-based ranking of Test
  candidates. This is the specific claim the holdout killed — such a projection is less reliable
  than saying "an average Test batter".
- **Rank thin-Test-sample players on translated outcome numbers.** If candidates must be compared
  on cross-format records, compare the raw records side by side, label the competitions, and let
  the reader weigh them — do not put a Test-equivalent number on them.
- **Treat a big FC sample as if it removes the uncertainty.** The failure case in the holdout was
  not lack of data — debutants averaged ~2,200 cross-format balls, half first-class — the signal
  itself does not carry.

Where a projection is unavoidable (a selection report has to say *something* about an uncapped
player), hedge it as a projection, ground it in the tempo evidence that does translate, and say
what does not: "projects to the low 30s on scoring shape — no reliable cross-format read on
dismissal rate exists".

## Population-level environment ratios (context captions only)

Fitted on pre-2023 bridging players (≥100 balls both sides), men's, warehouse-wide. A ratio is
"Test wicket rate ÷ that competition's wicket rate" for the same players — the environment gap,
not a per-player predictor.

| Competition class | Wicket ratio (pace / spin) | Scoring shift vs Test (pace) |
|---|---|---|
| First-class → Test | 1.04 / 1.18 | ≈ none (sixes ×0.77) |
| 50-over → Test | 0.65 / 0.68 | dots ×1.39 · sixes ×0.19 |
| 20-over → Test | 0.37 / 0.32 | dots ×2.21 · sixes ×0.05 |

Notable per-competition wicket ratios (same fit, shrunk toward class): County Championship 1.05 ·
Sheffield Shield 0.98 · international ODI 0.64 · IPL 0.41 · international T20 0.38. Read: Shield
and County dismissal environments sit close to Test level — the *environment* is comparable, but a
given player's Shield dismissal rate still does not predict their Test one.

## For any future feature work

Do not build a per-player cross-format outcome projection into playerprofile (or re-propose one
for matchupmodel — that line is closed, `LEAGUE_ADJUSTMENT_PLAN.md`). The reopen condition is
external: a demonstrated per-player *outcome* translation with same-period form control and
external validation. Tempo/rate features (league-adjusted economy, scoring-shape comparisons)
remain fair game.

**The one sanctioned projection (built 2026-07-15): within-T20 rate profiles.**
`referencebuilder/scripts/predict_t20_profile.py` predicts a batter's dot% / boundary rates /
singles / strike rate in another men's T20 league — gate-validated
(`referencebuilder/docs/T20_PROFILE_TRANSLATION.md`), rates only, every number carrying its
holdout error. A "projected profile in {league}" panel in the T20 pack may consume it, with the
gate context shown inline. It still never outputs an average or wicket rate.
