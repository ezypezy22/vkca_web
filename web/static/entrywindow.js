/**
 * entrywindow.js — N1MM-style "Entry Window", embedded inline in the Log
 * Entry tab (#tab-logentry) for standalone logging mode. Call/RST/Exchange
 * fields submit to /api/qsos/add; the "Worked This Session" list below it
 * (le-recent-tbody, in index.html) is fed by loadRecent() here too, with a
 * callsign search box, per-row edit (loads the QSO back into the form,
 * submits to /api/qsos/update) and delete (/api/qsos/delete).
 */
;(function () {
  'use strict';
  if (location.pathname !== '/') return;   // main-window-only, like settings.js

  const form        = document.getElementById('ew-form');
  if (!form) return;

  const bandsWrap    = document.getElementById('ew-bands');
  const runRadio     = document.getElementById('ew-run');
  const callInput    = document.getElementById('ew-call');
  const rstSent      = document.getElementById('ew-rst-sent');
  const rstRcvd      = document.getElementById('ew-rst-rcvd');
  const exchInput    = document.getElementById('ew-exchange');
  const errEl        = document.getElementById('ew-error');
  const logItBtn     = document.getElementById('ew-log-it');
  const recentTbody  = document.getElementById('le-recent-tbody');
  const radioBandEl  = document.getElementById('ew-radio-band');
  const radioFreqEl  = document.getElementById('ew-radio-freq');
  const freqInputEl  = document.getElementById('ew-freq-input');
  const modeBtnsEl   = document.getElementById('ew-mode-buttons');
  const qsoCountEl   = document.getElementById('ew-qso-count');
  const sentNrEl     = document.getElementById('ew-sent-nr-field');
  const searchInput  = document.getElementById('le-search-input');
  const summaryRowEl = document.getElementById('le-summary-row');
  const commentInput = document.getElementById('ew-comment');
  const clockDateEl  = document.getElementById('ew-clock-date');
  const clockTimeEl  = document.getElementById('ew-clock-time');
  const callTh       = document.getElementById('le-th-call');
  const timeTh       = document.getElementById('le-th-time');

  function showError(msg) { errEl.textContent = msg; errEl.classList.remove('hidden'); }
  function clearError()   { errEl.textContent = ''; }

  const effectiveCall = () => callInput.value.trim().toUpperCase();

  // Same shape as contest_log.is_valid_callsign() (the server re-checks it).
  const CALL_RE = /^(?:[A-Z0-9]{1,4}\/)?[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,8}[A-Z](?:\/[A-Z0-9]{1,6})?$/;

  // Only callsign characters can be typed or pasted into the Call field.
  callInput.addEventListener('input', () => {
    const clean = callInput.value.toUpperCase().replace(/[^A-Z0-9/]/g, '');
    if (clean !== callInput.value) callInput.value = clean;
  });

  // Live UTC clock (the VKCL Date/Time box).
  function tickClock() {
    const n = new Date();
    const p = x => String(x).padStart(2, '0');
    if (clockDateEl) clockDateEl.textContent = `${n.getUTCDate()}/${n.getUTCMonth() + 1}/${n.getUTCFullYear()}`;
    if (clockTimeEl) clockTimeEl.textContent = `${p(n.getUTCHours())}:${p(n.getUTCMinutes())}:${p(n.getUTCSeconds())}`;
  }
  tickClock();
  setInterval(tickClock, 1000);

  // Band comes from clickable buttons, not a <select>. Mode has its own
  // always-visible button row further down (#ew-mode-buttons/_activeMode) —
  // auto-synced from the live rig when one's connected, but always
  // manually clickable too, since an operator with no rig still has to
  // say what mode a QSO was on.
  let _bands = [];
  let _activeBand = null;
  let _radioBandSeen = false;   // only auto-pick a band from the rig once — a later rig
                                 // band change shouldn't yank the selection out from under
                                 // the operator mid-entry.

  function renderBands() {
    bandsWrap.innerHTML = _bands.map(b =>
      `<button type="button" data-band="${b}" class="${b === _activeBand ? 'active' : ''}">${b.toLowerCase()}</button>`
    ).join('');
  }

  // Band buttons + summary tiles come from the loaded plugin. They're built
  // at startup (before any log exists, so empty) and again whenever a log is
  // loaded or the plugin's list changes — see applyPluginLists().
  let _listsKey = '';
  function applyPluginLists(meta) {
    const bands = (meta && meta.loaded !== false && meta.bands) || [];
    const defs  = (meta && meta.loaded !== false && meta.gauge_defs) || [];
    const key = JSON.stringify([bands, defs.map(g => [g.label, g.value_key, g.fmt, g.colour])]);
    if (key === _listsKey) return;
    _listsKey = key;
    _bands = bands;
    if (!_bands.includes(_activeBand)) _activeBand = _bands[0] || null;
    renderBands();
    buildSummary(defs);
  }

  async function loadBands() {
    try {
      const res  = await fetch('/api/plugin_meta');
      applyPluginLists(await res.json());
    } catch (e) { console.warn('entrywindow: loadBands failed:', e); }
  }
  window.addEventListener('vka:loaded', () => { loadBands(); refreshRigStatus(); });

  // ── Summary — the same gauge_defs (label/value_key/colour/fmt) Overview's
  // own gauges use, as plain stat tiles rather than the full animated arc
  // gauges (those are tightly coupled to Overview's own DOM ids/state and
  // can't safely be reused for a second, independent row on this tab). ──
  let _summaryDefs = [];

  function buildSummary(defs) {
    _summaryDefs = defs;
    if (!summaryRowEl) return;
    summaryRowEl.innerHTML = defs.map((g, i) => `
      <div class="le-stat-tile">
        <div class="le-stat-tile-value" id="le-stat-val-${i}" style="color:${g.colour || 'var(--accent)'}">—</div>
        <div class="le-stat-tile-label">${window.VKA.escapeHtml(g.label || '')}</div>
      </div>`).join('');
  }

  function updateSummary(snap) {
    if (!summaryRowEl || !snap) return;
    _summaryDefs.forEach((g, i) => {
      const el = document.getElementById(`le-stat-val-${i}`);
      if (!el) return;
      const val = snap[g.value_key] ?? 0;
      el.textContent = window.VKA.fmtGaugeVal
        ? window.VKA.fmtGaugeVal(val, g.fmt)
        : Math.round(val).toLocaleString('en-AU');
    });
  }

  bandsWrap.addEventListener('click', e => {
    const btn = e.target.closest('button[data-band]');
    if (!btn) return;
    _activeBand = btn.dataset.band;
    renderBands();
    qsyToBand(_activeBand);
  });

  // ── Rig Control (Hamlib rigctld) — standalone Logger mode only, see
  // web/rigctld.py. The mode selector is always visible and clickable (an
  // operator with no rig connected still has to say what mode a QSO was
  // on) — when rigctld IS also connected, the same click additionally
  // commands the rig, and a live mode reading from the rig keeps the
  // selection in sync automatically. The editable frequency field and
  // band-click QSY only become active once the rig poller is actually
  // connected, since there's no rig to move otherwise. Configured in
  // Settings → Rig Control (host/port, per-band QSY default frequencies). ─
  const MODE_CHOICES = ['CW', 'USB', 'LSB', 'RTTY', 'FM'];
  let _rigctldConnected = false;
  let _liveMode = '';
  let _activeMode = null;        // the mode this QSO will actually be logged with
  let _bandDefaults = {};        // band -> freq_hz, from Settings → Rig Control (unset unless configured)
  let _contestMode = null;       // "CW"/"SSB" when the log's contest name pins one (e.g. Oceania DX CW)
  let _rstDefaultFor = null;     // effective mode the RST fields' default was last applied for

  // RST defaults to 59 for phone and 599 for CW. Only ever swaps a value
  // that is still exactly the other default (or blank), so anything the
  // operator typed themselves is left alone.
  function applyRstDefaults() {
    const eff = (_activeMode || _contestMode || '').toUpperCase();
    if (eff === _rstDefaultFor) return;
    _rstDefaultFor = eff;
    const want  = eff.startsWith('CW') ? '599' : '59';
    const other = want === '599' ? '59' : '599';
    [rstSent, rstRcvd].forEach(el => { if (el.value === other || el.value === '') el.value = want; });
  }
  const _lastFreqByBand = {};    // band -> freq_hz last actually seen on the rig, this session only

  async function setFreqHz(freqHz) {
    if (!freqHz || freqHz <= 0) return;
    try {
      const res  = await fetch('/api/rig/set_freq', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({freq_hz: Math.round(freqHz)}),
      });
      const data = await res.json();
      if (!res.ok || data.error) showError(data.error || 'Failed to QSY.');
    } catch (e) {
      showError(`QSY failed: ${e.message}`);
    }
  }

  // Clicking a band button QSYs the rig — to wherever the rig was last
  // observed on that band this session, or a Settings-configured default
  // if it hasn't been there yet. Silently does nothing if neither is
  // known (no configured default and never visited) rather than guessing
  // a frequency this app has no business assuming.
  function qsyToBand(band) {
    if (!_rigctldConnected) return;
    const target = _lastFreqByBand[band] ?? _bandDefaults[band];
    if (target) setFreqHz(target);
  }

  // Always rendered and clickable, regardless of rig-control status — see
  // the block comment above for why. The highlighted button is whatever
  // this QSO will actually be logged with.
  function renderModeButtons() {
    modeBtnsEl.innerHTML = MODE_CHOICES.map(m =>
      `<button type="button" data-mode="${m}" class="ew-mode-btn${m === _activeMode ? ' active' : ''}">${m}</button>`
    ).join('');
  }

  // Replaces the plain read-only frequency text with an editable field
  // when rig control is connected — same show/hide pattern as the mode
  // buttons above.
  function renderFreqField() {
    if (!_rigctldConnected) {
      freqInputEl.classList.add('hidden');
      radioFreqEl.classList.remove('hidden');
      return;
    }
    radioFreqEl.classList.add('hidden');
    freqInputEl.classList.remove('hidden');
  }

  freqInputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const mhz = parseFloat(freqInputEl.value);
      if (!isNaN(mhz) && mhz > 0) setFreqHz(mhz * 1e6);
      freqInputEl.blur();
    } else if (e.key === 'Escape') {
      e.stopPropagation();   // don't also trigger the global Escape handler (Wipe)
      freqInputEl.blur();    // just defocus — the next snapshot resyncs its value
    }
  });

  modeBtnsEl.addEventListener('click', async e => {
    const btn = e.target.closest('button[data-mode]');
    if (!btn) return;
    _activeMode = btn.dataset.mode;
    renderModeButtons();
    applyRstDefaults();
    if (!_rigctldConnected) return;   // manual selection only — nothing to command
    btn.disabled = true;
    try {
      const res  = await fetch('/api/rig/set_mode', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: btn.dataset.mode}),
      });
      const data = await res.json();
      if (!res.ok || data.error) showError(data.error || 'Failed to set mode.');
    } catch (e) {
      showError(`Set mode failed: ${e.message}`);
    } finally {
      btn.disabled = false;
    }
  });

  async function refreshRigStatus() {
    try {
      const [metaRes, cfgRes] = await Promise.all([
        fetch('/api/plugin_meta'), fetch('/api/settings/rigctld'),
      ]);
      const meta = await metaRes.json();
      const cfg  = await cfgRes.json();
      _rigctldConnected = !!meta.rigctld_connected;
      _reworkWindowHours = meta.loaded ? (meta.rework_window_hours || null) : null;
      _noBlocks = !!meta.loaded && meta.uses_block_structure === false && !_reworkWindowHours;
      _bandDefaults = cfg.band_defaults || {};
      _contestMode = meta.loaded ? (meta.contest_mode || null) : null;
      applyPluginLists(meta);
    } catch (e) {
      console.warn('entrywindow: refreshRigStatus failed:', e);
      _rigctldConnected = false;
    }
    if (!_activeMode) _activeMode = _contestMode || 'SSB';
    renderModeButtons();
    renderFreqField();
    applyRstDefaults();
  }
  setInterval(refreshRigStatus, 5000);

  function fmtTime(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').substring(0, 19) + ' UTC';
  }

  // ── "Time Left to Work" / "Next Block In" countdown — mirrors worked.js's
  // own dual-mode countdown exactly (see that file's header comment for why
  // a rolling per-contact rework window, e.g. VK RD's 4h same-band/mode
  // rule, and a fixed operating-block schedule need different logic), so
  // Logger mode's simplified worked list carries the same information the
  // full Worked tab does. ──────────────────────────────────────────────────
  const thCountdownEl = document.getElementById('le-th-countdown');
  let _reworkWindowHours = null;
  let _noBlocks = false;   // no operating blocks (e.g. CQ WW): hide the Next Block In column
  let _contestStart = null, _durationMins = null, _labelPrefix = 'B';

  function fmtRemaining(ms) {
    if (ms <= 0) return 'Workable';
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  }

  function readSessionConfig() {
    const ss = window.VKA?.lastSnap?.()?.session_status || {};
    _contestStart = ss.start_dt ? new Date(ss.start_dt + 'Z') : null;   // server times are naive UTC
    _durationMins = ss.duration_mins || null;
    _labelPrefix  = ss.label_prefix || 'B';
  }

  function countdownEnd(qsoTimeIso) {
    if (!qsoTimeIso) return null;
    const t = new Date(qsoTimeIso + 'Z');
    if (_reworkWindowHours) return new Date(t.getTime() + _reworkWindowHours * 3600000);
    if (!_contestStart || !_durationMins) return null;
    const elapsedMins = (t - _contestStart) / 60000;
    if (elapsedMins < 0) return null;
    const bn = Math.floor(elapsedMins / _durationMins);
    return new Date(_contestStart.getTime() + (bn + 1) * _durationMins * 60000);
  }

  function reworkModeKey(mode) {
    const m = (mode || '').toUpperCase();
    return (m === 'CW' || m.includes('RTTY') || m.includes('FSK')) ? 'CW_DIGITAL' : 'PHONE';
  }

  // Only the most recent valid (non-dupe) contact per (call, band,
  // mode-group) gets a real countdown in rework-window mode — an older,
  // superseded contact already had its own window exercised, and a
  // too-early rework attempt never legitimately reset anything either
  // (matches worked.js's own annotateCountdowns()).
  function annotateCountdowns(qsos) {
    let latest = null;
    if (_reworkWindowHours) {
      latest = new Map();
      qsos.forEach(q => {
        if (!q.time || q.dupe) return;
        const key = `${(q.call || '').toUpperCase()}|${(q.band || '').toUpperCase()}|${reworkModeKey(q.mode)}`;
        const cur = latest.get(key);
        if (!cur || new Date(q.time + 'Z') > new Date(cur.time + 'Z')) latest.set(key, q);
      });
      latest = new Set(latest.values());
    }
    qsos.forEach(q => {
      const end = countdownEnd(q.time);
      q._countdownAt = (end && (!latest || latest.has(q))) ? end.getTime() : null;
    });
  }

  function tickCountdowns() {
    if (!recentTbody) return;
    const now = Date.now();
    recentTbody.querySelectorAll('.ew-countdown').forEach(td => {
      const at = td.dataset.at;
      td.textContent = at ? fmtRemaining(Number(at) - now) : '—';
    });
  }
  setInterval(tickCountdowns, 1000);

  // Kept from the last loadRecent() so search-filtering and row edit/delete
  // clicks don't need a fresh server round-trip just to re-render.
  let _lastQsos = [];

  // Manual column sort (Call/Time headers) — once the operator picks a
  // column it overrides the smart default below entirely, until they
  // reload the tab. null = smart default: soonest-to-expire first for
  // rework-window contests, else most-recent-first.
  let _sortCol = null;   // null | 'call' | 'time'
  let _sortDir = 1;      // 1 = ascending, -1 = descending

  function setSort(col) {
    if (_sortCol === col) _sortDir *= -1;
    else { _sortCol = col; _sortDir = col === 'call' ? 1 : -1; }
    [callTh, timeTh].forEach(th => th?.classList.remove('sort-asc', 'sort-desc'));
    const activeTh = col === 'call' ? callTh : timeTh;
    activeTh?.classList.add(_sortDir === 1 ? 'sort-asc' : 'sort-desc');
    renderRecentRows();
  }
  callTh?.addEventListener('click', () => setSort('call'));
  timeTh?.addEventListener('click', () => setSort('time'));

  function renderRecentRows() {
    if (!recentTbody) return;
    const term = (searchInput?.value || '').trim().toUpperCase();
    let list = term ? _lastQsos.filter(q => (q.call || '').toUpperCase().includes(term)) : _lastQsos;
    list = [...list];
    if (_sortCol === 'call') {
      list.sort((a, b) => _sortDir * (a.call || '').localeCompare(b.call || ''));
    } else if (_sortCol === 'time') {
      list.sort((a, b) => _sortDir * (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    } else if (_reworkWindowHours) {
      // Rework-window contests (e.g. VK RD's 4h same-band/mode rule): show
      // the soonest-to-expire contacts first — oldest QSO time = closest
      // countdown to "Workable" — so the operator can see at a glance who
      // becomes reworkable soonest, rather than just who was logged last.
      // Rows with no active countdown (already workable, superseded, or a
      // dupe) sort to the end.
      list.sort((a, b) => (a._countdownAt ?? Infinity) - (b._countdownAt ?? Infinity));
    } else {
      list.sort((a, b) => (a.time < b.time ? 1 : a.time > b.time ? -1 : 0));
    }
    const recent = list.slice(0, 200);
    recentTbody.innerHTML = recent.map(q => `
      <tr data-qid="${q.qso_id || ''}">
        <td style="font-weight:bold">${window.VKA.escapeHtml(q.call || '—')}</td>
        <td>${(q.band || '').toLowerCase()}</td>
        <td>${q.mode || '—'}</td>
        <td>${q.sent_nr != null ? String(q.sent_nr).padStart(3, '0') : '—'}</td>
        <td>${window.VKA.escapeHtml(q.exchange || q.mult1 || '—')}</td>
        <td>${fmtTime(q.time)}</td>
        <td class="ew-countdown" data-at="${q._countdownAt || ''}"${_noBlocks ? ' style="display:none"' : ''}>${q._countdownAt ? fmtRemaining(q._countdownAt - Date.now()) : '—'}</td>
        <td class="le-actions">
          <button type="button" class="le-row-edit" data-qid="${q.qso_id || ''}" title="Edit this QSO">✎</button>
          <button type="button" class="le-row-del" data-qid="${q.qso_id || ''}" title="Delete this QSO">✕</button>
        </td>
      </tr>`).join('') || `<tr><td colspan="8">${term ? 'No matching QSOs.' : 'No QSOs logged yet.'}</td></tr>`;
  }
  searchInput?.addEventListener('input', renderRecentRows);

  async function loadRecent() {
    try {
      const qsos = await window.VKA.fetchQsos();
      if (qsoCountEl) qsoCountEl.textContent = qsos.length;
      // Next progressive serial number (see contest_log.py's add_qso()) —
      // same len(qsos)+1 count, zero-padded like OCDX's own "001".
      if (sentNrEl) sentNrEl.value = String(qsos.length + 1).padStart(3, '0');
      if (!recentTbody) return;
      readSessionConfig();
      annotateCountdowns(qsos);
      if (thCountdownEl) {
        thCountdownEl.textContent = _reworkWindowHours ? 'Time Left to Work' : 'Next Block In';
        thCountdownEl.style.display = _noBlocks ? 'none' : '';
      }
      _lastQsos = qsos;
      renderRecentRows();
    } catch (e) { console.warn('entrywindow: loadRecent failed:', e); }
  }

  // ── Edit an existing entry — loads it back into the form (like N1MM's
  // own "Edit" F-key), submit becomes an update instead of a new QSO.
  // Mode is genuinely editable now (the always-visible mode selector),
  // so an edit loads the QSO's own mode into it — and restores whatever
  // was selected before editing started on cancel/save, so a manually-set
  // mode doesn't leak into the next NEW QSO logged afterward. Run/S&P
  // can't be recovered from a fetched QSO (not exposed in that shape) —
  // left as whatever the toggle currently shows, matching this form's
  // other "can't fully restore" limitations. ─────────────────────────────
  let _editingQsoId = null;
  let _preEditMode  = null;   // _activeMode's value before edit started

  function startEdit(q) {
    _editingQsoId = q.qso_id || null;
    if (!_editingQsoId) { showError('Cannot edit this QSO (no ID).'); return; }
    clearError();
    callInput.value = q.call || '';
    rstSent.value = q.rst_sent || rstSent.value;
    rstRcvd.value = q.rst_rcvd || rstRcvd.value;
    exchInput.value = q.exchange || q.mult1 || '';
    if (commentInput) commentInput.value = q.comment || '';
    const band = (q.band || '').toUpperCase();
    if (_bands.includes(band)) { _activeBand = band; renderBands(); }
    _preEditMode = _activeMode;
    const editMode = (q.mode || '').toUpperCase();
    if (MODE_CHOICES.includes(editMode)) { _activeMode = editMode; renderModeButtons(); }
    logItBtn.textContent = 'Update QSO';
    callInput.focus();
  }

  function cancelEdit() {
    _editingQsoId = null;
    if (_preEditMode) { _activeMode = _preEditMode; renderModeButtons(); }
    _preEditMode = null;
    logItBtn.textContent = 'Log QSO';
  }

  async function deleteQso(qid, btn) {
    const q = _lastQsos.find(x => x.qso_id === qid);
    const ok = await window.VKA.showConfirm({
      title: 'Delete QSO',
      message: `Permanently delete the QSO with ${q?.call || 'this station'}?`,
      confirmLabel: 'Delete',
    });
    if (!ok) return;
    if (btn) btn.disabled = true;
    try {
      const res  = await fetch('/api/qsos/delete', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({qso_ids: [qid]}),
      });
      const data = await res.json();
      if (data.errors?.length) showError(data.errors.join('; '));
      if (_editingQsoId === qid) cancelEdit();
      window.VKA.invalidateQsosCache();
      window.dispatchEvent(new CustomEvent('vka:qsos_changed'));
      loadRecent();
    } catch (e) {
      showError(`Delete failed: ${e.message}`);
    }
  }

  recentTbody.addEventListener('click', e => {
    const editBtn = e.target.closest('.le-row-edit');
    if (editBtn) {
      const q = _lastQsos.find(x => x.qso_id === editBtn.dataset.qid);
      if (q) startEdit(q);
      return;
    }
    const delBtn = e.target.closest('.le-row-del');
    if (delBtn) deleteQso(delBtn.dataset.qid, delBtn);
  });

  // ── Right-click context menu (Edit / Delete) — an alternative to the
  // small per-row icon buttons; right-clicking anywhere on a row is easier
  // to hit than a tiny icon while operating fast. ────────────────────────
  let _ctxMenuEl = null;
  function closeCtxMenu() { _ctxMenuEl?.remove(); _ctxMenuEl = null; }
  function openCtxMenu(x, y, q) {
    closeCtxMenu();
    const el = document.createElement('div');
    el.className = 'le-ctx-menu';
    el.innerHTML = `
      <div class="panels-menu-row" data-act="edit">✎ Edit</div>
      <div class="panels-menu-row" data-act="delete">✕ Delete</div>`;
    document.body.appendChild(el);
    _ctxMenuEl = el;
    const rect = el.getBoundingClientRect();   // keep on-screen near the right/bottom edge
    el.style.left = Math.max(4, Math.min(x, window.innerWidth  - rect.width  - 8)) + 'px';
    el.style.top  = Math.max(4, Math.min(y, window.innerHeight - rect.height - 8)) + 'px';
    el.querySelector('[data-act="edit"]').addEventListener('click', () => { closeCtxMenu(); startEdit(q); });
    el.querySelector('[data-act="delete"]').addEventListener('click', () => { closeCtxMenu(); deleteQso(q.qso_id); });
  }
  recentTbody.addEventListener('contextmenu', e => {
    const tr = e.target.closest('tr[data-qid]');
    if (!tr) return;
    e.preventDefault();
    const q = _lastQsos.find(x => x.qso_id === tr.dataset.qid);
    if (q) openCtxMenu(e.clientX, e.clientY, q);
  });
  document.addEventListener('click', e => {
    if (_ctxMenuEl && !_ctxMenuEl.contains(e.target)) closeCtxMenu();
  });

  // ── Live callsign hint: country / zone / needed-mult / dupe + Super Check
  // Partial, from /api/lookup. Display only — it never fills in the received
  // exchange, which is whatever the other station sends. ─────────────────────
  const hintEl = document.getElementById('ew-hint');
  const scpEl  = document.getElementById('ew-scp');
  let _lookupTimer = null, _lookupSeq = 0;

  function renderHint(d, call) {
    if (!hintEl) return;
    if (!call) {
      hintEl.innerHTML = '<span class="ew-ph">Type a callsign to see its country, zones and what it is worth.</span>';
    } else if (!CALL_RE.test(call)) {
      hintEl.innerHTML = `<span class="ew-call">${window.VKA.escapeHtml(call)}</span><span class="ew-tag">not a valid callsign yet</span>`;
    } else if (!d.found) {
      hintEl.innerHTML = `<span class="ew-call">${window.VKA.escapeHtml(call)}</span><span class="ew-tag">unknown prefix</span>`;
    } else {
      const esc = window.VKA.escapeHtml;
      let h = `<span class="ew-call">${esc(call)}</span><span class="ew-ent">${esc(d.country)}</span><span>${esc(d.cont)} · CQ ${d.cq} · ITU ${d.itu}</span>`;
      if (d.dupe) h += '<span class="ew-tag dupe">DUPE</span>';
      else {
        if (d.new_country) h += '<span class="ew-tag new">NEW COUNTRY</span>';
        if (d.new_zone)    h += '<span class="ew-tag new">NEW ZONE</span>';
        if (d.points != null) h += `<span class="ew-tag">${d.points} pt${d.points === 1 ? '' : 's'}</span>`;
      }
      hintEl.innerHTML = h;
    }
    if (scpEl) {
      const c = (call || '').toUpperCase();
      scpEl.innerHTML = (d.scp || []).filter(x => x !== c).map(x => {
        const i = x.indexOf(c);
        const label = i >= 0 && c ? `${window.VKA.escapeHtml(x.slice(0, i))}<b>${window.VKA.escapeHtml(c)}</b>${window.VKA.escapeHtml(x.slice(i + c.length))}` : window.VKA.escapeHtml(x);
        return `<span data-call="${window.VKA.escapeHtml(x)}">${label}</span>`;
      }).join('');
    }
  }

  async function doLookup() {
    const call = effectiveCall();
    const seq = ++_lookupSeq;
    if (call.length < 2) { renderHint({}, ''); return; }
    try {
      const res = await fetch(`/api/lookup?call=${encodeURIComponent(call)}&band=${encodeURIComponent(_activeBand || '')}`);
      const d = await res.json();
      if (seq === _lookupSeq) renderHint(d, call);
    } catch (e) { /* hint is best-effort */ }
  }
  callInput.addEventListener('input', () => { clearTimeout(_lookupTimer); _lookupTimer = setTimeout(doLookup, 120); });
  bandsWrap.addEventListener('click', () => setTimeout(doLookup, 0));
  scpEl?.addEventListener('click', e => {
    const sp = e.target.closest('span[data-call]');
    if (sp) { callInput.value = sp.dataset.call; callInput.focus(); doLookup(); }
  });
  renderHint({}, '');   // initial placeholder

  function clearForm() {
    renderHint({}, '');
    clearError();
    callInput.value = ''; exchInput.value = '';
    if (commentInput) commentInput.value = '';
    if (_editingQsoId) cancelEdit();
    callInput.focus();
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    const call = effectiveCall();
    if (!call) { showError('Enter a callsign.'); return; }
    if (!CALL_RE.test(call)) { showError(`"${call}" is not a valid callsign.`); callInput.focus(); return; }
    if (!_activeBand && !_bands.length) {
      // loadBands()'s initial /api/plugin_meta fetch may not have resolved
      // yet if the operator started typing immediately after the tab
      // appeared — give it one more chance before actually failing.
      await loadBands();
    }
    if (!_activeBand && _bands.length) { _activeBand = _bands[0]; renderBands(); }
    if (!_activeBand) { showError('Pick a band.'); return; }
    const editing = !!_editingQsoId;
    const body = {
      call, band: _activeBand, mode: _activeMode || 'SSB',
      rst_sent: rstSent.value.trim(), rst_rcvd: rstRcvd.value.trim(),
      exchange: exchInput.value.trim(), is_run: !!runRadio.checked,
      comment: commentInput ? commentInput.value.trim() : '',
    };
    if (editing) body.qso_id = _editingQsoId;
    logItBtn.disabled = true;
    try {
      const res  = await fetch(editing ? '/api/qsos/update' : '/api/qsos/add', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.error) { showError(data.error || (editing ? 'Failed to update QSO.' : 'Failed to log QSO.')); return; }
      callInput.value = ''; exchInput.value = ''; renderHint({}, '');
      if (commentInput) commentInput.value = '';
      if (editing) cancelEdit();
      callInput.focus();
      window.VKA.invalidateQsosCache();
      window.dispatchEvent(new CustomEvent('vka:qsos_changed'));
      loadRecent();
      window.VKA?.showToast?.(editing ? 'QSO updated' : 'QSO logged', call, editing ? '✎' : '📝');
    } catch (e) {
      showError(`${editing ? 'Update' : 'Log'} failed: ${e.message}`);
    } finally {
      logItBtn.disabled = false;
    }
  });

  // Function keys (only while the Log Entry tab is the visible one): F5 Call,
  // F6 Exch Sent, F7 Exch Rcvd, F8 Cmnt, Esc / F12 clear the form. Enter
  // already submits natively via the form. Escape first closes the
  // right-click menu if one's open, and is left alone while typing in an
  // input elsewhere (e.g. the worked-list search box).
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && _ctxMenuEl) { closeCtxMenu(); return; }
    if (!document.getElementById('tab-logentry')?.classList.contains('active')) return;
    const t = e.target;
    if (e.key === 'Escape' && t?.closest && !t.closest('#ew-form') &&
        /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    const focusKey = {F5: callInput, F6: rstSent, F7: rstRcvd, F8: commentInput}[e.key];
    if (focusKey) { e.preventDefault(); focusKey.focus(); focusKey.select?.(); }
    else if (e.key === 'F12' || e.key === 'Escape') { e.preventDefault(); clearForm(); }
  });

  function updateHeader(snap) {
    const own = snap?.radio_info?.own;
    const r = window.VKA.formatRadio(own);
    if (r) {
      radioBandEl.textContent = r.band;
      radioBandEl.style.background = r.bandColor ? r.bandColor + '55' : '';
      radioFreqEl.textContent = r.freqStr + ' MHz';
      _liveMode = (r.modeStr || '').toUpperCase();
      // A live rig reading always wins over whatever was last manually
      // picked — the whole point of reading it is to track what the
      // operator is actually doing on the radio right now.
      if (_liveMode && MODE_CHOICES.includes(_liveMode)) _activeMode = _liveMode;
      if (own?.freq_hz && r.band) _lastFreqByBand[r.band] = own.freq_hz;
      // Don't clobber the field while the operator is mid-edit.
      if (document.activeElement !== freqInputEl) freqInputEl.value = r.freqStr;
      if (!_radioBandSeen && _bands.includes(r.band)) {
        _activeBand = r.band; renderBands(); _radioBandSeen = true;
      }
    } else {
      radioBandEl.textContent = '—'; radioFreqEl.textContent = '—';
      _liveMode = '';
      if (document.activeElement !== freqInputEl) freqInputEl.value = '';
    }
    // No rig connected at all and nothing manually picked yet — fall back
    // to the contest's own mode (e.g. Oceania DX CW) rather than leaving
    // the selector with nothing highlighted.
    if (!_activeMode) _activeMode = _contestMode || 'SSB';
    renderModeButtons();
    renderFreqField();
    applyRstDefaults();
  }

  window.addEventListener('vka:snapshot', e => { updateHeader(e.detail); loadRecent(); updateSummary(e.detail); });
  window.addEventListener('vka:qsos_changed', loadRecent);

  // Unlike the old dedicated popout window (where this was the only content
  // and always safe to focus on load), this now lives inline on the main
  // window's Log Entry tab — only steal focus when that tab is actually
  // the one the user switched to.
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'logentry') callInput.focus();
  });

  loadBands().then(() => {
    updateHeader(window.VKA.lastSnap()); loadRecent(); refreshRigStatus();
    updateSummary(window.VKA.lastSnap());
  });
})();
