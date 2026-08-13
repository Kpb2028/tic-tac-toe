# Tic Tac Toe

A browser game (`index.html`, `styles.css`, `app.js`) plus two Python serverless
functions in `api/` that record finished games to Supabase Postgres and serve
global aggregate statistics.

The game itself still runs entirely client-side and needs no backend. If the API
is missing or the database is unprovisioned, the analytics panel says so and the
game plays exactly as before.

## Layout

```
index.html  styles.css  app.js     the game, no build step
api/games.py                       POST — record one finished game
api/stats.py                       GET  — global aggregates
api/_db.py  _game.py  _http.py     shared helpers (underscore = not routed)
scripts/init_db.py                 idempotent schema setup
requirements.txt                   pinned psycopg
```

## Run

The game alone works over any static server, but `/api` needs the Vercel runtime:

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
vercel env pull .env.local
vercel dev
```

Don't open `index.html` directly. The page ships a `default-src 'none'` CSP and
`file://` origins are opaque, so `'self'` won't match and `app.js` silently fails
to load.

For the game with no analytics, any static server does:

```sh
python3 -m http.server 8771 --bind 127.0.0.1 --directory .
```

## Analytics

### Setup

1. Provision Postgres:

   ```sh
   vercel integration add supabase --prefix SUPABASE_
   ```

   The prefix matters only while an older Neon resource still holds the
   unprefixed `POSTGRES_URL` and `DATABASE_URL`. `api/_db.py` checks
   `SUPABASE_POSTGRES_URL` first and falls back to the plain names, so removing
   Neon later needs no code change.

2. Create the schema (idempotent, safe to re-run):

   ```sh
   vercel env pull .env.local
   .venv/bin/python scripts/init_db.py
   ```

3. Recommended: set a stable salt for rate-limit hashing, so buckets survive
   redeploys.

   ```sh
   vercel env add ANALYTICS_IP_SALT production
   ```

   Without it, each function instance generates its own random salt at start —
   rate limiting still works, but resets when an instance recycles.

### Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/api/games` | POST | Record one finished game |
| `/api/stats` | GET | Aggregates; `?scope=me` for the signed-in account |
| `/api/auth/login` | GET | Start sign-in: `?provider=google\|microsoft` |
| `/api/auth/callback` | GET | Provider redirect target; issues the session |
| `/api/auth/session` | GET, DELETE | Who is signed in / sign out |
| `/api/auth/account` | DELETE | Erase the account |

`POST /api/games` takes `{ mode, level, playerMark, outcome, moves, firstMove }`.
`level` and `playerMark` are required for `mode: "cpu"` and rejected otherwise.
A game played while signed in is linked to the account; anonymous play still
records, just unowned.

## Sign-in

Optional. With no provider credentials set, the account panel says so and
everything else works exactly as before.

### Register the OAuth apps

Both need the same redirect URI — your deployment's origin plus
`/api/auth/callback`, e.g. `https://014-tic-tac-toe.vercel.app/api/auth/callback`.

**Google** — Cloud Console → APIs & Services → Credentials → Create credentials →
OAuth client ID → Web application. Add the redirect URI, then copy the client ID
and secret.

**Microsoft** — Entra ID → App registrations → New registration. For supported
account types pick *any organizational directory and personal Microsoft
accounts*, which is what the default `common` tenant expects; anything narrower
needs `MICROSOFT_TENANT` set to match. Add a **Web** redirect URI, then create a
secret under Certificates & secrets — copy its *value*, not its ID.

### Environment variables

```sh
vercel env add GOOGLE_CLIENT_ID production
vercel env add GOOGLE_CLIENT_SECRET production
vercel env add MICROSOFT_CLIENT_ID production
vercel env add MICROSOFT_CLIENT_SECRET production
vercel env add APP_BASE_URL production      # https://014-tic-tac-toe.vercel.app
```

`MICROSOFT_TENANT` is optional and defaults to `common`. Providers appear in the
UI only when both their id and secret are present, so Google alone works fine.

`APP_BASE_URL` pins the redirect URI. Without it the value is derived from the
`Host` header, which an attacker can influence — it is only ever used to build
our own redirect URI, which the provider then checks against its registered
allow-list, but pinning it removes the question.

### How the session works

Sign-in is the authorization-code flow with PKCE, state, and nonce. The code is
exchanged server-side; provider tokens are never stored and never reach the
browser. What the browser gets is an opaque random token in a cookie marked
`HttpOnly`, `Secure`, `SameSite=Lax`, and only its SHA-256 is stored, so a
database disclosure yields no usable sessions.

