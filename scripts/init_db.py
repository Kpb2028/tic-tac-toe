"""One-off schema setup. Safe to re-run: every statement is IF NOT EXISTS.

    vercel env pull .env.local
    python3 scripts/init_db.py

Reads .env.local itself — unlike Node, Python has no --env-file flag, and the
values are only ever used to open the connection.
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "api"))

from _db import connect, connection_var  # noqa: E402


def load_env_file(path):
    """Minimal KEY=VALUE reader. Not a general dotenv parser."""
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        # Never let the file override something already exported.
        if key and key not in os.environ:
            os.environ[key] = value


STATEMENTS = (
    # CHECK constraints mirror api/_game.py so a bug in the API cannot write a
    # row the aggregate queries would then have to defend against.
    """
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
    """,
    "CREATE INDEX IF NOT EXISTS games_created_at_idx ON games (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS games_level_idx ON games (level) WHERE level IS NOT NULL",
    # Rate limiting keyed on a salted hash of the caller's IP. Raw addresses are
    # never stored, so this holds no personal data, and rows age out on write.
    """
    CREATE TABLE IF NOT EXISTS rate_limit (
      bucket       text        PRIMARY KEY,
      window_start timestamptz NOT NULL DEFAULT now(),
      hits         integer     NOT NULL DEFAULT 0
    )
    """,
    # Both tables are reached only through the connection string used by the
    # API. Enabling RLS with no policy means that if Supabase's anon or
    # authenticated PostgREST roles are ever pointed at this project, they read
    # and write nothing rather than everything.
    "ALTER TABLE games ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE rate_limit ENABLE ROW LEVEL SECURITY",
)


def main():
    load_env_file(ROOT / ".env.local")

    source = connection_var()
    if source is None:
        print("No Postgres connection string in the environment.", file=sys.stderr)
        print("Run `vercel env pull .env.local` first, then re-run this script.", file=sys.stderr)
        return 1

    print(f"Connecting using {source}")

    with connect() as conn, conn.cursor() as cur:
        for statement in STATEMENTS:
            cur.execute(statement)

    print("Schema ready: games, rate_limit (RLS enabled, no policies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
