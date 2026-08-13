"""OpenID Connect sign-in and server-side sessions.

Flow: /api/auth/login redirects to the provider, the provider redirects back to
/api/auth/callback with a code, we exchange it for tokens over TLS, then issue
our own opaque session cookie. Provider tokens are never stored and never
reach the browser.

The ID token's signature is not verified. That is sound only because the token
is read from the response of a direct, TLS-authenticated call to the provider's
own token endpoint (OpenID Connect Core 3.1.3.7). Never extend this to a token
that arrived any other way, e.g. posted by a client.
"""

import base64
import hashlib
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SESSION_COOKIE = "ttt_session"
SESSION_TTL_DAYS = 30
FLOW_TTL_SECONDS = 600  # a sign-in attempt must complete within 10 minutes
HTTP_TIMEOUT = 10


class AuthError(Exception):
    """Anything that should abort sign-in. The message is safe to show."""


class ProviderNotConfigured(AuthError):
    pass


def _microsoft_tenant():
    # "common" admits both work/school and personal Microsoft accounts.
    return os.environ.get("MICROSOFT_TENANT", "common")


PROVIDERS = {
    "google": {
        "label": "Google",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "client_id_var": "GOOGLE_CLIENT_ID",
        "client_secret_var": "GOOGLE_CLIENT_SECRET",
        "scope": "openid email profile",
        "extra": {"access_type": "online", "prompt": "select_account"},
    },
    "microsoft": {
        "label": "Microsoft",
        "authorize": None,  # tenant-dependent, built in _endpoints()
        "token": None,
        "client_id_var": "MICROSOFT_CLIENT_ID",
        "client_secret_var": "MICROSOFT_CLIENT_SECRET",
        "scope": "openid email profile",
        "extra": {"prompt": "select_account"},
    },
}


def _endpoints(provider):
    if provider == "microsoft":
        tenant = _microsoft_tenant()
        base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        return f"{base}/authorize", f"{base}/token"

    config = PROVIDERS[provider]
    return config["authorize"], config["token"]


def _credentials(provider):
    config = PROVIDERS[provider]
    client_id = os.environ.get(config["client_id_var"])
    client_secret = os.environ.get(config["client_secret_var"])

    if not client_id or not client_secret:
        raise ProviderNotConfigured(f"{config['label']} sign-in is not configured")

    return client_id, client_secret


def configured_providers():
    """Providers that have both a client id and secret set."""
    available = []
    for name, config in PROVIDERS.items():
        if os.environ.get(config["client_id_var"]) and os.environ.get(config["client_secret_var"]):
            available.append({"provider": name, "label": config["label"]})
    return available


def base_url(handler):
    """Absolute origin used to build the redirect URI.

    Pinned by APP_BASE_URL when set. Falling back to the Host header is
    convenient locally but attacker-influenceable, so the value is only ever
    used to build our own redirect URI — which the provider then checks against
    its registered allow-list, closing the loop.
    """
    configured = os.environ.get("APP_BASE_URL")
    if configured:
        return configured.rstrip("/")

    host = handler.headers.get("Host") or "localhost:3000"
    scheme = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"
    return f"{scheme}://{host}"


def redirect_uri(handler):
    return f"{base_url(handler)}/api/auth/callback"


# --- the flow ------------------------------------------------------------


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def begin(cur, handler, provider):
    """Record a pending sign-in and return the provider URL to redirect to."""
    if provider not in PROVIDERS:
        raise AuthError("Unknown provider")

    client_id, _ = _credentials(provider)
    authorize_url, _ = _endpoints(provider)

    state = _b64url(secrets.token_bytes(32))
    nonce = _b64url(secrets.token_bytes(32))
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())

    cur.execute(
        """
        INSERT INTO auth_flow (state, nonce, code_verifier, provider)
        VALUES (%s, %s, %s, %s)
        """,
        (state, nonce, verifier, provider),
    )

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(handler),
        "scope": PROVIDERS[provider]["scope"],
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **PROVIDERS[provider]["extra"],
    }

    return f"{authorize_url}?{urlencode(params)}"


