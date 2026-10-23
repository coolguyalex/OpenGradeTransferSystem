/*
 * Aspen Paste Grades
 * Paste "Last, First <tab> score" rows from a spreadsheet into one Aspen gradebook column.
 *
 * Runs in the page's own JS context (manifest "world": "MAIN") so it can call Aspen's
 * built-in grid functions (edit, deactivateCell, ...). That is the same path Aspen's own
 * "Fill Down" uses, so Aspen's dirty tracking, validation and autosave behave exactly as
 * if you had typed each score. No network calls, no storage beyond a sessionStorage undo
 * buffer that disappears when the tab closes.
 */
(() => {
  'use strict';
  // Already loaded (e.g. the bookmark was clicked twice): just reopen the panel.
  if (window.__aspenPaste) { (window.__aspenPaste.open || window.__aspenPaste.retry || (() => {}))(); return; }

  /* ===================== text + matching helpers ===================== */

  const norm = (s) =>
    String(s || '')
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/['’`]/g, '')
      .replace(/[^a-z0-9\s-]/g, ' ')
      .replace(/-/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

  function lev(a, b) {
    if (a === b) return 0;
    const m = a.length, n = b.length;
    if (!m) return n;
    if (!n) return m;
    let prev = Array.from({ length: n + 1 }, (_, j) => j);
    for (let i = 1; i <= m; i++) {
      const cur = [i];
      for (let j = 1; j <= n; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      prev = cur;
    }
    return prev[n];
  }

  // Aspen names are "Last, First Middle...". Sheet names are usually "Last, First" but we
  // also accept "First Last" by trying every plausible last-name length.
  function nameCandidates(raw) {
    if (raw.includes(',')) {
      const i = raw.indexOf(',');
      return [[norm(raw.slice(0, i)), norm(raw.slice(i + 1))]];
    }
    const t = norm(raw).split(' ').filter(Boolean);
    if (t.length <= 1) return [[t[0] || '', '']];
    const out = [];
    for (let k = 1; k <= Math.min(3, t.length - 1); k++) {
      out.push([t.slice(-k).join(' '), t.slice(0, -k).join(' ')]);
    }
    return out;
  }

  function splitAspenName(name) {
    const i = name.indexOf(',');
    const last = norm(i < 0 ? name : name.slice(0, i));
    const first = norm(i < 0 ? '' : name.slice(i + 1));
    return { last, first, firstTokens: first ? first.split(' ') : [] };
  }

  function scorePair([l, f], st) {
    let lastExact;
    if (l === st.last) lastExact = true;
    else if (l.length >= 5 && lev(l, st.last) <= 1) lastExact = false;
    else return 0;

    const ft = f ? f.split(' ') : [];
    const sf = st.firstTokens;
    if (!ft.length) return lastExact ? 1.6 : 0;
    let fs;
    if (f === st.first) fs = 3;
    else if (ft.every((t, i) => t === sf[i])) fs = 2.5;       // "Maria" vs "Maria Elena ..."
    else if (ft[0] === sf[0]) fs = 2;                           // same first name, other middle
    else if (ft.some((t) => sf.includes(t))) fs = 1.2;          // preferred name = a middle name
    else if (ft[0].length >= 4 && sf[0] && lev(ft[0], sf[0]) <= 1) fs = 1; // typo
    else if (ft[0].length === 1 && sf[0] && ft[0] === sf[0][0]) fs = 0.9;  // initial only
    else return 0;
    return lastExact ? fs + 1 : fs * 0.8;
  }

  // students: [{oid, name, last, first, firstTokens}]
  function matchName(raw, students) {
    const cands = nameCandidates(raw);
    const scored = students
      .map((st) => ({ st, s: Math.max(...cands.map((c) => scorePair(c, st))) }))
      .filter((x) => x.s >= 1.7)
      .sort((a, b) => b.s - a.s);
    if (!scored.length) return { oid: null, status: 'none' };
    if (scored.length > 1 && scored[0].s - scored[1].s < 0.01) return { oid: null, status: 'ambig' };
    return { oid: scored[0].st.oid, status: scored[0].s >= 3 ? 'ok' : 'check' };
  }

  /* ===================== paste parsing ===================== */

  function parseDelimited(t, d) {
    const rows = [];
    let row = [], cell = '', q = false;
    for (let i = 0; i < t.length; i++) {
      const c = t[i];
      if (q) {
        if (c === '"') { if (t[i + 1] === '"') { cell += '"'; i++; } else q = false; }
        else cell += c;
      } else if (c === '"' && cell === '') q = true;
      else if (c === d) { row.push(cell.trim()); cell = ''; }
      else if (c === '\n') { row.push(cell.trim()); rows.push(row); row = []; cell = ''; }
      else cell += c;
    }
    row.push(cell.trim());
    rows.push(row);
    return rows.filter((r) => r.some((c) => c !== ''));
  }

  function parseTable(text) {
    text = String(text || '').replace(/\r\n?/g, '\n');
    if (!text.trim()) return [];
    if (text.includes('\t')) return parseDelimited(text, '\t');
    // No tabs (typed or plain-text paste): "Last, First 85" per line.
    return text.split('\n').filter((l) => l.trim()).map((l) => {
      const m = l.match(/^(.*?)[,;\s]+(-?\d+(?:\.\d+)?)\s*$/);
      return m ? [m[1].trim(), m[2]] : [l.trim(), ''];
    });
  }

  const NUM = /^-?\d+(\.\d+)?$/;
  const cleanScore = (s) => String(s == null ? '' : s).replace(/,/g, '').trim();
  const isNum = (s) => NUM.test(cleanScore(s));
  const sameNum = (a, b) => isNum(a) && isNum(b) && parseFloat(cleanScore(a)) === parseFloat(cleanScore(b));

  function guessColumns(rows) {
    const n = Math.max(0, ...rows.map((r) => r.length));
    if (n <= 1) return { n, nameCol: 0, scoreCol: -1 };
    let nameCol = 0, bestAlpha = -1;
    for (let c = 0; c < n; c++) {
      const alpha = rows.filter((r) => /[a-z]/i.test(r[c] || '') && !isNum(r[c])).length;
      if (alpha > bestAlpha) { bestAlpha = alpha; nameCol = c; }
    }
    let scoreCol = -1;
    for (let c = n - 1; c >= 0; c--) {
      if (c === nameCol) continue;
      const filled = rows.filter((r) => (r[c] || '') !== '');
      const nums = filled.filter((r) => isNum(r[c]));
      if (nums.length && nums.length >= filled.length * 0.5) { scoreCol = c; break; }
    }
    if (scoreCol < 0) scoreCol = n - 1 === nameCol ? -1 : n - 1;
    return { n, nameCol, scoreCol };
  }

  /* ===================== reading Aspen's grid ===================== */

  function readStudents() {
    const out = [];
    document.querySelectorAll('tr[id^="stdrow"]').forEach((tr) => {
      const a = tr.querySelector('a[href*="openGradeInputDetail"]');
      if (!a) return;
      const m = a.getAttribute('href').match(/'([^']+)'/);
      if (!m) return;
      const name = a.textContent.replace(/\s+/g, ' ').trim();
      out.push({ oid: m[1], name, ...splitAspenName(name) });
    });
    return out;
  }

  function readColumns() {
    const anchors = [...document.querySelectorAll('a[href*="assignmentDetailPopup.do"][href*="oid=GCD"]')];
    const countIn = (el) => el.querySelectorAll('a[href*="assignmentDetailPopup.do"][href*="oid=GCD"]').length;
    const seen = new Set();
    const cols = [];
    for (const a of anchors) {
      const m = a.getAttribute('href').match(/oid=(GCD\w+)/);
      if (!m || seen.has(m[1])) continue;
      seen.add(m[1]);
      // Climb to the largest ancestor that still contains only this column's header link.
      let el = a;
      while (el.parentElement && countIn(el.parentElement) <= 1) el = el.parentElement;
      const lines = (el.innerText || el.textContent || '')
        .split('\n').map((s) => s.replace(/\s+/g, ' ').trim()).filter(Boolean);
      const name = a.textContent.replace(/\s+/g, ' ').trim();
      const date = (lines.find((l) => /^\d{1,2}\/\d{1,2}(\/\d{2,4})?$/.test(l))) || '';
      const cat = lines.find((l) => l !== name && l !== date && !/^\d/.test(l)) || '';
      cols.push({ id: m[1], name, date, cat, label: [date, name, cat].filter(Boolean).join(' · ') });
    }
    return cols;
  }

  function currentValue(cellId) {
    const e = document.getElementById('e' + cellId);
    if (e) return String(e.value).trim();
    const td = document.getElementById(cellId);
    if (!td) return null;
    let v = typeof window.getScoreValue === 'function' ? window.getScoreValue(td) : td.textContent;
    return String(v).replace(/<[^>]*>/g, '').replace(/&nbsp;/g, '').trim();
  }

  const cellIsLocked = (cellId) =>
    !document.getElementById(cellId) || !!(window.readOnly || (window.readOnlyCells && window.readOnlyCells[cellId]));

  /* ===================== writing through Aspen's own functions ===================== */

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function applyScores(items) {
    // items: [{cellId, value}]. Returns {done:[{cellId,value,prev}], skipped:[cellId]}
    const done = [], skipped = [];
    let error = null;
    for (const it of items) {
      try {
        if (cellIsLocked(it.cellId)) { skipped.push(it.cellId); continue; }
        const prev = currentValue(it.cellId);
        window.edit(it.cellId, false);          // opens the cell editor; saves the previous cell
        const el = document.getElementById('e' + it.cellId);
        if (!el) { skipped.push(it.cellId); continue; }
        el.value = it.value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        done.push({ cellId: it.cellId, value: it.value, prev: prev == null ? '' : prev });
      } catch (e) {
        // Stop, but still flush/verify what was already touched so Undo can cover it.
        error = (e && e.message) || String(e);
        break;
      }
    }
    // Flush the last edited cell the way Aspen does when you move off it.
    if (window.currentCellId != null) {
      // currentCellId stays set: Aspen's save callback looks that cell up when the response arrives.
      try { window.deactivateCell(window.currentCellId); } catch (e) { /* ignore */ }
    }
    // Wait for Aspen's save queue, then verify each cell actually saved.
    try {
      await Promise.race([window.ajaxSaveQueue, sleep(45000).then(() => { throw new Error('timeout'); })]);
    } catch (e) { /* verified below */ }
    await sleep(150);
    const rejected = [], unsaved = [];
    for (const d of done) {
      if (window.erroneousCells && window.erroneousCells[d.cellId]) rejected.push(d.cellId);
      else if (String(window.originalValues[d.cellId] == null ? '' : window.originalValues[d.cellId]).trim() !== String(d.value).trim()
               && !sameNum(window.originalValues[d.cellId], d.value)) unsaved.push(d.cellId);
    }
    const msgEl = document.getElementById('messageArea');
    const aspenMessage = msgEl ? msgEl.textContent.trim() : '';
    return { done, skipped, rejected, unsaved, aspenMessage, error, notAttempted: items.length - done.length - skipped.length };
  }

  /* ===================== undo buffer ===================== */

  const UNDO_KEY = 'aspenPaste.undo';
  let lastRun = null;
  try { lastRun = JSON.parse(sessionStorage.getItem(UNDO_KEY) || 'null'); } catch (e) { /* ignore */ }
  const saveUndo = (run) => {
    lastRun = run;
    try { sessionStorage.setItem(UNDO_KEY, JSON.stringify(run)); } catch (e) { /* ignore */ }
  };

  /* ===================== UI ===================== */

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, '');
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
    for (const k of kids.flat()) if (k != null) el.append(k.nodeType ? k : document.createTextNode(k));
    return el;
  }

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .fab { position: fixed; right: 18px; bottom: 18px; z-index: 2147483000; background: #1f4e9c; color: #fff;
      border: 0; border-radius: 22px; padding: 10px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
      box-shadow: 0 2px 8px rgba(0,0,0,.35); }
    .fab:hover { background: #17407f; }
    .panel { position: fixed; right: 18px; bottom: 18px; z-index: 2147483001; width: min(760px, calc(100vw - 36px));
      max-height: calc(100vh - 36px); overflow: auto; background: #fff; color: #1b1f24; border: 1px solid #b8c0cc;
      border-radius: 10px; box-shadow: 0 8px 28px rgba(0,0,0,.35); font-size: 13px; }
    .hd { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: #1f4e9c; color: #fff;
      position: sticky; top: 0; z-index: 1; }
    .hd b { font-size: 14px; }
    .x { background: none; border: 0; color: #fff; font-size: 20px; cursor: pointer; line-height: 1; }
    .bd { padding: 12px 14px; display: grid; gap: 10px; }
    label.l { display: block; font-weight: 600; margin-bottom: 3px; }
    select, input[type=text], textarea { width: 100%; font-size: 13px; padding: 5px 6px; border: 1px solid #98a2b3; border-radius: 5px; background: #fff; color: #1b1f24; }
    textarea { height: 92px; font-family: ui-monospace, Menlo, Consolas, monospace; resize: vertical; }
    .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; color: #4b5563; padding: 4px 6px; border-bottom: 2px solid #d5dae1; position: sticky; top: 41px; background: #fff; }
    td { padding: 3px 6px; border-bottom: 1px solid #e5e8ec; vertical-align: middle; }
    td select { padding: 3px 4px; }
    td input.sc { width: 64px; padding: 3px 5px; text-align: right; }
    tr.warn td { background: #fff7e0; } tr.bad td { background: #fdecea; } tr.same td { color: #6b7280; }
    .note { font-size: 12px; } .note.ok { color: #1a7f37; } .note.warn { color: #9a6700; } .note.bad { color: #b42318; }
    .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .sum { flex: 1 1 260px; color: #374151; }
    button.b { font-size: 13px; padding: 7px 14px; border-radius: 6px; border: 1px solid #1f4e9c; background: #1f4e9c; color: #fff; cursor: pointer; font-weight: 600; }
    button.b:disabled { opacity: .45; cursor: not-allowed; }
    button.b.sec { background: #fff; color: #1f4e9c; }
    .msg { padding: 8px 10px; border-radius: 6px; } .msg.ok { background: #e7f6ec; color: #14532d; } .msg.warn { background: #fff7e0; color: #7a4b00; } .msg.bad { background: #fdecea; color: #7a1c14; }
    .hint { color: #5b6573; font-size: 12px; } .miss { color: #5b6573; font-size: 12px; }
  `;

  function mount() {
    const host = h('div', { id: 'aspen-paste-host' });
    // Aspen's global key/click handlers hijack arrows, Enter, Tab, Ctrl+A/D... Keep our events to ourselves.
    ['keydown', 'keypress', 'keyup', 'click', 'mousedown'].forEach((ev) =>
      host.addEventListener(ev, (e) => e.stopPropagation()));
    const root = host.attachShadow({ mode: 'open' });
    root.append(h('style', {}, CSS));
    document.body.append(host);

    const fab = h('button', { class: 'fab', title: 'Paste scores from a spreadsheet' }, 'Paste grades');
    root.append(fab);

    let panel = null;
    const state = { students: [], cols: [], colId: '', rows: [], pasteInfo: null };

    function close() { if (panel) { panel.remove(); panel = null; } fab.style.display = ''; }
    fab.addEventListener('click', open);
    window.__aspenPaste.open = () => { if (!panel) open(); };
    // Launched from a bookmark: the person just asked for it, so open straight away.
    if (window.__aspenPasteAutoOpen) open();

    function open() {
      fab.style.display = 'none';
      state.students = readStudents();
      state.cols = readColumns();
      state.rows = []; state.colId = '';

      const sel = h('select', { id: 'col' },
        h('option', { value: '' }, state.cols.length ? '— choose an assignment —' : 'No assignment columns found'),
        state.cols.map((c) => h('option', { value: c.id }, c.label)));
      const ta = h('textarea', { placeholder: 'Paste from your spreadsheet: Last, First  [tab]  score\nAlder, Riley\t88' });
      const colPick = h('div', { class: 'row2', style: 'display:none' });
      const preview = h('div', {});
      const bar = h('div', { class: 'bar' });
      const status = h('div', {});
      const sum = h('div', { class: 'sum' });
      const fillBtn = h('button', { class: 'b', disabled: true }, 'Fill scores');
      const undoBtn = h('button', { class: 'b sec', style: 'display:none' }, 'Undo last fill');
      const replaceCb = h('input', { type: 'checkbox' });
      const replaceLbl = h('label', { class: 'hint', style: 'display:none;cursor:pointer' }, replaceCb, ' Also replace existing scores (e.g. placeholder 0s)');
      bar.append(sum, replaceLbl, undoBtn, fillBtn);

      panel = h('div', { class: 'panel' },
        h('div', { class: 'hd' }, h('b', {}, 'Paste grades into Aspen'),
          h('button', { class: 'x', title: 'Close', onclick: close }, '×')),
        h('div', { class: 'bd' },
          h('div', {}, h('label', { class: 'l' }, '1. Which Aspen column?'), sel),
          h('div', {}, h('label', { class: 'l' }, '2. Paste scores'), ta,
            h('div', { class: 'hint' }, 'Nothing is written until you review the table below and press Fill. Aspen saves each cell the moment it is filled; Undo restores the previous scores.')),
          colPick, preview, bar, status));
      root.append(panel);

      let nameSel, scoreSel;

      function rebuildColPick(info) {
        colPick.innerHTML = '';
        if (info.n <= 2) { colPick.style.display = 'none'; return; }
        const opts = (def, allowNone) => {
          const s = h('select', {});
          if (allowNone) s.append(h('option', { value: -1 }, '(none)'));
          for (let c = 0; c < info.n; c++) s.append(h('option', { value: c }, 'Column ' + (c + 1)));
          s.value = def; s.addEventListener('change', build);
          return s;
        };
        nameSel = opts(info.nameCol); scoreSel = opts(info.scoreCol, true);
        colPick.append(h('div', {}, h('label', { class: 'l' }, 'Name column'), nameSel),
                       h('div', {}, h('label', { class: 'l' }, 'Score column'), scoreSel));
        colPick.style.display = '';
      }

      function build(ev) {
        status.innerHTML = '';
        const table = parseTable(ta.value);
        if (!table.length || !state.colId) { state.rows = []; render(); return; }
        let info = guessColumns(table);
        if (ev && ev.target && (ev.target === nameSel || ev.target === scoreSel)) {
          info = { n: info.n, nameCol: +nameSel.value, scoreCol: +scoreSel.value };
        } else rebuildColPick(info);
        const claimed = new Set();
        state.rows = [];
        table.forEach((r, i) => {
          const pastedName = r[info.nameCol] || '';
          const value = info.scoreCol >= 0 ? cleanScore(r[info.scoreCol]) : '';
          const m = matchName(pastedName, state.students);
          if (i === 0 && m.status === 'none' && value && !isNum(value)) return; // header row
          const row = { pastedName, value, oid: m.oid, status: m.status, checked: false };
          row.dup = !!(row.oid && claimed.has(row.oid));
          if (row.oid) claimed.add(row.oid);
          recompute(row);
          row.checked = defaultChecked(row);
          state.rows.push(row);
        });
        render();
      }

      function recompute(row) {
        row.cellId = row.oid && state.colId ? state.colId + '|' + row.oid : null;
        row.locked = row.cellId ? cellIsLocked(row.cellId) : false;
        row.cur = row.cellId ? currentValue(row.cellId) : null;
        row.blank = row.value === '';
        row.nan = !row.blank && !isNum(row.value);
        row.same = !!(row.cur && sameNum(row.cur, row.value));
        row.over = !!(row.cur && !row.same);
      }
      // Rows that replace an existing score are only pre-checked when the toggle is on.
      // Fuzzy matches are never pre-checked: a human has to look at those.
      const defaultChecked = (r) =>
        !!r.cellId && !r.blank && !r.nan && !r.dup && !r.locked && !r.same &&
        (!r.over || replaceCb.checked) &&
        (r.status === 'ok' || r.status === 'manual');

      function noteFor(r) {
        if (r.blank) return ['bad', 'No score in paste'];
        if (r.nan) return ['bad', 'Not a number'];
        if (!r.oid) return ['bad', r.status === 'ambig' ? 'Ambiguous: pick a student' : 'No match: pick a student'];
        if (r.dup) return ['bad', 'Student already used above'];
        if (r.locked) return ['bad', 'Locked or unavailable in Aspen'];
        if (r.status === 'check') return ['warn', r.over ? 'Fuzzy match; replaces ' + r.cur : 'Fuzzy match: check'];
        if (r.same) return ['', 'No change'];
        if (r.over) return ['warn', 'Replaces ' + r.cur];
        return ['ok', 'New'];
      }
      const rowClass = (r) => { const n = noteFor(r)[0]; return n === 'bad' ? 'bad' : n === 'warn' ? 'warn' : r.same ? 'same' : ''; };

      function summarize() {
        const total = state.rows.length;
        const chosen = state.rows.filter((r) => r.checked && r.cellId && !r.blank && !r.locked);
        const over = chosen.filter((r) => r.over).length;
        const skipped = state.rows.filter((r) => !r.checked).length;
        sum.textContent = total
          ? `${total} pasted · ${chosen.length} will be filled${over ? ` (${over} replace existing)` : ''} · ${skipped} skipped`
          : '';
        replaceLbl.style.display = state.rows.some((r) => r.over) ? '' : 'none';
        fillBtn.disabled = chosen.length === 0;
        fillBtn.textContent = chosen.length ? `Fill ${chosen.length} score${chosen.length === 1 ? '' : 's'}` : 'Fill scores';
      }

      function render() {
        preview.innerHTML = '';
        if (!state.rows.length) {
          summarize();
          if (ta.value.trim() && !state.colId) preview.append(h('div', { class: 'hint' }, 'Choose an Aspen column to see the preview.'));
          return;
        }
        const tb = h('tbody', {});
        state.rows.forEach((r) => {
          const tr = h('tr', { class: rowClass(r) });
          const cb = h('input', { type: 'checkbox' });
          cb.checked = r.checked;
          cb.addEventListener('change', () => { r.checked = cb.checked; summarize(); });
          const pick = h('select', {},
            h('option', { value: '' }, '— skip —'),
            state.students.map((s) => h('option', { value: s.oid }, s.name)));
          pick.value = r.oid || '';
          pick.addEventListener('change', () => {
            r.oid = pick.value || null; r.status = r.oid ? 'manual' : 'none';
            const seen = new Set();
            state.rows.forEach((x) => { x.dup = !!(x.oid && seen.has(x.oid)); if (x.oid) seen.add(x.oid); });
            state.rows.forEach(recompute);
            r.checked = defaultChecked(r);
            render();
          });
          const val = h('input', { type: 'text', class: 'sc', value: r.value });
          val.addEventListener('input', () => {
            r.value = cleanScore(val.value); recompute(r);
            const [cls, txt] = noteFor(r); note.className = 'note ' + cls; note.textContent = txt;
            tr.className = rowClass(r); summarize();
          });
          const [cls, txt] = noteFor(r);
          const note = h('span', { class: 'note ' + cls }, txt);
          tr.append(h('td', {}, cb), h('td', {}, r.pastedName), h('td', {}, pick),
            h('td', {}, r.cur == null ? '' : r.cur), h('td', {}, val), h('td', {}, note));
          tb.append(tr);
        });
        const missing = state.students.filter((s) => !state.rows.some((r) => r.oid === s.oid));
        preview.append(
          h('table', {}, h('thead', {}, h('tr', {}, ...['', 'Pasted name', 'Aspen student', 'Now', 'New', ''].map((t) => h('th', {}, t)))), tb),
          missing.length ? h('div', { class: 'miss' }, `Not in your paste (${missing.length}): ` + missing.map((s) => s.name).join('; ')) : null);
        summarize();
      }

      function refreshUndo() {
        const ok = lastRun && lastRun.items && lastRun.items.length;
        undoBtn.style.display = ok ? '' : 'none';
        if (ok) undoBtn.textContent = `Undo last fill (${lastRun.items.length})`;
      }

      function showResult(res, verb) {
        const n = res.done.length;
        const problems = res.rejected.length + res.unsaved.length + res.skipped.length + (res.error ? 1 : 0);
        const lines = [`${verb} ${n - res.rejected.length - res.unsaved.length} of ${n + res.skipped.length + res.notAttempted} cell(s) saved in Aspen.`];
        if (res.error) lines.push(`Stopped early (${res.error}); ${res.notAttempted} not attempted. Reload the page and check the column.`);
        if (res.rejected.length) lines.push(`${res.rejected.length} rejected by Aspen${res.aspenMessage ? ': ' + res.aspenMessage : ''}. They're highlighted red in the grid.`);
        if (res.unsaved.length) lines.push(`${res.unsaved.length} did not confirm as saved (network hiccup?). Reload the page and check before retrying.`);
        if (res.skipped.length) lines.push(`${res.skipped.length} skipped (locked or missing cell).`);
        status.innerHTML = '';
        status.append(h('div', { class: 'msg ' + (problems ? 'warn' : 'ok') }, lines.join(' ')));
      }

      let busy = false;
      fillBtn.addEventListener('click', async () => {
        if (busy) return;
        const items = state.rows.filter((r) => r.checked && r.cellId && !r.blank && !r.locked)
          .map((r) => ({ cellId: r.cellId, value: r.value }));
        if (!items.length) return;
        busy = true; fillBtn.disabled = true; undoBtn.disabled = true;
        status.innerHTML = ''; status.append(h('div', { class: 'msg warn' }, 'Filling and saving…'));
        try {
          const res = await applyScores(items);
          const okDone = res.done.filter((d) => !res.rejected.includes(d.cellId));
          saveUndo({ at: Date.now(), items: okDone.map((d) => ({ cellId: d.cellId, prev: d.prev, value: d.value })) });
          showResult(res, 'Filled');
        } catch (e) {
          status.innerHTML = ''; status.append(h('div', { class: 'msg bad' }, 'Something went wrong: ' + e.message));
        }
        busy = false; undoBtn.disabled = false;
        state.rows.forEach(recompute); state.rows.forEach((r) => { r.checked = false; });
        render(); refreshUndo();
      });

      undoBtn.addEventListener('click', async () => {
        if (busy || !lastRun || !lastRun.items.length) return;
        busy = true; fillBtn.disabled = true; undoBtn.disabled = true;
        status.innerHTML = ''; status.append(h('div', { class: 'msg warn' }, 'Restoring previous scores…'));
        try {
          const res = await applyScores(lastRun.items.map((i) => ({ cellId: i.cellId, value: i.prev })).reverse());
          showResult(res, 'Undo restored');
          saveUndo(null);
        } catch (e) {
          status.innerHTML = ''; status.append(h('div', { class: 'msg bad' }, 'Undo failed: ' + e.message));
        }
        busy = false; undoBtn.disabled = false;
        state.rows.forEach(recompute); render(); refreshUndo();
      });

      replaceCb.addEventListener('change', () => {
        state.rows.forEach((r) => { if (r.over) r.checked = defaultChecked(r); });
        render();
      });
      sel.addEventListener('change', () => { state.colId = sel.value; build(); });
      ta.addEventListener('input', build);
      refreshUndo();
      ta.focus();
    }
  }

  /* ===================== boot ===================== */

  const gridPresent = () =>
    !!document.querySelector('tr[id^="stdrow"]') && typeof window.edit === 'function' && typeof window.deactivateCell === 'function';

  window.__aspenPaste = { norm, matchName, parseTable, guessColumns, readStudents, readColumns, applyScores, isNum, sameNum };

  function toast(msg) {
    const t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:2147483647;max-width:360px;background:#1f4e9c;color:#fff;' +
      'padding:12px 16px;border-radius:8px;font:14px/1.4 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.4)';
    document.body.append(t);
    setTimeout(() => t.remove(), 9000);
  }

  // manual = launched by a person (bookmark click): answer right away and never fail silently.
  let tries = 0;
  const boot = (manual) => {
    if (document.getElementById('aspen-paste-host')) { if (manual && window.__aspenPaste.open) window.__aspenPaste.open(); return; }
    if (gridPresent()) { mount(); return; }
    if (manual) {
      toast('Aspen Paste is running, but it does not see the Scores grid on this page. Go to Gradebook > Scores, then click the bookmark again.');
      return;
    }
    if (++tries < 20) setTimeout(boot, 1000);
  };
  window.__aspenPaste.retry = () => boot(true);
  boot(!!window.__aspenPasteAutoOpen);
})();
