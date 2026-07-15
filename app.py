"""
Opposition Bowler Profiles — Test cricket scouting tool.
One page per bowler covering pace, length, pitch zones, and danger areas.
No pandas or numpy — stdlib only.  All analytics live in profile.build_profile
so the dashboard and the PDF reports compute identically (single source of truth).
"""
import streamlit as st

from data_loaders import load_test_teams, load_team_bowlers, load_bowler_deliveries
from cricket_core.charts import (
    speed_violin, innings_violin, day_violin, pitch_scatter_map, beehive,
    zone_concentration, spell_summary_df, innings_summary_df, day_summary_df,
    wagon_wheel_zones,
)
from profile import build_profile, process_rows, team_flag as _team_flag, fmt as _fmt
from photos import get_photo_bytes
from cricket_core.theme import apply_theme

st.set_page_config(
    page_title="Bowler Profiles",
    page_icon="🏏",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🏏 Bowler Profiles")
    st.caption("Test cricket — opposition scouting")

    with st.spinner("Loading teams…"):
        teams_df = load_test_teams()

    if not teams_df:
        st.error("No team data available.")
        st.stop()

    team_names  = [r["team_name"] for r in teams_df]
    team_ids    = [r["team_id"]   for r in teams_df]
    _team_default = next((i for i, t in enumerate(team_ids) if t == "1004"), 0)
    sel_team    = st.selectbox("Opposition team", team_names, index=_team_default)
    sel_team_id = team_ids[team_names.index(sel_team)]

    with st.spinner("Loading bowlers…"):
        bowlers_df = load_team_bowlers(sel_team_id)

    if not bowlers_df:
        st.warning("No bowlers with enough Test data for this team.")
        st.stop()

    bowler_names  = [r["player_name"].strip() for r in bowlers_df]
    bowler_ids    = [r["bowler_id"] for r in bowlers_df]
    _bowler_default = next((i for i, bid in enumerate(bowler_ids) if bid == "1300076"), 0)
    sel_bowler    = st.selectbox("Bowler", bowler_names, index=_bowler_default)
    sel_bowler_id = bowler_ids[bowler_names.index(sel_bowler)]

    st.divider()
    st.subheader("Filters")
    hand_filter  = st.radio("Batter handedness", ["All", "vs LHB", "vs RHB"])
    pos_filter   = st.radio("Batting position", ["All positions", "Openers (1-2)", "Top 3", "Top 4"])
    spell_filter = st.radio("Spell", ["All", "Opening (Spell 1)", "Later (Spell 2+)"])

    st.divider()
    st.subheader("Wagon wheel")
    ww_sectors = st.radio("Sectors", [4, 6, 8], index=2, horizontal=True)

    st.divider()
    st.subheader("Length grouping")
    _len_mode = st.radio("Length grouping", ["Zones", "1m bands", "0.5m bands"], horizontal=True, label_visibility="collapsed")

# ── Load, then compute the whole profile via the shared core ────────────────────
with st.spinner(f"Loading {sel_bowler}'s Test data…"):
    raw = process_rows(load_bowler_deliveries(sel_bowler_id))

if not raw:
    st.warning("No delivery data found for this bowler.")
    st.stop()

P = build_profile(
    sel_bowler_id, hand=hand_filter, position=pos_filter, spell=spell_filter,
    length_mode=_len_mode, raw=raw,
)

# Unpack into the local names the rendering below already uses.
df, legal, beaten_df = P["df"], P["legal"], P["beaten_df"]
primary_type, is_pace, is_spin = P["primary_type"], P["is_pace"], P["is_spin"]
line_zones, length_zones = P["line_zones"], P["length_zones"]
speed_p05, speed_p95 = P["speed_p05"], P["speed_p95"]
n_balls, n_wkts, runs_tot = P["n_balls"], P["n_wkts"], P["runs"]
avg_spd, max_spd_99 = P["avg_spd"], P["max_spd_99"]
avg_len_m, short_pct = P["avg_len_m"], P["short_pct"]
round_pct, round_lhb, round_rhb = P["round_pct"], P["round_lhb"], P["round_rhb"]
beaten_pct, false_pct, n_tracked = P["beaten_pct"], P["false_pct"], P["n_tracked"]
dismissal_counts, n_dismissals, top_dismissal = P["dismissal_counts"], P["n_dismissals"], P["top_dismissal"]
avg_turn, avg_drift, big_turn_pct = P["avg_turn"], P["avg_drift"], P["big_turn_pct"]
stock = P["stock"]
wkt_zone, run_zone = P["wkt_zone"], P["run_zone"]
dline, dlen, dcell = P["danger_line"], P["danger_length"], P["danger_cell"]
spd_spell1, spd_spell2, spd_spell3p = P["spd_spell1"], P["spd_spell2"], P["spd_spell3p"]
spd_inn1, spd_inn2 = P["spd_inn1"], P["spd_inn2"]
len_spell1, len_spell2, len_spell3p = P["len_spell1"], P["len_spell2"], P["len_spell3p"]

# ── Header ─────────────────────────────────────────────────────────────────────
col_photo, col_info = st.columns([1, 5])

with col_photo:
    _photo = get_photo_bytes(sel_bowler_id, fmt="test", name=sel_bowler)
    if _photo:
        st.image(_photo, width="stretch")
    else:
        st.markdown(
            "<div style='width:100%;aspect-ratio:1;background:#1e2530;border-radius:12px;"
            "display:flex;align-items:center;justify-content:center;"
            "font-size:3rem;color:#444'>🏏</div>",
            unsafe_allow_html=True,
        )

with col_info:
    _flag, _ = _team_flag(sel_team)
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:14px;margin-bottom:4px;'>"
        f"<span class='player-name'>{sel_bowler}</span>"
        f"<span style='font-size:2rem;line-height:1;'>{_flag}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<span style='color:#6b7280;font-size:0.9rem'>{primary_type}</span>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
    with m1:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Balls</div>"
            f"<div class='value'>{n_balls:,}</div>"
            f"</div>", unsafe_allow_html=True
        )
    with m2:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Wickets</div>"
            f"<div class='value'>{n_wkts}</div>"
            f"</div>", unsafe_allow_html=True
        )
    with m3:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Economy</div>"
            f"<div class='value'>{_fmt(P['economy'])}</div>"
            f"</div>", unsafe_allow_html=True
        )
    with m4:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Bowling Avg</div>"
            f"<div class='value'>{_fmt(P['bowl_avg'])}</div>"
            f"</div>", unsafe_allow_html=True
        )
    with m5:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Strike Rate</div>"
            f"<div class='value'>{_fmt(P['strike_rate'])}</div>"
            f"</div>", unsafe_allow_html=True
        )
    with m6:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Avg speed</div>"
            f"<div class='value'>{_fmt(avg_spd)} kph</div>"
            f"<div class='sub'>P99: {_fmt(max_spd_99)} kph</div>"
            f"</div>", unsafe_allow_html=True
        )
    with m7:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Avg length</div>"
            f"<div class='value'>{_fmt(avg_len_m, '.2f')} m</div>"
            f"<div class='sub'>Short ball: {_fmt(short_pct, '.0f')}%</div>"
            f"</div>", unsafe_allow_html=True
        )
    with m8:
        _split = (
            f"LHB {_fmt(round_lhb, '.0f', '%')} · RHB {_fmt(round_rhb, '.0f', '%')}"
            if (round_lhb is not None or round_rhb is not None) else "no data"
        )
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Round the wkt</div>"
            f"<div class='value'>{_fmt(round_pct, '.0f', '%')}</div>"
            f"<div class='sub'>{_split}</div>"
            f"</div>", unsafe_allow_html=True
        )

