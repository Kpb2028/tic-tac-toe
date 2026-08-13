// Shared vocabulary between the browser and the API. Anything arriving over the
// wire is attacker-controlled, so the server re-derives every constraint here
// rather than trusting that the client sent a game it actually played.

export const MODES = ['cpu', 'human'];
export const LEVELS = ['easy', 'medium', 'hard'];
export const MARKS = ['X', 'O'];
export const OUTCOMES = ['X', 'O', 'draw'];

const MIN_MOVES = 5; // the earliest a line can be completed
const MAX_MOVES = 9;

function isIndex(value, max) {
  return Number.isInteger(value) && value >= 0 && value <= max;
}

/**
 * Validate a reported game. Returns { ok: true, game } or { ok: false, error }.
 *
 * Beyond field-level checks this enforces the arithmetic of tic tac toe: X moves
 * on odd turns and O on even ones, so the winner is fixed by the move count, and
 * a draw can only happen on a full board. That rejects most malformed or
 * casually forged payloads. It cannot prove the game was really played — the
 * board lives entirely in the client — so treat the data as self-reported.
 */
export function parseGame(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, error: 'Body must be a JSON object' };
  }

  const { mode, level, playerMark, outcome, moves, firstMove } = raw;

  if (!MODES.includes(mode)) return { ok: false, error: 'Invalid mode' };
  if (!OUTCOMES.includes(outcome)) return { ok: false, error: 'Invalid outcome' };
  if (!isIndex(firstMove, 8)) return { ok: false, error: 'Invalid firstMove' };

  if (!Number.isInteger(moves) || moves < MIN_MOVES || moves > MAX_MOVES) {
    return { ok: false, error: 'Invalid moves' };
  }

  // Level and mark describe the computer opponent; they are meaningless, and so
  // must be absent, for a two-human game.
  let normalisedLevel = null;
  let normalisedMark = null;

  if (mode === 'cpu') {
    if (!LEVELS.includes(level)) return { ok: false, error: 'Invalid level' };
    if (!MARKS.includes(playerMark)) return { ok: false, error: 'Invalid playerMark' };
    normalisedLevel = level;
    normalisedMark = playerMark;
  }

  if (outcome === 'draw') {
    if (moves !== MAX_MOVES) return { ok: false, error: 'A draw must fill the board' };
  } else {
    const moverOnFinalTurn = moves % 2 === 1 ? 'X' : 'O';
    if (outcome !== moverOnFinalTurn) {
      return { ok: false, error: 'Winner is inconsistent with the move count' };
    }
  }

  return {
    ok: true,
    game: {
      mode,
      level: normalisedLevel,
      playerMark: normalisedMark,
      outcome,
      moves,
      firstMove,
    },
  };
}
