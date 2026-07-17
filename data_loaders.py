import streamlit as st
from config import DATA_SCHEMA
from cricket_core.config import international_series_sql
from cricket_core.warehouse import set_conn_cursor, run_query

# Official international Tests only.  match_length_id does NOT separate internationals from
# domestic (Tests and Sheffield Shield both sit under id 5), so we filter on the competition
# type via Matches.series_id -> Series.name.  Verified to reproduce official Test tallies.
_TEST_SERIES = international_series_sql("Test")


def _intl_test(alias: str = "M") -> str:
    """WHERE-clause fragment restricting to official Test matches for a Matches alias."""
    return (f"{alias}.series_id IN "
            f"(SELECT series_id FROM [{DATA_SCHEMA}].[Series] WHERE name IN {_TEST_SERIES})")


def _intl(fmt: str = "Test", alias: str = "M") -> str:
    """WHERE fragment restricting to official internationals of a format (Test / ODI / T20I).
    match_length_id mixes internationals with domestic, so we scope by Series.name."""
    return (f"{alias}.series_id IN (SELECT series_id FROM [{DATA_SCHEMA}].[Series] "
            f"WHERE name IN {international_series_sql(fmt)})")


# The T20 pack pools ALL major men's T20 competitions (mlid='7'), not just internationals, then
# neutralises by league strength (referencebuilder/t20_league_strength.csv). Keep this list in
# sync with build_t20_league_strength.py. See memory t20-league-strength.
_T20_LEAGUES = (
    "International T20 M", "International T20 World Cup M", "England Domestic T20 M",
    "Aus Domestic T20 M", "Indian Premier League T20 M", "West Indies Domestic T20 M",
    "UAE Domestic T20 M", "Pakistan Domestic T20 M", "South Africa Domestic T20 M",
    "NZ Domestic T20 M", "USA Domestic T20 M", "Sri Lanka Domestic T20 M", "Global Super League M",
)


def _t20_all(alias: str = "M") -> str:
    """WHERE fragment for all major men's T20 competitions (T20 format = match_length_id '7')."""
    names = ",".join(f"'{n}'" for n in _T20_LEAGUES)
    return (f"{alias}.match_length_id='7' AND {alias}.series_id IN "
            f"(SELECT series_id FROM [{DATA_SCHEMA}].[Series] WHERE name IN ({names}))")