st.divider()

# ── Threat profile ─────────────────────────────────────────────────────────────
st.subheader("Threat Profile")
st.caption(
    "What you'll face most, and where the danger is. Beaten / false-shot rates use "
    "deliveries with shot-quality tracking; turn & drift use ball-tracking — both partial coverage."
)

_threat_cards = [
    ("Beaten %",     _fmt(beaten_pct, '.1f', '%'), f"played &amp; missed · n={n_tracked:,}"),
    ("False-shot %", _fmt(false_pct, '.1f', '%'),  "beaten + edges + mistimes"),
]
if top_dismissal:
    _md_pct = top_dismissal[1] / n_dismissals * 100
    _threat_cards.append(("Most likely out", f"{top_dismissal[0]}", f"{_md_pct:.0f}% of {n_dismissals} wkts"))
else:
    _threat_cards.append(("Most likely out", "—", "no wickets in selection"))
if is_spin:
    _threat_cards.append(("Avg turn",  _fmt(avg_turn, '.1f', '°'),  f"{_fmt(big_turn_pct, '.0f', '%')} turn ≥5°"))
    _threat_cards.append(("Avg drift", _fmt(avg_drift, '.1f', '°'), "in-air movement"))

for _col, (_lbl, _val, _sub) in zip(st.columns(len(_threat_cards)), _threat_cards):
    with _col:
        st.markdown(
            f"<div class='metric-card'><div class='label'>{_lbl}</div>"
            f"<div class='value'>{_val}</div><div class='sub'>{_sub}</div></div>",
            unsafe_allow_html=True,
        )

