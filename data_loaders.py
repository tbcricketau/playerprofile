import streamlit as st
from config import DATA_SCHEMA
from cricket_core.config import (international_series_sql, series_sql,
                                 T20_LEAGUE_SERIES, t20_pool_sql)
from cricket_core.warehouse import set_conn_cursor, run_query

# Official international Tests only.  match_length_id does NOT separate internationals from
# domestic (Tests and Sheffield Shield both sit under id 5), so we filter on the competition
# type via Matches.series_id -> Series.name.  Verified to reproduce official Test tallies.
_TEST_SERIES = international_series_sql("Test")


def _intl_test(alias: str = "M") -> str:
    """WHERE-clause fragment restricting to official Test matches for a Matches alias."""
    return (f"{alias}.series_id IN "
            f"(SELECT series_id FROM [{DATA_SCHEMA}].[Series] WHERE name IN {_TEST_SERIES})")


def _intl(fmt: str = "Test", alias: str = "M", level: str = "international") -> str:
    """WHERE fragment restricting to one format at one LEVEL of cricket.

    match_length_id mixes internationals with domestic, so we scope by Series.name. `level` picks
    which body of cricket counts as the player's record: "international" (the default, official
    internationals) or "a-team" (International 1st Class / Tour Matches / List A ODI). Format is
    the shape of the game, level is its standard — see cricket_core.config.A_TEAM_SERIES."""
    return (f"{alias}.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
            f"WHERE name IN {series_sql(fmt, level)})")


# The T20 pack pools ALL major men's T20 competitions (mlid='7'), not just internationals, then
# neutralises by league strength (referencebuilder/t20_league_strength.csv). The list now lives in
# cricket_core.config.T20_LEAGUE_SERIES — it was duplicated here and in matchupmodel, kept in sync
# by a comment asking the next person to remember. See memory t20-league-strength.
_T20_LEAGUES = T20_LEAGUE_SERIES


def _t20_all(alias: str = "M") -> str:
    """WHERE fragment for all major men's T20 competitions (T20 format = match_length_id '7')."""
    return (f"{alias}.match_length_id='7' AND {alias}.series_id IN "
            f"(SELECT series_id FROM [{DATA_SCHEMA}].[Series] WHERE name IN {t20_pool_sql()})")


def _scope(fmt: str, alias: str = "M", level: str = "international") -> str:
    """Which body of cricket a query counts. 'T20' pools all major T20 leagues; everything else is
    that format at that level — internationals by default, A-team cricket when level="a-team"."""
    return _t20_all(alias) if str(fmt).upper() == "T20" else _intl(fmt, alias, level)


@st.cache_data(ttl=3600)
def load_test_teams() -> list:
    """Teams that have bowled in Test matches."""
    conn, cursor = set_conn_cursor()
    query = f"""
    SELECT T.team_id, T.team_name
    FROM [{DATA_SCHEMA}].[Teams] AS T
    WHERE EXISTS (
        SELECT 1
        FROM [{DATA_SCHEMA}].[Deliveries] AS D
        JOIN [{DATA_SCHEMA}].[Matches]    AS M ON D.match_id = M.match_id
        WHERE D.team_bowling_id = T.team_id
          AND {_intl_test('M')}
    )
    ORDER BY T.team_name
    """
    result = run_query(query, conn, cursor)
    conn.close()
    return result


@st.cache_data(ttl=3600)
def load_team_bowlers(team_id: str) -> list:
    """Bowlers with >= 60 legal deliveries in Tests for this team."""
    conn, cursor = set_conn_cursor()
    query = f"""
    SELECT
        D.bowler_id,
        MAX(P.name)    AS player_name,
        MAX(P.surname) AS last_name,
        COUNT(*)       AS balls
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches]    AS M ON D.match_id   = M.match_id
    JOIN [{DATA_SCHEMA}].[Players]    AS P ON D.bowler_id  = P.player_id
    WHERE D.team_bowling_id     = '{team_id}'
      AND {_intl_test('M')}
      AND D.legal_ball          = '1'
    GROUP BY D.bowler_id
    HAVING COUNT(*) >= 60
    ORDER BY MAX(P.surname)
    """
    result = run_query(query, conn, cursor)
    conn.close()
    return result