def _post_form(url, fields):
    """POST form-encoded to a fixed provider endpoint and parse the JSON reply.

    `url` comes from the PROVIDERS table, never from a request, so this cannot
    be pointed at an arbitrary host.
    """
    request = Request(
        url,
        data=urlencode(fields).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # The body often explains the failure, but it can echo request details,
        # so it is logged rather than returned to the browser.
        print(f"Token endpoint {url} returned {exc.code}: {exc.read()[:400]!r}")
        raise AuthError("The identity provider rejected the sign-in")
    except (URLError, TimeoutError, ValueError) as exc:
        print(f"Token endpoint {url} failed: {exc!r}")
        raise AuthError("Could not reach the identity provider")


def _claims_from_id_token(token):
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Malformed ID token")

    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise AuthError("Malformed ID token")


def _check_claims(claims, provider, client_id, nonce):
    if claims.get("aud") != client_id:
        raise AuthError("ID token was issued for a different application")

    if claims.get("nonce") != nonce:
        raise AuthError("ID token nonce does not match the sign-in request")

    expires = claims.get("exp")
    if not isinstance(expires, (int, float)) or expires < time.time():
        raise AuthError("ID token has expired")

    issuer = claims.get("iss") or ""
    if provider == "google":
        if issuer not in ("https://accounts.google.com", "accounts.google.com"):
            raise AuthError("Unexpected ID token issuer")
    else:
        # With the "common" tenant the directory id varies per user, so the
        # shape is checked rather than an exact string.
        ok = issuer.startswith("https://login.microsoftonline.com/") and issuer.endswith("/v2.0")
        if not ok:
            raise AuthError("Unexpected ID token issuer")


def _identity_from_claims(claims, provider):
    subject = claims.get("sub")
    if not subject:
        raise AuthError("ID token has no subject")

    # Microsoft personal accounts put the address in preferred_username.
    email = claims.get("email") or claims.get("preferred_username")
    if not email or "@" not in email:
        raise AuthError("The provider did not return an email address")

    # Google states this explicitly; Microsoft does not, and an address from a
    # signed-in Microsoft account is treated as verified.
    verified = claims.get("email_verified")
    if provider == "google" and verified is False:
        raise AuthError("Your Google email address is not verified")

    return {
        "provider": provider,
        "subject": str(subject),
        "email": email.strip().lower(),
        "email_verified": True if verified is None else bool(verified),
        "name": (claims.get("name") or "").strip() or email.split("@")[0],
    }


def complete(cur, handler, state, code):
    """Validate the callback, exchange the code, and return the identity."""
    if not state or not code:
        raise AuthError("Missing state or code")

    # Single use: deleting as we read means a replayed callback finds nothing.
    cur.execute(
        """
        DELETE FROM auth_flow
        WHERE state = %s AND created_at > now() - (%s || ' seconds')::interval
        RETURNING nonce, code_verifier, provider
        """,
        (state, str(FLOW_TTL_SECONDS)),
    )
    flow = cur.fetchone()
    if flow is None:
        raise AuthError("This sign-in link has expired or was already used")

    provider = flow["provider"]
    client_id, client_secret = _credentials(provider)
    _, token_url = _endpoints(provider)

    tokens = _post_form(
        token_url,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(handler),
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": flow["code_verifier"],
        },
    )

    id_token = tokens.get("id_token")
    if not id_token:
        raise AuthError("The provider did not return an ID token")

    claims = _claims_from_id_token(id_token)
    _check_claims(claims, provider, client_id, flow["nonce"])
    return _identity_from_claims(claims, provider)


# --- users and sessions --------------------------------------------------


def upsert_user(cur, identity):
    """Find or create the account for an identity, and return its id.

    Accounts are keyed on (provider, subject), which never changes. An existing
    account is matched by email only when the address is verified, so signing in
    with a second provider joins the same account instead of creating another.
    """
    cur.execute(
        "SELECT user_id FROM identities WHERE provider = %s AND subject = %s",
        (identity["provider"], identity["subject"]),
    )
    row = cur.fetchone()

    if row is None and identity["email_verified"]:
        cur.execute("SELECT id AS user_id FROM users WHERE email = %s", (identity["email"],))
        row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO users (email, display_name) VALUES (%s, %s) RETURNING id AS user_id",
            (identity["email"], identity["name"]),
        )
        row = cur.fetchone()

    user_id = row["user_id"]

    cur.execute(
        """
        INSERT INTO identities (provider, subject, user_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (provider, subject) DO UPDATE SET user_id = EXCLUDED.user_id
        """,
        (identity["provider"], identity["subject"], user_id),
    )
    cur.execute("UPDATE users SET last_seen_at = now() WHERE id = %s", (user_id,))

    return user_id


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(cur, user_id):
    """Issue a session and return the raw token for the cookie.

    Only the hash is stored, so a database disclosure does not yield usable
    session tokens.
    """
    token = secrets.token_urlsafe(32)
    cur.execute(
        """
        INSERT INTO sessions (id, user_id, expires_at)
        VALUES (%s, %s, now() + (%s || ' days')::interval)
        """,
        (_hash_token(token), user_id, str(SESSION_TTL_DAYS)),
    )
    return token


def read_cookie(handler, name):
    header = handler.headers.get("Cookie")
    if not header:
        return None

    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:
        return None

    morsel = jar.get(name)
    return morsel.value if morsel else None


def current_user(cur, handler):
    """Return the signed-in user's row, or None."""
    token = read_cookie(handler, SESSION_COOKIE)
    if not token:
        return None

    cur.execute(
        """
        SELECT u.id, u.email, u.display_name
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.id = %s AND s.expires_at > now()
        """,
        (_hash_token(token),),
    )
    return cur.fetchone()


def destroy_session(cur, handler):
    token = read_cookie(handler, SESSION_COOKIE)
    if token:
        cur.execute("DELETE FROM sessions WHERE id = %s", (_hash_token(token),))


def cookie_header(token, secure=True):
    """Set-Cookie value for a new session.

    HttpOnly keeps it away from JavaScript, so XSS cannot exfiltrate a session.
    SameSite=Lax still sends it on the top-level redirect back from the provider
    while blocking it on cross-site POSTs, which is what protects the
    state-changing endpoints from CSRF.
    """
    parts = [
        f"{SESSION_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={SESSION_TTL_DAYS * 24 * 3600}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clearing_cookie_header(secure=True):
    parts = [f"{SESSION_COOKIE}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def is_secure_origin(handler):
    """False only for plain-HTTP localhost, where a Secure cookie is dropped."""
    host = handler.headers.get("Host") or ""
    forwarded_proto = handler.headers.get("X-Forwarded-Proto")
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip() == "https"
    return not host.startswith(("localhost", "127.0.0.1"))
