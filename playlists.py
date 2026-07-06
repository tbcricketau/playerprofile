"""playlists.py — build per-insight Fairplay video playlists for a bowler profile.

Turns the same ball-sets the report describes (stock ball, wickets, new-ball out-swingers,
beaten bat) into ordered lists of playable clips, written as a JSON sidecar next to the PDF.
Uses the shared `ludis_cricket.video` clip resolver, so the format/plumbing is reusable by
other projects (livetrackingdashboard etc.).
"""
from ludis_cricket.video import playlist_item, resolve_playlist, write_playlists, attach_hawkeye
from ludis_cricket.lookups import conditions_tier, conditions_bucket

# Over-select this many candidates per list, then keep the first `cap` whose clip exists
# (coverage is patchy, so we need headroom). One HEAD probe per candidate (cached).
_CAND_MULT = 4


def _fmt_speed(r):
    s = r.get("ball_speed_n")
    return f"{s:.0f} km/h" if s else None


def _swing_word(r, is_spin):
    d = r.get("swing_dir")
    if d == "straight" or d is None:
        return None
    verb = "drift" if is_spin else "swing"
    return f"{verb} in" if d == "in" else (f"{verb} away")


def _turn_word(r, is_spin):
    """Turn/seam direction off the pitch, batter-relative to the clip's batter."""
    d = r.get("seam_dir")
    if d == "straight" or d is None:
        return None
    verb = "turn" if is_spin else "seam"
    return f"{verb} in" if d == "in" else (f"{verb} away")


def _outcome(r):
    if r.get("is_wicket"):
        return (r.get("how_out") or "wicket").lower()
    runs = int(r.get("bat_score_n") or 0)
    if runs == 0:
        return "dot"
    return f"{runs} run" + ("s" if runs != 1 else "")


def _caption(r, is_spin):
    parts = []
    ov, bo = r.get("over_n"), r.get("ball_in_over")
    if ov is not None:
        parts.append(f"Ov {ov}.{bo}" if bo not in (None, "", "None") else f"Ov {ov}")
    bt = r.get("ball_type")
    if bt:
        parts.append(f"{bt[0].lower()} {bt[1]}")
    for x in (_fmt_speed(r), _turn_word(r, is_spin), _swing_word(r, is_spin), _outcome(r)):
        if x:
            parts.append(x)
    vc = r.get("venue_country")
    if vc and vc != "None":
        yr = (r.get("match_date") or "")[:4]
        parts.append(f"{vc}{(' ' + yr) if yr else ''}")   # conditions cue for like-for-like
    return " · ".join(parts)


def _item(r, is_spin):
    return playlist_item(
        r.get("delivery_id"), r.get("clip_stem"), _caption(r, is_spin),
        meta={
            "over": r.get("over_n"), "speed_kph": r.get("ball_speed_n"),
            "swing_dir": r.get("swing_dir"), "seam_dir": r.get("seam_dir"),
            "length_m": r.get("pitch_length_m"), "line_m": r.get("pitch_line_m"),
            "is_wicket": bool(r.get("is_wicket")), "how_out": r.get("how_out"),
            "match": r.get("match_name"), "date": r.get("match_date"),
            "country": r.get("venue_country"), "city": r.get("venue_city"),
        },
    )


def _diversify(rows):
    """Interleave a recency-ordered list across outcome types (wicket / boundary / dot /
    other) so the top of a stock-ball playlist shows a VARIETY of the delivery rather than a
    clump of wickets. Recency is preserved within each outcome bucket."""
    buckets = {"wkt": [], "bdry": [], "dot": [], "other": []}
    for r in rows:
        if r.get("is_wicket"):
            k = "wkt"
        elif (r.get("bat_score_n") or 0) in (4.0, 6.0):
            k = "bdry"
        elif (r.get("bat_score_n") or 0) == 0:
            k = "dot"
        else:
            k = "other"
        buckets[k].append(r)
    # round-robin, leading with a couple of representative outcomes rather than wickets first
    order = ["dot", "other", "bdry", "wkt"]
    out, i = [], 0
    while any(buckets[k] for k in order):
        for k in order:
            if buckets[k]:
                out.append(buckets[k].pop(0))
        i += 1
        if i > 500:
            break
    return out


