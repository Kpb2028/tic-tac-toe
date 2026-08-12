'use strict';

(() => {
  const LINES = [
    [0, 1, 2], [3, 4, 5], [6, 7, 8],
    [0, 3, 6], [1, 4, 7], [2, 5, 8],
    [0, 4, 8], [2, 4, 6],
  ];

  const STORAGE_KEY = 'tictactoe.v1';
  const CPU_DELAY_MS = 320;
  const MAX_SCORE = 9999;

  const MODES = ['cpu', 'human'];
  const LEVELS = ['easy', 'medium', 'hard'];
  const MARKS = ['X', 'O'];

  const DEFAULTS = {
    mode: 'cpu',
    level: 'hard',
    playerMark: 'X',
    scores: { X: 0, O: 0, draw: 0 },
  };

  const el = {
    status: document.getElementById('status'),
    board: document.getElementById('board'),
    newGame: document.getElementById('new-game'),
    resetScores: document.getElementById('reset-scores'),
    mode: document.getElementById('mode'),
    level: document.getElementById('level'),
    mark: document.getElementById('mark'),
    fieldLevel: document.getElementById('field-level'),
    fieldMark: document.getElementById('field-mark'),
    scoreX: document.getElementById('score-x'),
    scoreO: document.getElementById('score-o'),
    scoreDraw: document.getElementById('score-draw'),
  };

  const cells = Array.from(document.querySelectorAll('.cell'));

  const settings = load();

  let board = new Array(9).fill(null);
  let turn = 'X';
  let over = false;
  let winLine = null;
  let thinking = false;
  let cpuTimer = 0;

  // --- persistence -------------------------------------------------------
  // Everything read back from localStorage is untrusted: validate each field
  // against a known set instead of merging the parsed object into state.

  function load() {
    const fallback = { ...DEFAULTS, scores: { ...DEFAULTS.scores } };
    let raw;
    try {
      raw = window.localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      return fallback; // storage disabled (private mode, blocked cookies)
    }
    if (!raw) return fallback;

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      return fallback;
    }
    if (!parsed || typeof parsed !== 'object') return fallback;

    const scores = parsed.scores && typeof parsed.scores === 'object' ? parsed.scores : {};
    return {
      mode: MODES.includes(parsed.mode) ? parsed.mode : fallback.mode,
      level: LEVELS.includes(parsed.level) ? parsed.level : fallback.level,
      playerMark: MARKS.includes(parsed.playerMark) ? parsed.playerMark : fallback.playerMark,
      scores: {
        X: clampScore(scores.X),
        O: clampScore(scores.O),
        draw: clampScore(scores.draw),
      },
    };
  }

  function clampScore(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.min(MAX_SCORE, Math.max(0, Math.floor(n)));
  }

  function save() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (err) {
      /* storage full or unavailable — the game still plays, scores just don't persist */
    }
  }

  // --- rules -------------------------------------------------------------

  function winnerOf(b) {
    for (const line of LINES) {
      const [a, c, d] = line;
      if (b[a] && b[a] === b[c] && b[a] === b[d]) return { mark: b[a], line };
    }
    return null;
  }

  function isFull(b) {
    return b.every((cell) => cell !== null);
  }

  function emptyCells(b) {
    const out = [];
    for (let i = 0; i < b.length; i += 1) if (!b[i]) out.push(i);
    return out;
  }

  function other(mark) {
    return mark === 'X' ? 'O' : 'X';
  }

  function cpuMark() {
    return other(settings.playerMark);
  }

  function versusCpu() {
    return settings.mode === 'cpu';
  }

  // --- computer opponent -------------------------------------------------

  function pickRandom(list) {
    return list[Math.floor(Math.random() * list.length)];
  }

  // Score is from `me`'s point of view; the depth term makes it prefer a fast
  // win and a slow loss, so it never stalls on an already-won board.
  function minimax(b, toMove, me, depth) {
    const win = winnerOf(b);
    if (win) return win.mark === me ? 10 - depth : depth - 10;
    if (isFull(b)) return 0;

    const maximizing = toMove === me;
    let best = maximizing ? -Infinity : Infinity;

    for (const i of emptyCells(b)) {
      b[i] = toMove;
      const score = minimax(b, other(toMove), me, depth + 1);
      b[i] = null;
      if (maximizing) {
        if (score > best) best = score;
      } else if (score < best) {
        best = score;
      }
    }
    return best;
  }

  function bestMove(b, me) {
    let best = -Infinity;
    let choices = [];
    for (const i of emptyCells(b)) {
      b[i] = me;
      const score = minimax(b, other(me), me, 1);
      b[i] = null;
      if (score > best) {
        best = score;
        choices = [i];
      } else if (score === best) {
        choices.push(i);
      }
    }
    return pickRandom(choices);
  }

  function cpuMove() {
    const open = emptyCells(board);
    if (!open.length) return null;
    if (settings.level === 'easy') return pickRandom(open);
    if (settings.level === 'medium' && Math.random() < 0.45) return pickRandom(open);
    return bestMove(board, cpuMark());
  }

  function scheduleCpu() {
    thinking = true;
    render();
    cpuTimer = window.setTimeout(() => {
      cpuTimer = 0;
      thinking = false;
      const move = cpuMove();
      if (move === null) {
        render();
        return;
      }
      play(move);
    }, CPU_DELAY_MS);
  }

  // --- game flow ---------------------------------------------------------

  function play(index) {
    if (over || thinking || board[index]) return;

    board[index] = turn;
    const win = winnerOf(board);

    if (win) {
      over = true;
      winLine = win.line;
      settings.scores[win.mark] = clampScore(settings.scores[win.mark] + 1);
      save();
    } else if (isFull(board)) {
      over = true;
      settings.scores.draw = clampScore(settings.scores.draw + 1);
      save();
    } else {
      turn = other(turn);
    }

    render();
    if (!over && versusCpu() && turn === cpuMark()) scheduleCpu();
  }

  function newGame() {
    if (cpuTimer) window.clearTimeout(cpuTimer);
    cpuTimer = 0;
    board = new Array(9).fill(null);
    turn = 'X';
    over = false;
    winLine = null;
    thinking = false;
    render();
    if (versusCpu() && cpuMark() === 'X') scheduleCpu();
  }

  // --- rendering ---------------------------------------------------------

  function describe(mark) {
    if (!versusCpu()) return mark;
    return mark === settings.playerMark ? `You (${mark})` : `Computer (${mark})`;
  }

  function statusText() {
    const win = winLine ? board[winLine[0]] : null;
    if (win) return `${describe(win)} wins`;
    if (over) return 'Draw';
    if (thinking) return 'Computer is thinking…';
    return `${describe(turn)} to move`;
  }

  function cellLabel(index, mark) {
    const row = Math.floor(index / 3) + 1;
    const col = (index % 3) + 1;
    return `Row ${row}, column ${col}, ${mark ? mark : 'empty'}`;
  }

  function render() {
    cells.forEach((cell, i) => {
      const mark = board[i];
      cell.textContent = mark || '';
      cell.classList.toggle('mark-x', mark === 'X');
      cell.classList.toggle('mark-o', mark === 'O');
      cell.classList.toggle('win', Boolean(winLine && winLine.includes(i)));
      cell.setAttribute('aria-disabled', String(Boolean(mark) || over || thinking));
      cell.setAttribute('aria-label', cellLabel(i, mark));
    });

    el.status.textContent = statusText();
    el.scoreX.textContent = String(settings.scores.X);
    el.scoreO.textContent = String(settings.scores.O);
    el.scoreDraw.textContent = String(settings.scores.draw);

    el.mode.value = settings.mode;
    el.level.value = settings.level;
    el.mark.value = settings.playerMark;
    el.fieldLevel.classList.toggle('hidden', !versusCpu());
    el.fieldMark.classList.toggle('hidden', !versusCpu());
  }

  // --- input -------------------------------------------------------------

  el.board.addEventListener('click', (event) => {
    const cell = event.target.closest('.cell');
    if (!cell) return;
    const index = Number(cell.dataset.index);
    if (Number.isInteger(index) && index >= 0 && index < 9) play(index);
  });

  el.board.addEventListener('keydown', (event) => {
    const steps = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -3, ArrowDown: 3 };
    const step = steps[event.key];
    if (step === undefined) return;
    const current = cells.indexOf(document.activeElement);
    if (current < 0) return;

    let next;
    if (Math.abs(step) === 1) {
      const row = Math.floor(current / 3);
      const col = (current % 3) + step;
      if (col < 0 || col > 2) return;
      next = row * 3 + col;
    } else {
      next = current + step;
      if (next < 0 || next > 8) return;
    }
    event.preventDefault();
    cells[next].focus();
  });

  el.newGame.addEventListener('click', newGame);

  el.resetScores.addEventListener('click', () => {
    settings.scores = { X: 0, O: 0, draw: 0 };
    save();
    render();
  });

  el.mode.addEventListener('change', () => {
    if (MODES.includes(el.mode.value)) settings.mode = el.mode.value;
    save();
    newGame();
  });

  el.level.addEventListener('change', () => {
    if (LEVELS.includes(el.level.value)) settings.level = el.level.value;
    save();
    newGame();
  });

  el.mark.addEventListener('change', () => {
    if (MARKS.includes(el.mark.value)) settings.playerMark = el.mark.value;
    save();
    newGame();
  });

  newGame();
})();
