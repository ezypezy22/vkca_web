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
  const wipeBtn      = document.getElementById('ew-wipe');
  const logItBtn     = document.getElementById('ew-log-it');
  const recentTbody  = document.getElementById('le-recent-tbody');
  const radioBandEl  = document.getElementById('ew-radio-band');
  const radioFreqEl  = document.getElementById('ew-radio-freq');
  const freqInputEl  = document.getElementById('ew-freq-input');
  const radioModeEl  = document.getElementById('ew-radio-mode');
  const modeBtnsEl   = document.getElementById('ew-mode-buttons');
  const qsoCountEl   = document.getElementById('ew-qso-count');
  const fkeysWrap    = document.getElementById('ew-fkeys');
  const stopBtn      = document.getElementById('ew-stop');
  const searchInput  = document.getElementById('le-search-input');

  function showError(msg) { errEl.textContent = msg; errEl.classList.remove('hidden'); }
  function clearError()   { errEl.textContent = ''; }

  // Band comes from clickable buttons, not a <select> — there's no
  // separate "Mode" control at all: like N1MM's own Entry Window, mode is
  // read from the live rig readout (radio_udp, see #ew-radio-mode) rather
  // than typed in, falling back to a plain default when no radio is seen.
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

  async function loadBands() {
    try {
      const res  = await fetch('/api/plugin_meta');
      const meta = await res.json();
      _bands = meta.bands || [];
      if (!_activeBand && _bands.length) _activeBand = _bands[0];
      renderBands();
    } catch (e) { console.warn('entrywindow: loadBands failed:', e); }
  }

  bandsWrap.addEventListener('click', e => {
    const btn = e.target.closest('button[data-band]');
    if (!btn) return;
    _activeBand = btn.dataset.band;
    renderBands();
    qsyToBand(_activeBand);
  });

  // ── Rig Control (Hamlib rigctld) — standalone Logger mode only, see
  // web/rigctld.py. Mode buttons, the editable frequency field, band-click
  // QSY, and F-key CW macros only ever become active once the rig poller
  // is actually connected — CW macros additionally require the rig to
  // read CW, since this app has no audio path for SSB/voice. Configured in
  // Settings → Rig Control (host/port, macro text per F-key, per-band QSY
  // default frequencies). ──────────────────────────────────────────────
  const MODE_CHOICES = ['CW', 'USB', 'LSB', 'RTTY', 'FM'];
  let _rigctldConnected = false;
  let _liveMode = '';
  let _macroSlots = new Set();   // fkey slot numbers ("1".."9") with non-empty macro text configured
  let _bandDefaults = {};        // band -> freq_hz, from Settings → Rig Control (unset unless configured)
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

  function updateFkeyEnablement() {
    const isCW = _liveMode === 'CW';
    const active = _rigctldConnected && isCW;
    const reason = !_rigctldConnected ? 'Rig Control not connected — see Settings'
      : !isCW ? 'CW macros only — rig is not in CW mode'
      : '';
    fkeysWrap.querySelectorAll('button[data-fkey]').forEach(btn => {
      const enabled = active && _macroSlots.has(btn.dataset.fkey);
      btn.disabled = !enabled;
      btn.title = enabled ? '' : (reason || 'No macro text configured for this key — see Settings');
    });
    if (stopBtn) { stopBtn.disabled = !active; stopBtn.title = active ? '' : (reason || ''); }
  }

  function renderModeButtons() {
    if (!_rigctldConnected) {
      modeBtnsEl.classList.add('hidden'); modeBtnsEl.innerHTML = '';
      radioModeEl.classList.remove('hidden');
      return;
    }
    radioModeEl.classList.add('hidden');
    modeBtnsEl.classList.remove('hidden');
    modeBtnsEl.innerHTML = MODE_CHOICES.map(m =>
      `<button type="button" data-mode="${m}" class="ew-mode-btn${m === _liveMode ? ' active' : ''}">${m}</button>`
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
      e.stopPropagation();   // don't also trigger the global Escape handler (Wipe + stop CW send)
      freqInputEl.blur();    // just defocus — the next snapshot resyncs its value
    }
  });

  modeBtnsEl.addEventListener('click', async e => {
    const btn = e.target.closest('button[data-mode]');
    if (!btn) return;
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

  async function sendMacro(btn) {
    if (!btn || btn.disabled) return;
    clearError();
    btn.disabled = true;
    try {
      const res  = await fetch('/api/rig/send_morse', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({fkey: btn.dataset.fkey, his_call: callInput.value.trim()}),
      });
      const data = await res.json();
      if (!res.ok || data.error) showError(data.error || 'Failed to send macro.');
    } catch (e) {
      showError(`Send failed: ${e.message}`);
    } finally {
      updateFkeyEnablement();   // re-derives real state rather than assuming re-enabled
    }
  }
  fkeysWrap.addEventListener('click', e => sendMacro(e.target.closest('button[data-fkey]')));

  stopBtn?.addEventListener('click', () => {
    if (stopBtn.disabled) return;
    // Best-effort — not every rig backend supports aborting mid-send, so
    // this deliberately doesn't surface a failure as an alarming error.
    fetch('/api/rig/stop_morse', {method: 'POST'}).catch(e =>
      console.warn('entrywindow: stop_morse failed:', e));
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
      _macroSlots = new Set(
        Object.entries(cfg.macros || {}).filter(([, v]) => (v || '').trim()).map(([k]) => k));
      _bandDefaults = cfg.band_defaults || {};
    } catch (e) {
      console.warn('entrywindow: refreshRigStatus failed:', e);
      _rigctldConnected = false;
    }
    renderModeButtons();
    renderFreqField();
    updateFkeyEnablement();
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

  function renderRecentRows() {
    if (!recentTbody) return;
    const term = (searchInput?.value || '').trim().toUpperCase();
    let list = term ? _lastQsos.filter(q => (q.call || '').toUpperCase().includes(term)) : _lastQsos;
    list = [...list];
    if (_reworkWindowHours) {
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
        <td>${window.VKA.escapeHtml(q.mult1 || '—')}</td>
        <td>${fmtTime(q.time)}</td>
        <td class="ew-countdown" data-at="${q._countdownAt || ''}">${q._countdownAt ? fmtRemaining(q._countdownAt - Date.now()) : '—'}</td>
        <td class="le-actions">
          <button type="button" class="le-row-edit" data-qid="${q.qso_id || ''}" title="Edit this QSO">✎</button>
          <button type="button" class="le-row-del" data-qid="${q.qso_id || ''}" title="Delete this QSO">✕</button>
        </td>
      </tr>`).join('') || `<tr><td colspan="7">${term ? 'No matching QSOs.' : 'No QSOs logged yet.'}</td></tr>`;
  }
  searchInput?.addEventListener('input', renderRecentRows);

  async function loadRecent() {
    try {
      const qsos = await window.VKA.fetchQsos();
      if (qsoCountEl) qsoCountEl.textContent = qsos.length;
      if (!recentTbody) return;
      readSessionConfig();
      annotateCountdowns(qsos);
      if (thCountdownEl) thCountdownEl.textContent = _reworkWindowHours ? 'Time Left to Work' : 'Next Block In';
      _lastQsos = qsos;
      renderRecentRows();
    } catch (e) { console.warn('entrywindow: loadRecent failed:', e); }
  }

  // ── Edit an existing entry — loads it back into the form (like N1MM's
  // own "Edit" F-key), submit becomes an update instead of a new QSO.
  // Mode isn't editable here (this form has no mode selector — mode is
  // always read from the live rig for a NEW entry), so an edit keeps the
  // QSO's own original mode rather than overwriting it with whatever the
  // rig currently reads. Run/S&P can't be recovered from a fetched QSO
  // (not exposed in that shape) — left as whatever the toggle currently
  // shows, matching this form's other "can't fully restore" limitations. ──
  let _editingQsoId = null;
  let _editingMode  = null;

  function startEdit(q) {
    _editingQsoId = q.qso_id || null;
    _editingMode  = q.mode || null;
    if (!_editingQsoId) { showError('Cannot edit this QSO (no ID).'); return; }
    clearError();
    callInput.value = q.call || '';
    rstSent.value = q.rst_sent || rstSent.value;
    rstRcvd.value = q.rst_rcvd || rstRcvd.value;
    exchInput.value = q.mult1 || '';
    const band = (q.band || '').toUpperCase();
    if (_bands.includes(band)) { _activeBand = band; renderBands(); }
    logItBtn.textContent = 'Update It';
    callInput.focus();
  }

  function cancelEdit() {
    _editingQsoId = null;
    _editingMode  = null;
    logItBtn.textContent = 'Log It';
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

  function clearForm() {
    clearError();
    callInput.value = ''; exchInput.value = '';
    if (_editingQsoId) cancelEdit();
    callInput.focus();
  }
  wipeBtn.addEventListener('click', clearForm);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    const call = callInput.value.trim().toUpperCase();
    if (!call) { showError('Enter a callsign.'); return; }
    if (!_activeBand && !_bands.length) {
      // loadBands()'s initial /api/plugin_meta fetch may not have resolved
      // yet if the operator started typing immediately after the tab
      // appeared — give it one more chance before actually failing.
      await loadBands();
    }
    if (!_activeBand && _bands.length) { _activeBand = _bands[0]; renderBands(); }
    if (!_activeBand) { showError('Pick a band.'); return; }
    const editing = !!_editingQsoId;
    let mode;
    if (editing) {
      mode = _editingMode || 'SSB';
    } else {
      const snap = window.VKA.lastSnap();
      const r = window.VKA.formatRadio(snap?.radio_info?.own);
      mode = r?.modeStr || 'SSB';
    }
    const body = {
      call, band: _activeBand, mode,
      rst_sent: rstSent.value.trim(), rst_rcvd: rstRcvd.value.trim(),
      exchange: exchInput.value.trim(), is_run: !!runRadio.checked,
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
      callInput.value = ''; exchInput.value = '';
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

  // F12 "Wipe" always works; Escape wipes the form AND (best-effort) stops
  // any in-progress CW send. F1-F11 mirror a click on their matching macro
  // button — real contest operators drive these from the keyboard, not the
  // mouse — but only while the Log Entry tab is actually the active one, so
  // this doesn't hijack function keys elsewhere in the app. Enter already
  // submits natively via the form.
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && _ctxMenuEl) { closeCtxMenu(); return; }
    if (e.key === 'F12') { e.preventDefault(); clearForm(); }
    else if (e.key === 'Escape') { clearForm(); if (stopBtn && !stopBtn.disabled) stopBtn.click(); }
    else if (/^F(?:[1-9]|1[01])$/.test(e.key)) {
      if (!document.getElementById('tab-logentry')?.classList.contains('active')) return;
      const btn = fkeysWrap.querySelector(`button[data-fkey="${e.key.slice(1)}"]`);
      if (btn && !btn.disabled) { e.preventDefault(); btn.click(); }
    }
  });

  function updateHeader(snap) {
    const own = snap?.radio_info?.own;
    const r = window.VKA.formatRadio(own);
    if (r) {
      radioBandEl.textContent = r.band;
      radioBandEl.style.background = r.bandColor ? r.bandColor + '55' : '';
      radioFreqEl.textContent = r.freqStr + ' MHz';
      radioModeEl.textContent = r.modeStr || '—';
      _liveMode = (r.modeStr || '').toUpperCase();
      if (own?.freq_hz && r.band) _lastFreqByBand[r.band] = own.freq_hz;
      // Don't clobber the field while the operator is mid-edit.
      if (document.activeElement !== freqInputEl) freqInputEl.value = r.freqStr;
      if (!_radioBandSeen && _bands.includes(r.band)) {
        _activeBand = r.band; renderBands(); _radioBandSeen = true;
      }
    } else {
      radioBandEl.textContent = '—'; radioFreqEl.textContent = '—'; radioModeEl.textContent = '—';
      _liveMode = '';
      if (document.activeElement !== freqInputEl) freqInputEl.value = '';
    }
    renderModeButtons();
    renderFreqField();
    updateFkeyEnablement();
  }

  window.addEventListener('vka:snapshot', e => { updateHeader(e.detail); loadRecent(); });
  window.addEventListener('vka:qsos_changed', loadRecent);

  // Unlike the old dedicated popout window (where this was the only content
  // and always safe to focus on load), this now lives inline on the main
  // window's Log Entry tab — only steal focus when that tab is actually
  // the one the user switched to.
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'logentry') callInput.focus();
  });

  loadBands().then(() => { updateHeader(window.VKA.lastSnap()); loadRecent(); refreshRigStatus(); });
})();
