from cricket_core.warehouse import set_conn_cursor, run_query
from config import DATA_SCHEMA

conn, cursor = set_conn_cursor()

# Show the actual team names returned by load_test_teams
rows = run_query(f"""
    SELECT T.team_id, T.team_name
    FROM [{DATA_SCHEMA}].[Teams] AS T
    WHERE EXISTS (
        SELECT 1
        FROM [{DATA_SCHEMA}].[Deliveries] AS D
        JOIN [{DATA_SCHEMA}].[Matches]    AS M ON D.match_id = M.match_id
        WHERE D.team_bowling_id = T.team_id
          AND M.match_length_id IN ('2','3','4','5','6')
    )
    ORDER BY T.team_name
""", conn, cursor)

for r in rows:
    print(r["team_id"], repr(r["team_name"]))

conn.close()
