"""GET /api/auth/callback — finish sign-in and issue the session cookie."""

import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402

from _auth import (  # noqa: E402
    AuthError,
    complete,
    cookie_header,
    create_session,
    is_secure_origin,
    upsert_user,
)
from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_GET(self):
        query = parse_qs(urlsplit(self.path).query)

        # The provider reports refusals here too (e.g. the user cancelled).
        if query.get("error"):
            self._finish("/?signin=cancelled")
            return

        state = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]

        try:
            with connect() as conn, conn.cursor() as cur:
                identity = complete(cur, self, state, code)
                user_id = upsert_user(cur, identity)
                token = create_session(cur, user_id)

            self._finish("/?signin=ok", cookie_header(token, secure=is_secure_origin(self)))

        except AuthError as exc:
            # Never reflect the provider's text back into the page.
            print(f"Sign-in rejected: {exc}", file=sys.stderr)
            self._finish("/?signin=failed")
        except MissingDatabaseUrl:
            self._finish("/?signin=unavailable")
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                self._finish("/?signin=unavailable")
                return
            print(f"Sign-in failed: {exc!r}", file=sys.stderr)
            self._finish("/?signin=failed")

    def _finish(self, location, set_cookie=None):
        """Redirect back to the game. Location is always a fixed local path."""
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()
