# Web scouting report, batting page: redesign (16-10-2026)

The batting page of the web scouting reports (`report_web.py`, `_batter_scope`), as Scouting links it
in place of the A4 reports.

## Layout pass: built, not rolled out

Built on Ben Duckett's England ODI page (2540202), from Tom's read of the England pages:

- The facts as tiles across the card (`fact_tiles`), not label rows down its left.
- Reels beside the numbers they show (`_reels`): Dismissals and Danger ball at the head of *Where they
  get out*, Risky stroke and False shots at the head of *How they score*. The Vision section at the end
  is gone.
- Scoring by side only: runs off side and runs leg side (`_sides`, the wheel's eight areas). No shot
  types in the figures or the facts. "Pull / Hook" reads "Pull" against spin.
- The separate First 30 balls section is gone (it is a fact tile). Your field shows only when a field
  exists.
- A new section, *Line, length and pace* (`_line_length`): hitting the stumps against missing them (pace
  and spin on the all-bowling page), length by pitching line with BPD per cell, and slower balls
  (under the bowler's `off_pace_kph` in `referencebuilder/data/bowler_speed_profile_by_format.csv`)
  against stock pace.

## Tom's calls (atq, 16-10-2026)

- **Roll-out waits for the visuals.** The layout and the charts go live together. Until then the live
  pages stay as they are. Only Duckett's page has been rebuilt (box and laptop coach_build, not
  uploaded).
- **Visuals to mock up on Duckett's page, all four:**
  1. Danger map: the length × pitching line grid drawn on the pitch, bowler at the bottom, each area
     shaded by BPD with the number in it.
  2. Stumps view: where the ball passed the stumps, by line and height, shaded by BPD, with a pace /
     spin switch.
  3. Catch positions on a ground plan, with a bar for bowled / LBW / caught behind. Check first how
     many catches carry a usable position.
  4. Bowler types as bars: the average per type, a line at the career average.
- **Chart first, table on a switch.** Each chart gets a Chart / Table toggle (the `panes` switch the
  wheel uses). The chart shows by default.
- **England T20I packs: build now (Tom, 29-10-2026)**, closed to players, without waiting on his
  review of the ODI pack. If that review changes the design, both sets are rebuilt. The T20I Batting
  plans cards (pooled T20 leagues) were built with the 28-10 rebuild.

## Visuals: built on Duckett, waiting on Tom's read (16-10-2026)

All four are in `report_visuals.py`, each on a Chart / Table switch, and shaded by BPD against the
batter's own BPD on the same balls (much quicker / quicker / about usual / longer / no dismissals; under
20 balls greyed). Danger map: equal-width columns, since to scale the channel is a sliver. Stumps view:
line (wide off / off / stumps ±0.15 m / leg) by height (bottom half, top half, over the stumps, head
high), the stumps a white frame so no number is hidden; pace and spin panels side by side on the
all-bowling page. Catch map: lookup-33 positions placed with `cricket_core.lookups.field_coords` on the
pitch-centred ground of `field_engine.field_diagram`, plus a how-out bar. Nothing committed until Tom
approves; the code is on the laptop and the box (`~/projects/playerprofile`).

Ideas raised but not chosen for the first round: slower balls as a speed strip, shots as risk against
reward, length / line / seam tables as bar strips, early innings as BPD by stage, recent form, our
options as bars.
