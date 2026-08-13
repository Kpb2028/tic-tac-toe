import { createHash, randomBytes } from 'node:crypto';
import { db, MissingDatabaseUrl, UNDEFINED_TABLE } from '../lib/db.js';
import { parseGame } from '../lib/game.js';

const HOURLY_LIMIT = 120; // generous for a human, cheap to enforce, caps spam

// A stable salt keeps the IP hashes unlinkable across deploys while staying
// consistent within one. Without ANALYTICS_IP_SALT the fallback is per-instance
// random, so rate limiting still works but resets when an instance recycles.
const IP_SALT = process.env.ANALYTICS_IP_SALT || randomBytes(32).toString('hex');

function clientIp(req) {
  const forwarded = req.headers['x-forwarded-for'];
  if (typeof forwarded === 'string' && forwarded.length) {
    return forwarded.split(',')[0].trim();
  }
  if (Array.isArray(forwarded) && forwarded.length) return forwarded[0].trim();
  return req.headers['x-real-ip'] || req.socket?.remoteAddress || 'unknown';
}

function bucketFor(req) {
  return createHash('sha256').update(`${IP_SALT}:${clientIp(req)}`).digest('hex').slice(0, 32);
}

// The endpoint sends no CORS headers, so a browser on another origin cannot read
// the response — but a form-style POST would still arrive. Rejecting a mismatched
// Origin closes that. A missing Origin (curl, server-side calls) is allowed
// through: it carries no cross-site authority to abuse.
function originAllowed(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try {
    return new URL(origin).host === req.headers.host;
  } catch {
    return false;
  }
}

function readBody(req) {
  if (typeof req.body === 'string') {
    try {
      return JSON.parse(req.body);
    } catch {
      return null;
    }
  }
  return req.body ?? null;
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  if (!originAllowed(req)) {
    return res.status(403).json({ error: 'Cross-origin requests are not accepted' });
  }

  const parsed = parseGame(readBody(req));
  if (!parsed.ok) return res.status(400).json({ error: parsed.error });

  const game = parsed.game;

  try {
    const sql = db();

    // Upsert and read the counter in one round trip. The CASE arms restart the
    // window in place, so no separate cleanup job is needed.
    const [limit] = await sql`
      INSERT INTO rate_limit (bucket, window_start, hits)
      VALUES (${bucketFor(req)}, now(), 1)
      ON CONFLICT (bucket) DO UPDATE SET
        hits = CASE
          WHEN rate_limit.window_start < now() - interval '1 hour' THEN 1
          ELSE rate_limit.hits + 1
        END,
        window_start = CASE
          WHEN rate_limit.window_start < now() - interval '1 hour' THEN now()
          ELSE rate_limit.window_start
        END
      RETURNING hits
    `;

    if (limit.hits > HOURLY_LIMIT) {
      res.setHeader('Retry-After', '3600');
      return res.status(429).json({ error: 'Too many games recorded from this address' });
    }

    await sql`
      INSERT INTO games (mode, level, player_mark, outcome, moves, first_move)
      VALUES (
        ${game.mode}, ${game.level}, ${game.playerMark},
        ${game.outcome}, ${game.moves}, ${game.firstMove}
      )
    `;

    return res.status(201).json({ recorded: true });
  } catch (err) {
    if (err instanceof MissingDatabaseUrl || err?.code === UNDEFINED_TABLE) {
      return res.status(503).json({ error: 'Analytics storage is not configured' });
    }
    console.error('Failed to record game:', err);
    return res.status(500).json({ error: 'Could not record game' });
  }
}
