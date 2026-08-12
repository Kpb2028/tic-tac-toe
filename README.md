# Tic Tac Toe

Static three-file game: `index.html`, `styles.css`, `app.js`. No build step, no
dependencies, no network calls.

## Run

Serve the folder over HTTP — don't open `index.html` directly. The page ships a
`default-src 'none'; script-src 'self'; style-src 'self'` Content-Security-Policy,
and `file://` origins are opaque, so `'self'` won't match and `app.js` silently
fails to load.

```sh
python3 -m http.server 8771 --bind 127.0.0.1 --directory /Users/k/projects/014-tic-tac-toe
```

Then open http://127.0.0.1:8771/.

## Deploy (Render)

`render.yaml` declares a static site rooted at the repo, with no build command
and the security headers a `<meta>` CSP can't carry. Push the repo to GitHub,
then in the Render dashboard: **New → Blueprint**, pick the repo, apply. Render
reads `render.yaml`, serves the folder over HTTPS, and redeploys on every push
to `main`.

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

- The computer picks uniformly at random among equally-scored best moves, so
  perfect play still varies game to game.
- Stored state is treated as untrusted: every field is validated against a known
  set and scores are clamped to 0–9999 on load.
- Board and status updates use `textContent` only — no `innerHTML` anywhere.
- Status changes are announced through an `aria-live="polite"` region.
- The CSP lives in a `<meta>` tag, which can't carry `frame-ancestors` — browsers
  ignore it there. If this ever gets hosted somewhere real, send
  `Content-Security-Policy: frame-ancestors 'none'` (plus `X-Content-Type-Options:
  nosniff` and HSTS) as response headers from the server.