def _scope(fmt: str, alias: str = "M") -> str:
    """Format scope: 'T20' pools all major T20 leagues; everything else = that format's internationals."""
    return _t20_all(alias) if str(fmt).upper() == "T20" else _intl(fmt, alias)


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
def load_bowler_info(bowler_id: str, fmt: str = "Test") -> dict:
    """Name, surname and primary (most-common) bowling team for a bowler in a format's
    internationals. Falls back to the Players table for the name if the bowler has no
    deliveries in that format (e.g. a white-ball specialist with no Tests)."""
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
      AND {_intl(fmt, 'M')}
    GROUP BY P.name, P.surname, T.team_name
    ORDER BY COUNT(*) DESC
    """
    result = run_query(query, conn, cursor)
    if not result:      # no deliveries in this format — at least get the name
        result = run_query(f"SELECT TOP 1 P.name AS player_name, P.surname AS last_name, "
                           f"'' AS team_name FROM [{DATA_SCHEMA}].[Players] P "
                           f"WHERE P.player_id = '{bowler_id}'", conn, cursor)
    conn.close()
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


@st.cache_data(ttl=3600)
def load_bowler_deliveries(bowler_id: str, dev_limit: int = 0, fmt: str = "Test") -> list:
    """All deliveries for a bowler in a format's internationals, with fields needed for profiling.
    fmt: 'Test' | 'ODI' | 'T20I' (scopes to that format's official international series).
    dev_limit: if > 0, caps rows returned (for fast local testing only).
    """
    conn, cursor = set_conn_cursor()
    top_clause = f"TOP {dev_limit}" if dev_limit > 0 else ""
    query = f"""
    SELECT {top_clause}
        D.[match_id],
        D.[delivery_id],
        D.[striker_id],
        D.[video_file_name],
        M.[match_length_id],
        S.[name]                                     AS season,
        SR.[gender_id],
        CONVERT(VARCHAR(10), M.[match_date], 120)   AS match_date,
        CONCAT(
            L_ml.[description], ' ',
            TA.[team_name], ' v ', TB.[team_name], ' ',
            FORMAT(M.[match_date], 'dd-MM-yyyy')
        )                                            AS match_name,
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
        L_str.[description]                          AS stroke,
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
        L_bm.[description]                           AS ball_movement,
        D.[release_line_unmirrored],
        D.[release_height],
        D.[bounce_angle_delta],
        D.[striker_hand_id],
        L_sh.[description]                           AS striker_hand,
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
        L_bps.[description]                          AS bowler_pace_spin,
        L_plgp1.[description]                        AS pitch_length_group_pace,
        L_plgp2.[description]                        AS pitch_length_group_pace_2,
        L_plgp.[description]                         AS pitch_line_group_pace,
        L_plgs1.[description]                        AS pitch_length_group_spin,
        L_plgs.[description]                         AS pitch_line_group_spin,
        VC.[name]                                    AS venue_country,
        V.[city_name]                                AS venue_city,
        SR.[name]                                    AS competition
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches]    AS M   ON D.[match_id]     = M.[match_id]
    LEFT JOIN [{DATA_SCHEMA}].[Venues] AS V  ON M.[venue_id]     = V.[venue_id]
    LEFT JOIN [{DATA_SCHEMA}].[Countries] AS VC ON V.[country_id] = VC.[country_id]
    LEFT JOIN [{DATA_SCHEMA}].[Seasons] AS S ON M.[season_id]    = S.[season_id]
    LEFT JOIN [{DATA_SCHEMA}].[Series] AS SR ON M.[series_id]    = SR.[series_id]
    LEFT JOIN [{DATA_SCHEMA}].[Teams] AS TA  ON M.[team_a_id]   = TA.[team_id]
    LEFT JOIN [{DATA_SCHEMA}].[Teams] AS TB  ON M.[team_b_id]   = TB.[team_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_ml
        ON L_ml.[lookup_type_id]  = 3    AND L_ml.[id]  = M.[match_length_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_sh
        ON L_sh.[lookup_type_id]  = 10   AND L_sh.[id]  = D.[striker_hand_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_str
        ON L_str.[lookup_type_id] = 24   AND L_str.[id] = D.[stroke_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_bps
        ON L_bps.[lookup_type_id] = 2805 AND L_bps.[id] = D.[bowler_pace_spin_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_plgp1
        ON L_plgp1.[lookup_type_id] = 2819 AND L_plgp1.[id] = D.[pitch_length_group_pace_1_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_plgp2
        ON L_plgp2.[lookup_type_id] = 2820 AND L_plgp2.[id] = D.[pitch_length_group_pace_2_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_plgp
        ON L_plgp.[lookup_type_id]  = 2823 AND L_plgp.[id]  = D.[pitch_line_group_pace_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_plgs1
        ON L_plgs1.[lookup_type_id] = 2821 AND L_plgs1.[id] = D.[pitch_length_group_spin_1_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_plgs
        ON L_plgs.[lookup_type_id]  = 2824 AND L_plgs.[id]  = D.[pitch_line_group_spin_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_bm
        ON L_bm.[lookup_type_id]    = 2812 AND L_bm.[id]    = D.[ball_movement_id]
    WHERE D.[bowler_id]          = '{bowler_id}'
      AND {_scope(fmt, 'M')}
    ORDER BY M.[match_date], D.[match_innings], D.[over], D.[ball_in_over]
    """
    result = run_query(query, conn, cursor)
    conn.close()
    return result
