"""POST /api/pay/webhook — Stripe's callback, and the only thing that grants
supporter status.

The redirect back to the site proves nothing: anyone can visit `/?support=thanks`.
Entitlement is recorded here, and only after the signature verifies.

Stripe retries on any non-2xx and may deliver the same event more than once, so
the insert is idempotent on the session id and unexpected event types are
acknowledged rather than rejected — a 4xx would put them in a retry loop.
"""

import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
import stripe as stripe_sdk  # noqa: E402

from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402
from _http import send_json  # noqa: E402
from _pay import StripeNotConfigured, webhook_secret  # noqa: E402

MAX_BODY = 1 << 20  # 1 MB; Stripe events are far smaller

RECORD_SQL = """
    INSERT INTO payments (
      session_id, user_id, payment_intent, amount_minor, currency, status
    )
    VALUES (%s, %s::uuid, %s, %s, %s, %s)
    ON CONFLICT (session_id) DO UPDATE SET
      status         = EXCLUDED.status,
      payment_intent = COALESCE(EXCLUDED.payment_intent, payments.payment_intent)
"""


def field(obj, name, default=None):
    """Read a key from a Stripe object.

    stripe.StripeObject routes attribute access through __getattr__ to its own
    field map, so `.get(...)` raises AttributeError rather than behaving like
    the dict method. Subscripting is the only safe accessor.
    """
    try:
        return obj[name]
    except (KeyError, TypeError, IndexError):
        return default


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_GET(self):
        send_json(self, 405, {"error": "Method not allowed"}, {"Allow": "POST"})

    def do_POST(self):
        # The raw bytes are what the signature covers, so the body must not be
        # parsed or re-encoded before verification.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            send_json(self, 400, {"error": "Bad Content-Length"})
            return

        if length <= 0 or length > MAX_BODY:
            send_json(self, 400, {"error": "Bad payload size"})
            return

        payload = self.rfile.read(length)
        signature = self.headers.get("Stripe-Signature") or ""

        try:
            event = stripe_sdk.Webhook.construct_event(payload, signature, webhook_secret())
        except StripeNotConfigured:
            send_json(self, 503, {"error": "Payments are not configured"})
            return
        except ValueError:
            send_json(self, 400, {"error": "Malformed payload"})
            return
        except stripe_sdk.SignatureVerificationError:
            # Either a forgery or a stale timestamp. Never process it.
            print("Rejected a webhook with an invalid signature", file=sys.stderr)
            send_json(self, 400, {"error": "Invalid signature"})
            return

        if event["type"] != "checkout.session.completed":
            # Acknowledged so Stripe stops retrying something we ignore.
            send_json(self, 200, {"ignored": event["type"]})
            return

        session = event["data"]["object"]

        # payment_status is the authoritative field; a completed session can
        # still be unpaid for asynchronous methods.
        if field(session, "payment_status") != "paid":
            send_json(self, 200, {"ignored": "unpaid session"})
            return

        metadata = field(session, "metadata") or {}
        user_id = field(metadata, "user_id") or field(session, "client_reference_id")
        if not user_id:
            print("Paid session carried no user reference", file=sys.stderr)
            send_json(self, 200, {"ignored": "no user reference"})
            return

        try:
            owner = str(uuid.UUID(user_id))
        except (ValueError, AttributeError, TypeError):
            print("Paid session carried an unusable user reference", file=sys.stderr)
            send_json(self, 200, {"ignored": "bad user reference"})
            return

        try:
            with connect() as conn, conn.cursor() as cur:
                # The account may have been deleted between checkout and this
                # callback. The payment is still a financial record worth
                # keeping, so it is stored unlinked rather than lost to a
                # foreign key violation that Stripe would retry forever.
                cur.execute("SELECT 1 AS ok FROM users WHERE id = %s::uuid", (owner,))
                if cur.fetchone() is None:
                    owner = None

                cur.execute(
                    RECORD_SQL,
                    (
                        field(session, "id"),
                        owner,
                        field(session, "payment_intent"),
                        field(session, "amount_total"),
                        field(session, "currency"),
                        "paid",
                    ),
                )
            send_json(self, 200, {"recorded": True, "linked": owner is not None})

        except MissingDatabaseUrl:
            send_json(self, 503, {"error": "Storage is not configured"})
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                send_json(self, 503, {"error": "Storage is not configured"})
                return
            # A 5xx makes Stripe retry, which is what we want for a transient
            # database failure — the payment must not be silently dropped.
            print(f"Could not record payment: {exc!r}", file=sys.stderr)
            send_json(self, 500, {"error": "Could not record payment"})
