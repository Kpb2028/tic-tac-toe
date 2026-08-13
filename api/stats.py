"""GET /api/stats — global aggregates for the analytics panel."""

import os
import sys
from http.server import BaseHTTPRequestHandler

# The function's own directory is not guaranteed to be on sys.path in every
# runtime, and the underscore-prefixed helpers live beside this file.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import psycopg  # noqa: E402

from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402
from _http import send_json  # noqa: E402

WINDOW_DAYS = 14

# One round trip: the four aggregates are independent, so they are assembled
# server-side rather than issued as four statements.
STATS_SQL = """
    WITH core AS (
      SELECT
        count(*)::int                                  AS total,
        count(*) FILTER (WHERE outcome = 'X')::int     AS x_wins,
        count(*) FILTER (WHERE outcome = 'O')::int     AS o_wins,
        count(*) FILTER (WHERE outcome = 'draw')::int  AS draws,
        COALESCE(avg(moves), 0)::float                 AS avg_moves
      FROM games
    ),
    levels AS (
      SELECT json_agg(
        json_build_object(
          'level', level, 'total', total,
          'playerWins', player_wins, 'cpuWins', cpu_wins, 'draws', draws
        ) ORDER BY ord
      ) AS rows
      FROM (
        SELECT
          level,
          CASE level WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END AS ord,
          count(*)::int                                                            AS total,
          count(*) FILTER (WHERE outcome = player_mark)::int                        AS player_wins,
          count(*) FILTER (WHERE outcome <> 'draw' AND outcome <> player_mark)::int AS cpu_wins,
          count(*) FILTER (WHERE outcome = 'draw')::int                             AS draws
        FROM games
        WHERE mode = 'cpu' AND level IS NOT NULL AND player_mark IS NOT NULL
        GROUP BY level
      ) t
    ),
    opens AS (
      SELECT json_object_agg(first_move::text, n) AS map
      FROM (SELECT first_move, count(*)::int AS n FROM games GROUP BY first_move) t
    ),
    days AS (
      SELECT json_agg(json_build_object('day', day, 'count', n) ORDER BY day) AS rows
      FROM (
        SELECT d::date AS day, count(g.id)::int AS n
        -- Bind parameters arrive untyped, and "date - %s" matches no operator,
        -- so the offset and both bounds are cast explicitly.
        FROM generate_series(
          ((now() AT TIME ZONE 'UTC')::date - (%s)::int)::timestamp,
          ((now() AT TIME ZONE 'UTC')::date)::timestamp,
          interval '1 day'
        ) d
        LEFT JOIN games g ON (g.created_at AT TIME ZONE 'UTC')::date = d::date
        GROUP BY d
      ) t
    )
    SELECT json_build_object(
      'total',      core.total,
      'xWins',      core.x_wins,
      'oWins',      core.o_wins,
      'draws',      core.draws,
      'avgMoves',   core.avg_moves,
      'byLevel',    COALESCE(levels.rows, '[]'::json),
      'firstMoves', COALESCE(opens.map, '{}'::json),
      'daily',      COALESCE(days.rows, '[]'::json)
    ) AS payload
    FROM core, levels, opens, days
"""


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_POST(self):
        send_json(self, 405, {"error": "Method not allowed"}, {"Allow": "GET"})

    def do_GET(self):
        # Deliberately uncached (send_json sets no-store): the page refetches
        # immediately after recording a game, and a CDN hit would show stats
        # omitting the game just finished, which reads as a bug.
        try:
            with connect() as conn, conn.cursor() as cur:
                cur.execute(STATS_SQL, (WINDOW_DAYS - 1,))
                send_json(self, 200, cur.fetchone()["payload"])

        except MissingDatabaseUrl:
            send_json(self, 503, {"error": "Analytics storage is not configured"})
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                send_json(self, 503, {"error": "Analytics storage is not configured"})
                return
            print(f"Failed to load stats: {exc!r}", file=sys.stderr)
            send_json(self, 500, {"error": "Could not load stats"})