def _with_hawkeye(items, rows):
    """Attach Hawkeye multi-camera angles (front-on/side-on) where the match has coverage —
    the modal player shows angle toggles per clip. Best-effort, no-op without coverage."""
    try:
        by_id = {str(r.get("delivery_id")): r for r in rows if r.get("delivery_id")}
        return attach_hawkeye(items, by_id)
    except Exception:
        return items


def _resolve_take(rows, is_spin, cap, target_country=None):
    """Resolve candidate clips (probing recency-first, since storage coverage is concentrated
    on recent matches), then order the ones that EXIST by like-for-like conditions tier —
    target country, then same conditions bucket, then the rest — recency within each tier.
    Ordering the *resolved* set (not the candidates) avoids un-clipped tier-1 balls crowding
    out the clipped ones. Returns (items_with_url, n_available, n_considered)."""
    items = [_item(r, is_spin) for r in rows[: max(cap * _CAND_MULT, 48)]]
    resolved, avail, _ = resolve_playlist(items, drop_missing=True)
    # stable tier sort keeps the incoming (recency/illustrative) order within each tier
    resolved.sort(key=lambda it: conditions_tier((it.get("meta") or {}).get("country"), target_country))
    return _with_hawkeye(resolved[:cap], rows), min(avail, cap), len(rows)


def build_playlists(P: dict, cap: int = 10, target_country: str | None = None) -> dict:
    """Return {playlists: {...}, meta: {...}} ready for write_playlists. Insights: stock ball,
    wickets, new-ball out-swingers (pace). Illustrative balls first (false shots / wickets),
    only deliveries whose clip is actually in storage.

    `target_country` = where the upcoming series is played (e.g. 'Australia' for a home
    series). When set, clips are ordered by LIKE-FOR-LIKE conditions first — same country,
    then the same conditions bucket (AUS↔SA/NZ etc.), then the rest — and by recency within
    each tier. When None, pure recency (coverage is better on recent matches anyway)."""
    df = [r for r in P["df"] if r.get("clip_stem")]
    is_spin, is_pace = P["is_spin"], P["is_pace"]
    out, counts = {}, {}

    def add(key, rows):
        if not rows:
            return
        # Probe in the caller's order (recency / illustrative-first); _resolve_take then orders
        # the clips that actually exist by like-for-like conditions tier.
        items, avail, considered = _resolve_take(rows, is_spin, cap, target_country)
        if items:
            out[key] = items
            counts[key] = {"shown": len(items), "available": avail, "in_group": considered}

    # Recency ordering (coverage is better on recent matches); tier is layered on in add().
    def _recent_first(rows):
        rows.sort(key=lambda r: r.get("match_date") or "", reverse=True)
        return rows

    # Stock ball & each ball type: show a VARIETY of the delivery (dots, ones, the odd wicket) —
    # not just his wicket balls — so a viewer sees the typical ball. Recency order gives a natural
    # spread of outcomes; _diversify then interleaves outcomes so wickets don't clump at the top.
    st = (P.get("ball_types") or {}).get("stock")
    if st:
        add("stock_ball", _diversify(_recent_first(
            [r for r in df if r.get("ball_type") == (st["band"], st["region"])])))

    # One playlist per ball type shown in the report table (keyed bt_0.. matching row order),
    # so each ball-type row can link straight to that ball type's clips.
    for i, t in enumerate(((P.get("ball_types") or {}).get("types") or [])[:6]):
        add(f"bt_{i}", _diversify(_recent_first(
            [r for r in df if r.get("ball_type") == (t["band"], t["region"])])))

    # Wickets: all bowler-credited wicket balls, most recent first.
    add("wickets", _recent_first([r for r in df if r.get("is_wicket") and r.get("how_out")]))

    # Danger zone: deliveries in his most-lethal line × length cell (wickets/false shots first),
    # zoned with the same line/length zones the danger cell was computed from.
    dc = P.get("danger_cell")
    if dc and P.get("line_zones") and P.get("length_zones"):
        lz, ez = P["line_zones"], P["length_zones"]

        def _in_cell(r):
            x, y = r.get("pitch_line_m"), r.get("pitch_length_m")
            if x is None or y is None:
                return False
            rl = next((lbl for x0, x1, lbl in lz if x0 <= x < x1), None)
            re_ = next((lbl for y0, y1, lbl in ez if y0 <= y < y1), None)
            return rl == dc.get("line") and re_ == dc.get("length")
        cell = _recent_first([r for r in df if _in_cell(r)])
        cell.sort(key=lambda r: (not r.get("is_wicket"), not r.get("is_false_shot")))
        add("danger_cell", cell)

    # New-ball out-swingers (pace only): overs <= 25, swing label = out; recent first.
    if is_pace:
        add("new_ball_outswing", _recent_first(
            [r for r in df if r.get("swing_dir") == "out"
             and r.get("over_n") is not None and r["over_n"] <= 25]))

    order_note = ("most recent first" if not target_country else
                  f"like-for-like conditions first ({target_country} → similar conditions "
                  f"[{conditions_bucket(target_country) or 'n/a'}] → rest), most recent within each")
    meta = {
        "bowler": P.get("name"), "bowler_id": P.get("bowler_id"),
        "hand_filter": P.get("filters", {}).get("hand"),
        "target_country": target_country, "order": order_note,
        "counts": counts,
        "note": "Clips resolved via ludis_cricket.video (SSO SAS). 'available' = clips found in "
                "storage; coverage is per-delivery so some balls have no clip. Order: " + order_note + ".",
    }
    return {"playlists": out, "meta": meta}


