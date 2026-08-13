"""DELETE /api/auth/account — erase the account.

Games played while signed in are kept but unlinked (games.user_id is ON DELETE
SET NULL), so the global totals stay consistent while nothing remains that ties
a row to a person.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402

from _auth import clearing_cookie_header, current_user, is_secure_origin  # noqa: E402
from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402
from _http import origin_allowed, send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_GET(self):
        send_json(self, 405, {"error": "Method not allowed"}, {"Allow": "DELETE"})

    def do_DELETE(self):
        if not origin_allowed(self):
            send_json(self, 403, {"error": "Cross-origin requests are not accepted"})
            return

        try:
            with connect() as conn, conn.cursor() as cur:
                user = current_user(cur, self)
                if user is None:
                    send_json(self, 401, {"error": "Not signed in"})
                    return

                # identities and sessions cascade from users; games do not, so
                # their user_id is nulled by the foreign key instead.
                cur.execute("DELETE FROM users WHERE id = %s", (user["id"],))

            send_json(
                self,
                200,
                {"deleted": True},
                {"Set-Cookie": clearing_cookie_header(secure=is_secure_origin(self))},
            )

        except MissingDatabaseUrl:
            send_json(self, 503, {"error": "Account storage is not configured"})
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                send_json(self, 503, {"error": "Account storage is not configured"})
                return
            print(f"Account deletion failed: {exc!r}", file=sys.stderr)
            send_json(self, 500, {"error": "Could not delete the account"})
