/**
 * worked.js — Full QSO log (all worked, not just last 5)
 * Paginated with filter for performance on large logs
 */
;(function () {
  'use strict';
  const BAND_COLS = {
    '160M':'#e040fb','80M':'#ff6b35','60M':'#f0c040','40M':'#2ed573',
    '30M':'#00bcd4','20M':'#00d4aa','17M':'#64b5f6','15M':'#ff5252',
    '12M':'#ffab40','10M':'#69f0ae','6M':'#ea80fc','2M':'#80d8ff',
  };

  let _allQsos  = [];
  let _filtered = [];
  const PAGE_SIZE = 100;
  let _page = 0;

  const tbody    = document.getElementById('worked-tbody');
  const countEl  = document.getElementById('worked-count');
  const filterEl = document.getElementById('worked-filter');
  const prevBtn  = document.getElementById('worked-prev');
  const nextBtn  = document.getElementById('worked-next');
  const pageEl   = document.getElementById('worked-page');

  function fmt(isoStr) {
    if (!isoStr) return '—';
    return String(isoStr).replace('T',' ').substring(0,19)+' UTC';
  }

  async function load() {
    try {
      const res = await fetch('/api/qsos');
      _allQsos  = await res.json();
      _page     = 0;
      applyFilter();
    } catch(e) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="color:var(--red);padding:12px">Failed: ${e.message}</td></tr>`;
    }
  }

  function applyFilter() {
    const q = (filterEl?.value || '').toLowerCase().trim();
    _filtered = q
      ? _allQsos.filter(r =>
          (r.call||'').toLowerCase().includes(q) ||
          (r.band||'').toLowerCase().includes(q) ||
          (r.mode||'').toLowerCase().includes(q) ||
          (r.mult1||'').toLowerCase().includes(q))
      : _allQsos;
    _page = 0;
    render();
  }

  function render() {
    if (!tbody) return;
    const total = _filtered.length;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    _page = Math.max(0, Math.min(_page, pages - 1));
    const start = _page * PAGE_SIZE;
    const slice = _filtered.slice(start, start + PAGE_SIZE);

    if (countEl)  countEl.textContent  = total.toLocaleString();
    if (pageEl)   pageEl.textContent   = `${_page + 1} / ${pages}`;
    if (prevBtn)  prevBtn.disabled     = _page === 0;
    if (nextBtn)  nextBtn.disabled     = _page >= pages - 1;

    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    slice.forEach(q => {
      const band = (q.band||'').toUpperCase();
      const col  = BAND_COLS[band] || 'var(--muted)';
      const isDupe = q.dupe ? '✗' : '';
      const tr   = document.createElement('tr');
      if (q.dupe) tr.style.opacity = '0.4';
      tr.innerHTML = `
        <td style="color:var(--accent);font-weight:bold">${q.call||'—'}</td>
        <td style="color:${col}">${band.toLowerCase()}</td>
        <td>${q.mode||'—'}</td>
        <td style="color:${col}">${q.mult1||'—'}</td>
        <td>${q.pts||0}</td>
        <td style="color:var(--muted);font-size:0.85em">${fmt(q.time)}</td>
        <td style="color:var(--red);font-size:0.85em">${isDupe}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  filterEl?.addEventListener('input', applyFilter);
  prevBtn?.addEventListener('click', () => { _page--; render(); });
  nextBtn?.addEventListener('click', () => { _page++; render(); });

  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab === 'worked') load(); });
})();
