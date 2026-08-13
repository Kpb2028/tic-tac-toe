import { db, MissingDatabaseUrl, UNDEFINED_TABLE } from '../lib/db.js';

const WINDOW_DAYS = 14;

export default async function handler(req, res) {
  // Deliberately uncached: the page refetches immediately after recording a
  // game, and a CDN hit would show the visitor stats that omit the game they
  // just finished, which reads as a bug. Volume here is a handful of rows.
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const sql = db();

    // One round trip. Neon's HTTP driver bills a request per statement, and the
    // four aggregates are independent, so they are assembled server-side.
    const [row] = await sql`
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
            count(*)::int                                                       AS total,
            count(*) FILTER (WHERE outcome = player_mark)::int                  AS player_wins,
            count(*) FILTER (WHERE outcome <> 'draw' AND outcome <> player_mark)::int AS cpu_wins,
            count(*) FILTER (WHERE outcome = 'draw')::int                       AS draws
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
          -- Bind parameters arrive untyped, and "date - $1" matches no operator,
          -- so the offset and both bounds are cast explicitly.
          FROM generate_series(
            ((now() AT TIME ZONE 'UTC')::date - (${WINDOW_DAYS - 1})::int)::timestamp,
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
    `;

    return res.status(200).json(row.payload);
  } catch (err) {
    if (err instanceof MissingDatabaseUrl || err?.code === UNDEFINED_TABLE) {
      return res.status(503).json({ error: 'Analytics storage is not configured' });
    }
    console.error('Failed to load stats:', err);
    return res.status(500).json({ error: 'Could not load stats' });
  }
}