The ID token's signature is not verified. That is sound only because the token
is read from the response of a direct, TLS-authenticated call to the provider's
own token endpoint — the one case OpenID Connect Core 3.1.3.7 allows it. Its
`aud`, `iss`, `exp`, and `nonce` are all checked. Never extend this to a token
that arrived any other way.

Accounts are keyed on the provider's immutable subject, not the email. Signing
in with Google and then Microsoft on the same *verified* address joins one
account rather than creating two.

### Deleting an account

The Delete account button erases the user row; identities and sessions cascade.
Games are kept but unlinked — `games.user_id` is `ON DELETE SET NULL` — so the
global totals stay consistent while nothing ties a row to a person.

### Schema

`games` holds one row per finished game — mode, level, player mark, outcome,
move count, opening square, timestamp, and a nullable `user_id`. `rate_limit`
holds one row per caller bucket.

Accounts add `users` (email, display name), `identities` (provider plus the
provider's subject), `sessions` (the SHA-256 of a cookie token), and `auth_flow`
(a sign-in in progress, deleted on use).

**On personal data:** before sign-in existed, nothing in this database linked a
row to a person. That is no longer true — `users.email` identifies someone, and
a linked game says what they played. Still absent: IP addresses, user agents,
tracking cookies, and any third-party analytics. Anonymous play remains fully
anonymous, and account deletion is a real feature rather than a support request.

Every table has row-level security enabled with no policies. Nothing here is
reached through PostgREST — the API connects as the database owner — so if
Supabase's `anon` or `authenticated` roles are ever pointed at this project they
read and write nothing rather than everything.

## Deploy

**Vercel** — the full app, analytics included. `vercel.json` carries the security
headers, and `api/*.py` deploys as Python functions automatically once
`requirements.txt` is present. Connect the GitHub repo under project Settings →
Git for deploys on push.

**Render** — `render.yaml` declares a static site, which has no compute. The game
works; `/api` returns 404 and the analytics panel reports itself unavailable.

Both configs carry the same CSP, so a policy change has to be made twice —
they will drift apart otherwise.

## Play

- Click a square, or Tab to the board and move with the arrow keys, then Enter/Space.
- Opponent: **Computer** or **Another player** on the same keyboard.
- Difficulty: **Easy** (random), **Medium** (optimal ~55% of moves), **Unbeatable**
  (full minimax — the best you can do is draw).
- You can play X (first) or O (second) against the computer.
- Scores and settings persist in `localStorage` under `tictactoe.v1`.

Changing opponent, difficulty, or your mark starts a fresh game; scores carry over
until you hit **Reset scores**.

## Notes

- **The analytics are self-reported.** The board lives in the browser, so the
  numbers record what visitors' browsers claimed happened. `api/_game.py` enforces
  what is checkable — X moves on odd turns so the winner is fixed by the move
  count, and a draw must fill the board — which rejects malformed and casually
  forged payloads. It cannot prove a game was played. Treat the figures as
  indicative, not audited.
- Writes are capped at 120 games per hour per caller, keyed on a salted SHA-256
  hash of the IP. Raw addresses are never stored, and the handlers override
  `log_message` so the runtime's access log doesn't print them either.
- `/api/games` rejects a request whose `Origin` doesn't match the host, and sends
  no CORS headers, so other origins can neither read responses nor post forms.
- Request bodies over 4 KB are refused unread; a legitimate payload is under 200
  bytes.
- All SQL uses psycopg parameter binding. No value is ever interpolated into a
  query string.
- `prepare_threshold` is disabled on every connection. Supabase's pooler runs in
  transaction mode, where a prepared statement cannot outlive the checkout that
  created it, and leaving it on causes intermittent "prepared statement already
  exists" errors.
- Connections are opened per invocation rather than cached at module scope:
  instances freeze between requests, and a socket resumed after a freeze is often
  already closed by the pooler.
- The analytics DOM is built with `createElement`/`textContent`. No `innerHTML`
  anywhere in the project.
- Bar widths and heatmap colours are set through the CSSOM (`el.style.width`),
  which CSP allows — a `style` attribute in markup would be blocked by
  `style-src 'self'`.
- The computer picks uniformly at random among equally-scored best moves, so
  perfect play still varies game to game.
- Stored `localStorage` state is treated as untrusted: every field is validated
  against a known set and scores are clamped to 0–9999 on load.
- `/api/stats` is served `no-store`. The page refetches right after recording a
  game, and a cached response would omit it and look broken.
