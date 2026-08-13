"""Validation for a reported game.

Anything arriving over the wire is attacker-controlled, so every constraint is
re-derived here rather than trusting that the client sent a game it played.
"""

MODES = ("cpu", "human")
LEVELS = ("easy", "medium", "hard")
MARKS = ("X", "O")
OUTCOMES = ("X", "O", "draw")

MIN_MOVES = 5  # the earliest a line can be completed
MAX_MOVES = 9


def _is_int(value):
    # bool is a subclass of int, and True would otherwise pass as 1.
    return isinstance(value, int) and not isinstance(value, bool)


def parse_game(raw):
    """Return ``(game, None)`` on success or ``(None, error_message)``.

    Beyond field checks this enforces the arithmetic of tic tac toe: X moves on
    odd turns and O on even ones, so the winner is fixed by the move count, and
    a draw can only happen on a full board. That rejects malformed and casually
    forged payloads. It cannot prove the game was really played — the board
    lives entirely in the client — so treat the data as self-reported.
    """
    if not isinstance(raw, dict):
        return None, "Body must be a JSON object"

    mode = raw.get("mode")
    outcome = raw.get("outcome")
    moves = raw.get("moves")
    first_move = raw.get("firstMove")

    if mode not in MODES:
        return None, "Invalid mode"
    if outcome not in OUTCOMES:
        return None, "Invalid outcome"
    if not _is_int(first_move) or not 0 <= first_move <= 8:
        return None, "Invalid firstMove"
    if not _is_int(moves) or not MIN_MOVES <= moves <= MAX_MOVES:
        return None, "Invalid moves"

    # Level and mark describe the computer opponent; they are meaningless, and
    # so must be absent, for a two-human game.
    level = None
    player_mark = None

    if mode == "cpu":
        if raw.get("level") not in LEVELS:
            return None, "Invalid level"
        if raw.get("playerMark") not in MARKS:
            return None, "Invalid playerMark"
        level = raw["level"]
        player_mark = raw["playerMark"]

    if outcome == "draw":
        if moves != MAX_MOVES:
            return None, "A draw must fill the board"
    else:
        mover_on_final_turn = "X" if moves % 2 else "O"
        if outcome != mover_on_final_turn:
            return None, "Winner is inconsistent with the move count"

    return {
        "mode": mode,
        "level": level,
        "player_mark": player_mark,
        "outcome": outcome,
        "moves": moves,
        "first_move": first_move,
    }, None