def write_profile_playlists(P: dict, pdf_path: str, cap: int = 10) -> str | None:
    """Build playlists for a profile and write `<pdf>.playlists.json` next to the PDF.
    Returns the sidecar path, or None if nothing resolvable was found."""
    built = build_playlists(P, cap=cap)
    if not built["playlists"]:
        return None
    out_path = pdf_path.rsplit(".", 1)[0] + ".playlists.json"
    write_playlists(out_path, built["playlists"], meta=built["meta"])
    return out_path


# ── ODI bowling playlists ──────────────────────────────────────────────────────────
_ODI_VARIATION_MOVES = {"Slower ball", "Offcutter", "Legcutter", "Knuckle Ball", "Back of Hand"}


def _is_odi_variation(r, off_pace):
    """A slower-ball / cutter: coded as one (lookup 2812), or clearly off his stock pace."""
    if r.get("ball_movement") in _ODI_VARIATION_MOVES:
        return True
    s = r.get("ball_speed_n")
    return bool(off_pace and s and s <= off_pace)


def build_odi_playlists(P: dict, cap: int = 8, target_country: str | None = None) -> dict:
    """Video playlists for an ODI bowler profile — wickets, powerplay, death, yorkers, slower
    balls — reusing the shared clip resolver + captions. Only deliveries whose clip is actually
    in storage (coverage is per-delivery, concentrated on recent matches)."""
    df = [r for r in (P.get("raw") or []) if r.get("clip_stem")]
    is_spin, is_pace = P["is_spin"], P["is_pace"]
    off_pace = P.get("off_pace_kph")
    out, counts = {}, {}

    def _recent(rows):
        return sorted(rows, key=lambda r: r.get("match_date") or "", reverse=True)

    def add(key, rows):
        if not rows:
            return
        items, avail, considered = _resolve_take(rows, is_spin, cap, target_country)
        if items:
            out[key] = items
            counts[key] = {"shown": len(items), "available": avail, "in_group": considered}

    # Wickets — all bowler-credited, most recent first
    add("wickets", _recent([r for r in df if r.get("is_wicket") and r.get("how_out")]))
    # Powerplay / Death — a VARIETY of how he bowls in the phase (outcomes interleaved)
    add("powerplay", _diversify(_recent([r for r in df if r.get("phase") == "Powerplay"])))
    add("death", _diversify(_recent([r for r in df if r.get("phase") == "Death"])))
    if is_pace:
        from odi_profile import _is_bouncer
        # Yorkers / very full — the block-hole balls
        add("yorkers", _diversify(_recent(
            [r for r in df if r.get("pitch_length_m") is not None and r["pitch_length_m"] < 2.0])))
        # Bouncers / short balls
        add("bouncers", _diversify(_recent([r for r in df if _is_bouncer(r)])))
        # Slower balls, and the slower-ball yorker / slower-ball bouncer specifically
        if off_pace:
            add("slower_balls", _diversify(_recent(
                [r for r in df if _is_odi_variation(r, off_pace)])))
            add("slower_yorkers", _diversify(_recent(
                [r for r in df if r.get("pitch_length_m") is not None and r["pitch_length_m"] < 2.0
                 and _is_odi_variation(r, off_pace)])))
            add("slower_bouncers", _diversify(_recent(
                [r for r in df if _is_bouncer(r) and _is_odi_variation(r, off_pace)])))

    meta = {
        "bowler": P.get("name"), "bowler_id": P.get("bowler_id"), "format": "ODI",
        "target_country": target_country, "counts": counts,
        "note": "Clips via ludis_cricket.video (SSO SAS); coverage is per-delivery, concentrated "
                "on recent matches, so older balls may have no clip.",
    }
    return {"playlists": out, "meta": meta}