@st.cache_data(ttl=86400)
def load_fielding_positions() -> dict:
    """Fielding-position lookup (type 33): {id_str: description}."""
    conn, cursor = set_conn_cursor()
    query = f"SELECT id, description FROM [{DATA_SCHEMA}].[Lookups] WHERE lookup_type_id = 33"
    result = run_query(query, conn, cursor)
    conn.close()
    return {str(r["id"]): r["description"] for r in result}


@st.cache_data(ttl=3600)
def load_bowler_catch_positions(bowler_id: str) -> dict:
    """For a bowler's caught Test dismissals: {delivery_id: fielding_position_id}.

    The catcher is the DeliveryFielders row with fielder_catch = 1.  Some catches
    have no recorded position (id 0/28/NULL) — those map to None.
    """
    conn, cursor = set_conn_cursor()
    query = f"""
    SELECT D.[delivery_id] AS delivery_id, DF.[fielder_event_position_id] AS pos_id
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches] AS M ON D.match_id = M.match_id
    JOIN [{DATA_SCHEMA}].[DeliveryFielders] AS DF
        ON DF.delivery_id = D.delivery_id AND DF.fielder_catch = 1
    WHERE D.bowler_id = '{bowler_id}'
      AND {_intl_test('M')}
      AND D.bowler_dismissal = '1'
      AND D.how_out_id = '5'
    """
    result = run_query(query, conn, cursor)
    conn.close()
    out = {}
    for r in result:
        pid = r["pos_id"]
        out[r["delivery_id"]] = None if pid in (None, "None", "0", "28") else pid
    return out


@st.cache_data(ttl=3600)
def load_bowler_info(bowler_id: str, fmt: str = "Test", level: str = "international") -> dict:
    """Name, surname and primary (most-common) bowling team for a bowler in one format at one
    level. Falls back to the Players table for the name if the bowler has no deliveries in that
    scope (e.g. a white-ball specialist with no Tests, or an uncapped A-team player)."""
    conn, cursor = set_conn_cursor()
    query = f"""
    SELECT TOP 1
        P.name    AS player_name,
        P.surname AS last_name,
        T.team_name AS team_name
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches] AS M ON D.match_id = M.match_id
    JOIN [{DATA_SCHEMA}].[Players] AS P ON D.bowler_id = P.player_id
    JOIN [{DATA_SCHEMA}].[Teams]   AS T ON D.team_bowling_id = T.team_id
    WHERE D.bowler_id = '{bowler_id}'
      AND {_scope(fmt, 'M', level)}
    GROUP BY P.name, P.surname, T.team_name
    ORDER BY COUNT(*) DESC
    """
    result = run_query(query, conn, cursor)
    if not result:      # no deliveries in this format — at least get the name
        result = run_query(f"SELECT TOP 1 P.name AS player_name, P.surname AS last_name, "
                           f"'' AS team_name FROM [{DATA_SCHEMA}].[Players] P "
                           f"WHERE P.player_id = '{bowler_id}'", conn, cursor)
    conn.close()
    if not result:
        # No warehouse record at all — a reserved 99xxxxxxx id for a player only Cricket-21 has
        # (Nachiket Bhute). Name from the C21 map, in the warehouse's "Surname, Other names" form.
        import c21_source
        nm = (c21_source.player_map().get(str(bowler_id)) or {}).get("name") or ""
        if nm:
            first, _sep, last = nm.rpartition(" ")
            return {"player_name": f"{last}, {first}" if first else last, "last_name": last,
                    "team_name": ""}
    return result[0] if result else {}


