/**
 * missing.js — Missing Multipliers panel
 * Fetches /api/missing on tab switch and filters client-side.
 */

;(function () {
  'use strict';

  const tbody  = document.getElementById('missing-tbody');
  const count  = document.getElementById('missing-count');
  const filter = document.getElementById('missing-filter');

  const STATE_COLS = {
    NSW:'#00d4aa',QLD:'#f0c040',VIC:'#64b5f6',SA:'#ff6b35',
    WA:'#e040fb', TAS:'#2ed573',NT:'#ff5252',ACT:'#ffab40',
  };

  let _rows = [];

  async function load() {
    try {
      const res  = await fetch('/api/missing');
      _rows = await res.json();
      render();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="2" style="color:var(--red);padding:12px">
        Failed to load: ${e.message}</td></tr>`;
    }
  }

  function render() {
    const q = (filter.value || '').toLowerCase().trim();
    const filtered = q
      ? _rows.filter(r =>
          r.mult.toLowerCase().includes(q) ||
          (r.region || '').toLowerCase().includes(q))
      : _rows;

    count.textContent = filtered.length;

    tbody.innerHTML = '';
    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="2" style="color:var(--muted);padding:12px;
        font-style:italic">${_rows.length ? 'No matches' : 'All multipliers worked!'}</td></tr>`;
      return;
    }

    const frag = document.createDocumentFragment();
    filtered.forEach((r, i) => {
      const tr = document.createElement('tr');
      const col = STATE_COLS[r.region] || 'var(--muted)';
      tr.innerHTML = `
        <td style="color:${col};font-weight:bold">${r.mult}</td>
        <td style="color:${col}">${r.region || '—'}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  filter.addEventListener('input', render);

  // Reload when snapshot changes (new QSOs may have worked mults)
  window.addEventListener('vka:snapshot', load);

  // Also reload on tab switch
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'missing') load();
  });

})();
