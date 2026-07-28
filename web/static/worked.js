/**
 * worked.js — Full QSO log (all worked, not just last 5)
 * Paginated with filter for performance on large logs.
 * Adds the old desktop app's "Block" / live-ticking "Next Block In" countdown
 * (which operating block this QSO falls in, and when the current block ends)
 * plus multi-select delete.
 */
;(function () {
  'use strict';
  const BAND_COLS = window.VKA.BAND_COLS;

  let _allQsos  = [];
  let _filtered = [];
  let _selected = new Set();
  let _tickHandle = null;
  const PAGE_SIZE = 100;
  let _page = 0;
  let _sortCol = null, _sortDir = 1;   // 1 = ascending, -1 = descending

  // Session/block config, pulled from the latest snapshot.
  let _contestStart = null;   // Date
  let _durationMins = null;
  let _labelPrefix  = 'B';

  const tbody       = document.getElementById('worked-tbody');
  const countEl     = document.getElementById('worked-count');
  const filterEl    = document.getElementById('worked-filter');
  const prevBtn     = document.getElementById('worked-prev');
  const nextBtn     = document.getElementById('worked-next');
  const pageEl       = document.getElementById('worked-page');
  const deleteBtn     = document.getElementById('worked-delete-btn');
  const selectAllChk  = document.getElementById('worked-select-all');
  const exportCsvBtn  = document.getElementById('worked-export-csv-btn');
  const exportAdifBtn = document.getElementById('worked-export-adif-btn');

  function fmt(isoStr) {
    if (!isoStr) return '—';
    return String(isoStr).replace('T',' ').substring(0,19)+' UTC';
  }

  function fmtRemaining(ms) {
    if (ms <= 0) return 'Workable';
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    return `${h}h ${String(m).padStart(2,'0')}m ${String(s).padStart(2,'0')}s`;
  }

  function readSessionConfig() {
    const snap = window.VKA?.lastSnap?.();
    const ss   = snap?.session_status || {};
    _contestStart = ss.start_dt ? new Date(ss.start_dt+'Z') : null;   // server times are naive UTC
    _durationMins = ss.duration_mins || null;
    _labelPrefix  = ss.label_prefix || 'B';
  }

  function blockInfo(qsoTimeIso) {
    if (!_contestStart || !_durationMins || !qsoTimeIso) return null;
    const t = new Date(qsoTimeIso+'Z');   // server times are naive UTC
    const elapsedMins = (t - _contestStart) / 60000;
    if (elapsedMins < 0) return null;
    const bn = Math.floor(elapsedMins / _durationMins);
    const blockEnd = new Date(_contestStart.getTime() + (bn + 1) * _durationMins * 60000);
    return { label: `${_labelPrefix}${bn + 1}`, blockEnd };
  }

  // Bumped on every load() call so an older, slower-to-resolve fetch can't
  // clobber the table with stale rows after a newer one already rendered
  // (e.g. a rapid snapshot-tick + tab-switch) — mirrors report.js's own
  // _loadGeneration pattern (see issue #64).
  let _loadGeneration = 0;

  async function load() {
    const gen = ++_loadGeneration;
    readSessionConfig();
    try {
      const data = await window.VKA.fetchQsos();
      if (gen !== _loadGeneration) return;
      _allQsos  = data;
      _page     = 0;
      applyFilter();
    } catch(e) {
      if (gen !== _loadGeneration) return;
      if (tbody) tbody.innerHTML = `<tr><td colspan="13" style="color:var(--red);padding:12px">Failed: ${e.message}</td></tr>`;
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
    applySort();
    _page = 0;
    render();
  }

  // Click-to-sort column headers — numeric columns (pts) compare as
  // numbers, everything else (including time, an ISO string, which sorts
  // correctly as text) compares case-insensitively as text.
  function applySort() {
    if (!_sortCol) return;
    const col = _sortCol, dir = _sortDir, numeric = col === 'pts';
    _filtered = [..._filtered].sort((a, b) => {
      let av = a[col], bv = b[col];
      if (numeric) { av = av || 0; bv = bv || 0; return (av - bv) * dir; }
      av = String(av || '').toLowerCase(); bv = String(bv || '').toLowerCase();
      return av.localeCompare(bv) * dir;
    });
  }

  function updateSortHeaders() {
    document.querySelectorAll('.sortable-th').forEach(th => {
      th.classList.toggle('sort-asc',  th.dataset.sort === _sortCol && _sortDir === 1);
      th.classList.toggle('sort-desc', th.dataset.sort === _sortCol && _sortDir === -1);
    });
  }

  document.querySelectorAll('#tab-worked .sortable-th').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (_sortCol === col) _sortDir = -_sortDir; else { _sortCol = col; _sortDir = 1; }
      updateSortHeaders();
      applySort();
      _page = 0;
      render();
    });
  });

  function updateDeleteBtn() {
    if (deleteBtn) deleteBtn.disabled = _selected.size === 0;
  }

  function renderQrzCell(val, status) {
    if (status === 'pending')   return `<span style="color:var(--muted);font-style:italic" title="Looking up on QRZ.com…">…</span>`;
    if (status === 'not_found') return `<span style="color:var(--muted)" title="Not found on QRZ.com">✗</span>`;
    if (status === 'found')     return val ? window.VKA.escapeHtml(val) : `<span style="color:var(--muted)" title="No data on QRZ.com">—</span>`;
    return `<span style="color:var(--muted)">—</span>`;   // "none" — QRZ lookup not configured/never attempted
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
    if (selectAllChk) selectAllChk.checked = false;

    tbody.innerHTML = '';
    const frag = document.createDocumentFragment();
    slice.forEach(q => {
      const band = (q.band||'').toUpperCase();
      const col  = BAND_COLS[band] || 'var(--muted)';
      const isDupe = q.dupe ? '✗' : '';
      const bi = blockInfo(q.time);
      const tr   = document.createElement('tr');
      if (q.dupe) tr.style.opacity = '0.4';
      tr.innerHTML = `
        <td><input type="checkbox" class="worked-row-chk" data-qid="${q.qso_id||''}" ${_selected.has(q.qso_id) ? 'checked' : ''}></td>
        <td style="color:var(--accent);font-weight:bold">${window.VKA.escapeHtml(q.call||'—')}</td>
        <td style="color:${col}">${band.toLowerCase()}</td>
        <td>${q.mode||'—'}</td>
        <td style="color:${col}">${window.VKA.escapeHtml(q.mult1||'—')}</td>
        <td>${q.pts||0}</td>
        <td>${renderQrzCell(q.qrz_name,  q.qrz_status)}</td>
        <td>${renderQrzCell(q.qrz_grid,  q.qrz_status)}</td>
        <td>${renderQrzCell(q.qrz_state, q.qrz_status)}</td>
        <td style="color:var(--muted);font-size:0.85em">${fmt(q.time)}</td>
        <td style="color:var(--accent3)">${bi ? bi.label : '—'}</td>
        <td class="worked-countdown" data-block-end="${bi ? bi.blockEnd.toISOString() : ''}" style="font-size:0.85em">${bi ? fmtRemaining(bi.blockEnd - new Date()) : '—'}</td>
        <td style="color:var(--red);font-size:0.85em">${isDupe}</td>`;
      frag.appendChild(tr);
    });
    tbody.appendChild(frag);
  }

  function tickCountdowns() {
    if (!tbody) return;
    const now = new Date();
    tbody.querySelectorAll('.worked-countdown').forEach(td => {
      const iso = td.dataset.blockEnd;
      if (!iso) return;
      td.textContent = fmtRemaining(new Date(iso) - now);
    });
  }

  async function deleteSelected() {
    if (!_selected.size) return;
    const calls = _allQsos.filter(q => _selected.has(q.qso_id)).map(q => q.call).join(', ');
    const msg = _selected.size === 1
      ? `Permanently delete this QSO (${calls}) from the database?`
      : `Permanently delete ${_selected.size} QSOs (${calls}) from the database?`;
    if (!window.confirm(msg)) return;
    try {
      const res  = await fetch('/api/qsos/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qso_ids: [..._selected] }),
      });
      const data = await res.json();
      if (data.errors && data.errors.length) console.warn('Delete errors:', data.errors);
      _selected.clear();
      updateDeleteBtn();
      // Must happen before load() below, not just the vka:qsos_changed
      // dispatch after it — otherwise load() can still serve the
      // just-deleted rows back out of the shared cache's short TTL.
      window.VKA.invalidateQsosCache();
      await load();
      window.dispatchEvent(new CustomEvent('vka:qsos_changed'));
    } catch (e) { console.warn('Delete failed:', e); }
  }

  // ── Export (filtered + sorted view, not the whole log — the titlebar's
  // own CSV menu already covers a full unfiltered export via
  // /api/export/csv/qsos; this one respects whatever the operator has
  // actually filtered/sorted down to here, plus the QRZ enrichment columns
  // that endpoint doesn't have) ─────────────────────────────────────────
  function qsoDateParts(iso) {
    const s = String(iso || '');
    return { date: s.slice(0,4)+s.slice(5,7)+s.slice(8,10), time: s.slice(11,13)+s.slice(14,16)+s.slice(17,19) };
  }

  function csvCell(v) {
    v = String(v ?? '');
    return /[",\n]/.test(v) ? '"' + v.replace(/"/g,'""') + '"' : v;
  }

  async function exportCsv() {
    const cols = ['call','band','mode','mult1','pts','qrz_name','qrz_grid','qrz_state','time','dupe'];
    const lines = [cols.join(',')];
    _filtered.forEach(q => lines.push(cols.map(c => csvCell(c === 'dupe' ? (q.dupe ? '1' : '0') : q[c])).join(',')));
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    await window.VKA.downloadBlob(blob, `vkcontest_worked_${new Date().toISOString().slice(0,10)}.csv`, '✓ CSV Saved', '📄');
  }

  async function exportAdif() {
    const lines = ['Generated by VK Contest Analyzer', '<ADIF_VER:5>3.1.4', '<PROGRAMID:16>VKContestAnalyzer', '<EOH>', ''];
    _filtered.forEach(q => {
      if (q.dupe) return;   // dupes aren't real contacts — don't pollute an ADIF import with them
      const { date, time } = qsoDateParts(q.time);
      const call = String(q.call || '').trim();
      if (!call || !date) return;
      const band = String(q.band || '').toLowerCase();
      const mode = String(q.mode || '').toUpperCase();
      const rec = [
        `<CALL:${call.length}>${call}`,
        `<QSO_DATE:${date.length}>${date}`,
        `<TIME_ON:${time.length}>${time}`,
      ];
      if (band) rec.push(`<BAND:${band.length}>${band}`);
      if (mode) rec.push(`<MODE:${mode.length}>${mode}`);
      rec.push('<EOR>');
      lines.push(rec.join(' '));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    await window.VKA.downloadBlob(blob, `vkcontest_worked_${new Date().toISOString().slice(0,10)}.adi`, '✓ ADIF Saved', '📄');
  }

  exportCsvBtn?.addEventListener('click', () => exportCsv().catch(e => console.warn('CSV export failed:', e)));
  exportAdifBtn?.addEventListener('click', () => exportAdif().catch(e => console.warn('ADIF export failed:', e)));

  filterEl?.addEventListener('input', applyFilter);
  prevBtn?.addEventListener('click', () => { _page--; render(); });
  nextBtn?.addEventListener('click', () => { _page++; render(); });
  deleteBtn?.addEventListener('click', deleteSelected);

  tbody?.addEventListener('change', e => {
    if (!e.target.classList.contains('worked-row-chk')) return;
    const qid = e.target.dataset.qid;
    if (e.target.checked) _selected.add(qid); else _selected.delete(qid);
    updateDeleteBtn();
  });

  selectAllChk?.addEventListener('change', () => {
    const checked = selectAllChk.checked;
    tbody?.querySelectorAll('.worked-row-chk').forEach(chk => {
      chk.checked = checked;
      if (checked) _selected.add(chk.dataset.qid); else _selected.delete(chk.dataset.qid);
    });
    updateDeleteBtn();
  });

  window.addEventListener('vka:snapshot', load);
  window.addEventListener('vka:tabchange', e => { if (e.detail.tab === 'worked') load(); });

  if (!_tickHandle) _tickHandle = setInterval(tickCountdowns, 1000);
})();