# ── Batting playlists ────────────────────────────────────────────────────────────
def _bat_caption(r):
    parts = []
    ov = r.get("over")
    if ov not in (None, "", "None"):
        parts.append(f"Ov {ov}")
    lb, lr = r.get("length_band"), r.get("line_region")
    if lb and lr:
        parts.append(f"{lb.lower()} {lr}")
    s = r.get("ball_speed_n")
    if s:
        parts.append(f"{s:.0f} km/h")
    bt = r.get("bowler_type_simple")
    if bt and bt != "Other":
        parts.append(f"v {bt}")
    if r.get("is_out"):
        parts.append((r.get("how_out") or "out").lower())
    elif r.get("is_false_shot"):
        parts.append("false shot")
    return " · ".join(parts)


def _bat_item(r):
    return playlist_item(r.get("delivery_id"), r.get("clip_stem"), _bat_caption(r), meta={
        "over": r.get("over"), "speed_kph": r.get("ball_speed_n"),
        "length": r.get("length_band"), "line": r.get("line_region"),
        "seam_dir": r.get("seam_dir"), "swing_dir": r.get("swing_dir"),
        "is_out": bool(r.get("is_out")), "how_out": r.get("how_out"),
        "bowler_type": r.get("bowler_type_simple"), "match": r.get("match_name"), "date": r.get("match_date"),
    })


def _bat_take(rows, cap):
    items = [_bat_item(r) for r in rows[: cap * _CAND_MULT]]
    resolved, avail, _ = resolve_playlist(items, drop_missing=True)
    return _with_hawkeye(resolved[:cap], rows)


def build_batting_playlists(P: dict, cap: int = 8) -> dict:
    """{key: [resolved items]} for a batter profile: the danger ball, his risky stroke's false
    shots, dismissals — recent/illustrative first, only deliveries whose clip is in storage."""
    raw = [r for r in (P.get("raw") or []) if r.get("clip_stem")]
    out = {}

    def add(key, rows):
        items = _bat_take(rows, cap)
        if items:
            out[key] = items

    g = P.get("grid_danger")
    if g:
        cell = [r for r in raw if r.get("length_band") == g["length_band"] and r.get("line_region") == g["line_region"]]
        cell.sort(key=lambda r: r.get("match_date") or "", reverse=True)
        cell.sort(key=lambda r: (not r.get("is_out"), not r.get("is_false_shot")))
        add("danger", cell)

    strokes = [d for d in (P.get("dims", {}).get("stroke") or []) if d["balls"] >= 30 and d.get("false_pct") is not None]
    if strokes:
        risky = max(strokes, key=lambda d: d["false_pct"])
        sr = [r for r in risky.get("rows", []) if r.get("is_false_shot") or r.get("is_out")]
        sr.sort(key=lambda r: r.get("match_date") or "", reverse=True)
        add("risky_stroke", sr)

    outs = [r for r in raw if r.get("is_out")]
    outs.sort(key=lambda r: r.get("match_date") or "", reverse=True)
    add("dismissals", outs)

    false_shots = [r for r in raw if r.get("is_false_shot") and not r.get("is_out")]
    false_shots.sort(key=lambda r: r.get("match_date") or "", reverse=True)
    add("false_shots", false_shots)
    return out
