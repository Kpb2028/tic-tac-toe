"""Postgres access for the analytics endpoints."""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row

#: Postgres error code for "relation does not exist" — i.e. the schema script
#: was never run.
UNDEFINED_TABLE = "42P01"

# Checked in order. The Supabase Marketplace resource is installed under a
# SUPABASE_ prefix because an earlier Neon resource already holds the unprefixed
# names; the plain forms stay as fallbacks so this keeps working once Neon is
# removed, and for any manually configured connection string.
URL_VARS = (
    "SUPABASE_POSTGRES_URL",
    "SUPABASE_DATABASE_URL",
    "POSTGRES_URL",
    "DATABASE_URL",
)


# libpq raises on any query parameter it does not recognise, and Supabase's
# pooler URL carries a "supa" marker of its own, so unknown keys are dropped
# rather than passed through.
LIBPQ_PARAMS = frozenset(
    {
        "application_name",
        "channel_binding",
        "client_encoding",
        "connect_timeout",
        "gssencmode",
        "keepalives",
        "keepalives_count",
        "keepalives_idle",
        "keepalives_interval",
        "options",
        "sslcert",
        "sslkey",
        "sslmode",
        "sslpassword",
        "sslrootcert",
        "target_session_attrs",
    }
)


class MissingDatabaseUrl(RuntimeError):
    """No connection string in the environment."""


def normalise_url(url):
    """Strip query parameters libpq would reject, keeping sslmode and friends."""
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key in LIBPQ_PARAMS
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def connection_var():
    """Name of the environment variable holding the connection string."""
    for name in URL_VARS:
        if os.environ.get(name):
            return name
    return None


def connect():
    """Open a connection, configured for Supabase's transaction pooler.

    A connection per invocation rather than a module-level one: instances are
    frozen between requests, and a socket resumed after a freeze is often
    already closed by the pooler. Supavisor is built for this pattern.
    """
    name = connection_var()
    if name is None:
        raise MissingDatabaseUrl()

    conn = psycopg.connect(
        normalise_url(os.environ[name]), row_factory=dict_row, connect_timeout=10
    )

    # Supavisor's transaction mode hands a different backend to each statement,
    # so a prepared statement cannot outlive the checkout that created it.
    # Leaving this on produces intermittent "prepared statement already exists".
    conn.prepare_threshold = None

    return conn


def is_missing_schema(exc):
    return getattr(getattr(exc, "diag", None), "sqlstate", None) == UNDEFINED_TABLE
