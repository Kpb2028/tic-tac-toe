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
    analyticsState: document.getElementById('analytics-state'),
    analyticsBody: document.getElementById('analytics-body'),
    statTotal: document.getElementById('stat-total'),
    statDraws: document.getElementById('stat-draws'),
    statAvg: document.getElementById('stat-avg'),
    outcomeBars: document.getElementById('outcome-bars'),
    levelRows: document.getElementById('level-rows'),
    heatmap: document.getElementById('heatmap'),
    daily: document.getElementById('daily'),
    accountState: document.getElementById('account-state'),
    accountSignedOut: document.getElementById('account-signed-out'),
    accountSignedIn: document.getElementById('account-signed-in'),
    accountEmail: document.getElementById('account-email'),
    providerButtons: document.getElementById('provider-buttons'),
    signOut: document.getElementById('sign-out'),
    deleteAccount: document.getElementById('delete-account'),
    scopeSwitch: document.getElementById('scope-switch'),
    scopeGlobal: document.getElementById('scope-global'),
    scopeMe: document.getElementById('scope-me'),
  };

  const cells = Array.from(document.querySelectorAll('.cell'));

  const settings = load();

  let board = new Array(9).fill(null);
  let turn = 'X';
  let over = false;
  let winLine = null;
  let thinking = false;
  let cpuTimer = 0;
  let movesPlayed = []; // cell indexes in order, for the analytics payload

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
    movesPlayed.push(index);
    const win = winnerOf(board);

    if (win) {
      over = true;
      winLine = win.line;
      settings.scores[win.mark] = clampScore(settings.scores[win.mark] + 1);
      save();
      recordGame(win.mark);
    } else if (isFull(board)) {
      over = true;
      settings.scores.draw = clampScore(settings.scores.draw + 1);
      save();
      recordGame('draw');
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
    movesPlayed = [];
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

  // --- analytics ---------------------------------------------------------
  // The API is same-origin, which is all connect-src 'self' permits. Every call
  // is best-effort: on a static-only host /api does not exist, so a failure
  // degrades this panel and leaves the game untouched.
  //
  // All DOM here is built with createElement/textContent rather than innerHTML,
  // so server-supplied values can never be parsed as markup.

  const OUTCOME_BARS = [
    { key: 'xWins', label: 'X wins', fill: '' },
    { key: 'oWins', label: 'O wins', fill: 'positive' },
    { key: 'draws', label: 'Draws', fill: 'neutral' },
  ];

  let statsPending = false;
  let statsScope = 'global';
  let signedIn = false;

  function analyticsMessage(text, isError) {
    el.analyticsState.textContent = text;
    el.analyticsState.classList.toggle('error', Boolean(isError));
    el.analyticsState.classList.remove('hidden');
    el.analyticsBody.classList.add('hidden');
  }

  function recordGame(outcome) {
    const payload = {
      mode: settings.mode,
      outcome,
      moves: movesPlayed.length,
      firstMove: movesPlayed[0],
    };
    if (settings.mode === 'cpu') {
      payload.level = settings.level;
      payload.playerMark = settings.playerMark;
    }

    fetch('/api/games', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((res) => {
        if (res.ok) loadStats();
      })
      .catch(() => {
        /* offline or no API — the local scoreboard already updated */
      });
  }

  function loadStats() {
    if (statsPending) return;
    statsPending = true;

    const url = statsScope === 'me' ? '/api/stats?scope=me' : '/api/stats';

    fetch(url, { headers: { Accept: 'application/json' } })
      .then((res) => {
        if (res.status === 503) {
          analyticsMessage('Analytics storage is not configured yet.');
          return null;
        }
        if (res.status === 401) {
          // The session expired between rendering the switch and asking.
          setScope('global');
          loadSession();
          return null;
        }
        if (!res.ok) {
          analyticsMessage('Analytics are unavailable.', true);
          return null;
        }
        return res.json();
      })
      .then((data) => {
        if (data) renderStats(data);
      })
      .catch(() => {
        analyticsMessage('Analytics are unavailable on this host.', true);
      })
      .finally(() => {
        statsPending = false;
      });
  }

  function renderStats(data) {
    if (!data || typeof data !== 'object') {
      analyticsMessage('Analytics are unavailable.', true);
      return;
    }

    const total = Number(data.total) || 0;

    el.statTotal.textContent = String(total);
    el.statDraws.textContent = String(Number(data.draws) || 0);
    el.statAvg.textContent = total ? (Number(data.avgMoves) || 0).toFixed(1) : '—';

    renderOutcomes(data, total);
    renderLevels(Array.isArray(data.byLevel) ? data.byLevel : []);
    renderHeatmap(data.firstMoves && typeof data.firstMoves === 'object' ? data.firstMoves : {});
    renderDaily(Array.isArray(data.daily) ? data.daily : []);

    if (!total) {
      analyticsMessage(
        statsScope === 'me'
          ? 'You have no recorded games yet — finish one while signed in.'
          : 'No games recorded yet — finish one to start the tally.',
      );
      return;
    }

    el.analyticsState.classList.add('hidden');
    el.analyticsBody.classList.remove('hidden');
  }

  function barRow(label, value, share, fillClass) {
    const li = document.createElement('li');
    li.className = 'bar';

    const name = document.createElement('span');
    name.className = 'bar-label';
    name.textContent = label;

    const track = document.createElement('div');
    track.className = 'bar-track';

    const fill = document.createElement('div');
    fill.className = fillClass ? `bar-fill ${fillClass}` : 'bar-fill';
    fill.style.width = `${share}%`; // CSSOM write: allowed under style-src 'self'
    track.appendChild(fill);

    const count = document.createElement('span');
    count.className = 'bar-value';
    count.textContent = String(value);

    li.append(name, track, count);
    return li;
  }

  function renderOutcomes(data, total) {
    el.outcomeBars.replaceChildren(
      ...OUTCOME_BARS.map(({ key, label, fill }) => {
        const value = Number(data[key]) || 0;
        return barRow(label, value, total ? (value / total) * 100 : 0, fill);
      }),
    );
  }

  function renderLevels(rows) {
    if (!rows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 4;
      td.textContent = 'No computer games yet';
      tr.appendChild(td);
      el.levelRows.replaceChildren(tr);
      return;
    }

    el.levelRows.replaceChildren(
      ...rows.map((row) => {
        const tr = document.createElement('tr');

        const level = document.createElement('th');
        level.scope = 'row';
        level.textContent = row.level === 'hard' ? 'unbeatable' : String(row.level);

        const counts = [row.playerWins, row.cpuWins, row.draws].map((n) => {
          const td = document.createElement('td');
          td.textContent = String(Number(n) || 0);
          return td;
        });

        tr.append(level, ...counts);
        return tr;
      }),
    );
  }

  function renderHeatmap(map) {
    const counts = [];
    for (let i = 0; i < 9; i += 1) counts.push(Number(map[String(i)]) || 0);
    const peak = Math.max(...counts, 1);

    el.heatmap.replaceChildren(
      ...counts.map((n, i) => {
        const cell = document.createElement('div');
        cell.className = 'heat-cell';
        cell.textContent = String(n);

        // Accent brown, floored well above zero so any non-empty square stays
        // visible against the canvas colour.
        if (n) {
          const alpha = 0.12 + 0.68 * (n / peak);
          cell.style.backgroundColor = `rgba(139, 69, 19, ${alpha.toFixed(3)})`;
        }

        const label = `Row ${Math.floor(i / 3) + 1}, column ${(i % 3) + 1}: ${n} opening${n === 1 ? '' : 's'}`;
        cell.setAttribute('aria-label', label);
        cell.title = label;
        return cell;
      }),
    );
  }

  function renderDaily(rows) {
    const peak = rows.reduce((max, row) => Math.max(max, Number(row.count) || 0), 0);

    el.daily.replaceChildren(
      ...rows.map((row) => {
        const n = Number(row.count) || 0;

        const li = document.createElement('li');
        li.className = 'day';

        const bar = document.createElement('div');
        bar.className = 'day-bar';
        bar.style.height = peak ? `${Math.max(3, (n / peak) * 100)}%` : '3px';

        const label = `${String(row.day).slice(0, 10)}: ${n} game${n === 1 ? '' : 's'}`;
        li.title = label;
        li.setAttribute('aria-label', label);
        li.appendChild(bar);
        return li;
      }),
    );
  }

  // --- account -----------------------------------------------------------
  // The session lives in an HttpOnly cookie, so this code cannot read it and
  // never sees a token. Signed-in state is whatever /api/auth/session reports.

  const PROVIDER_LABELS = { google: 'Google', microsoft: 'Microsoft' };

  // Fixed strings only — the callback redirects with a code, never with text
  // from the provider, so nothing user-controlled reaches the page.
  const SIGNIN_MESSAGES = {
    ok: 'Signed in.',
    failed: 'Sign-in did not complete. Please try again.',
    cancelled: 'Sign-in was cancelled.',
    unavailable: 'Sign-in is not available right now.',
  };

  function accountMessage(text, isError) {
    el.accountState.textContent = text;
    el.accountState.classList.toggle('error', Boolean(isError));
    el.accountState.classList.remove('hidden');
  }

  function setScope(scope) {
    statsScope = scope;
    el.scopeGlobal.setAttribute('aria-pressed', String(scope === 'global'));
    el.scopeMe.setAttribute('aria-pressed', String(scope === 'me'));
  }

  function renderProviders(providers) {
    el.providerButtons.replaceChildren(
      ...providers.map((entry) => {
        // A link, not a form: form-action 'none' in the CSP blocks submissions.
        const link = document.createElement('a');
        link.className = 'btn';
        link.href = `/api/auth/login?provider=${encodeURIComponent(entry.provider)}`;
        link.textContent = `Continue with ${PROVIDER_LABELS[entry.provider] || entry.label}`;
        link.rel = 'nofollow';
        return link;
      }),
    );
  }

  function renderAccount(data) {
    const providers = Array.isArray(data.providers) ? data.providers : [];
    signedIn = Boolean(data.signedIn);

    // Nothing to offer without a configured provider, so the invitation to sign
    // in stays hidden rather than sitting above an empty row of buttons.
    const canSignIn = !data.unavailable && providers.length > 0;

    el.accountSignedIn.classList.toggle('hidden', !signedIn);
    el.accountSignedOut.classList.toggle('hidden', signedIn || !canSignIn);
    el.scopeSwitch.classList.toggle('hidden', !signedIn);

    if (signedIn) {
      el.accountEmail.textContent = data.email || '';
      el.accountState.classList.add('hidden');
      return;
    }

    setScope('global');
    renderProviders(providers);

    if (data.unavailable) {
      accountMessage('Sign-in is unavailable — the account storage is not set up yet.');
    } else if (!canSignIn) {
      accountMessage('Sign-in is not available on this deployment.');
    } else {
      el.accountState.classList.add('hidden');
    }
  }

  function loadSession() {
    return fetch('/api/auth/session', { headers: { Accept: 'application/json' } })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) renderAccount(data);
        else accountMessage('Accounts are unavailable on this host.');
      })
      .catch(() => {
        accountMessage('Accounts are unavailable on this host.');
      })
      .finally(loadStats);
  }

  function reportSignInOutcome() {
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get('signin');
    if (!outcome) return;

    // Strip the marker so a reload doesn't repeat the message.
    params.delete('signin');
    const query = params.toString();
    window.history.replaceState({}, '', window.location.pathname + (query ? `?${query}` : ''));

    if (SIGNIN_MESSAGES[outcome]) accountMessage(SIGNIN_MESSAGES[outcome], outcome !== 'ok');
  }

  el.signOut.addEventListener('click', () => {
    fetch('/api/auth/session', { method: 'DELETE' })
      .then(() => {
        setScope('global');
        return loadSession();
      })
      .catch(() => accountMessage('Could not sign out.', true));
  });

  el.deleteAccount.addEventListener('click', () => {
    const confirmed = window.confirm(
      'Delete your account? Your email address and sign-in details are erased. ' +
        'Games you played stay in the global totals but stop being linked to you. ' +
        'This cannot be undone.',
    );
    if (!confirmed) return;

    fetch('/api/auth/account', { method: 'DELETE' })
      .then((res) => {
        if (!res.ok) throw new Error('delete failed');
        setScope('global');
        return loadSession().then(() => accountMessage('Your account was deleted.'));
      })
      .catch(() => accountMessage('Could not delete the account.', true));
  });

  el.scopeGlobal.addEventListener('click', () => {
    if (statsScope === 'global') return;
    setScope('global');
    loadStats();
  });

  el.scopeMe.addEventListener('click', () => {
    if (statsScope === 'me' || !signedIn) return;
    setScope('me');
    loadStats();
  });

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
  // After loadSession, not before: renderAccount clears the status line, which
  // would wipe the outcome message from a sign-in that had just failed.
  loadSession().then(reportSignInOutcome); // loadSession also loads the stats
})();
