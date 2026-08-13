"""POST /api/games — record one finished game."""

import hashlib
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler

# The function's own directory is not guaranteed to be on sys.path in every
# runtime, and the underscore-prefixed helpers live beside this file.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import psycopg  # noqa: E402

from _auth import current_user  # noqa: E402
from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402
from _game import parse_game  # noqa: E402
from _http import client_ip, origin_allowed, read_json_body, send_json  # noqa: E402

HOURLY_LIMIT = 120  # generous for a human, cheap to enforce, caps spam

# A stable salt keeps the IP hashes unlinkable across deploys while staying
# consistent within one. Without ANALYTICS_IP_SALT the fallback is per-instance
# random, so rate limiting still works but resets when an instance recycles.
IP_SALT = os.environ.get("ANALYTICS_IP_SALT") or secrets.token_hex(32)

# Upsert and read the counter in one round trip. The CASE arms restart the
# window in place, so no separate cleanup job is needed.
RATE_LIMIT_SQL = """
    INSERT INTO rate_limit (bucket, window_start, hits)
    VALUES (%s, now(), 1)
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
"""

INSERT_SQL = """
    INSERT INTO games (mode, level, player_mark, outcome, moves, first_move, user_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_GET(self):
        send_json(self, 405, {"error": "Method not allowed"}, {"Allow": "POST"})

    def do_POST(self):
        if not origin_allowed(self):
            send_json(self, 403, {"error": "Cross-origin requests are not accepted"})
            return

        game, error = parse_game(read_json_body(self))
        if error:
            send_json(self, 400, {"error": error})
            return

        try:
            with connect() as conn, conn.cursor() as cur:
                # Sign-in is required to play, so an unowned game is not a
                # thing that can legitimately happen.
                user = current_user(cur, self)
                if user is None:
                    send_json(self, 401, {"error": "Sign in to record games"})
                    return

                cur.execute(RATE_LIMIT_SQL, (self._bucket(),))

                if cur.fetchone()["hits"] > HOURLY_LIMIT:
                    send_json(
                        self,
                        429,
                        {"error": "Too many games recorded from this address"},
                        {"Retry-After": "3600"},
                    )
                    return

                cur.execute(
                    INSERT_SQL,
                    (
                        game["mode"],
                        game["level"],
                        game["player_mark"],
                        game["outcome"],
                        game["moves"],
                        game["first_move"],
                        user["id"],
                    ),
                )

            send_json(self, 201, {"recorded": True, "linked": True})

        except MissingDatabaseUrl:
            send_json(self, 503, {"error": "Analytics storage is not configured"})
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                send_json(self, 503, {"error": "Analytics storage is not configured"})
                return
            print(f"Failed to record game: {exc!r}", file=sys.stderr)
            send_json(self, 500, {"error": "Could not record game"})

    def _bucket(self):
        digest = hashlib.sha256(f"{IP_SALT}:{client_ip(self)}".encode("utf-8"))
        return digest.hexdigest()[:32]
