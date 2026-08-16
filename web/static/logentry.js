/**
 * logentry.js — QSO entry form for standalone logging mode (Log Entry tab).
 * Only ever relevant for a log created via "+ New Log" (see app.js's
 * btn-new-log flow and STATE.is_standalone_log) — the tab itself stays
 * hidden otherwise (overview.js's loadPluginMeta() gate), and the backing
 * /api/qsos/add endpoint independently refuses to write into anything else,
 * so this module doesn't need its own copy of that guardrail.
 */
;(function () {
  'use strict';
  if (location.pathname !== '/') return;   // main-window-only, like settings.js

  const form       = document.getElementById('logentry-form');
  if (!form) return;

  const callInput  = document.getElementById('le-call');
  const bandSelect = document.getElementById('le-band');
  const modeSelect = document.getElementById('le-mode');
  const rstSent    = document.getElementById('le-rst-sent');
  const rstRcvd    = document.getElementById('le-rst-rcvd');
  const exchInput  = document.getElementById('le-exchange');
  const errEl      = document.getElementById('le-error');
  const submitBtn  = document.getElementById('le-submit');
  const recentTbody = document.getElementById('le-recent-tbody');

  function showError(msg) { errEl.textContent = msg; errEl.classList.remove('hidden'); }
  function clearError()   { errEl.classList.add('hidden'); }

  // Band list comes from the loaded plugin's own band_list() (same source
  // "What if?"'s band dropdown already uses — see /api/plugin_meta) rather
  // than a hardcoded list here, so this form only ever offers bands the
  // active contest's rules actually allow.
  let _bandsLoaded = false;
  async function loadBands() {
    try {
      const res  = await fetch('/api/plugin_meta');
      const meta = await res.json();
      const bands = meta.bands || [];
      bandSelect.innerHTML = bands.map(b => `<option value="${b}">${b.toLowerCase()}</option>`).join('');
      _bandsLoaded = true;
    } catch (e) { console.warn('logentry: loadBands failed:', e); }
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    return String(iso).replace('T', ' ').substring(0, 19) + ' UTC';
  }

  async function loadRecent() {
    if (!recentTbody) return;
    try {
      const qsos = await window.VKA.fetchQsos();
      const recent = [...qsos].sort((a, b) => (a.time < b.time ? 1 : a.time > b.time ? -1 : 0)).slice(0, 10);
      recentTbody.innerHTML = recent.map(q => `
        <tr>
          <td style="color:var(--accent);font-weight:bold">${window.VKA.escapeHtml(q.call || '—')}</td>
          <td>${(q.band || '').toLowerCase()}</td>
          <td>${q.mode || '—'}</td>
          <td>${window.VKA.escapeHtml(q.mult1 || '—')}</td>
          <td style="color:var(--muted);font-size:0.85em">${fmtTime(q.time)}</td>
        </tr>`).join('') || `<tr><td colspan="5" style="color:var(--muted)">No QSOs logged yet.</td></tr>`;
    } catch (e) { console.warn('logentry: loadRecent failed:', e); }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    const call = callInput.value.trim().toUpperCase();
    if (!call) { showError('Enter a callsign.'); return; }
    const body = {
      call, band: bandSelect.value, mode: modeSelect.value,
      rst_sent: rstSent.value.trim(), rst_rcvd: rstRcvd.value.trim(),
      exchange: exchInput.value.trim(),
    };
    submitBtn.disabled = true; submitBtn.textContent = 'Logging…';
    try {
      const res  = await fetch('/api/qsos/add', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || data.error) { showError(data.error || 'Failed to log QSO.'); return; }
      // Call/exchange clear for the next contact; band/mode/RST stay as
      // sticky defaults — the common case is working several stations in a
      // row on the same band/mode with similar signal reports.
      callInput.value = ''; exchInput.value = '';
      callInput.focus();
      window.VKA.invalidateQsosCache();
      window.dispatchEvent(new CustomEvent('vka:qsos_changed'));
      loadRecent();
      window.VKA?.showToast?.('QSO logged', call, '📝');
    } catch (e) {
      showError(`Log failed: ${e.message}`);
    } finally {
      submitBtn.disabled = false; submitBtn.textContent = '📝 Log QSO';
    }
  });

  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab !== 'logentry') return;
    if (!_bandsLoaded) loadBands();
    loadRecent();
  });
  // A QSO logged from elsewhere (there isn't one yet, but matches the
  // pattern every other qsos-consuming tab already follows) or deleted via
  // Worked should still refresh this tab's own recent-list if it happens
  // to be the active one.
  window.addEventListener('vka:qsos_changed', () => {
    if (document.getElementById('tab-logentry')?.classList.contains('active')) loadRecent();
  });
})();
