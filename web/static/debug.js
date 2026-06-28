/**
 * debug.js — Debug Mults tab: full QSO list with mult resolution details
 */
;(function () {
  'use strict';
  let _allQsos = [];
  const filter = document.getElementById('debug-filter');

  async function load() {
    const res  = await fetch('/api/qsos');
    _allQsos   = await res.json();
    render();
  }

  function render() {
    const q   = (filter?.value || '').toLowerCase().trim();
    const rows = q
      ? _allQsos.filter(r =>
          (r.call||'').toLowerCase().includes(q) ||
          (r.mult1||'').toLowerCase().includes(q) ||
          (r.band||'').toLowerCase().includes(q) ||
          (r.mult_source||'').toLowerCase().includes(q))
      : _allQsos;

    const tbody = document.getElementById('debug-tbody');
    if (!tbody) return;
    const count = document.getElementById('debug-count');
    if (count) count.textContent = rows.length;

    // Virtual render: only show first 500 for performance
    const slice = rows.slice(0, 500);
    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    slice.forEach(q => {
      const isDupe = q.dupe ? 'DUPE' : '';
      const tr = document.createElement('tr');
      tr.style.opacity = q.dupe ? '0.45' : '1';
      tr.innerHTML = `
        <td style="color:var(--accent);font-weight:bold">${q.call||'—'}</td>
        <td>${(q.band||'?').toUpperCase()}</td>
        <td>${q.mode||'—'}</td>
        <td style="color:var(--accent3)">${q.mult1||'—'}</td>
        <td style="color:var(--muted);font-size:0.77em">${q.raw_mult||'—'}</td>
        <td style="color:var(--muted);font-size:0.77em">${q.mult_source||'—'}</td>
        <td>${q.pts||0}</td>
        <td style="color:var(--red);font-size:0.77em">${isDupe}</td>
        <td style="color:var(--muted);font-size:0.77em">${(q.time||'').substring(0,19)}</td>`;
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
  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab==='debug') load(); });
})();