_threat_lines = []
if stock:
    _threat_lines.append(
        f"<b>Stock ball:</b> {stock['length']} / {stock['line']} — "
        f"{stock['share'] * 100:.0f}% of deliveries land here"
    )
if dismissal_counts:
    _order = sorted(dismissal_counts.items(), key=lambda kv: -kv[1])
    _dpieces = " · ".join(f"{k} {v / n_dismissals * 100:.0f}%" for k, v in _order)
    _threat_lines.append(f"<b>How they take wickets:</b> {_dpieces}")
    if P["catch_pos_counts"]:
        _cp = " · ".join(f"{k} {v}" for k, v in P["catch_pos_counts"].most_common(5))
        _threat_lines.append(f"<b>Catches to:</b> {_cp}")
if _threat_lines:
    st.markdown("<div class='info-box'>" + "<br>".join(_threat_lines) + "</div>", unsafe_allow_html=True)

st.divider()

# ── Pitch maps ─────────────────────────────────────────────────────────────────
st.subheader("Visualizations")

_metric_options = {
    "Balls":               "count",
    "Wickets":             "wickets",
    "Runs":                "runs",
    "Economy":             "economy",
    "Bowling Average":     "avg",
    "Bowling Strike Rate": "sr",
}
_metric_label = st.selectbox("Metric", list(_metric_options.keys()), label_visibility="collapsed")
_metric = _metric_options[_metric_label]

# Line data is batter-relative (off = same sign for both hands), so we don't mirror the
# zone *labels* — but for the bowler's-eye view we DO reverse the axis for a LHB so the
# off side renders on the right.  The wagon's hit-x is absolute and mirrors via is_lhb.
_is_lhb = (hand_filter == "vs LHB")
flip_x = _is_lhb

_col_pitch, _col_bee, _col_ww = st.columns(3)
with _col_pitch:
    st.plotly_chart(
        pitch_scatter_map(df, line_zones, length_zones, value=_metric, title="Pitch map", flip_x=flip_x),
        width="stretch",
    )
with _col_bee:
    st.plotly_chart(
        beehive(df, metric=_metric, title="Beehive", line_zones=line_zones, flip_x=flip_x),
        width="stretch",
    )
