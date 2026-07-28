/**
 * missing.js — Missing Multipliers panel
 * Fetches /api/missing on tab switch and filters client-side.
 */

;(function () {
  'use strict';

  const tbody  = document.getElementById('missing-tbody');
  const count  = document.getElementById('missing-count');
  const filter = document.getElementById('missing-filter');
  const strip  = document.getElementById('missing-region-strip');

  const STATE_COLS = {
    NSW:'#00d4aa',QLD:'#f0c040',VIC:'#64b5f6',SA:'#ff6b35',
    WA:'#e040fb', TAS:'#2ed573',NT:'#ff5252',ACT:'#ffab40',
  };

  let _rows = [];

  // Bumped on every load() call so an older, slower-to-resolve fetch can't
  // clobber the table with stale rows after a newer one already rendered
  // (e.g. a rapid snapshot-tick + tab-switch) — mirrors report.js's own
  // _loadGeneration pattern (see issue #64).
  let _loadGeneration = 0;

  // ── Region summary chips (worked/total per region, click to quick-filter) ──
  // Reuses snap.region_heat, already computed for the Overview state-bars
  // panel — no extra fetch needed.
  function renderRegionStrip() {
    if (!strip || !filter) return;
    const heat = window.VKA?.lastSnap?.()?.region_heat;
    if (!heat || !heat.length) { strip.innerHTML = ''; return; }

    const activeRegion = (filter.value || '').trim().toUpperCase();
    strip.innerHTML = '';
    const frag = document.createDocumentFragment();
    heat.forEach(r => {
      const region  = r.state || r.region || '?';
      const missing = Math.max(0, (r.total || 0) - (r.worked || 0));
      if (!missing) return;   // fully worked — nothing to quick-filter to
      const col = STATE_COLS[region] || 'var(--muted)';
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'missing-region-chip' + (activeRegion === region ? ' active' : '');
      chip.style.color = col;
      chip.style.borderColor = col;
      chip.innerHTML = `<span>${region} · ${missing} missing</span>`;
      chip.addEventListener('click', () => {
        filter.value = (filter.value.trim().toUpperCase() === region) ? '' : region;
        render();
      });
      frag.appendChild(chip);
    });
    strip.appendChild(frag);
  }

  async function load() {
    if (!tbody) return;
    const gen = ++_loadGeneration;
    try {
      const res  = await fetch('/api/missing');
      const data = await res.json();
      if (gen !== _loadGeneration) return;
      _rows = data;
      render();
    } catch (e) {
      if (gen !== _loadGeneration) return;
      tbody.innerHTML = `<tr><td colspan="3" style="color:var(--red);padding:12px">
        Failed to load: ${e.message}</td></tr>`;
    }
  }

  function render() {
    if (!tbody) return;
    const q = (filter?.value || '').toLowerCase().trim();
    const filtered = q
      ? _rows.filter(r =>
          r.mult.toLowerCase().includes(q) ||
          (r.region || '').toLowerCase().includes(q))
      : _rows;

    if (count) count.textContent = filtered.length;
    renderRegionStrip();

    tbody.innerHTML = '';
    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="3" style="color:var(--muted);padding:12px;
        font-style:italic">${_rows.length ? 'No matches' : 'All multipliers worked!'}</td></tr>`;
      return;
    }

    // Cross-reference against the DX Cluster tab's own live spot list (see
    // cluster.js's window.VKA.getRecentSpottedMults()) — turns this from a
    // static checklist into "this one's actionable right now" without a
    // second network fetch, since cluster.js already keeps the spot list
    // client-side.
    const spotted = window.VKA?.getRecentSpottedMults?.() || {};

    const frag = document.createDocumentFragment();
    filtered.forEach((r, i) => {
      const tr = document.createElement('tr');
      const col = STATE_COLS[r.region] || 'var(--muted)';
      const spot = spotted[r.mult];
      const ageMin = spot ? Math.max(0, Math.round((Date.now() - spot._receivedAt) / 60000)) : null;
      const spotCell = spot
        ? `<span class="badge" style="color:var(--green);border:1px solid var(--green);background:rgba(46,213,115,.12)"
             title="Spotted by ${window.VKA.escapeHtml(spot.spotter||'?')} on ${spot.freq} kHz">
             📡 ${spot.band} · ${ageMin===0?'just now':ageMin+'m ago'}</span>`
        : '';
      tr.innerHTML = `
        <td style="color:${col};font-weight:bold">${r.mult}</td>
        <td style="color:${col}">${r.region || '—'}</td>
        <td>${spotCell}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  // A new NEW_MULT spot lands independently of the snapshot stream (it
  // comes over the DX Cluster tab's own WebSocket) — re-render so a
  // "spotted" badge can appear without waiting for the next QSO/snapshot
  // tick. Cheap: re-renders from the already-fetched _rows, no new fetch.
  window.addEventListener('vka:cluster_spot', () => { if (_rows.length) render(); });

  filter?.addEventListener('input', render);

  // Reload when snapshot changes (new QSOs may have worked mults)
  window.addEventListener('vka:snapshot', load);

  // Also reload on tab switch
  window.addEventListener('vka:tabchange', e => {
    if (e.detail.tab === 'missing') load();
  });

})();
