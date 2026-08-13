"""Small helpers shared by the request handlers.

Modules under ``api/`` whose names start with an underscore are not routed as
functions by Vercel, so this file is import-only.
"""

import json


def send_json(handler, status, payload, extra_headers=None):
    """Write a JSON response. Always no-store: both endpoints are dynamic."""
    body = json.dumps(payload).encode("utf-8")

    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for key, value in (extra_headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()

    handler.wfile.write(body)


def read_json_body(handler, limit=4096):
    """Parse the request body as JSON, or return None if it is unusable.

    The length cap is a cheap guard: a legitimate payload here is well under
    200 bytes, so anything larger is not worth buffering.
    """
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        return None

    if length <= 0 or length > limit:
        return None

    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def origin_allowed(handler):
    """Reject a browser POST from another origin.

    The endpoint sends no CORS headers, so a cross-origin script cannot read a
    response — but a form-style POST would still arrive. A missing Origin
    (curl, server-side calls) is allowed: it carries no cross-site authority.
    """
    origin = handler.headers.get("Origin")
    if not origin:
        return True

    from urllib.parse import urlparse

    try:
        return urlparse(origin).netloc == (handler.headers.get("Host") or "")
    except ValueError:
        return False


def client_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.headers.get("X-Real-Ip") or "unknown"
