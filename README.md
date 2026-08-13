# Tic Tac Toe

A browser game (`index.html`, `styles.css`, `app.js`) plus two serverless
functions in `api/` that record finished games to Postgres and serve global
aggregate statistics.

The game itself still runs entirely client-side and needs no backend. If the API
is missing or the database is unprovisioned, the analytics panel says so and the
game plays exactly as before.

## Run

The game alone works over any static server, but `/api` needs the Vercel runtime:

```sh
npm install
vercel env pull .env.local   # writes DATABASE_URL from the Neon integration
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

1. Provision Postgres: `vercel integration add neon`. This creates the database,
   connects it to the project, and injects `DATABASE_URL`.
2. Create the schema (idempotent, safe to re-run):

   ```sh
   vercel env pull .env.local
   node --env-file=.env.local scripts/init-db.mjs
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
| `/api/stats` | GET | Global aggregates for the panel |

`POST /api/games` takes `{ mode, level, playerMark, outcome, moves, firstMove }`.
`level` and `playerMark` are required for `mode: "cpu"` and rejected otherwise.

### Schema

`games` holds one row per finished game — mode, level, player mark, outcome,
move count, opening square, timestamp. `rate_limit` holds one row per caller
bucket. Neither table stores an IP address, a user agent, a cookie, or any other
identifier: there is nothing in the database that links a row to a person.

## Deploy

**Vercel** — the full app, analytics included. `vercel.json` carries the security
headers, and `api/` deploys as Node functions automatically. Connect the GitHub
repo under project Settings → Git for deploys on push.

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
  numbers record what visitors' browsers claimed happened. `lib/game.js` enforces
  the arithmetic of the game — X moves on odd turns so the winner is fixed by the
  move count, and a draw must fill the board — which rejects malformed and
  casually forged payloads. It cannot prove a game was played. Treat the figures
  as indicative, not audited.
- Writes are capped at 120 games per hour per caller, keyed on a salted SHA-256
  hash of the IP. Raw addresses are never stored.
- `/api/games` rejects a request whose `Origin` doesn't match the host, and sends
  no CORS headers, so other origins can neither read responses nor post forms.
- All SQL uses parameterised tagged templates; no value is ever interpolated into
  a query string.
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
