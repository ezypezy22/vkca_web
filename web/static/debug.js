/**
 * debug.js — Debug Mults tab: full QSO list with mult resolution details
 */
;(function () {
  'use strict';
  const escapeHtml = window.VKA.escapeHtml;
  let _allQsos = [];
  const filter = document.getElementById('debug-filter');
  const anomaliesChk = document.getElementById('debug-anomalies-only');

  // An "anomaly" here means the log had a mult candidate (raw_mult, whatever
  // the plugin extracted from the exchange) that never resolved into an
  // actual mult1 value — a real scoring gap, not just "no mult on this QSO"
  // (most QSOs legitimately have no raw_mult at all, e.g. dupes/no-mult
  // sections, and shouldn't be flagged). Point at this table with the
  // filter instead of eyeballing hundreds of rows for the one that's wrong.
  function isAnomaly(q) {
    return !!(q.raw_mult && String(q.raw_mult).trim() && !(q.mult1 && String(q.mult1).trim()));
  }

  // Bumped on every load() call so an older, slower-to-resolve fetch can't
  // clobber the table with stale rows after a newer one already rendered
  // (e.g. a rapid snapshot-tick + tab-switch) — mirrors report.js's own
  // _loadGeneration pattern (see issue #64).
  let _loadGeneration = 0;

  async function load() {
    const gen = ++_loadGeneration;
    const data = await window.VKA.fetchQsos();
    if (gen !== _loadGeneration) return;
    _allQsos = data;
    render();
  }

  function render() {
    const q = (filter?.value || '').toLowerCase().trim();
    let rows = q
      ? _allQsos.filter(r =>
          (r.call||'').toLowerCase().includes(q) ||
          (r.mult1||'').toLowerCase().includes(q) ||
          (r.band||'').toLowerCase().includes(q) ||
          (r.mult_source||'').toLowerCase().includes(q))
      : _allQsos;
    const anomalyCount = _allQsos.reduce((n,r) => n + (isAnomaly(r)?1:0), 0);
    if (anomaliesChk?.checked) rows = rows.filter(isAnomaly);

    const tbody = document.getElementById('debug-tbody');
    if (!tbody) return;
    const count = document.getElementById('debug-count');
    if (count) count.textContent = anomaliesChk?.checked
      ? `${rows.length} anomal${rows.length===1?'y':'ies'}`
      : `${rows.length}${anomalyCount ? ` (${anomalyCount} anomal${anomalyCount===1?'y':'ies'})` : ''}`;

    // Virtual render: only show first 500 for performance
    const slice = rows.slice(0, 500);
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    slice.forEach(q => {
      const isDupe = q.dupe ? 'DUPE' : '';
      const anomaly = isAnomaly(q);
      const tr = document.createElement('tr');
      tr.style.opacity = q.dupe ? '0.45' : '1';
      if (anomaly) { tr.style.background = 'rgba(255,71,87,.08)'; tr.style.borderLeft = '2px solid var(--red)'; }
      tr.innerHTML = `
        <td style="color:var(--accent);font-weight:bold">${escapeHtml(q.call||'—')}</td>
        <td>${(q.band||'?').toUpperCase()}</td>
        <td>${q.mode||'—'}</td>
        <td style="color:var(--accent3)">${escapeHtml(q.mult1||'—')}</td>
        <td style="color:var(--muted);font-size:0.77em">${escapeHtml(q.raw_mult||'—')}</td>
        <td style="color:var(--muted);font-size:0.77em">${q.mult_source||'—'}</td>
        <td>${q.pts||0}</td>
        <td style="color:var(--red);font-size:0.77em">${isDupe}${anomaly ? ' ⚠' : ''}</td>
        <td style="color:var(--muted);font-size:0.77em">${(q.time||'').substring(0,19)}</td>`;
      if (anomaly) tr.title = 'Anomaly: raw_mult was extracted but never resolved into mult1 — check this QSO\'s scoring.';
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);

    if (rows.length > 500) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td colspan="9" style="color:var(--muted);text-align:center;padding:8px">
        … ${rows.length - 500} more rows — use filter to narrow</td>`;
      tbody.appendChild(tr);
    }
  }

  filter?.addEventListener('input', render);
  anomaliesChk?.addEventListener('change', render);
  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab==='debug') load(); });
})();