@st.cache_data(ttl=3600)
def search_bowlers(name_like: str) -> list:
    """Bowlers whose name/surname matches a search string, with Test ball counts
    and derived bowling type — for resolving report player IDs."""
    conn, cursor = set_conn_cursor()
    like = name_like.replace("'", "''")
    query = f"""
    SELECT
        b.bowler_id,
        b.player_name,
        b.last_name,
        b.balls,
        b.bowl_type,
        (SELECT TOP 1 T.team_name
         FROM [{DATA_SCHEMA}].[Deliveries] D2
         JOIN [{DATA_SCHEMA}].[Matches] M2 ON D2.match_id = M2.match_id
         JOIN [{DATA_SCHEMA}].[Teams]   T  ON D2.team_bowling_id = T.team_id
         WHERE D2.bowler_id = b.bowler_id AND {_intl_test('M2')}
         GROUP BY T.team_name ORDER BY COUNT(*) DESC) AS team_name
    FROM (
        SELECT
            D.bowler_id,
            MAX(P.name)    AS player_name,
            MAX(P.surname) AS last_name,
            COUNT(*)       AS balls,
            MAX(CASE
                WHEN D.[bowler_style_id] IN ('1','2') THEN 'Fast'
                WHEN D.[bowler_style_id] = '3' THEN 'Medium'
                WHEN D.[bowler_style_id] = '4' AND D.[bowler_hand_id] = '1' THEN 'Off Spin'
                WHEN D.[bowler_style_id] = '4' AND D.[bowler_hand_id] = '2' THEN 'Left Orthodox'
                WHEN D.[bowler_style_id] = '5' AND D.[bowler_hand_id] = '1' THEN 'Leg Break'
                WHEN D.[bowler_style_id] = '5' AND D.[bowler_hand_id] = '2' THEN 'Left Unorthodox'
                ELSE 'Other' END) AS bowl_type
        FROM [{DATA_SCHEMA}].[Deliveries] AS D
        JOIN [{DATA_SCHEMA}].[Matches] AS M ON D.match_id  = M.match_id
        JOIN [{DATA_SCHEMA}].[Players] AS P ON D.bowler_id = P.player_id
        WHERE {_intl_test('M')}
          AND D.legal_ball = '1'
          AND (P.name LIKE '%{like}%' OR P.surname LIKE '%{like}%')
        GROUP BY D.bowler_id
        HAVING COUNT(*) >= 60
    ) b
    ORDER BY b.balls DESC
    """
    result = run_query(query, conn, cursor)
    conn.close()
    return result


def load_bowler_deliveries(bowler_id: str, dev_limit: int = 0, fmt: str = "Test",
                           level: str = "international",
                           source: str = "warehouse", dedupe: bool = True) -> list:
    """All deliveries for a bowler in one format at one level, with fields needed for profiling.

    fmt:    'Test' | 'ODI' | 'T20I' | 'T20'  — the shape of the game.
    level:  'international' | 'a-team'       — the standard of the game (see _intl).
    source: 'warehouse' | 'c21' | 'both'     — where the ball record comes from.

    The three are orthogonal. `source` exists because the warehouse holds no Indian domestic
    cricket at all, so an India A bowler's record there can be a few hundred balls at 38%
    tracking while Cricket-21 has thousands at 98% (see c21_source). 'both' unions them and
    re-sorts by date; the C21 rows carry `source='c21'` so a consumer can tell them apart.

    dev_limit: if > 0, caps rows returned (for fast local testing only).

    The warehouse pull is cached on (id, dev_limit, fmt, level) ONLY — `_warehouse_bowler_rows`.
    `dedupe` and `source` used to sit on the cached function, so a caller passing dedupe=False
    for the clips missed the cache the profile had just filled and re-ran the same ~300 s query.
    For a warehouse-only player the two calls are byte-identical; ~15 bowlers in a full
    build_opponent_about run paid it twice (measured 24-09-2026).
    """
    if source not in ("warehouse", "c21", "both"):
        raise ValueError(f"unknown source {source!r} — warehouse | c21 | both")
    if source != "warehouse":
        import c21_source
        extra = c21_source.load_bowler_deliveries(bowler_id, fmt=fmt)
        if source == "c21":
            return extra[:dev_limit] if dev_limit > 0 else extra
        base = _warehouse_bowler_rows(bowler_id, dev_limit, fmt, level)
        # STATISTICS dedupe, CLIPS do not. A match held by both sources must count once or the
        # averages double (c21_source.merge_with_warehouse) — but the two sources hold DIFFERENT
        # footage of that match, and dropping one side throws playable clips away. Zimbabwe's C21
        # pull cost Sikandar Raza 11 of 14 wicket balls to left-handers that way (2026-09-13), all
        # of which played. Clip builders pass dedupe=False and take the union.
        rows = c21_source.merge_with_warehouse(base, extra) if dedupe else base + extra
        both = sorted(rows, key=lambda r: str(r.get("match_date") or ""))
        return both[:dev_limit] if dev_limit > 0 else both
    return _warehouse_bowler_rows(bowler_id, dev_limit, fmt, level)