with _col_ww:
    # Fixed-size figure (width/height baked into the layout) + width="content"
    # + responsive:False.  This is what finally stops the fullscreen-toggle shrink: with
    # no container-width feedback and no Plotly autosize, there is no loop to run.
    st.plotly_chart(
        wagon_wheel_zones(df, metric=_metric, title="Wagon Wheel", n_sectors=ww_sectors, is_lhb=_is_lhb),
        width="content",
        config={"responsive": False, "displayModeBar": False},
    )

st.divider()

# ── Spell analysis ─────────────────────────────────────────────────────────────
st.subheader("Spell Analysis")
c1, c2, c3 = st.columns(3)

with c1:
    st.plotly_chart(speed_violin(df, speed_min=speed_p05, speed_max=speed_p95), width="stretch")

with c2:
    st.plotly_chart(innings_violin(df, speed_min=speed_p05, speed_max=speed_p95), width="stretch")

with c3:
    st.plotly_chart(day_violin(df, speed_min=speed_p05, speed_max=speed_p95), width="stretch")

spell_tbl = spell_summary_df(df, is_pace)
if spell_tbl:
    st.dataframe(spell_tbl, width="stretch", hide_index=True)

innings_tbl = innings_summary_df(df, is_pace)
if innings_tbl:
    st.dataframe(innings_tbl, width="stretch", hide_index=True)

day_tbl = day_summary_df(df, is_pace)
if day_tbl:
    st.dataframe(day_tbl, width="stretch", hide_index=True)

# ── Spell / innings / length callout ──────────────────────────────────────────
_box_lines = []

if is_pace and spd_spell1 is not None:
    _sp_parts = [f"Spell 1: {spd_spell1:.1f} kph"]
    if spd_spell2 is not None:
        _sp_parts.append(f"Spell 2: {spd_spell2:.1f} kph")
    if spd_spell3p is not None:
        _sp_parts.append(f"Spell 3+: {spd_spell3p:.1f} kph")
    _sp_trend = ""
    if spd_spell1 is not None and spd_spell3p is not None:
        _d = spd_spell1 - spd_spell3p
        _sp_trend = f" — {abs(_d):.1f} kph {'drop' if _d > 0 else 'gain'} from first to last spell"
    elif spd_spell1 is not None and spd_spell2 is not None:
        _d = spd_spell1 - spd_spell2
        _sp_trend = f" — {abs(_d):.1f} kph {'drop' if _d > 0 else 'gain'} from Spell 1 to 2"
    _box_lines.append(f"<b>Speed by spell:</b> {' → '.join(_sp_parts)}{_sp_trend}")

if spd_inn1 is not None and spd_inn2 is not None:
    _id = spd_inn1 - spd_inn2
    _box_lines.append(
        f"<b>Speed by innings:</b> 1st innings {spd_inn1:.1f} kph → 2nd innings {spd_inn2:.1f} kph "
        f"({abs(_id):.1f} kph {'faster' if _id > 0 else 'slower'} in their first bowl)"
    )
elif spd_inn1 is not None:
    _box_lines.append(f"<b>Speed by innings:</b> 1st innings {spd_inn1:.1f} kph (insufficient 2nd innings data)")

if len_spell1 is not None:
    _ln_parts = [f"Spell 1: {len_spell1:.1f}m"]
    if len_spell2 is not None:
        _ln_parts.append(f"Spell 2: {len_spell2:.1f}m")
    if len_spell3p is not None:
        _ln_parts.append(f"Spell 3+: {len_spell3p:.1f}m")
    _ln_trend = ""
    _last_len = len_spell3p if len_spell3p is not None else len_spell2
    if _last_len is not None:
        _ld = _last_len - len_spell1
        _ln_trend = f" — bowling {'fuller' if _ld < 0 else 'shorter'} as the spell progresses ({abs(_ld):.1f}m)"
    _box_lines.append(f"<b>Length by spell:</b> {' → '.join(_ln_parts)}{_ln_trend}")

if _box_lines:
    st.markdown(
        "<div class='info-box'>" + "<br>".join(_box_lines) + "</div>",
        unsafe_allow_html=True,
    )

