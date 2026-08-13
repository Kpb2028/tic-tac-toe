// One-off schema setup. Safe to re-run: every statement is IF NOT EXISTS.
//
//   vercel env pull .env.local
//   node --env-file=.env.local scripts/init-db.mjs
//
// Node does not auto-load .env.local, hence the explicit --env-file flag.

import { neon } from '@neondatabase/serverless';

const url = process.env.DATABASE_URL || process.env.POSTGRES_URL;

if (!url) {
  console.error('DATABASE_URL is not set. Run `vercel env pull .env.local` first,');
  console.error('then re-run with: node --env-file=.env.local scripts/init-db.mjs');
  process.exit(1);
}

const sql = neon(url);

// CHECK constraints mirror lib/game.js so a bug in the API cannot write a row
// the aggregate queries would then have to defend against.
await sql`
  CREATE TABLE IF NOT EXISTS games (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    mode        text        NOT NULL CHECK (mode IN ('cpu', 'human')),
    level       text        CHECK (level IN ('easy', 'medium', 'hard')),
    player_mark text        CHECK (player_mark IN ('X', 'O')),
    outcome     text        NOT NULL CHECK (outcome IN ('X', 'O', 'draw')),
    moves       smallint    NOT NULL CHECK (moves BETWEEN 5 AND 9),
    first_move  smallint    NOT NULL CHECK (first_move BETWEEN 0 AND 8)
  )
`;

await sql`CREATE INDEX IF NOT EXISTS games_created_at_idx ON games (created_at DESC)`;
await sql`CREATE INDEX IF NOT EXISTS games_level_idx ON games (level) WHERE level IS NOT NULL`;

// Rate limiting keyed on a salted hash of the caller's IP. Raw addresses are
// never stored, so this holds no personal data, and rows age out on write.
await sql`
  CREATE TABLE IF NOT EXISTS rate_limit (
    bucket       text        PRIMARY KEY,
    window_start timestamptz NOT NULL DEFAULT now(),
    hits         integer     NOT NULL DEFAULT 0
  )
`;

console.log('Schema ready: games, rate_limit');