# Lookup types this loader resolves client-side, and the column each fills. Fetching the
# `description` for every ball is what made this query slow: the SQL itself runs in about 7
# seconds on a 15,000-ball career and the rows took another 297 to arrive, at roughly 6 seconds
# per text column per 15,000 rows (measured 24-09-2026). The ids are a few bytes each and the
# vocabulary is a few hundred rows, so the join belongs here, not on the wire.
_LOOKUP_COLS = {
    "stroke": (24, "stroke_id"),
    "ball_movement": (2812, "ball_movement_id"),
    "striker_hand": (10, "striker_hand_id"),
    "bowler_pace_spin": (2805, "bowler_pace_spin_id"),
    "pitch_length_group_pace": (2819, "pitch_length_group_pace_1_id"),
    "pitch_length_group_pace_2": (2820, "pitch_length_group_pace_2_id"),
    "pitch_line_group_pace": (2823, "pitch_line_group_pace_id"),
    "pitch_length_group_spin": (2821, "pitch_length_group_spin_1_id"),
    "pitch_line_group_spin": (2824, "pitch_line_group_spin_id"),
}
_lookup_cache: dict = {}


def _lookups(conn, cursor) -> dict:
    """{(lookup_type_id, id): description} for the types this loader needs, read once per process.
    A missing id reads "None", which is what a LEFT JOIN miss gave and what every consumer of
    these string rows already expects."""
    if not _lookup_cache:
        types = ", ".join(str(t) for t, _ in _LOOKUP_COLS.values())
        rows = run_query(f"SELECT [lookup_type_id], [id], [description] FROM [{DATA_SCHEMA}].[Lookups] "
                         f"WHERE [lookup_type_id] IN ({types})", conn, cursor)
        for r in rows:
            _lookup_cache[(r["lookup_type_id"], r["id"])] = r["description"]
    return _lookup_cache


def _match_facts(bowler_id, fmt, level, conn, cursor) -> dict:
    """{match_id: {season, match_name, venue_country, venue_city, competition, …}} — the columns
    that describe the MATCH, fetched once per match instead of once per ball. `match_name` alone
    is ~40 characters repeated on every delivery."""
    q = f"""
    SELECT M.[match_id],
           M.[match_length_id],
           SR.[gender_id],
           S.[name]  AS season,
           CONCAT(L_ml.[description], ' ', TA.[team_name], ' v ', TB.[team_name], ' ',
                  FORMAT(M.[match_date], 'dd-MM-yyyy')) AS match_name,
           VC.[name] AS venue_country,
           V.[city_name] AS venue_city,
           SR.[name] AS competition
    FROM [{DATA_SCHEMA}].[Matches] AS M
    LEFT JOIN [{DATA_SCHEMA}].[Venues] AS V  ON M.[venue_id]  = V.[venue_id]
    LEFT JOIN [{DATA_SCHEMA}].[Countries] AS VC ON V.[country_id] = VC.[country_id]
    LEFT JOIN [{DATA_SCHEMA}].[Seasons] AS S ON M.[season_id] = S.[season_id]
    LEFT JOIN [{DATA_SCHEMA}].[Series] AS SR ON M.[series_id] = SR.[series_id]
    LEFT JOIN [{DATA_SCHEMA}].[Teams] AS TA  ON M.[team_a_id] = TA.[team_id]
    LEFT JOIN [{DATA_SCHEMA}].[Teams] AS TB  ON M.[team_b_id] = TB.[team_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_ml
        ON L_ml.[lookup_type_id] = 3 AND L_ml.[id] = M.[match_length_id]
    WHERE M.[match_id] IN (SELECT DISTINCT D.[match_id] FROM [{DATA_SCHEMA}].[Deliveries] AS D
                           JOIN [{DATA_SCHEMA}].[Matches] AS M2 ON D.[match_id] = M2.[match_id]
                           WHERE D.[bowler_id] = '{bowler_id}' AND {_scope(fmt, 'M2', level)})
    """
    return {r["match_id"]: r for r in run_query(q, conn, cursor)}


