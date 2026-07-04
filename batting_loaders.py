"""
batting_loaders.py — warehouse queries for the batting profile (Test / red-ball).

Mirrors data_loaders.py (bowling) but keyed on striker_id.  Everything is returned
as strings (run_query stringifies) — parse in batter_profile.process_batting_rows.

Scope = official international Tests only, via Matches.series_id -> Series.name
("International Tests M"), same as the bowling loaders.  match_length_id is NOT used for
scope (it mixes Tests with domestic first-class).
"""
from ludis_cricket.warehouse import set_conn_cursor, run_query
from ludis_cricket.config import international_series_sql
from config import DATA_SCHEMA

# Official international Tests only (via Matches.series_id -> Series.name); match_length_id
# mixes Tests with domestic first-class, so it's not used for scope.
_TEST_SERIES = international_series_sql("Test")


def _intl_test(alias: str = "M") -> str:
    return (f"{alias}.series_id IN "
            f"(SELECT series_id FROM [{DATA_SCHEMA}].[Series] WHERE name IN {_TEST_SERIES})")

# Derived bowler-type CASE (who the batter is facing) — reused from the bowling side.
_BOWLER_TYPE_CASE = """
    CASE
        WHEN D.[bowler_style_id] IN ('1','2') AND D.[bowler_hand_id]='1' THEN 'Right Fast'
        WHEN D.[bowler_style_id] IN ('1','2') AND D.[bowler_hand_id]='2' THEN 'Left Fast'
        WHEN D.[bowler_style_id]='3' AND D.[bowler_hand_id]='1' THEN 'Right Medium'
        WHEN D.[bowler_style_id]='3' AND D.[bowler_hand_id]='2' THEN 'Left Medium'
        WHEN D.[bowler_style_id]='4' AND D.[bowler_hand_id]='1' THEN 'Off Spin'
        WHEN D.[bowler_style_id]='4' AND D.[bowler_hand_id]='2' THEN 'Left Orthodox'
        WHEN D.[bowler_style_id]='5' AND D.[bowler_hand_id]='1' THEN 'Leg Break'
        WHEN D.[bowler_style_id]='5' AND D.[bowler_hand_id]='2' THEN 'Left Unorthodox'
        ELSE 'Other' END
"""


def load_test_batters(min_runs: int = 500) -> list:
    """Batters with >= min_runs off the bat in red-ball matches."""
    conn, cur = set_conn_cursor()
    q = f"""
    SELECT D.[striker_id]                              AS batter_id,
           MAX(P.[name])                               AS player_name,
           MAX(P.[surname])                            AS last_name,
           COUNT(*)                                    AS balls,
           SUM(CAST(D.[bat_score] AS int))             AS runs
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches] AS M ON D.[match_id] = M.[match_id]
    LEFT JOIN [{DATA_SCHEMA}].[Players] AS P ON D.[striker_id] = P.[player_id]
    WHERE {_intl_test('M')} AND D.[striker_id] IS NOT NULL
    GROUP BY D.[striker_id]
    HAVING SUM(CAST(D.[bat_score] AS int)) >= {min_runs}
    ORDER BY SUM(CAST(D.[bat_score] AS int)) DESC
    """
    rows = run_query(q, conn, cur)
    conn.close()
    return rows


def search_batters(term: str) -> list:
    """Fuzzy name search over red-ball batters (>=200 runs)."""
    conn, cur = set_conn_cursor()
    safe = term.replace("'", "''")
    q = f"""
    SELECT D.[striker_id] AS batter_id,
           MAX(P.[name]) AS player_name,
           COUNT(*) AS balls, SUM(CAST(D.[bat_score] AS int)) AS runs
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches] AS M ON D.[match_id] = M.[match_id]
    LEFT JOIN [{DATA_SCHEMA}].[Players] AS P ON D.[striker_id] = P.[player_id]
    WHERE {_intl_test('M')}
      AND (P.[surname] LIKE '%{safe}%' OR P.[name] LIKE '%{safe}%')
    GROUP BY D.[striker_id]
    HAVING SUM(CAST(D.[bat_score] AS int)) >= 200
    ORDER BY SUM(CAST(D.[bat_score] AS int)) DESC
    """
    rows = run_query(q, conn, cur)
    conn.close()
    return rows


def load_batter_info(batter_id: str) -> dict:
    """Name + primary team (most-faced batting team) for the header."""
    conn, cur = set_conn_cursor()
    q = f"""
    SELECT TOP 1 P.[name] AS player_name,
        (SELECT TOP 1 T.[team_name]
         FROM [{DATA_SCHEMA}].[Deliveries] D2
         JOIN [{DATA_SCHEMA}].[Teams] T ON D2.[team_batting_id] = T.[team_id]
         WHERE D2.[striker_id] = '{batter_id}'
         GROUP BY T.[team_name] ORDER BY COUNT(*) DESC) AS team_name
    FROM [{DATA_SCHEMA}].[Players] P
    WHERE P.[player_id] = '{batter_id}'
    """
    rows = run_query(q, conn, cur)
    conn.close()
    return rows[0] if rows else {}


