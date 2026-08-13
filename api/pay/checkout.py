"""POST /api/pay/checkout — start a one-off supporter payment.

Returns the URL of a Stripe-hosted Checkout page for the browser to navigate to.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
import stripe as stripe_sdk  # noqa: E402

from _auth import base_url, current_user  # noqa: E402
from _db import MissingDatabaseUrl, connect, is_missing_schema  # noqa: E402
from _http import origin_allowed, send_json  # noqa: E402
from _pay import (  # noqa: E402
    PRODUCT_NAME,
    StripeNotConfigured,
    amount_minor,
    client,
    currency,
)


class handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence the default access log, which would print client IPs."""

    def do_GET(self):
        send_json(self, 405, {"error": "Method not allowed"}, {"Allow": "POST"})

    def do_POST(self):
        if not origin_allowed(self):
            send_json(self, 403, {"error": "Cross-origin requests are not accepted"})
            return

        try:
            with connect() as conn, conn.cursor() as cur:
                user = current_user(cur, self)
                if user is None:
                    send_json(self, 401, {"error": "Sign in first"})
                    return

                user_id = str(user["id"])
                email = user["email"]

            origin = base_url(self)
            stripe = client()

            # The price is built here from server-side configuration. Nothing
            # about the amount comes from the request body.
            session = stripe.checkout.Session.create(
                mode="payment",
                success_url=f"{origin}/?support=thanks",
                cancel_url=f"{origin}/?support=cancelled",
                client_reference_id=user_id,
                customer_email=email,
                metadata={"user_id": user_id},
                line_items=[
                    {
                        "quantity": 1,
                        "price_data": {
                            "currency": currency(),
                            "unit_amount": amount_minor(),
                            "product_data": {"name": PRODUCT_NAME},
                        },
                    }
                ],
                # Guards against a double-click opening two sessions.
                idempotency_key=f"checkout:{user_id}:{amount_minor()}:{currency()}",
            )

            send_json(self, 200, {"url": session.url})

        except StripeNotConfigured:
            send_json(self, 503, {"error": "Payments are not configured"})
        except stripe_sdk.StripeError as exc:
            # exc.user_message is safe to surface; the rest may leak detail.
            print(f"Stripe rejected the checkout session: {exc!r}", file=sys.stderr)
            send_json(self, 502, {"error": "Could not start checkout"})
        except MissingDatabaseUrl:
            send_json(self, 503, {"error": "Payments are not configured"})
        except psycopg.Error as exc:
            if is_missing_schema(exc):
                send_json(self, 503, {"error": "Payments are not configured"})
                return
            print(f"Checkout failed: {exc!r}", file=sys.stderr)
            send_json(self, 500, {"error": "Could not start checkout"})