@st.cache_data(ttl=3600)
def _warehouse_bowler_rows(bowler_id: str, dev_limit: int, fmt: str, level: str) -> list:
    """The warehouse half of load_bowler_deliveries — see its docstring for why this is the
    cached unit."""
    conn, cursor = set_conn_cursor()
    top_clause = f"TOP {dev_limit}" if dev_limit > 0 else ""
    query = f"""
    SELECT {top_clause}
        D.[match_id],
        D.[delivery_id],
        D.[striker_id],
        D.[video_file_name],
        M.[match_length_id],
        CONVERT(VARCHAR(10), M.[match_date], 120)   AS match_date,
        D.[match_innings],
        D.[over],
        D.[ball_in_over],
        D.[bowler_spell],
        D.[match_day],
        D.[striker_batting_position],
        D.[over_the_wicket],
        D.[bowler_variation],
        D.[legal_ball],
        D.[wide_runs],
        D.[noball_runs],
        D.[bat_score],
        D.[hit_to_x_physical],
        D.[hit_to_y_physical],
        D.[hit_to_length],
        D.[hit_to_angle],
        D.[bowler_dismissal],
        D.[how_out_id],
        D.[shot_quality_id],
        D.[stroke_id],
        D.[batter_missed_id],
        D.[ball_speed],
        D.[pitch_line],
        D.[pitch_length],
        D.[pitch_line_coded],
        D.[pitch_length_coded],
        D.[at_stumps_line],
        D.[at_stumps_height],
        D.[movement_in_air],
        D.[movement_off_pitch],
        D.[movement_in_air_group_swing_id],
        D.[movement_off_pitch_group_seam_id],
        D.[ball_movement_id],
        D.[release_line_unmirrored],
        D.[release_height],
        D.[bounce_angle_delta],
        D.[striker_hand_id],
        CASE
            WHEN D.[bowler_style_id] IN ('1','2') AND D.[bowler_hand_id] = '1' THEN 'Right Fast'
            WHEN D.[bowler_style_id] IN ('1','2') AND D.[bowler_hand_id] = '2' THEN 'Left Fast'
            WHEN D.[bowler_style_id] = '3'        AND D.[bowler_hand_id] = '1' THEN 'Right Medium'
            WHEN D.[bowler_style_id] = '3'        AND D.[bowler_hand_id] = '2' THEN 'Left Medium'
            WHEN D.[bowler_style_id] = '4'        AND D.[bowler_hand_id] = '1' THEN 'Off Spin'
            WHEN D.[bowler_style_id] = '4'        AND D.[bowler_hand_id] = '2' THEN 'Left Orthodox'
            WHEN D.[bowler_style_id] = '5'        AND D.[bowler_hand_id] = '1' THEN 'Leg Break'
            WHEN D.[bowler_style_id] = '5'        AND D.[bowler_hand_id] = '2' THEN 'Left Unorthodox'
            ELSE 'Other'
        END                                          AS bowler_type_simple,
        D.[bowler_pace_spin_id],
        D.[pitch_length_group_pace_1_id],
        D.[pitch_length_group_pace_2_id],
        D.[pitch_line_group_pace_id],
        D.[pitch_length_group_spin_1_id],
        D.[pitch_line_group_spin_id]
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches]    AS M   ON D.[match_id]     = M.[match_id]
    WHERE D.[bowler_id]          = '{bowler_id}'
      AND {_scope(fmt, 'M', level)}
    ORDER BY M.[match_date], D.[match_innings], D.[over], D.[ball_in_over]
    """
    result = run_query(query, conn, cursor)
    # Put back, from here, exactly what the LEFT JOINs used to send on every row: the lookup
    # descriptions and the columns that describe the match. Same keys, same strings — verified
    # row for row against the old query before this replaced it.
    look = _lookups(conn, cursor)
    facts = _match_facts(bowler_id, fmt, level, conn, cursor)
    conn.close()
    for r in result:
        for col, (type_id, id_col) in _LOOKUP_COLS.items():
            r[col] = look.get((str(type_id), r.get(id_col)), "None")
        m = facts.get(r["match_id"], {})
        for col in ("season", "gender_id", "match_name", "venue_country", "venue_city",
                    "competition"):
            r[col] = m.get(col, "None")
    return result
