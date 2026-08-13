"""GET /api/auth/session — who is signed in. DELETE — sign out."""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402

from _auth import (  # noqa: E402
    clearing_cookie_header,
    configured_providers,
    current_user,
    destroy_session,
    is_secure_origin,
)
from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402
from _http import origin_allowed, send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_GET(self):
        providers = configured_providers()

        try:
            with connect() as conn, conn.cursor() as cur:
                user = current_user(cur, self)

            if user is None:
                send_json(self, 200, {"signedIn": False, "providers": providers})
                return

            send_json(
                self,
                200,
                {
                    "signedIn": True,
                    "email": user["email"],
                    "displayName": user["display_name"],
                    "providers": providers,
                },
            )

        except MissingDatabaseUrl:
            send_json(self, 200, {"signedIn": False, "providers": [], "unavailable": True})
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                send_json(self, 200, {"signedIn": False, "providers": [], "unavailable": True})
                return
            print(f"Could not read session: {exc!r}", file=sys.stderr)
            send_json(self, 500, {"error": "Could not read session"})

    def do_DELETE(self):
        # SameSite=Lax already keeps the cookie off cross-site requests; this is
        # the belt to that braces.
        if not origin_allowed(self):
            send_json(self, 403, {"error": "Cross-origin requests are not accepted"})
            return

        try:
            with connect() as conn, conn.cursor() as cur:
                destroy_session(cur, self)
        except (MissingDatabaseUrl, psycopg.Error) as exc:
            # Clearing the cookie still logs the browser out, so this is not
            # worth failing over.
            print(f"Sign-out could not clear the row: {exc!r}", file=sys.stderr)

        send_json(
            self,
            200,
            {"signedIn": False},
            {"Set-Cookie": clearing_cookie_header(secure=is_secure_origin(self))},
        )
