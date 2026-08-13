"""GET /api/auth/login?provider=google|microsoft — start sign-in."""

import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402

from _auth import AuthError, ProviderNotConfigured, begin  # noqa: E402
from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402
from _http import send_json  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_POST(self):
        send_json(self, 405, {"error": "Method not allowed"}, {"Allow": "GET"})

    def do_GET(self):
        query = parse_qs(urlsplit(self.path).query)
        provider = (query.get("provider") or [""])[0]

        try:
            with connect() as conn, conn.cursor() as cur:
                destination = begin(cur, self, provider)

            # The URL is built from the fixed provider table, never from input.
            self.send_response(302)
            self.send_header("Location", destination)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        except ProviderNotConfigured as exc:
            send_json(self, 503, {"error": str(exc)})
        except AuthError as exc:
            send_json(self, 400, {"error": str(exc)})
        except MissingDatabaseUrl:
            send_json(self, 503, {"error": "Sign-in storage is not configured"})
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                send_json(self, 503, {"error": "Sign-in storage is not configured"})
                return
            print(f"Sign-in failed to start: {exc!r}", file=sys.stderr)
            send_json(self, 500, {"error": "Could not start sign-in"})