def load_batter_deliveries(batter_id: str) -> list:
    """Every red-ball delivery faced by the batter, with the fields the profile needs."""
    conn, cur = set_conn_cursor()
    q = f"""
    SELECT
        D.[match_id], D.[match_innings], D.[over], D.[ball_in_over],
        D.[team_batting_id], D.[team_bowling_id],
        D.[striker_batting_position],
        D.[legal_ball], D.[bat_score], D.[wide_runs], D.[noball_runs],
        D.[striker_dismissed], D.[batter_dismissal], D.[how_out_id], D.[batter_out_id],
        D.[stroke_id], L_str.[description] AS stroke,
        D.[shot_quality_id],
        D.[off_bat_angle], D.[off_bat_speed],
        D.[hit_to_angle], D.[hit_to_x_physical], D.[hit_to_length],
        D.[striker_movement_id], L_sm.[description] AS striker_movement,
        D.[ball_speed],
        D.[pitch_line], D.[pitch_length], D.[at_stumps_line], D.[at_stumps_height],
        D.[movement_in_air], D.[movement_off_pitch],
        D.[movement_in_air_group_swing_id], D.[movement_off_pitch_group_seam_id],
        D.[over_the_wicket],
        D.[striker_hand_id], L_sh.[description] AS striker_hand,
        D.[bowler_id], D.[bowler_hand_id], D.[bowler_style_id],
        D.[bowler_pace_spin_id], L_bps.[description] AS bowler_pace_spin,
        {_BOWLER_TYPE_CASE} AS bowler_type_simple,
        D.[delivery_id], D.[video_file_name], M.[match_length_id],
        S.[name] AS season, SR.[gender_id],
        CONVERT(VARCHAR(10), M.[match_date], 120) AS match_date
    FROM [{DATA_SCHEMA}].[Deliveries] AS D
    JOIN [{DATA_SCHEMA}].[Matches] AS M ON D.[match_id] = M.[match_id]
    LEFT JOIN [{DATA_SCHEMA}].[Seasons] AS S ON M.[season_id] = S.[season_id]
    LEFT JOIN [{DATA_SCHEMA}].[Series] AS SR ON M.[series_id] = SR.[series_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_str ON L_str.[lookup_type_id]=24 AND L_str.[id]=D.[stroke_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_sh  ON L_sh.[lookup_type_id]=10 AND L_sh.[id]=D.[striker_hand_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_bps ON L_bps.[lookup_type_id]=2805 AND L_bps.[id]=D.[bowler_pace_spin_id]
    LEFT JOIN [{DATA_SCHEMA}].[Lookups] AS L_sm  ON L_sm.[lookup_type_id]=2812 AND L_sm.[id]=D.[striker_movement_id]
    WHERE D.[striker_id] = '{batter_id}' AND {_intl_test('M')}
    ORDER BY M.[match_date], D.[match_innings], D.[over], D.[ball_in_over]
    """
    rows = run_query(q, conn, cur)
    conn.close()
    return rows


def load_batter_innings(batter_id: str) -> list:
    """Per-innings aggregation for the share-of-runs metric: the batter's off-bat runs
    and balls in each innings, the team's off-bat innings total, and the match total
    (both teams) — computed in SQL so we don't pull every ball twice."""
    conn, cur = set_conn_cursor()
    q = f"""
    WITH inn AS (
        SELECT D.[match_id], D.[match_innings],
               SUM(CAST(D.[bat_score] AS int)) AS team_bat,
               SUM(CASE WHEN D.[striker_id] = '{batter_id}' THEN CAST(D.[bat_score] AS int) ELSE 0 END) AS his_runs,
               SUM(CASE WHEN D.[striker_id] = '{batter_id}' AND D.[legal_ball]='1' THEN 1 ELSE 0 END) AS his_balls,
               MAX(CASE WHEN D.[striker_id] = '{batter_id}' AND D.[striker_dismissed]='1' THEN 1 ELSE 0 END) AS his_out
        FROM [{DATA_SCHEMA}].[Deliveries] D
        JOIN [{DATA_SCHEMA}].[Matches] M ON D.[match_id] = M.[match_id]
        WHERE {_intl_test('M')}
          AND D.[match_id] IN (SELECT DISTINCT match_id FROM [{DATA_SCHEMA}].[Deliveries] WHERE striker_id='{batter_id}')
        GROUP BY D.[match_id], D.[match_innings]
    ),
    match_tot AS (
        SELECT match_id, SUM(team_bat) AS match_bat FROM inn GROUP BY match_id
    )
    SELECT i.[match_id], i.[match_innings], i.[team_bat], i.[his_runs], i.[his_balls], i.[his_out],
           mt.[match_bat]
    FROM inn i JOIN match_tot mt ON i.match_id = mt.match_id
    WHERE i.his_balls > 0
    ORDER BY i.[match_id], i.[match_innings]
    """
    rows = run_query(q, conn, cur)
    conn.close()
    return rows