st.divider()

# ── Beaten zones (where they beat the bat) ─────────────────────────────────────
if beaten_df:
    st.subheader("Beaten Zones (play-and-miss)")
    st.caption(f"Where the batter played and missed — {len(beaten_df):,} beaten balls in this selection.")
    _bc_map, _bc_txt = st.columns([3, 2])
    with _bc_map:
        st.plotly_chart(
            pitch_scatter_map(beaten_df, line_zones, length_zones,
                              value="count", title="Where they beat the bat", min_balls=1),
            width="stretch",
        )
    with _bc_txt:
        miss_zone = zone_concentration(beaten_df, line_zones, length_zones, "count")
        if miss_zone:
            st.markdown(
                f"<div class='info-box'>"
                f"<b>Most common miss:</b> {miss_zone['length']} / {miss_zone['line']} — "
                f"{miss_zone['share'] * 100:.0f}% of beaten balls "
                f"({int(miss_zone['value'])} of {int(miss_zone['total'])}).<br>"
                f"<span style='color:#6b7280'>Beaten {_fmt(beaten_pct, '.1f', '%')} · "
                f"False-shot {_fmt(false_pct, '.1f', '%')} of tracked balls (n={n_tracked:,}).</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    st.divider()

# ── Danger zones summary ───────────────────────────────────────────────────────
st.subheader("Danger Zones Summary")

# Context reflects the active sidebar filters — the whole section is hand- and
# position-agnostic, working out the zones for whatever subset is selected.
_ctx_parts = [{"All": "All batters", "vs LHB": "vs LHB", "vs RHB": "vs RHB"}[hand_filter]]
if pos_filter != "All positions":
    _ctx_parts.append(pos_filter)
if spell_filter != "All":
    _ctx_parts.append(spell_filter)
st.caption("Showing: " + " · ".join(_ctx_parts) + "  ·  zones follow the pitch-line / length-grouping settings")


def _danger_card(header, big, sub, accent="#b91c1c"):
    return (
        f"<div class='danger-box'>"
        f"<div style='font-size:0.7rem;color:{accent};text-transform:uppercase;"
        f"letter-spacing:.08em;margin-bottom:6px'>{header}</div>"
        f"<div style='font-size:1.15rem;font-weight:700;margin-bottom:4px'>{big}</div>"
        f"<div style='font-size:0.85rem;color:#6b7280'>{sub}</div>"
        f"</div>"
    )


_r1c1, _r1c2 = st.columns(2)
with _r1c1:
    if wkt_zone:
        st.markdown(_danger_card(
            "⚠ Wickets — where most come from",
            f"{wkt_zone['length']} / {wkt_zone['line']}",
            f"{wkt_zone['share'] * 100:.0f}% of wickets — {int(wkt_zone['value'])} of {int(wkt_zone['total'])} "
            f"({wkt_zone['balls']:,} balls in this zone)",
        ), unsafe_allow_html=True)
    else:
        st.info("Insufficient wicket data for this selection.")
with _r1c2:
    if run_zone:
        st.markdown(_danger_card(
            "Runs — where most are conceded",
            f"{run_zone['length']} / {run_zone['line']}",
            f"{run_zone['share'] * 100:.0f}% of runs — {int(run_zone['value'])} of {int(run_zone['total'])} "
            f"({run_zone['balls']:,} balls in this zone)",
            accent="#6b7280",
        ), unsafe_allow_html=True)
    else:
        st.info("Insufficient run data for this selection.")


def _rate_sub(dz):
    tag = " · ⚠ low sample" if dz.get("low_conf") else ""
    return (
        f"{dz['wickets']} wkts from {dz['balls']:,} balls · "
        f"{dz['adj_rate']:.1f}% adjusted ({dz['rate']:.1f}% raw){tag}"
    )


_r2c1, _r2c2, _r2c3 = st.columns(3)
with _r2c1:
    if dline:
        st.markdown(_danger_card("⚠ Danger line", f"{dline['line']}", _rate_sub(dline)),
                    unsafe_allow_html=True)
    else:
        st.info("Insufficient data for a danger line (need ≥30 balls in a zone).")
with _r2c2:
    if dlen:
        st.markdown(_danger_card("⚠ Danger length", f"{dlen['length']}", _rate_sub(dlen)),
                    unsafe_allow_html=True)
    else:
        st.info("Insufficient data for a danger length (need ≥30 balls in a band).")
with _r2c3:
    if dcell:
        st.markdown(_danger_card("⚠ Most lethal zone (by rate)",
                                 f"{dcell['length']} / {dcell['line']}", _rate_sub(dcell)),
                    unsafe_allow_html=True)
    else:
        st.info("Insufficient data for a most-lethal zone (need ≥30 balls in a cell).")

st.markdown("<div style='margin-top:1.25rem'></div>", unsafe_allow_html=True)

with st.expander("How is the danger length / lethal zone worked out?"):
    st.markdown(
        """
**Brief explanation**

We *don't* simply crown the length with the highest wicket percentage. If a bowler
took 1 wicket from only 33 balls at a length, that reads as a scary 3% — but it's
really just one ball, and one ball doesn't make a length dangerous.

So we **blend each length's record with the bowler's overall average**, and we trust
a length more the *more deliveries* he's bowled there:

- A length he's hammered away at for hundreds of balls is taken at face value.
- A length with only a handful of balls gets pulled back towards his normal rate,
  because we haven't seen enough to believe a freak number.

A length only rises to the top of the list if it's **consistently** productive over a
big sample — not a one-off. The card shows the **adjusted** rate (what we actually
trust) next to the **raw** rate (the unsmoothed number), plus the balls behind it, and
flags *“low sample”* when a winner is built on very few wickets.

*Example — Cummins to top-4 left-handers:* short balls read 3.0% raw off 33 balls, but
adjust to ~1.9%; back-of-a-length is 2.0% off **490** balls and holds at ~2.0% — so
back-of-a-length is the genuine danger, not the short ball.

---

**Technical detail**

This is **empirical-Bayes shrinkage** with a Beta prior. Each zone's wicket rate is
shrunk toward the subset baseline `p₀ = total wickets / total balls`:

```
adjusted_rate = (wickets + K·p₀) / (balls + K)
```

`K` is the prior strength in balls (currently **80** — roughly 13 overs). It's
equivalent to starting every zone from a `Beta(K·p₀, K·(1−p₀))` prior and updating it
with that zone's `(wickets, balls)`. Small samples sit near `p₀`; large samples
dominate the prior and converge on the raw rate. Zones are ranked by `adjusted_rate`,
with a `min_balls = 30` floor, a `min_wkts = 3` eligibility gate, and a low-confidence
flag when `wickets < 5`. The baseline `p₀` is recomputed for whatever hand / position /
spell subset is selected, so the shrinkage target always matches the current view.
        """
    )

# ── Short-ball profile (pace only) ─────────────────────────────────────────────
if is_pace and n_balls > 0:
    st.divider()
    st.subheader("Short-ball Usage")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Short ball frequency</div>"
            f"<div class='value'>{_fmt(short_pct, '.0f')}%</div>"
            f"<div class='sub'>of legal deliveries</div>"
            f"</div>", unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Short ball wickets</div>"
            f"<div class='value'>{P['sb_wkts']}</div>"
            f"<div class='sub'>from {P['sb_n']} short balls</div>"
            f"</div>", unsafe_allow_html=True
        )
    with c3:
        st.markdown(
            f"<div class='metric-card'>"
            f"<div class='label'>Short ball economy</div>"
            f"<div class='value'>{_fmt(P['sb_econ'])}</div>"
            f"<div class='sub'>{P['sb_runs']} runs conceded</div>"
            f"</div>", unsafe_allow_html=True
        )
