/**
 * entrywindow.js — N1MM-style "Entry Window", embedded inline in the Log
 * Entry tab (#tab-logentry) for standalone logging mode. Call/RST/Exchange
 * fields submit to /api/qsos/add; the "Worked This Session" list below it
 * (le-recent-tbody, in index.html) is fed by loadRecent() here too.
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
  const radioModeEl  = document.getElementById('ew-radio-mode');
  const qsoCountEl   = document.getElementById('ew-qso-count');

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
  });

  function fmtTime(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').substring(0, 19) + ' UTC';
  }

  async function loadRecent() {
    try {
      const qsos = await window.VKA.fetchQsos();
      if (qsoCountEl) qsoCountEl.textContent = qsos.length;
      if (!recentTbody) return;
      const recent = [...qsos].sort((a, b) => (a.time < b.time ? 1 : a.time > b.time ? -1 : 0)).slice(0, 200);
      recentTbody.innerHTML = recent.map(q => `
        <tr>
          <td style="font-weight:bold">${window.VKA.escapeHtml(q.call || '—')}</td>
          <td>${(q.band || '').toLowerCase()}</td>
          <td>${q.mode || '—'}</td>
          <td>${window.VKA.escapeHtml(q.mult1 || '—')}</td>
          <td>${fmtTime(q.time)}</td>
        </tr>`).join('') || `<tr><td colspan="5">No QSOs logged yet.</td></tr>`;
    } catch (e) { console.warn('entrywindow: loadRecent failed:', e); }
  }

  function clearForm() {
    clearError();
    callInput.value = ''; exchInput.value = '';
    callInput.focus();
  }
  wipeBtn.addEventListener('click', clearForm);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    const call = callInput.value.trim().toUpperCase();
    if (!call) { showError('Enter a callsign.'); return; }
    if (!_activeBand) { showError('Pick a band.'); return; }
    const snap = window.VKA.lastSnap();
    const r = window.VKA.formatRadio(snap?.radio_info?.own);
    const body = {
      call, band: _activeBand, mode: (r?.modeStr || 'SSB'),
      rst_sent: rstSent.value.trim(), rst_rcvd: rstRcvd.value.trim(),
      exchange: exchInput.value.trim(), is_run: !!runRadio.checked,
    };
    logItBtn.disabled = true;
    try {
      const res  = await fetch('/api/qsos/add', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.error) { showError(data.error || 'Failed to log QSO.'); return; }
      callInput.value = ''; exchInput.value = '';
      callInput.focus();
      window.VKA.invalidateQsosCache();
      window.dispatchEvent(new CustomEvent('vka:qsos_changed'));
      loadRecent();
      window.VKA?.showToast?.('QSO logged', call, '📝');
    } catch (e) {
      showError(`Log failed: ${e.message}`);
    } finally {
      logItBtn.disabled = false;
    }
  });

  // F12 "Wipe" and Esc — the only two F-keys wired to a real action (see
  // the plan's rationale: no rig/keying integration here, so the rest of
  // the F1-F11 row stays visually present but disabled). Enter already
  // submits natively via the form.
  document.addEventListener('keydown', e => {
    if (e.key === 'F12') { e.preventDefault(); clearForm(); }
    else if (e.key === 'Escape') { clearForm(); }
  });

  function updateHeader(snap) {
    const r = window.VKA.formatRadio(snap?.radio_info?.own);
    if (r) {
      radioBandEl.textContent = r.band;
      radioBandEl.style.background = r.bandColor ? r.bandColor + '55' : '';
      radioFreqEl.textContent = r.freqStr + ' MHz';
      radioModeEl.textContent = r.modeStr || '—';
      if (!_radioBandSeen && _bands.includes(r.band)) {
        _activeBand = r.band; renderBands(); _radioBandSeen = true;
      }
    } else {
      radioBandEl.textContent = '—'; radioFreqEl.textContent = '—'; radioModeEl.textContent = '—';
    }
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

  loadBands().then(() => { updateHeader(window.VKA.lastSnap()); loadRecent(); });
})();
