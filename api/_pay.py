"""Stripe configuration and supporter lookups.

Only hosted Checkout is used: the browser is redirected to Stripe's own page,
so no card details ever reach this app and the Content-Security-Policy needs no
Stripe origins. The redirect back is cosmetic — entitlement is granted solely by
the signature-verified webhook.
"""

import os

import stripe

# The amount lives here, never in the request. A client-supplied price is the
# classic payments vulnerability: the buyer picks what to pay.
DEFAULT_AMOUNT_MINOR = 500  # 5.00 in the configured currency
DEFAULT_CURRENCY = "usd"
PRODUCT_NAME = "Tic Tac Toe supporter"

# Stripe's Managed Payments (on by default) makes Stripe the merchant of record
# and handles VAT, but every inline price must declare what is being sold.
# txcd_10000000 is "General - Electronically Supplied Services", the closest fit
# for a digital supporter payment. Which code applies is a tax question, not a
# code one — override with STRIPE_TAX_CODE if your accountant says otherwise.
DEFAULT_TAX_CODE = "txcd_10000000"


class StripeNotConfigured(RuntimeError):
    """No secret key in the environment."""


def secret_key():
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise StripeNotConfigured()
    return key


def webhook_secret():
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise StripeNotConfigured()
    return secret


def configured():
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def client():
    stripe.api_key = secret_key()
    return stripe


def amount_minor():
    """Charge amount in the currency's minor unit, from the environment."""
    raw = os.environ.get("STRIPE_SUPPORT_AMOUNT")
    if not raw:
        return DEFAULT_AMOUNT_MINOR
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_AMOUNT_MINOR
    # Stripe's own floor for most currencies is around 50 minor units.
    return value if 50 <= value <= 100_000 else DEFAULT_AMOUNT_MINOR


def currency():
    return (os.environ.get("STRIPE_CURRENCY") or DEFAULT_CURRENCY).lower()


def tax_code():
    return os.environ.get("STRIPE_TAX_CODE") or DEFAULT_TAX_CODE


def is_supporter(cur, user_id):
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM payments WHERE user_id = %s AND status = 'paid') AS ok",
        (user_id,),
    )
    return bool(cur.fetchone()["ok"])
