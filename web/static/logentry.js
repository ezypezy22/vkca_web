/**
 * logentry.js — Log Entry tab for standalone logging mode. QSOs are logged
 * exclusively through the N1MM-style Entry Window popout (entrywindow.js,
 * POST /api/entry_window) — this tab is just the launcher plus a read-only
 * Recently Logged list. Only ever relevant for a log created via "+ New Log"
 * (see app.js's btn-new-log flow and STATE.is_standalone_log) — the tab
 * itself stays hidden otherwise (overview.js's loadPluginMeta() gate).
 */
;(function () {
  'use strict';
  if (location.pathname !== '/') return;   // main-window-only, like settings.js

  const openEntryWindowBtn = document.getElementById('le-open-entry-window');
  if (!openEntryWindowBtn) return;

  const errEl        = document.getElementById('le-error');
  const recentTbody  = document.getElementById('le-recent-tbody');

  function showError(msg) { errEl.textContent = msg; errEl.classList.remove('hidden'); }
  function clearError()   { errEl.classList.add('hidden'); }

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

  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab !== 'logentry') return;
    loadRecent();
  });

  // Opens the N1MM-style Entry Window (entrywindow.js) in its own popped-out
  // pywebview window — reused if already open, see /api/entry_window.
  openEntryWindowBtn.addEventListener('click', async () => {
    clearError();
    openEntryWindowBtn.disabled = true;
    try {
      const res  = await fetch('/api/entry_window', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || data.error) showError(data.error || 'Failed to open Entry Window.');
    } catch (e) {
      showError(`Failed to open Entry Window: ${e.message}`);
    } finally {
      openEntryWindowBtn.disabled = false;
    }
  });

  // A QSO logged via the Entry Window (or deleted via Worked) should still
  // refresh this tab's own recent-list if it happens to be the active one.
  window.addEventListener('vka:qsos_changed', () => {
    if (document.getElementById('tab-logentry')?.classList.contains('active')) loadRecent();
  });
})();
